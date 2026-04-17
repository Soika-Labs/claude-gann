"""gann_search_agents — discover agents on the GANN network."""
from __future__ import annotations

from ..state import get_state

TOOL_DEF = {
    "name": "gann_search_agents",
    "description": (
        "Search the GANN network for agents by capability, name, or keyword. "
        "Returns matching agents with their IDs, names, capabilities, and scores."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — capability name, agent name, or keyword.",
            },
            "status": {
                "type": "string",
                "description": "Filter by agent status (e.g. 'online'). Omit for all.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 10).",
                "default": 10,
            },
        },
        "required": ["query"],
    },
}


def handle(arguments: dict) -> str:
    import json

    state = get_state()
    state.ensure_connected()

    results = state.client.search_agents(
        query=arguments["query"],
        status=arguments.get("status") or None,
        limit=int(arguments.get("limit", 10)),
    )

    agents = []
    for a in results.agents:
        agents.append({
            "agent_id": str(a.agent_id),
            "name": getattr(a, "agent_name", None),
            "status": getattr(a, "status", None),
            "capabilities": getattr(a, "capabilities", None),
            "search_score": getattr(a, "search_score", None),
        })

    return json.dumps({"total": results.total, "agents": agents})
