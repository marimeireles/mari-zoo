"""Event source abstraction for harness-agnostic request/response monitoring."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    pass


@dataclass
class RequestEvent:
    """Represents an HTTP request event."""

    url: str
    method: str
    timestamp: float
    session_id: str | None = None


@dataclass
class ResponseEvent:
    """Represents an HTTP response event."""

    url: str
    method: str
    status_code: int
    content_type: str
    timestamp: float
    session_id: str | None = None


# Type alias for request handlers
RequestHandler = Callable[[RequestEvent], Awaitable[None]]


class EventSource(ABC):
    """Abstract base class for event sources.

    Event sources monitor HTTP traffic and dispatch events to registered handlers.
    Different implementations can use different mechanisms (proxy, websocket, etc.)
    while providing a unified interface.
    """

    @abstractmethod
    async def start(self) -> None:
        """Start listening for events.

        Must be called before registering handlers.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening and clean up resources."""
        pass

    @abstractmethod
    def on_request(
        self,
        pattern: str,
        handler: RequestHandler,
        *,
        wait_for_response: bool = False,
    ) -> str:
        """Register a handler for requests matching a URL pattern.

        Args:
            pattern: Regex pattern to match against request URLs
            handler: Async callback invoked when pattern matches
            wait_for_response: If True, wait for the response to complete
                              before invoking the handler. Useful for
                              page load detection.

        Returns:
            Handler ID that can be used to remove the handler later.
        """
        pass

    @abstractmethod
    def remove_handler(self, handler_id: str) -> None:
        """Remove a previously registered handler.

        Args:
            handler_id: ID returned from on_request()
        """
        pass

    async def __aenter__(self) -> "EventSource":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()
