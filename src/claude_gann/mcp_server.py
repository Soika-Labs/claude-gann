"""
MCP Server entry point for the Claude Code GANN plugin.

Run directly:   claude-gann-mcp          (registered as console_scripts entry)
Or via Python:   python -m claude_gann.mcp_server

The server exposes 11 tools over MCP stdio transport:
    gann_create_agent, gann_register_agent, gann_connect, gann_disconnect, gann_status,
  gann_search_agents, gann_get_schema, gann_validate_input,
  gann_send_message, gann_receive_messages, gann_reply
"""
from __future__ import annotations

import asyncio
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .tools.create_agent import TOOL_DEF as CREATE_AGENT_DEF, handle as handle_create_agent
from .tools.register import TOOL_DEF as REGISTER_DEF, handle as handle_register
from .tools.connect import TOOL_DEF as CONNECT_DEF, handle as handle_connect
from .tools.search import TOOL_DEF as SEARCH_DEF, handle as handle_search
from .tools.messaging import (
    SEND_TOOL_DEF,
    RECEIVE_TOOL_DEF,
    REPLY_TOOL_DEF,
    handle_send,
    handle_receive,
    handle_reply,
)
from .tools.schema import (
    GET_SCHEMA_DEF,
    VALIDATE_INPUT_DEF,
    handle_get_schema,
    handle_validate_input,
)
from .tools.status import (
    STATUS_DEF,
    DISCONNECT_DEF,
    handle_status,
    handle_disconnect,
)

logger = logging.getLogger("gann.mcp")

# Build the tool catalogue ------------------------------------------------

_TOOLS: list[dict] = [
    CREATE_AGENT_DEF,
    REGISTER_DEF,
    CONNECT_DEF,
    SEARCH_DEF,
    SEND_TOOL_DEF,
    RECEIVE_TOOL_DEF,
    REPLY_TOOL_DEF,
    GET_SCHEMA_DEF,
    VALIDATE_INPUT_DEF,
    STATUS_DEF,
    DISCONNECT_DEF,
]

_HANDLERS: dict[str, object] = {
    "gann_create_agent": handle_create_agent,
    "gann_register_agent": handle_register,
    "gann_connect": handle_connect,
    "gann_search_agents": handle_search,
    "gann_send_message": handle_send,
    "gann_receive_messages": handle_receive,
    "gann_reply": handle_reply,
    "gann_get_schema": handle_get_schema,
    "gann_validate_input": handle_validate_input,
    "gann_status": handle_status,
    "gann_disconnect": handle_disconnect,
}


def _build_server() -> Server:
    server = Server("gann")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in _TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        handler = _HANDLERS.get(name)
        if handler is None:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        try:
            result = handler(arguments)  # type: ignore[operator]
            return [TextContent(type="text", text=result)]
        except Exception as exc:
            logger.exception("tool %s failed", name)
            return [TextContent(type="text", text=f"Error: {exc}")]

    return server


async def _run() -> None:
    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    import os, sys
    log_path = os.environ.get("CLAUDE_GANN_LOG_FILE") or os.path.join(
        os.path.expanduser("~"), ".claude-gann-mcp.log"
    )
    fmt = "%(asctime)s %(name)s %(levelname)s %(message)s"
    handlers = [logging.FileHandler(log_path, mode="a")]
    # Also emit to stderr so a parent that captures it can see it.
    handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.DEBUG, format=fmt, handlers=handlers)
    logging.getLogger("gann").setLevel(logging.DEBUG)
    logging.getLogger("gann.quic").setLevel(logging.DEBUG)
    logging.getLogger("gann.mcp").info("claude-gann MCP starting; log_file=%s", log_path)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
