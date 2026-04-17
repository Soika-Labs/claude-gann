"""
Singleton state for the GANN MCP server.

Holds the GannClient, agent identity, background event loop for async QUIC
operations, and an incoming-message queue that tools can drain.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PendingSession:
    """An inbound QUIC session held open so Claude can reply later."""

    session_id: str
    peer_agent_id: str
    mode: str  # "direct" or "relay"
    channel: Any  # SignalingChannel
    result: Any  # QuicDirectFirstResult
    writer: Any | None  # QUIC stream writer (direct mode only)
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class GannState:
    """Mutable session state shared across all MCP tool handlers."""

    client: Any | None = None  # GannClient (typed as Any to avoid import at module level)
    agent_id: uuid.UUID | None = None
    api_key: str = ""
    base_url: str = "https://api.gnna.io"
    connected: bool = False

    # Background asyncio loop for QUIC operations
    loop: asyncio.AbstractEventLoop | None = None
    loop_thread: threading.Thread | None = None

    # Inbound messages received by the QUIC responder
    incoming: asyncio.Queue[dict] = field(default_factory=lambda: asyncio.Queue())

    # Sessions held open waiting for Claude to reply via gann_reply
    pending_sessions: dict[str, PendingSession] = field(default_factory=dict)
    _pending_lock: threading.Lock = field(default_factory=threading.Lock)

    def ensure_connected(self) -> None:
        if not self.connected or self.client is None:
            raise RuntimeError(
                "Not connected to GANN. Call gann_connect first."
            )

    def start_event_loop(self) -> asyncio.AbstractEventLoop:
        """Start a dedicated daemon thread running an asyncio event loop."""
        if self.loop is not None and self.loop.is_running():
            return self.loop

        self.loop = asyncio.new_event_loop()

        def _run(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        self.loop_thread = threading.Thread(
            target=_run,
            args=(self.loop,),
            daemon=True,
            name="gann-quic-loop",
        )
        self.loop_thread.start()
        return self.loop

    def stop_event_loop(self) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.loop = None
        self.loop_thread = None


# Module-level singleton
_state = GannState()


def get_state() -> GannState:
    return _state
