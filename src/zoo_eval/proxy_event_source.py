"""Proxy-based event source using Redis pub/sub."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from .event_source import EventSource, RequestEvent, RequestHandler, ResponseEvent

if TYPE_CHECKING:
    import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Redis channel for proxy events
CHANNEL = "zoo:proxy:events"


class ProxyEventSource(EventSource):
    """Event source that receives events from mitmproxy via Redis pub/sub.

    The mitmproxy addon publishes request/response events to a Redis channel.
    This class subscribes to that channel and dispatches events to handlers.

    Supports session filtering for multi-agent scenarios where multiple
    browsers are running through the same proxy.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        session_id: str | None = None,
    ):
        """Initialize the proxy event source.

        Args:
            redis_url: Redis connection URL
            session_id: If provided, only process events matching this session.
                       Events are tagged with session ID via X-Zoo-Session header.
        """
        self.redis_url = redis_url
        self.session_id = session_id

        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._task: asyncio.Task | None = None

        # Handler registry: id -> (compiled_pattern, handler, wait_for_response)
        self._handlers: dict[str, tuple[re.Pattern, RequestHandler, bool]] = {}

        # Pending requests waiting for response: handler_id -> (event, handler)
        self._pending_responses: dict[str, tuple[RequestEvent, RequestHandler]] = {}

        # Counter for generating unique handler IDs
        self._handler_counter = 0

    async def start(self, max_retries: int = 5, base_delay: float = 1.0) -> None:
        """Start listening for events from Redis.

        Args:
            max_retries: Maximum number of connection attempts
            base_delay: Base delay between retries (doubles each attempt)
        """
        try:
            import redis.asyncio as aioredis
        except ImportError:
            raise ImportError(
                "redis package required for ProxyEventSource. "
                "Install with: pip install redis[hiredis]"
            )

        last_error = None
        for attempt in range(max_retries):
            try:
                self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe(CHANNEL)

                self._task = asyncio.create_task(self._listen())
                logger.info(
                    f"ProxyEventSource started, listening on {CHANNEL}"
                    + (f" (session: {self.session_id})" if self.session_id else "")
                )
                return  # Success!

            except Exception as e:
                last_error = e
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"Redis connection attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                # Clean up failed connection attempt
                if self._pubsub:
                    try:
                        await self._pubsub.close()
                    except Exception:
                        pass
                    self._pubsub = None
                if self._redis:
                    try:
                        await self._redis.close()
                    except Exception:
                        pass
                    self._redis = None

                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)

        # All retries exhausted
        raise ConnectionError(
            f"Failed to connect to Redis after {max_retries} attempts: {last_error}"
        )

    async def stop(self) -> None:
        """Stop listening and clean up."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._pubsub:
            await self._pubsub.unsubscribe(CHANNEL)
            await self._pubsub.close()
            self._pubsub = None

        if self._redis:
            await self._redis.close()
            self._redis = None

        self._handlers.clear()
        self._pending_responses.clear()
        logger.info("ProxyEventSource stopped")

    async def _listen(self) -> None:
        """Main event loop - listen for Redis messages with auto-reconnect."""
        reconnect_delay = 1.0
        max_reconnect_delay = 30.0

        while True:
            try:
                async for message in self._pubsub.listen():
                    if message["type"] != "message":
                        continue

                    try:
                        await self._handle_message(message["data"])
                    except Exception as e:
                        logger.error(f"Error handling proxy event: {e}")

                    # Reset reconnect delay on successful message
                    reconnect_delay = 1.0

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    f"ProxyEventSource connection lost: {e}. "
                    f"Reconnecting in {reconnect_delay:.1f}s..."
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

                # Try to reconnect
                try:
                    import redis.asyncio as aioredis

                    if self._pubsub:
                        try:
                            await self._pubsub.close()
                        except Exception:
                            pass
                    if self._redis:
                        try:
                            await self._redis.close()
                        except Exception:
                            pass

                    self._redis = aioredis.from_url(
                        self.redis_url, decode_responses=True
                    )
                    self._pubsub = self._redis.pubsub()
                    await self._pubsub.subscribe(CHANNEL)
                    logger.info("ProxyEventSource reconnected to Redis")
                except Exception as reconnect_error:
                    logger.error(f"Failed to reconnect to Redis: {reconnect_error}")

    async def _handle_message(self, data: str) -> None:
        """Parse and dispatch a Redis message."""
        event_data = json.loads(data)

        # Filter by session if configured. Accept session-less events as a
        # wildcard — this lets proxies that can't inject X-Zoo-Session (e.g.
        # Squid for HTTPS CONNECTs) still drive scene triggers.
        event_session = event_data.get("session_id")
        if self.session_id and event_session and event_session != self.session_id:
            return

        event_type = event_data.get("type")

        if event_type == "request":
            event = RequestEvent(
                url=event_data["url"],
                method=event_data["method"],
                timestamp=event_data["timestamp"],
                session_id=event_session,
            )
            await self._dispatch_request(event)

        elif event_type == "response":
            event = ResponseEvent(
                url=event_data["url"],
                method=event_data["method"],
                status_code=event_data["status_code"],
                content_type=event_data.get("content_type", ""),
                timestamp=event_data["timestamp"],
                session_id=event_session,
            )
            await self._dispatch_response(event)

    async def _dispatch_request(self, event: RequestEvent) -> None:
        """Dispatch a request event to matching handlers."""
        for handler_id, (pattern, handler, wait_for_response) in list(
            self._handlers.items()
        ):
            if pattern.search(event.url):
                if wait_for_response:
                    # Store for later when response arrives
                    key = f"{handler_id}:{event.url}"
                    self._pending_responses[key] = (event, handler)
                    logger.debug(
                        f"Request matched {pattern.pattern}, waiting for response"
                    )
                else:
                    # Fire immediately
                    logger.debug(f"Request matched {pattern.pattern}, firing handler")
                    try:
                        await handler(event)
                    except Exception as e:
                        logger.error(f"Handler error for {pattern.pattern}: {e}")

    async def _dispatch_response(self, event: ResponseEvent) -> None:
        """Dispatch response events to handlers waiting for them."""
        # Find pending requests that match this response URL
        keys_to_remove = []
        for key, (req_event, handler) in list(self._pending_responses.items()):
            if req_event.url == event.url and req_event.method == event.method:
                keys_to_remove.append(key)
                logger.debug(f"Response received for {event.url}, firing handler")
                try:
                    await handler(req_event)
                except Exception as e:
                    logger.error(f"Handler error for response {event.url}: {e}")

        for key in keys_to_remove:
            del self._pending_responses[key]

    def on_request(
        self,
        pattern: str,
        handler: RequestHandler,
        *,
        wait_for_response: bool = False,
    ) -> str:
        """Register a handler for requests matching a URL pattern."""
        self._handler_counter += 1
        handler_id = f"proxy_h_{self._handler_counter}"

        compiled = re.compile(pattern, re.IGNORECASE)
        self._handlers[handler_id] = (compiled, handler, wait_for_response)

        logger.debug(
            f"Registered handler {handler_id} for pattern '{pattern}'"
            + (" (wait_for_response)" if wait_for_response else "")
        )
        return handler_id

    def remove_handler(self, handler_id: str) -> None:
        """Remove a previously registered handler."""
        if handler_id in self._handlers:
            del self._handlers[handler_id]
            logger.debug(f"Removed handler {handler_id}")

        # Also remove any pending responses for this handler
        keys_to_remove = [k for k in self._pending_responses if k.startswith(handler_id)]
        for key in keys_to_remove:
            del self._pending_responses[key]
