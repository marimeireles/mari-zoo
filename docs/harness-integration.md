# Harness Integration Guide

This guide explains how to integrate a new agent harness with zoo-eval's scene trigger system.

## API Surface

These are the public APIs for harness integration:

| Module | Class/Function | Purpose |
|--------|---------------|---------|
| `zoo_eval.event_source` | `EventSource` | Abstract interface for event sources |
| `zoo_eval.event_source` | `RequestEvent` | Event data class |
| `zoo_eval.proxy_event_source` | `ProxyEventSource` | Redis-based event source (recommended) |
| `zoo_eval.scenes` | `SceneManager` | Scene loading and trigger management |
| `zoo_eval.zoo` | `Zoo`, `ZooConfig` | Zoo environment access |
| `zoo_eval.models` | `Task`, `RunConfig` | Task and config models |

**Harness-specific modules (don't import for generic code):**
- `zoo_eval.browser_use_runner` - browser_use harness implementation
- `zoo_eval.claude_sdk_runner` - claude_sdk harness implementation

## Overview

Zoo-eval supports multiple agent harnesses (browser_use, claude_sdk, etc.). Scene triggers allow actions to fire in response to agent behavior (e.g., "send an email when the agent visits auth.zoo").

The **proxy event system** makes triggers harness-agnostic by detecting HTTP traffic at the proxy layer rather than inside the browser.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Your Harness  │────▶│    mitmproxy    │────▶│      squid      │────▶ Zoo Services
│  (any browser)  │     │ (event publish) │     │   (caching)     │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                                 │ Redis pub/sub
                                 ▼
                        ┌─────────────────┐
                        │ ProxyEventSource│
                        │  (zoo-eval)     │
                        └────────┬────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │  SceneManager   │
                        │ (fires triggers)│
                        └─────────────────┘
```

## How It Works

1. **All HTTP traffic** goes through mitmproxy (port 3128)
2. **mitmproxy addon** publishes request/response events to Redis channel `zoo:proxy:events`
3. **ProxyEventSource** subscribes to Redis and matches URL patterns
4. **SceneManager** fires actions when patterns match (e.g., run a script)

## Trigger Types

| Type | Description | Uses Proxy Events |
|------|-------------|-------------------|
| `request` | Fires when agent makes HTTP request matching pattern | Yes |
| `poll` | Polls an endpoint until condition is met | No (direct HTTP) |
| `time` | Fires after a delay | No |
| `page_load` | Fires immediately when scene loads | No |

## Integrating a New Harness

### Step 1: Configure Proxy

Your harness must route all HTTP traffic through the Zoo proxy:

```python
# The proxy URL is available from Zoo config
proxy_url = "http://localhost:3128"  # or zoo.config.proxy_url

# Example: Configure browser to use proxy
browser = Browser(proxy=proxy_url)
```

### Step 2: Create ProxyEventSource (Optional)

If your task uses scenes with triggers, create a `ProxyEventSource`:

```python
from zoo_eval.proxy_event_source import ProxyEventSource

# Create event source with unique session ID for isolation
session_id = str(uuid.uuid4())
event_source = ProxyEventSource(
    redis_url="redis://localhost:6379",
    session_id=session_id,
)
```

### Step 3: Pass Session ID to Browser

For session filtering to work, your browser must send the session ID header:

```python
# Add this header to all requests
headers = {"X-Zoo-Session": session_id}
```

**Note:** If you can't add custom headers, omit `session_id` when creating ProxyEventSource. Events from all sessions will be received (works fine for single-agent scenarios).

### Step 4: Wire Up SceneManager

```python
from zoo_eval.scenes import SceneManager

# Create SceneManager with event source
scene_manager = SceneManager(
    zoo=zoo,
    universe_path=universe_path,
    universe_sites=universe.sites,
    event_source=event_source,  # Pass the event source
)

# Load scene and run setup scripts
await scene_manager.load_and_setup(task.scene_name)

# Set up all triggers (request, poll, time, etc.)
await scene_manager.setup_triggers()

# ... run your agent ...

# Clean up when done
await scene_manager.cleanup()
```

### Complete Example

```python
import asyncio
import uuid
from pathlib import Path

from zoo_eval.proxy_event_source import ProxyEventSource
from zoo_eval.scenes import SceneManager
from zoo_eval.zoo import Zoo, ZooConfig

async def run_task_with_triggers(task, universe_path):
    # Set up Zoo
    zoo = Zoo(ZooConfig(proxy_url="http://localhost:3128"))

    # Create event source for this task
    session_id = str(uuid.uuid4())
    event_source = ProxyEventSource(
        redis_url="redis://localhost:6379",
        session_id=session_id,
    )

    # Create scene manager
    scene_manager = SceneManager(
        zoo=zoo,
        universe_path=universe_path,
        event_source=event_source,
    )

    try:
        # Load scene (runs setup scripts)
        if task.scene_name:
            await scene_manager.load_and_setup(task.scene_name)
            await scene_manager.setup_triggers()

        # Run your agent here
        # Make sure it uses the proxy and sends X-Zoo-Session header
        result = await run_my_agent(
            task=task,
            proxy_url=zoo.config.proxy_url,
            session_header={"X-Zoo-Session": session_id},
        )

        return result

    finally:
        await scene_manager.cleanup()
```

## The EventSource Interface

If you need custom event handling, you can implement the `EventSource` interface:

```python
from zoo_eval.event_source import EventSource, RequestEvent

class MyCustomEventSource(EventSource):
    async def start(self) -> None:
        """Start listening for events."""
        pass

    async def stop(self) -> None:
        """Stop listening and clean up."""
        pass

    def on_request(
        self,
        pattern: str,
        handler: Callable[[RequestEvent], Awaitable[None]],
        *,
        wait_for_response: bool = False,
    ) -> str:
        """Register handler for requests matching URL pattern.

        Args:
            pattern: Regex pattern to match URLs
            handler: Async callback when pattern matches
            wait_for_response: If True, wait for response before firing

        Returns:
            Handler ID for later removal
        """
        pass

    def remove_handler(self, handler_id: str) -> None:
        """Remove a previously registered handler."""
        pass
```

## CLI Usage

Enable proxy events from the command line:

```bash
# Run with proxy-based triggers
zoo-eval run <universe> --task <task> --use-proxy-events

# Custom Redis URL (if not localhost)
zoo-eval run <universe> --task <task> --use-proxy-events --redis-url redis://host:6379
```

## Scene File Format

Scenes define triggers in YAML:

```yaml
name: my_scene
description: "Example scene with request trigger"

# Setup runs before agent starts
setup:
  - type: script
    script_path: "scripts/seed_data.py"

# Actions fire based on triggers
actions:
  - trigger:
      type: request
      url_contains: "auth.zoo"  # Simple substring match
      # OR url_pattern: "auth\\.zoo.*login"  # Regex pattern
      # method: POST  # Optional: filter by HTTP method
      # wait_for_load: true  # Optional: wait for response
      # timeout: 60  # Optional: trigger timeout in seconds
    type: script
    script_path: "scripts/on_auth_visit.py"
```
