"""gann_create_agent — scaffold, register, and connect a local GANN agent."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..state import get_state
from .connect import handle as handle_connect
from .register import handle as handle_register
from .status import handle_disconnect

FIXED_GANN_TOOLS = [
    "mcp__gann__gann_create_agent",
    "mcp__gann__gann_register_agent",
    "mcp__gann__gann_connect",
    "mcp__gann__gann_disconnect",
    "mcp__gann__gann_status",
    "mcp__gann__gann_search_agents",
    "mcp__gann__gann_send_message",
    "mcp__gann__gann_receive_messages",
    "mcp__gann__gann_reply",
    "mcp__gann__gann_get_schema",
    "mcp__gann__gann_validate_input",
]

TOOL_DEF = {
    "name": "gann_create_agent",
    "description": (
        "Create a Claude Code or Claude Cowork-oriented GANN agent scaffold for the user, "
        "then register it on GANN and connect this session as that agent. Before calling "
        "this tool, ask "
        "the user for the agent name and any specific skills or extra tools they want. "
        "If key inputs are still missing, this tool returns `needs_input=true` and explicit "
        "questions for Claude to ask the user next. Skills and tools can be auto-generated "
        "or provided by the user."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "description": "GANN API key. Optional — falls back to GANN_API_KEY env var.",
            },
            "base_url": {
                "type": "string",
                "description": "GANN server base URL. Optional — falls back to GANN_BASE_URL env var or https://api.gnna.io.",
            },
            "agent_name": {
                "type": "string",
                "description": "Human-readable name for the new agent. Ask the user for this before calling the tool.",
            },
            "description": {
                "type": "string",
                "description": "Short description of what the agent does. If omitted, a default description is generated.",
            },
            "skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of skills/capabilities. If omitted, Claude can auto-generate them.",
            },
            "skills_mode": {
                "type": "string",
                "enum": ["auto", "custom"],
                "description": "Whether skills should be auto-generated or provided by the user.",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of extra Claude tools to allow (for example WebFetch, Bash, Read, Edit). If omitted, tools are inferred when possible.",
            },
            "tools_mode": {
                "type": "string",
                "enum": ["auto", "custom"],
                "description": "Whether extra Claude tools should be auto-generated or provided by the user.",
            },
            "project_dir": {
                "type": "string",
                "description": "Optional directory path for the new local agent project. Defaults to a slugified version of agent_name in the current working directory.",
            },
            "target_runtime": {
                "type": "string",
                "enum": ["claude-code", "claude-cowork"],
                "description": "Which Claude host the scaffold should target. `claude-code` generates a local Claude Code workflow. `claude-cowork` adds a Cowork remote-connector template while still including local smoke-test files.",
                "default": "claude-code",
            },
            "startup_mode": {
                "type": "string",
                "enum": ["auto", "daemon", "interactive"],
                "description": "How the generated agent should start locally. `daemon` creates a background responder loop, `interactive` starts an interactive Claude session, and `auto` picks a sensible default.",
                "default": "auto",
            },
            "prompt": {
                "type": "string",
                "description": "Optional extra operating instructions appended to the generated CLAUDE.md prompt.",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Whether to overwrite an existing scaffold directory if it already exists.",
                "default": False,
            },
            "auto_connect": {
                "type": "boolean",
                "description": "Whether to disconnect any current session and connect this MCP session as the new agent after registration.",
                "default": True,
            },
            "extra_mcp_servers": {
                "type": "object",
                "description": (
                    "Additional MCP server configurations to include in the scaffold's .claude/settings.json. "
                    "Each key is a server name (e.g. 'zapier', 'slack') and the value is an object with "
                    "'command', 'args' (optional), and 'env' (optional) fields — the same format Claude Code uses. "
                    "All tools from these servers are automatically allowed. "
                    "Example: {\"zapier\": {\"command\": \"npx\", \"args\": [\"-y\", \"@anthropic-ai/zapier-mcp-server\"], "
                    "\"env\": {\"ZAPIER_API_KEY\": \"zap_xxx\"}}}"
                ),
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "args": {"type": "array", "items": {"type": "string"}},
                        "env": {"type": "object", "additionalProperties": {"type": "string"}},
                    },
                    "required": ["command"],
                },
            },
            "version": {
                "type": "string",
                "description": "Agent version string passed to registration.",
                "default": "1",
            },
            "summary": {
                "type": "string",
                "description": "Optional short summary stored in the GANN registration record.",
            },
        },
        "required": [],
    },
}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "gann-agent"


def _coerce_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        return [part for part in parts if part]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _default_description(agent_name: str, skills: list[str]) -> str:
    if skills:
        return f"{agent_name} handles {', '.join(skills)} requests over GANN."
    return f"{agent_name} is a Claude-powered GANN agent."


def _normalize_target_runtime(value: object) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "": "claude-code",
        "code": "claude-code",
        "claude-code": "claude-code",
        "cowork": "claude-cowork",
        "claude-cowork": "claude-cowork",
    }
    return aliases.get(normalized, "claude-code")


def _infer_skills(agent_name: str, description: str, provided: list[str]) -> list[str]:
    if provided:
        return provided
    primary = _slugify(agent_name).replace("-", "_")
    inferred = [primary]
    text = f"{agent_name} {description}".lower()
    keyword_map = {
        "research": ["research", "search", "analyze", "analysis"],
        "web_fetching": ["web", "http", "api", "fetch", "baserow"],
        "automation": ["automate", "automation", "workflow"],
        "coding": ["code", "program", "script", "debug", "build", "test"],
    }
    for skill_name, markers in keyword_map.items():
        if any(marker in text for marker in markers):
            inferred.append(skill_name)
    return _dedupe(inferred)


def _infer_tools(description: str, skills: list[str], provided: list[str]) -> list[str]:
    if provided:
        return _dedupe(provided)

    text = f"{description} {' '.join(skills)}".lower()
    inferred: list[str] = []

    if any(marker in text for marker in ["web", "http", "api", "fetch", "baserow", "documentation"]):
        inferred.append("WebFetch")
    if any(marker in text for marker in ["code", "script", "debug", "build", "shell", "test"]):
        inferred.extend(["Bash", "Read", "Edit"])

    return _dedupe(inferred)


def _build_capabilities(skills: list[str], description: str) -> list[dict[str, str]]:
    capabilities: list[dict[str, str]] = []
    for skill in skills:
        capability_name = _slugify(skill).replace("-", "_")
        capabilities.append({
            "name": capability_name,
            "description": f"Supports {skill}. {description}".strip(),
        })
    return capabilities


def _build_input_schema(agent_name: str, skills: list[str]) -> dict:
    skill_text = ", ".join(skills) if skills else "general agent work"
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": f"Action for {agent_name} to perform.",
            },
            "content": {
                "type": "string",
                "description": f"Primary request for the agent. Typical areas: {skill_text}.",
            },
            "context": {
                "type": "object",
                "description": "Optional structured context, references, or metadata.",
            },
        },
        "required": ["action", "content"],
    }


def _build_output_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "error"],
                "description": "Whether the request succeeded.",
            },
            "response": {
                "type": "string",
                "description": "Human-readable response from the agent.",
            },
            "artifacts": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Optional structured artifacts produced by the agent.",
            },
            "error": {
                "type": "string",
                "description": "Error message when status is error.",
            },
        },
        "required": ["status", "response"],
    }


def _resolve_project_path(project_dir: str | None, agent_name: str) -> Path:
    if project_dir:
        path = Path(project_dir).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    return Path.cwd() / _slugify(agent_name)


def _render_settings_json(api_key: str, base_url: str, extra_mcp_servers: dict | None = None) -> str:
    servers: dict = {
        "gann": {
            "command": "claude-gann-mcp",
            "env": {
                "GANN_API_KEY": api_key,
                "GANN_BASE_URL": base_url,
            },
        }
    }
    for name, cfg in (extra_mcp_servers or {}).items():
        entry: dict = {"command": cfg["command"]}
        if cfg.get("args"):
            entry["args"] = cfg["args"]
        if cfg.get("env"):
            entry["env"] = cfg["env"]
        servers[name] = entry
    return json.dumps({"mcpServers": servers}, indent=2) + "\n"


def _render_env_file() -> str:
    anthropic_base_url = os.environ.get("ANTHROPIC_BASE_URL", "http://localhost:8082")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-0000")
    anthropic_auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "00000")
    return (
        f"ANTHROPIC_BASE_URL={anthropic_base_url}\n"
        f"ANTHROPIC_API_KEY={anthropic_api_key}\n"
        f"ANTHROPIC_AUTH_TOKEN={anthropic_auth_token}\n"
    )


def _render_cowork_connector_json(
    agent_name: str,
    agent_id: str,
    description: str,
    skills: list[str],
    base_url: str,
) -> str:
    return json.dumps(
        {
            "display_name": agent_name,
            "target_runtime": "claude-cowork",
            "transport": "remote-mcp",
            "server_url": "https://your-domain.example.com/sse",
            "auth": {
                "type": "bearer",
                "token_env": "GANN_MCP_AUTH_TOKEN",
            },
            "agent": {
                "agent_id": agent_id,
                "description": description,
                "skills": skills,
                "gann_base_url": base_url,
            },
            "deployment": {
                "command": "claude-gann-mcp-remote",
                "args": ["--port", "8090"],
                "env": {
                    "GANN_API_KEY": "<your-gann-api-key>",
                    "GANN_BASE_URL": base_url,
                    "GANN_MCP_AUTH_TOKEN": "<generate-a-secret-token>",
                },
            },
            "notes": [
                "1. Deploy claude-gann-mcp-remote on a server reachable by Cowork.",
                "2. Set the env vars in the deployment section.",
                "3. Put it behind a TLS reverse proxy (nginx, Caddy, Cloudflare Tunnel).",
                "4. Replace server_url above with the actual URL.",
                "5. Add this as a custom MCP connector in Claude Cowork.",
            ],
        },
        indent=2,
    ) + "\n"


def _render_prompt(
    agent_name: str,
    agent_id: str,
    description: str,
    skills: list[str],
    tools: list[str],
    target_runtime: str,
    startup_mode: str,
    extra_prompt: str,
) -> str:
    skill_lines = "\n".join(f"- {skill}" for skill in skills) if skills else "- general_assistance"
    tool_lines = "\n".join(f"- {tool}" for tool in tools) if tools else "- No extra built-in tools beyond the GANN toolset"
    extra_block = f"\n## Extra Instructions\n\n{extra_prompt.strip()}\n" if extra_prompt.strip() else ""

    if target_runtime == "claude-cowork":
        runtime_block = (
            "1. Immediately call gann_connect with agent_id '{agent_id}' to go online.\n"
            "2. Confirm you are connected and ready to receive work.\n"
            "3. Use gann_receive_messages to listen for incoming requests. Prefer wait_timeout when you want blocking behavior.\n"
            "4. This scaffold targets Claude Cowork via a remote MCP connector. Use the included Claude Code launcher files only for local smoke tests before deployment.\n\n"
        ).format(agent_id=agent_id)
    else:
        runtime_block = (
            "1. Immediately call gann_connect with agent_id '{agent_id}' to go online.\n"
            "2. Confirm you are connected and ready to receive work.\n"
            "3. Use gann_receive_messages to listen for incoming requests. Prefer wait_timeout when you want blocking behavior.\n"
            "4. The local launcher for this agent uses `{startup_mode}` mode by default.\n\n"
        ).format(agent_id=agent_id, startup_mode=startup_mode)

    return (
        f"# {agent_name}\n\n"
        f"You are **{agent_name}** operating on the GANN (Global Agentic Neural Network).\n\n"
        f"## Mission\n\n{description}\n\n"
        f"## Skills\n\n{skill_lines}\n\n"
        f"## Preferred Extra Tools\n\n{tool_lines}\n\n"
        f"## Startup\n\n"
        f"{runtime_block}"
        f"## Operating Rules\n\n"
        f"- Handle requests that match your skills.\n"
        f"- Use gann_reply to answer inbound sessions.\n"
        f"- Use gann_search_agents and gann_send_message when collaboration with other agents is useful.\n"
        f"- Keep responses concise, structured, and reliable.\n"
        f"- Use gann_status if connectivity seems wrong.\n"
        f"- Use only the tools available in this session.\n"
        f"- If the user asks for work outside your scope, say so clearly.\n"
        f"{extra_block}"
    )


def _infer_startup_mode(agent_name: str, description: str, skills: list[str], requested_mode: str) -> str:
    if requested_mode in {"daemon", "interactive"}:
        return requested_mode

    text = f"{agent_name} {description} {' '.join(skills)}".lower()
    daemon_markers = [
        "listen",
        "listener",
        "monitor",
        "receive",
        "reply",
        "worker",
        "daemon",
        "service",
        "automation",
        "background",
        "supplier",
        "component",
        "responder",
        "webhook",
        "queue",
    ]
    interactive_markers = [
        "chat",
        "assistant",
        "copilot",
        "reviewer",
        "interactive",
        "generalbot",
    ]

    if any(marker in text for marker in interactive_markers):
        return "interactive"
    if any(marker in text for marker in daemon_markers):
        return "daemon"
    return "daemon"


def _extra_mcp_tool_patterns(extra_mcp_server_names: list[str]) -> list[str]:
    """Return wildcard --allowedTools patterns for every extra MCP server."""
    return [f"mcp__{name}__*" for name in extra_mcp_server_names]


def _render_start_sh(agent_id: str, extra_tools: list[str], startup_mode: str, extra_mcp_server_names: list[str] | None = None) -> str:
    all_extra = list(extra_tools) + _extra_mcp_tool_patterns(extra_mcp_server_names or [])
    extra_tools_csv = ",".join(all_extra)
    if startup_mode == "interactive":
        return f"""#!/bin/bash
# Start the scaffolded GANN agent using Claude Code CLI

set -e

AGENT_ID="${{1:-{agent_id}}}"
BASE_TOOLS="{','.join(FIXED_GANN_TOOLS)}"
EXTRA_TOOLS="{extra_tools_csv}"

if [ -n "$EXTRA_TOOLS" ]; then
  ALLOWED_TOOLS="$BASE_TOOLS,$EXTRA_TOOLS"
else
  ALLOWED_TOOLS="$BASE_TOOLS"
fi

cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

CLAUDE_BIN="${{CLAUDE_BIN:-$(command -v /opt/homebrew/bin/claude 2>/dev/null || command -v claude)}}"
SYSTEM_PROMPT="$(cat CLAUDE.md)"

echo "=== GANN Agent ==="
echo "Agent ID: $AGENT_ID"
echo "GANN:     ${{GANN_BASE_URL:-https://api.gnna.io}}"
echo "Claude:   $CLAUDE_BIN"
echo "Mode:     interactive"
echo ""

exec "$CLAUDE_BIN" \
  --mcp-config .claude/settings.json \
  --allowedTools "$ALLOWED_TOOLS" \
  --system-prompt "$SYSTEM_PROMPT"
"""

        return f"""#!/bin/bash
# Start the scaffolded GANN agent as a background daemon loop

set -e

AGENT_ID="${{1:-{agent_id}}}"
BASE_TOOLS="{','.join(FIXED_GANN_TOOLS)}"
EXTRA_TOOLS="{extra_tools_csv}"

if [ -n "$EXTRA_TOOLS" ]; then
    ALLOWED_TOOLS="$BASE_TOOLS,$EXTRA_TOOLS"
else
    ALLOWED_TOOLS="$BASE_TOOLS"
fi

cd "$(dirname "$0")"

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

CLAUDE_BIN="${{CLAUDE_BIN:-$(command -v /opt/homebrew/bin/claude 2>/dev/null || command -v claude)}}"
SYSTEM_PROMPT="$(cat CLAUDE.md)"

echo "=== GANN Agent ==="
echo "Agent ID: $AGENT_ID"
echo "GANN:     ${{GANN_BASE_URL:-https://api.gnna.io}}"
echo "Claude:   $CLAUDE_BIN"
echo "Mode:     daemon"
echo ""
echo "Running in background loop. Press Ctrl+C to stop."
echo ""

trap 'echo ""; echo "Shutting down..."; exit 0' INT TERM

while true; do
    echo "[$(date '+%H:%M:%S')] Connecting and waiting for messages..."
    "$CLAUDE_BIN" --print \
        --mcp-config .claude/settings.json \
        --allowedTools "$ALLOWED_TOOLS" \
        -p "$SYSTEM_PROMPT\n\nExecute these steps:\n1. Call gann_connect with agent_id '$AGENT_ID'.\n2. Call gann_receive_messages with wait_timeout set to 120.\n3. If you receive a message, process it according to your role and reply using gann_reply.\n4. Call gann_disconnect." 2>&1 | while IFS= read -r line; do
            echo "[$(date '+%H:%M:%S')] $line"
        done

    echo "[$(date '+%H:%M:%S')] Cycle complete. Reconnecting in 5s..."
    sleep 5
done
"""


def _render_chat_sh(agent_id: str, extra_tools: list[str], extra_mcp_server_names: list[str] | None = None) -> str:
    all_extra = list(extra_tools) + _extra_mcp_tool_patterns(extra_mcp_server_names or [])
    extra_tools_csv = ",".join(all_extra)
    return f"""#!/bin/bash
# Start the scaffolded GANN agent in interactive mode

set -e

AGENT_ID="${{1:-{agent_id}}}"
BASE_TOOLS="{','.join(FIXED_GANN_TOOLS)}"
EXTRA_TOOLS="{extra_tools_csv}"

if [ -n "$EXTRA_TOOLS" ]; then
    ALLOWED_TOOLS="$BASE_TOOLS,$EXTRA_TOOLS"
else
    ALLOWED_TOOLS="$BASE_TOOLS"
fi

cd "$(dirname "$0")"

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

CLAUDE_BIN="${{CLAUDE_BIN:-$(command -v /opt/homebrew/bin/claude 2>/dev/null || command -v claude)}}"
SYSTEM_PROMPT="$(cat CLAUDE.md)"

exec "$CLAUDE_BIN" \
    --mcp-config .claude/settings.json \
    --allowedTools "$ALLOWED_TOOLS" \
    --system-prompt "$SYSTEM_PROMPT"
"""


def _render_readme(
    agent_name: str,
    agent_id: str,
    description: str,
    skills: list[str],
    tools: list[str],
    target_runtime: str,
    startup_mode: str,
) -> str:
    skills_text = ", ".join(skills) if skills else "general assistance"
    tools_text = ", ".join(tools) if tools else "no extra built-in tools"
    default_launcher = "./start.sh"
    alternate_launcher = "./chat.sh" if startup_mode == "daemon" else "./start.sh"

    if target_runtime == "claude-cowork":
        file_list = (
            "- `CLAUDE.md`: system instructions for the agent\n"
            "- `.claude/settings.json`: Claude Code MCP config for local smoke tests\n"
            "- `.env`: local Anthropic/Claude proxy environment variables\n"
            "- `start.sh`: local smoke-test launcher for this agent\n"
            "- `chat.sh`: local interactive smoke-test launcher\n"
            "- `cowork-connector.json`: template metadata for a Claude Cowork remote MCP connector\n"
            "- `agent.json`: scaffold metadata and generated schemas\n"
        )
        run_block = (
            "Local smoke test:\n\n"
            f"```bash\n{default_launcher}\n```\n\n"
            "Claude Cowork deployment:\n\n"
            "```bash\n"
            "# 1. Install the plugin on your server\n"
            "pip install claude-gann-plugin\n\n"
            "# 2. Set environment variables\n"
            "export GANN_API_KEY=\"your-gann-api-key\"\n"
            "export GANN_BASE_URL=\"https://api.gnna.io\"\n"
            "export GANN_MCP_AUTH_TOKEN=\"generate-a-secret-token\"\n\n"
            "# 3. Start the remote MCP server\n"
            "claude-gann-mcp-remote --port 8090\n"
            "```\n\n"
            "Then:\n\n"
            "1. Put the server behind a TLS reverse proxy (nginx, Caddy, Cloudflare Tunnel).\n"
            "2. Update `server_url` in `cowork-connector.json` to the public URL (e.g. `https://mcp.example.com/sse`).\n"
            "3. Add the remote MCP URL as a custom connector in Claude Cowork.\n"
        )
        notes_block = (
            f"- Description: {description}\n"
            "- Claude Cowork supports remote MCP connectors, not local stdio MCP servers.\n"
            "- `claude-gann-mcp-remote` wraps the same 11 GANN tools as SSE or Streamable HTTP.\n"
            "- Use `--transport streamable-http` for the newer MCP transport spec.\n"
            "- Set `GANN_MCP_AUTH_TOKEN` to protect the endpoint with bearer-token auth.\n"
            f"- Use `{default_launcher}` or `./chat.sh` only for local smoke tests before remote deployment.\n"
            "- If you regenerate this scaffold, use `overwrite=true`.\n"
            "- Make sure the user enables the required GANN agent subscription at `https://console.gnna.io`.\n"
        )
    else:
        file_list = (
            "- `CLAUDE.md`: system instructions for the agent\n"
            "- `.claude/settings.json`: MCP configuration for the GANN plugin\n"
            "- `.env`: local Anthropic/Claude proxy environment variables\n"
            "- `start.sh`: primary launcher for this agent\n"
            "- `chat.sh`: always-available interactive launcher\n"
            "- `agent.json`: scaffold metadata and generated schemas\n"
        )
        run_block = (
            "Default mode:\n\n"
            f"```bash\n{default_launcher}\n```\n\n"
            "Interactive chat mode:\n\n"
            "```bash\n./chat.sh\n```\n\n"
        )
        notes_block = (
            f"- Description: {description}\n"
            "- If you regenerate this scaffold, use `overwrite=true`.\n"
            "- Make sure the user enables the required GANN agent subscription at `https://console.gnna.io`.\n"
            f"- If the agent should run continuously, keep `{default_launcher}` running in its own terminal.\n"
            f"- If you want to inspect or guide the agent manually, use `{alternate_launcher}`.\n"
        )

    return (
        f"# {agent_name}\n\n"
        f"This folder was generated by `gann_create_agent`. It contains a GANN agent scaffold targeting `{target_runtime}`.\n\n"
        f"## Overview\n\n"
        f"- Agent name: `{agent_name}`\n"
        f"- Agent ID: `{agent_id}`\n"
        f"- Target runtime: `{target_runtime}`\n"
        f"- Startup mode: `{startup_mode}`\n"
        f"- Skills: {skills_text}\n"
        f"- Extra Claude tools: {tools_text}\n\n"
        f"## Files\n\n"
        f"{file_list}\n"
        f"## Run\n\n"
        f"{run_block}"
        f"## Notes\n\n"
        f"{notes_block}"
    )


def _write_scaffold(
    project_path: Path,
    *,
    overwrite: bool,
    settings_json: str,
    env_text: str,
    prompt_text: str,
    readme_text: str,
    start_sh: str,
    chat_sh: str,
    cowork_connector_json: str | None,
    metadata: dict,
) -> list[str]:
    if project_path.exists() and any(project_path.iterdir()) and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing directory: {project_path}. Pass overwrite=true to replace scaffold files."
        )

    (project_path / ".claude").mkdir(parents=True, exist_ok=True)

    files = {
        project_path / ".claude" / "settings.json": settings_json,
        project_path / ".env": env_text,
        project_path / "CLAUDE.md": prompt_text,
        project_path / "README.md": readme_text,
        project_path / "start.sh": start_sh,
        project_path / "chat.sh": chat_sh,
        project_path / "agent.json": json.dumps(metadata, indent=2) + "\n",
    }
    if cowork_connector_json is not None:
        files[project_path / "cowork-connector.json"] = cowork_connector_json

    for file_path, content in files.items():
        file_path.write_text(content, encoding="utf-8")

    os.chmod(project_path / "start.sh", 0o755)
    os.chmod(project_path / "chat.sh", 0o755)
    return [str(path) for path in files]


def _parse_json_result(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw}


def _wizard_questions(
    *,
    agent_name: str,
    skills_mode: str,
    provided_skills: list[str],
    tools_mode: str,
    provided_tools: list[str],
) -> list[dict[str, str]]:
    questions: list[dict[str, str]] = []
    if not agent_name:
        questions.append({
            "field": "agent_name",
            "question": "What should the new agent be called?",
        })
    if not skills_mode:
        questions.append({
            "field": "skills_mode",
            "question": "Should I auto-generate the agent skills or do you want to provide them? Reply with 'auto' or 'custom'.",
        })
    elif skills_mode == "custom" and not provided_skills:
        questions.append({
            "field": "skills",
            "question": "List the skills or capabilities this agent should have.",
        })

    if not tools_mode:
        questions.append({
            "field": "tools_mode",
            "question": "Should I auto-select extra Claude tools for this agent or do you want to provide them? Reply with 'auto' or 'custom'.",
        })
    elif tools_mode == "custom" and not provided_tools:
        questions.append({
            "field": "tools",
            "question": "List any extra Claude tools this agent should be allowed to use, for example WebFetch, Bash, Read, or Edit.",
        })

    return questions


def handle(arguments: dict) -> str:
    api_key = arguments.get("api_key") or os.environ.get("GANN_API_KEY") or ""
    base_url = arguments.get("base_url") or os.environ.get("GANN_BASE_URL") or "https://api.gnna.io"
    agent_name = str(arguments.get("agent_name") or "").strip()
    provided_description = str(arguments.get("description") or "").strip()
    extra_mcp_servers: dict = arguments.get("extra_mcp_servers") or {}
    extra_mcp_names = list(extra_mcp_servers.keys())
    provided_skills = _coerce_string_list(arguments.get("skills"))
    provided_tools = _coerce_string_list(arguments.get("tools"))
    skills_mode = str(arguments.get("skills_mode") or "").strip().lower()
    tools_mode = str(arguments.get("tools_mode") or "").strip().lower()
    extra_prompt = str(arguments.get("prompt") or "")
    target_runtime = _normalize_target_runtime(arguments.get("target_runtime"))
    startup_mode = _infer_startup_mode(
        agent_name,
        provided_description,
        provided_skills,
        str(arguments.get("startup_mode") or "auto").strip().lower(),
    )
    overwrite = bool(arguments.get("overwrite", False))
    auto_connect = bool(arguments.get("auto_connect", True))
    version = str(arguments.get("version") or "1")
    summary = str(arguments.get("summary") or "").strip()

    if provided_skills and not skills_mode:
        skills_mode = "custom"
    if provided_tools and not tools_mode:
        tools_mode = "custom"

    wizard_questions = _wizard_questions(
        agent_name=agent_name,
        skills_mode=skills_mode,
        provided_skills=provided_skills,
        tools_mode=tools_mode,
        provided_tools=provided_tools,
    )
    if wizard_questions:
        return json.dumps({
            "created": False,
            "needs_input": True,
            "message": "More user input is needed before the agent can be scaffolded.",
            "questions": wizard_questions,
            "current_values": {
                "agent_name": agent_name or None,
                "skills_mode": skills_mode or None,
                "skills": provided_skills,
                "tools_mode": tools_mode or None,
                "tools": provided_tools,
            },
        })

    if not api_key:
        return json.dumps({
            "created": False,
            "error": "No API key provided. Pass api_key or set GANN_API_KEY env var.",
        })

    description = provided_description or _default_description(agent_name, provided_skills)
    skills = provided_skills if skills_mode == "custom" else _infer_skills(agent_name, description, provided_skills)
    tools = provided_tools if tools_mode == "custom" else _infer_tools(description, skills, provided_tools)
    capabilities = _build_capabilities(skills, description)
    inputs = _build_input_schema(agent_name, skills)
    outputs = _build_output_schema()

    register_payload = {
        "api_key": api_key,
        "base_url": base_url,
        "agent_name": agent_name,
        "description": description,
        "capabilities": capabilities,
        "inputs": inputs,
        "outputs": outputs,
        "version": version,
    }
    if summary:
        register_payload["summary"] = summary

    register_result = _parse_json_result(handle_register(register_payload))
    if not register_result.get("registered"):
        return json.dumps({
            "created": False,
            "registered": False,
            "error": register_result.get("error") or "Agent registration failed.",
            "agent_name": agent_name,
        })

    agent_id = str(register_result.get("agent_id") or "")
    project_path = _resolve_project_path(arguments.get("project_dir"), agent_name)

    metadata = {
        "agent_name": agent_name,
        "agent_id": agent_id,
        "description": description,
        "target_runtime": target_runtime,
        "startup_mode": startup_mode,
        "skills": skills,
        "tools": tools,
        "capabilities": capabilities,
        "inputs": inputs,
        "outputs": outputs,
        "base_url": base_url,
        "extra_mcp_servers": extra_mcp_servers if extra_mcp_servers else None,
        "subscription_required": True,
        "subscription_message": "Make sure the user purchases or enables a GANN agent subscription at https://console.gnna.io so the new agent can remain active.",
    }

    try:
        files = _write_scaffold(
            project_path,
            overwrite=overwrite,
            settings_json=_render_settings_json(api_key, base_url, extra_mcp_servers or None),
            env_text=_render_env_file(),
            prompt_text=_render_prompt(agent_name, agent_id, description, skills, tools, target_runtime, startup_mode, extra_prompt),
            readme_text=_render_readme(agent_name, agent_id, description, skills, tools, target_runtime, startup_mode),
            start_sh=_render_start_sh(agent_id, tools, startup_mode, extra_mcp_names),
            chat_sh=_render_chat_sh(agent_id, tools, extra_mcp_names),
            cowork_connector_json=(
                _render_cowork_connector_json(agent_name, agent_id, description, skills, base_url)
                if target_runtime == "claude-cowork"
                else None
            ),
            metadata=metadata,
        )
    except Exception as exc:
        return json.dumps({
            "created": False,
            "registered": True,
            "agent_id": agent_id,
            "error": str(exc),
        })

    connect_result: dict = {"connected": False, "message": "auto_connect disabled"}
    if auto_connect:
        state = get_state()
        if state.connected:
            handle_disconnect({})
        connect_result = _parse_json_result(handle_connect({
            "api_key": api_key,
            "base_url": base_url,
            "agent_id": agent_id,
        }))

    result = {
        "created": True,
        "registered": True,
        "connected": bool(connect_result.get("connected", False)),
        "agent_name": agent_name,
        "agent_id": agent_id,
        "project_path": str(project_path),
        "files": files,
        "target_runtime": target_runtime,
        "startup_mode": startup_mode,
        "skills": skills,
        "tools": tools,
        "extra_mcp_servers": list(extra_mcp_servers.keys()) if extra_mcp_servers else [],
        "message": (
            f"Created a {target_runtime} scaffold for '{agent_name}', registered it on GANN, "
            f"and {'connected this session as the new agent' if connect_result.get('connected') else 'left it disconnected'}."
        ),
        "subscription_reminder": "Tell the user to purchase or enable a GANN agent subscription at https://console.gnna.io.",
        "next_steps": (
            [
                f"cd {project_path}",
                "Review CLAUDE.md, agent.json, and cowork-connector.json.",
                f"Run ./start.sh to smoke-test the agent locally in {startup_mode} mode.",
                "Replace the placeholder server_url in cowork-connector.json.",
                "Deploy claude-gann-mcp-remote on a server with TLS (see README.md for instructions).",
                "Add the remote MCP URL as a custom connector in Claude Cowork.",
                "Purchase or enable the GANN agent subscription at https://console.gnna.io.",
            ]
            if target_runtime == "claude-cowork"
            else [
                f"cd {project_path}",
                "Review CLAUDE.md and agent.json.",
                f"Run ./start.sh to launch the scaffolded local agent in {startup_mode} mode.",
                "Run ./chat.sh if you want an interactive Claude session for the same agent.",
                "Purchase or enable the GANN agent subscription at https://console.gnna.io.",
            ]
        ),
        "connect_result": connect_result,
    }
    return json.dumps(result)