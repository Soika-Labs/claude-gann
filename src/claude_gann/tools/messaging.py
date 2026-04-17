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
                "type": "object",
                "description": "JSON payload to send to the target agent.",
            },
        },
        "required": ["target_agent_id", "payload"],
    },
}

RECEIVE_TOOL_DEF = {
    "name": "gann_receive_messages",
    "description": (
        "Drain inbound messages that arrived from other GANN agents via QUIC. "
        "Returns all messages currently in the queue (non-blocking). "
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
                "type": "object",
                "description": "JSON response payload to send back to the remote agent.",
            },
        },
        "required": ["session_id", "payload"],
    },
}


def handle_send(arguments: dict) -> str:
    import json

    state = get_state()
    state.ensure_connected()

    peer_id = uuid.UUID(arguments["target_agent_id"])
    payload = arguments["payload"]

    result = quic_manager.send_message(state, peer_id, payload)
    return json.dumps(result)


def handle_receive(arguments: dict) -> str:
    import json

    state = get_state()
    state.ensure_connected()

    max_msgs = int(arguments.get("max_messages", 50))
    messages: list[dict] = []

    while len(messages) < max_msgs:
        try:
            msg = state.incoming.get_nowait()
            messages.append(msg)
        except Exception:
            break

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
    payload = arguments["payload"]

    result = quic_manager.reply_to_session(state, session_id, payload)
    return json.dumps(result)
