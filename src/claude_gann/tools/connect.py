"""gann_connect — connect this Claude Code agent to the GANN network."""
from __future__ import annotations

import os
import uuid

from ..state import get_state
from .. import quic_manager

TOOL_DEF = {
    "name": "gann_connect",
    "description": (
        "Connect this Claude Code session to the GANN (Global Agentic Neural Network). "
        "Registers the agent, starts heartbeating, and opens a QUIC listener so other "
        "agents on the network can reach you. Must be called before any other gann_* tool."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "description": "GANN API key. Falls back to GANN_API_KEY env var.",
            },
            "agent_id": {
                "type": "string",
                "description": "UUID of the agent to register as (required).",
            },
            "base_url": {
                "type": "string",
                "description": "GANN server base URL. Falls back to GANN_BASE_URL env var or https://api.gnna.io.",
            },
            "capacity": {
                "type": "integer",
                "description": "LoadTracker capacity (default 4).",
                "default": 4,
            },
            "heartbeat_interval_s": {
                "type": "number",
                "description": "Seconds between heartbeats (default 30).",
                "default": 30,
            },
        },
        "required": ["api_key", "agent_id"],
    },
}


def handle(arguments: dict) -> str:
    import json
    from gann_sdk import GannClient, LoadTracker

    state = get_state()

    if state.connected:
        return json.dumps({
            "connected": True,
            "agent_id": str(state.agent_id),
            "message": "Already connected.",
        })

    api_key = arguments.get("api_key") or os.environ.get("GANN_API_KEY") or ""
    base_url = arguments.get("base_url") or os.environ.get("GANN_BASE_URL") or "https://api.gnna.io"
    agent_id_str = arguments.get("agent_id")
    capacity = int(arguments.get("capacity", 4))
    heartbeat_interval = float(arguments.get("heartbeat_interval_s", 30))

    if not api_key:
        return json.dumps({
            "connected": False,
            "error": "No API key provided. Pass api_key or set GANN_API_KEY env var.",
        })

    if not agent_id_str:
        return json.dumps({
            "connected": False,
            "error": "No agent_id provided. Pass the UUID of the agent to register as.",
        })

    agent_id = uuid.UUID(agent_id_str)
    tracker = LoadTracker(capacity=capacity)

    client = GannClient(
        api_key=api_key,
        base_url=base_url,
        load_tracker=tracker,
    )
    client.connect_agent(agent_id, heartbeat_interval=heartbeat_interval)

    state.client = client
    state.agent_id = agent_id
    state.api_key = api_key
    state.base_url = base_url
    state.connected = True

    # Start background event loop + QUIC accept loop
    state.start_event_loop()
    quic_manager.start_accept_loop(state)

    return json.dumps({
        "connected": True,
        "agent_id": str(agent_id),
        "base_url": base_url,
        "heartbeat_interval_s": heartbeat_interval,
        "message": "Connected to GANN. Heartbeating and QUIC listener active.",
    })
