"""gann_get_schema + gann_validate_input — agent schema tools."""
from __future__ import annotations

from ..state import get_state

GET_SCHEMA_DEF = {
    "name": "gann_get_schema",
    "description": (
        "Fetch the input/output schema of a registered GANN agent. "
        "Useful before sending a message to understand what the agent expects."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "UUID of the agent whose schema to fetch.",
            },
        },
        "required": ["agent_id"],
    },
}

VALIDATE_INPUT_DEF = {
    "name": "gann_validate_input",
    "description": (
        "Validate a payload against a GANN agent's registered input schema. "
        "Returns whether the payload is valid and any errors."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "UUID of the target agent.",
            },
            "payload": {
                "type": "object",
                "description": "The payload to validate.",
            },
            "capability": {
                "type": "string",
                "description": "Optional capability name to validate against.",
            },
        },
        "required": ["agent_id", "payload"],
    },
}


def handle_get_schema(arguments: dict) -> str:
    import json

    state = get_state()
    state.ensure_connected()

    schema = state.client.get_agent_schema(arguments["agent_id"])
    return json.dumps({
        "agent_id": str(schema.agent_id),
        "inputs": schema.inputs,
        "outputs": schema.outputs,
    })


def handle_validate_input(arguments: dict) -> str:
    import json
    from gann_sdk import SchemaValidationError

    state = get_state()
    state.ensure_connected()

    try:
        state.client.validate_agent_input(
            arguments["agent_id"],
            arguments["payload"],
            capability=arguments.get("capability"),
            label=arguments.get("label", "input"),
        )
        return json.dumps({"valid": True})
    except SchemaValidationError as exc:
        return json.dumps({"valid": False, "error": str(exc)})
