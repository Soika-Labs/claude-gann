"""gann_status + gann_disconnect — lifecycle tools."""
from __future__ import annotations

import os

from ..state import get_state

STATUS_DEF = {
    "name": "gann_status",
    "description": (
        "Check the current GANN connection status — whether connected, "
        "agent ID, base URL, and environment configuration."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

DISCONNECT_DEF = {
    "name": "gann_disconnect",
    "description": (
        "Disconnect from the GANN network. Stops heartbeats, "
        "closes the QUIC listener, and cleans up resources."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def handle_status(_arguments: dict) -> str:
    import json

    state = get_state()

    api_key_set = bool(state.api_key or os.environ.get("GANN_API_KEY"))
    base_url = state.base_url or os.environ.get("GANN_BASE_URL", "https://api.gnna.io")

    try:
        import gann_sdk  # noqa: F401
        sdk_installed = True
    except ImportError:
        sdk_installed = False

    try:
        import aioquic  # noqa: F401
        quic_available = True
    except ImportError:
        quic_available = False

    return json.dumps({
        "connected": state.connected,
        "agent_id": str(state.agent_id) if state.agent_id else None,
        "base_url": base_url,
        "api_key_configured": api_key_set,
        "gann_sdk_installed": sdk_installed,
        "quic_available": quic_available,
        "incoming_queue_size": state.incoming.qsize(),
        "pending_reply_sessions": len(state.pending_sessions),
    })


def handle_disconnect(_arguments: dict) -> str:
    import json

    state = get_state()

    if not state.connected:
        return json.dumps({"disconnected": True, "message": "Was not connected."})

    state.connected = False
    state.stop_event_loop()

    if state.client:
        try:
            state.client.disconnect()
        except Exception:
            pass
        state.client = None

    state.agent_id = None

    return json.dumps({"disconnected": True, "message": "Disconnected from GANN."})
