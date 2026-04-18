"""gann_send_message + gann_receive_messages + gann_reply — P2P QUIC messaging tools."""
from __future__ import annotations

import uuid

from ..state import get_state
from .. import quic_manager

SEND_TOOL_DEF = {
    "name": "gann_send_message",
    "description": (
        "Send a JSON message to another agent on GANN via P2P QUIC (direct first, "
        "relay fallback). Returns the peer's response. Requires gann_connect first."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "target_agent_id": {
                "type": "string",
                "description": "UUID of the target agent to message.",
            },
            "payload": {
                "description": "JSON payload to send to the target agent. Can be a JSON object or a JSON string.",
            },
        },
        "required": ["target_agent_id", "payload"],
    },
}

RECEIVE_TOOL_DEF = {
    "name": "gann_receive_messages",
    "description": (
        "Drain inbound messages that arrived from other GANN agents via QUIC. "
        "If wait_timeout is set, blocks up to that many seconds waiting for at least one message. "
        "Each message includes a session_id — use gann_reply with that session_id "
        "to send a response back to the remote agent through the still-open session. "
        "Requires gann_connect first."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "max_messages": {
                "type": "integer",
                "description": "Maximum number of messages to return (default 50).",
                "default": 50,
            },
            "wait_timeout": {
                "type": "integer",
                "description": "Seconds to wait for at least one message before returning empty. 0 = non-blocking (default). Max 120.",
                "default": 0,
            },
        },
        "required": [],
    },
}

REPLY_TOOL_DEF = {
    "name": "gann_reply",
    "description": (
        "Reply to an inbound message from a remote GANN agent. Uses the session_id "
        "from gann_receive_messages to send a response back through the still-open "
        "P2P QUIC or relay session. The session is closed after the reply is sent. "
        "Sessions time out after 5 minutes if not replied to."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session_id from the inbound message (returned by gann_receive_messages).",
            },
            "payload": {
                "description": "JSON response payload to send back to the remote agent. Can be a JSON object or a JSON string.",
            },
        },
        "required": ["session_id", "payload"],
    },
}


def _coerce_payload(raw: object) -> dict:
    """Accept payload as dict or JSON string and return a dict."""
    import json as _json
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, TypeError):
            pass
        return {"message": raw}
    return {"data": raw}


def handle_send(arguments: dict) -> str:
    import json

    state = get_state()
    state.ensure_connected()

    peer_id = uuid.UUID(arguments["target_agent_id"])
    payload = _coerce_payload(arguments.get("payload", {}))

    result = quic_manager.send_message(state, peer_id, payload)
    return json.dumps(result)


def handle_receive(arguments: dict) -> str:
    import json
    import time

    state = get_state()
    state.ensure_connected()

    max_msgs = int(arguments.get("max_messages", 50))
    wait_timeout = min(int(arguments.get("wait_timeout", 0)), 120)
    messages: list[dict] = []

    deadline = time.monotonic() + wait_timeout if wait_timeout > 0 else 0

    # If wait_timeout > 0, poll the queue every 0.5s until a message arrives or timeout
    while True:
        while len(messages) < max_msgs:
            try:
                msg = state.incoming.get_nowait()
                messages.append(msg)
            except Exception:
                break

        if messages or wait_timeout <= 0:
            break

        if time.monotonic() >= deadline:
            break

        time.sleep(0.5)

    # Include count of sessions still awaiting reply
    with state._pending_lock:
        pending_count = len(state.pending_sessions)

    return json.dumps({
        "count": len(messages),
        "messages": messages,
        "pending_sessions": pending_count,
    })


def handle_reply(arguments: dict) -> str:
    import json

    state = get_state()
    state.ensure_connected()

    session_id = arguments["session_id"]
    payload = _coerce_payload(arguments.get("payload", {}))

    result = quic_manager.reply_to_session(state, session_id, payload)
    return json.dumps(result)
