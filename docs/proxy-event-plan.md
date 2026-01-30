# Plan: Proxy-Based Harness-Agnostic Scene Triggers

## Goal
Replace CDP-based request triggers in `SceneManager` with proxy-based event detection, making scene triggers work with any harness (browser_use, claude_sdk, future harnesses).

---

## Current State

**SceneManager (`scenes.py`)** uses CDP to:
1. **Request triggers** - `Network.requestWillBeSent` events to detect URL patterns
2. **Page load triggers** - `Page.loadEventFired` to know when navigation completes

**Proxy** (`the_zoo` repo):
- Runs at `localhost:3128`
- All browser traffic already routes through it
- Type unknown (likely Squid based on port), but we control it

---

## Proposed Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Any Browser   │────▶│  mitmproxy      │────▶│  Zoo Services   │
│  (any harness)  │     │  (port 3128)    │     │  (.zoo domains) │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                                 │ Redis pub/sub
                                 ▼
                        ┌─────────────────┐
                        │     Redis       │
                        │ (already in zoo)│
                        └────────┬────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │  SceneManager   │
                        │  (subscriber)   │
                        └─────────────────┘
```

**Key idea**: mitmproxy addon publishes request events to Redis. SceneManager subscribes and receives notifications in real-time. Redis is already part of the_zoo infrastructure - no new services needed.

---

## Detailed Plan

### Phase 1: Proxy Infrastructure

#### 1.1 Replace/Configure Proxy with mitmproxy

**Location**: `the_zoo` repo (Docker changes)

**Option A - Replace existing proxy**:
- Swap the proxy container for mitmproxy
- Pros: Simpler, single proxy
- Cons: Might break existing functionality

**Option B - Chain proxies** (RECOMMENDED):
- mitmproxy → existing proxy → Zoo services
- Pros: Non-breaking, can test in isolation
- Cons: Extra hop (negligible latency)

**Decision**: Start with Option B for safety, migrate to A later if desired.

#### 1.2 mitmproxy Addon for Event Emission

Create addon that publishes to Redis on each request:
- URL, Method, Headers, Timestamp
- Session ID (from `X-Zoo-Session` header)

```python
# zoo_event_addon.py
from mitmproxy import http
import redis
import json
import time

# Connect to Redis (same network as other zoo services)
r = redis.Redis(host='redis', port=6379, decode_responses=True)

CHANNEL = "zoo:requests"

class ZooEventEmitter:
    def request(self, flow: http.HTTPFlow):
        # Extract session ID from header if present
        session_id = flow.request.headers.get("X-Zoo-Session", "default")

        event = {
            "type": "request",
            "url": flow.request.pretty_url,
            "method": flow.request.method,
            "timestamp": time.time(),
            "session_id": session_id,
        }

        # Publish to Redis channel
        r.publish(CHANNEL, json.dumps(event))

    def response(self, flow: http.HTTPFlow):
        # Also emit response events for page load heuristics
        session_id = flow.request.headers.get("X-Zoo-Session", "default")

        event = {
            "type": "response",
            "url": flow.request.pretty_url,
            "method": flow.request.method,
            "status_code": flow.response.status_code,
            "content_type": flow.response.headers.get("content-type", ""),
            "timestamp": time.time(),
            "session_id": session_id,
        }

        r.publish(CHANNEL, json.dumps(event))

addons = [ZooEventEmitter()]
```

**Dependencies**: `redis` package (add to mitmproxy container)

#### 1.3 Docker Configuration

```yaml
# In the_zoo/docker-compose.yml
mitmproxy:
  image: mitmproxy/mitmproxy:latest
  command: mitmdump -s /addons/zoo_event_addon.py --mode upstream:http://existing-proxy:3129
  ports:
    - "3128:8080"   # Browsers connect here (takes over main proxy port)
  volumes:
    - ./addons:/addons
  depends_on:
    - redis
    - existing-proxy  # Rename current proxy service
  networks:
    - zoo-network

# Rename existing proxy service and move to internal port
existing-proxy:
  # ... existing proxy config ...
  ports:
    - "3129:3128"  # Internal only, mitmproxy forwards here
```

**Alternative**: If existing proxy is simple (just DNS/routing), we might replace it entirely with mitmproxy.

**mitmproxy Dockerfile** (if we need custom image with redis):
```dockerfile
FROM mitmproxy/mitmproxy:latest
RUN pip install redis
COPY zoo_event_addon.py /addons/
```

---

### Phase 2: SceneManager Refactor

#### 2.1 Create EventSource Abstraction

```python
# event_source.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Awaitable

@dataclass
class RequestEvent:
    url: str
    method: str
    timestamp: float
    session_id: str | None = None

@dataclass
class ResponseEvent:
    url: str
    method: str
    status_code: int
    content_type: str
    timestamp: float
    session_id: str | None = None

RequestHandler = Callable[[RequestEvent], Awaitable[None]]

class EventSource(ABC):
    @abstractmethod
    async def start(self): pass

    @abstractmethod
    async def stop(self): pass

    @abstractmethod
    def on_request(
        self,
        pattern: str,
        handler: RequestHandler,
        wait_for_response: bool = False,
    ) -> str:
        """Register handler for URL pattern.

        Args:
            pattern: Regex pattern to match URLs
            handler: Async callback when pattern matches
            wait_for_response: If True, wait for response before firing handler
                              (for page load heuristic)

        Returns:
            Handler ID for later removal
        """
        pass

    @abstractmethod
    def remove_handler(self, handler_id: str): pass
```

#### 2.2 Implement ProxyEventSource

```python
# proxy_event_source.py
import redis.asyncio as redis  # async redis client
import asyncio
import json
import re
from .event_source import EventSource, RequestEvent, ResponseEvent

CHANNEL = "zoo:requests"

class ProxyEventSource(EventSource):
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        session_id: str | None = None,  # Filter to specific session
    ):
        self.redis_url = redis_url
        self.session_id = session_id
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._handlers: dict[str, tuple[str, RequestHandler, bool]] = {}  # id -> (pattern, handler, wait_for_response)
        self._task: asyncio.Task | None = None
        self._pending_requests: dict[str, RequestEvent] = {}  # For response correlation

    async def start(self):
        self._redis = redis.from_url(self.redis_url)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(CHANNEL)
        self._task = asyncio.create_task(self._listen())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.unsubscribe(CHANNEL)
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()

    async def _listen(self):
        async for message in self._pubsub.listen():
            if message["type"] != "message":
                continue

            event_data = json.loads(message["data"])

            # Filter by session if configured
            if self.session_id and event_data.get("session_id") != self.session_id:
                continue

            if event_data["type"] == "request":
                event = RequestEvent(
                    url=event_data["url"],
                    method=event_data["method"],
                    timestamp=event_data["timestamp"],
                    session_id=event_data.get("session_id"),
                )
                await self._dispatch_request(event)

            elif event_data["type"] == "response":
                event = ResponseEvent(
                    url=event_data["url"],
                    method=event_data["method"],
                    status_code=event_data["status_code"],
                    content_type=event_data.get("content_type", ""),
                    timestamp=event_data["timestamp"],
                    session_id=event_data.get("session_id"),
                )
                await self._dispatch_response(event)

    async def _dispatch_request(self, event: RequestEvent):
        for handler_id, (pattern, handler, wait_for_response) in list(self._handlers.items()):
            if re.search(pattern, event.url):
                if wait_for_response:
                    # Store for response correlation
                    self._pending_requests[handler_id] = (event, handler)
                else:
                    await handler(event)

    async def _dispatch_response(self, event: ResponseEvent):
        # Check if any pending request matches this response
        for handler_id, (req_event, handler) in list(self._pending_requests.items()):
            if req_event.url == event.url:
                # Response received - fire the handler now
                del self._pending_requests[handler_id]
                await handler(req_event)

    def on_request(
        self,
        pattern: str,
        handler: RequestHandler,
        wait_for_response: bool = False,
    ) -> str:
        handler_id = f"h_{id(handler)}_{len(self._handlers)}"
        self._handlers[handler_id] = (pattern, handler, wait_for_response)
        return handler_id

    def remove_handler(self, handler_id: str):
        self._handlers.pop(handler_id, None)
        self._pending_requests.pop(handler_id, None)
```

**Dependencies**: `redis[hiredis]` (async redis with fast parser)

#### 2.3 Keep CDP Implementation as Fallback

```python
# cdp_event_source.py (existing logic, refactored)
class CDPEventSource(EventSource):
    """CDP-based event source for browser_use harness fallback."""

    def __init__(self, browser):
        self.browser = browser
        # ... existing CDP logic moved here
```

#### 2.4 Update SceneManager

```python
# scenes.py changes
class SceneManager:
    def __init__(
        self,
        zoo: Zoo,
        event_source: EventSource | None = None,  # NEW
        ...
    ):
        self.event_source = event_source
        # ... rest unchanged

    async def attach_to_browser(self, browser):
        # If no event source provided, fall back to CDP
        if self.event_source is None:
            self.event_source = CDPEventSource(browser)

        await self.event_source.start()
        # ... setup triggers using self.event_source.on_request()
```

---

### Phase 3: Handle Page Load Events

**Problem**: Proxy sees requests but not DOM lifecycle events.

**Options**:

#### Option A: Heuristic (RECOMMENDED for v1)
- Trigger fires when main document request completes
- Add configurable delay (e.g., 500ms) after request
- Good enough for most cases

```python
# In trigger config
trigger:
  type: request
  url_contains: "/checkout"
  wait_for_load: true       # Uses heuristic
  load_delay_ms: 500        # Wait after request
```

#### Option B: Response-based detection
- mitmproxy can also emit response events
- Watch for response complete on main document
- Still not true "DOMContentLoaded" but closer

#### Option C: Hybrid (if needed later)
- Proxy handles request triggers
- CDP/harness-specific for true page load
- More complex, only if Option A proves insufficient

**Decision**: Implement Option A first. It's simple and probably sufficient. Add Option B/C only if real tasks need it.

---

### Phase 4: Session Correlation

**Problem**: Multiple agents running = multiple browsers = mixed request streams.

**Solutions**:

#### 4.1 Header Injection
Each harness injects `X-Zoo-Session: <uuid>` header:

```python
# browser_use harness
browser = Browser(
    extra_headers={"X-Zoo-Session": session_id}
)

# claude_sdk harness
# Configure via mcp args or browser context
```

**Pros**: Clean, explicit
**Cons**: Requires harness changes

#### 4.2 Port-based (alternative)
- mitmproxy listens on multiple ports
- Each agent session uses different port
- Events tagged by port

**Pros**: No browser changes
**Cons**: More complex proxy config

**Decision**: Start with header injection (4.1). It's cleaner.

---

### Phase 5: Integration & Migration

#### 5.1 Configuration
```python
# In RunConfig or similar
class RunConfig:
    use_proxy_events: bool = True  # New flag
    redis_url: str = "redis://localhost:6379"  # Zoo's Redis
```

#### 5.2 Backwards Compatibility
- Keep CDP code, just make it fallback
- `use_proxy_events=False` uses old behavior
- Allows gradual migration

#### 5.3 Runner Changes

```python
# In runner.py / agent_runner.py
import uuid

async def run_task(self, task):
    # Generate unique session ID for multi-agent isolation
    session_id = str(uuid.uuid4())

    if config.use_proxy_events:
        event_source = ProxyEventSource(
            redis_url=config.redis_url,
            session_id=session_id,
        )
    else:
        event_source = None  # Will fall back to CDP in SceneManager

    scene_manager = SceneManager(zoo, event_source=event_source, ...)

    # Pass session_id to harness for header injection
    # browser_use: extra_headers={"X-Zoo-Session": session_id}
    # claude_sdk: configure via MCP args or browser context
```

---

## Failure Modes & Mitigations

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Redis connection drops | Triggers stop firing | Auto-reconnect (redis-py handles this) |
| mitmproxy crashes | All traffic fails | Docker restart policy, health checks |
| High latency in pub/sub | Triggers fire late | Redis is fast (<1ms); benchmark to confirm |
| Pattern matches wrong session | Wrong action fires | Session ID filtering in ProxyEventSource |
| Proxy not running | Browsers can't connect | Health check before task starts |
| Race: handler not registered yet | Miss early requests | Register handlers before browser navigates |
| Redis not running | Events lost | Redis is core infra, should always be up |
| mitmproxy can't reach Redis | Events not published | Docker networking; same compose network |

---

## Testing Plan

1. **Unit tests**: ProxyEventSource with mock WebSocket
2. **Integration test**: mitmproxy addon in Docker, verify events received
3. **E2E test**: Run existing task with proxy events, compare to CDP results
4. **Performance test**: Measure latency (CDP vs proxy) - should be <50ms difference
5. **Multi-session test**: Two concurrent agents, verify session isolation

---

## Implementation Order

1. [x] **Phase 1.2**: Create mitmproxy addon (standalone test) - `mitmproxy/zoo_event_addon.py`
2. [x] **Phase 1.3**: Docker config in `the_zoo` - `the_zoo/core/mitmproxy/`, updated `docker-compose.yaml`
3. [x] **Phase 2.1-2.2**: EventSource abstraction + ProxyEventSource - `src/zoo_eval/event_source.py`, `src/zoo_eval/proxy_event_source.py`
4. [x] **Phase 2.4**: Update SceneManager to use EventSource - `src/zoo_eval/scenes.py`
5. [x] **Phase 3**: Page load heuristic - Implemented via `wait_for_response` flag
6. [x] **Phase 4**: Session correlation - Session ID generated per task, passed to ProxyEventSource
7. [x] **Phase 5**: Config flags + backwards compat - `RunConfig.use_proxy_events`, `RunConfig.redis_url`
8. [ ] Testing & benchmarking

---

## Open Questions

1. ~~**the_zoo access**: Do we have access to modify the proxy setup there?~~ ✅ Yes
2. **Current proxy type**: Is it Squid? Can we replace or must chain? (Need to check the_zoo repo)
3. **Performance requirement**: What's acceptable latency for triggers? (<100ms assumed)
4. ~~**Multi-agent frequency**: How often do concurrent agents run?~~ ✅ Yes, some tasks have multi-agent

---

## Dependencies to Add

**zoo-eval (Python)**:
```toml
# pyproject.toml
dependencies = [
    "redis[hiredis]>=5.0",  # Async Redis with fast parser
    # ... existing deps
]
```

**mitmproxy container**:
```
redis>=5.0
```

---

## Estimated Complexity

- **Phase 1**: Medium (Docker/infra work)
- **Phase 2**: Low-Medium (clean refactor)
- **Phase 3**: Low (simple heuristic)
- **Phase 4**: Low (header injection)
- **Phase 5**: Low (config plumbing)

Total: Medium complexity, low risk due to fallback strategy.
