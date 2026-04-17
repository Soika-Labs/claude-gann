"""gann_register_agent — register a new agent on the GANN network."""
from __future__ import annotations

import json
import os

import requests

TOOL_DEF = {
    "name": "gann_register_agent",
    "description": (
        "Register a new agent on the GANN network. Returns the agent_id which you "
        "need for gann_connect. The agent's input/output schemas describe what "
        "payloads this agent accepts and returns."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "description": "GANN API key. Falls back to GANN_API_KEY env var.",
            },
            "base_url": {
                "type": "string",
                "description": "GANN server base URL. Falls back to GANN_BASE_URL env var or https://api.gnna.io.",
            },
            "agent_name": {
                "type": "string",
                "description": "Human-readable name for the agent (must be unique per owner).",
            },
            "description": {
                "type": "string",
                "description": "What this agent does.",
            },
            "capabilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Capability identifier (e.g. 'code_review').",
                        },
                        "description": {
                            "type": "string",
                            "description": "What this capability does.",
                        },
                    },
                    "required": ["name", "description"],
                },
                "description": "List of capabilities this agent exposes.",
            },
            "inputs": {
                "type": "object",
                "description": "JSON Schema describing the payloads this agent accepts.",
            },
            "outputs": {
                "type": "object",
                "description": "JSON Schema describing the payloads this agent returns.",
            },
            "agent_type": {
                "type": "string",
                "description": "Agent type (default 'task'). Cannot be 'proxy'.",
                "default": "task",
            },
            "version": {
                "type": "string",
                "description": "Agent version string (default '1').",
                "default": "1",
            },
            "summary": {
                "type": "string",
                "description": "Short summary (optional).",
            },
        },
        "required": ["agent_name", "description", "capabilities", "inputs", "outputs"],
    },
}


def handle(arguments: dict) -> str:
    api_key = arguments.get("api_key") or os.environ.get("GANN_API_KEY") or ""
    base_url = arguments.get("base_url") or os.environ.get("GANN_BASE_URL") or "https://api.gnna.io"

    if not api_key:
        return json.dumps({
            "registered": False,
            "error": "No API key provided. Pass api_key or set GANN_API_KEY env var.",
        })

    agent_name = arguments.get("agent_name", "").strip()
    description = arguments.get("description", "").strip()
    capabilities = arguments.get("capabilities")
    inputs = arguments.get("inputs")
    outputs = arguments.get("outputs")

    if not agent_name:
        return json.dumps({"registered": False, "error": "agent_name is required and cannot be empty."})
    if not description:
        return json.dumps({"registered": False, "error": "description is required and cannot be empty."})
    if not capabilities or not isinstance(capabilities, list):
        return json.dumps({"registered": False, "error": "capabilities must be a non-empty array."})
    if not inputs or not isinstance(inputs, dict):
        return json.dumps({"registered": False, "error": "inputs must be a JSON object (schema)."})
    if not outputs or not isinstance(outputs, dict):
        return json.dumps({"registered": False, "error": "outputs must be a JSON object (schema)."})

    body: dict = {
        "agent_name": agent_name,
        "description": description,
        "capabilities": capabilities,
        "inputs": inputs,
        "outputs": outputs,
    }

    # Optional fields
    agent_type = arguments.get("agent_type")
    if agent_type:
        body["agent_type"] = agent_type
    version = arguments.get("version")
    if version:
        body["version"] = version
    summary = arguments.get("summary")
    if summary:
        body["summary"] = summary

    url = base_url.rstrip("/") + "/.gann/register"
    try:
        resp = requests.post(
            url,
            json=body,
            headers={
                "GANN-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return json.dumps({
            "registered": True,
            "agent_id": data.get("agent_id"),
            "status": data.get("status"),
            "heartbeat_interval": data.get("heartbeat_interval"),
            "message": (
                f"Agent '{agent_name}' registered successfully. "
                f"Use agent_id '{data.get('agent_id')}' with gann_connect to go online."
            ),
        })
    except requests.HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.response.text  # type: ignore[union-attr]
        except Exception:
            pass
        return json.dumps({
            "registered": False,
            "error": f"HTTP {exc.response.status_code}: {error_body}" if exc.response is not None else str(exc),
        })
    except Exception as exc:
        return json.dumps({"registered": False, "error": str(exc)})
