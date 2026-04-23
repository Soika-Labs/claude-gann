"""
Remote MCP Server for Claude Cowork / HTTP clients.

Run directly:   claude-gann-mcp-remote                     (SSE on 0.0.0.0:8090)
With options:    claude-gann-mcp-remote --port 9000 --host 127.0.0.1
Streamable HTTP: claude-gann-mcp-remote --transport streamable-http

This exposes the same 11 GANN tools as the stdio server, but over
HTTP+SSE or Streamable HTTP so Claude Cowork (and other remote MCP
clients) can connect.

Deployment: run behind a reverse proxy (nginx, Caddy, Cloudflare Tunnel)
with TLS termination, then point the Cowork connector's server_url here.
"""
from __future__ import annotations

import argparse
import logging
import os

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .mcp_server import _build_server

logger = logging.getLogger("gann.mcp.remote")

# ---------------------------------------------------------------------------
# Bearer-token auth (optional but recommended)
# ---------------------------------------------------------------------------

_AUTH_TOKEN = os.environ.get("GANN_MCP_AUTH_TOKEN", "")


def _check_auth(request: Request) -> bool:
    """Return True if the request is authorized."""
    if not _AUTH_TOKEN:
        return True  # no token configured — allow all
    auth = request.headers.get("authorization", "")
    return auth == f"Bearer {_AUTH_TOKEN}"


# ---------------------------------------------------------------------------
# SSE transport app
# ---------------------------------------------------------------------------

def _build_sse_app() -> Starlette:
    from mcp.server.sse import SseServerTransport

    mcp = _build_server()
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        if not _check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        async with sse.connect_sse(
            request.scope, request.receive, request._send  # type: ignore[arg-type]
        ) as (read_stream, write_stream):
            await mcp.run(read_stream, write_stream, mcp.create_initialization_options())

    async def handle_messages(request: Request):
        if not _check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        await sse.handle_post_message(request.scope, request.receive, request._send)  # type: ignore[arg-type]

    async def health(request: Request):
        return JSONResponse({"status": "ok", "transport": "sse", "server": "gann"})

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages/", endpoint=handle_messages, methods=["POST"]),
            Route("/health", endpoint=health),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["GET", "POST"],
                allow_headers=["*"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Streamable HTTP transport app
# ---------------------------------------------------------------------------

def _build_streamable_http_app() -> Starlette:
    from mcp.server.streamable_http import StreamableHTTPServerTransport
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    mcp = _build_server()

    async def _create_transport() -> StreamableHTTPServerTransport:
        return StreamableHTTPServerTransport(mcp_session_id=None)

    session_manager = StreamableHTTPSessionManager(
        app=mcp,
        create_transport=_create_transport,
    )

    async def handle_mcp(request: Request):
        if not _check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        await session_manager.handle_request(request.scope, request.receive, request._send)  # type: ignore[arg-type]

    async def health(request: Request):
        return JSONResponse({"status": "ok", "transport": "streamable-http", "server": "gann"})

    async def on_startup():
        await session_manager.run()

    async def on_shutdown():
        pass

    return Starlette(
        routes=[
            Route("/mcp", endpoint=handle_mcp, methods=["GET", "POST", "DELETE"]),
            Route("/health", endpoint=health),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["GET", "POST", "DELETE"],
                allow_headers=["*"],
            ),
        ],
        on_startup=[on_startup],
        on_shutdown=[on_shutdown],
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the GANN MCP server as a remote HTTP endpoint for Claude Cowork"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8090, help="Port (default: 8090)")
    parser.add_argument(
        "--transport",
        choices=["sse", "streamable-http"],
        default="sse",
        help="MCP transport to use (default: sse)",
    )
    parser.add_argument("--log-level", default="info", help="Log level (default: info)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(name)s %(levelname)s %(message)s",
    )

    if args.transport == "streamable-http":
        app = _build_streamable_http_app()
        logger.info("Starting GANN MCP remote server (streamable-http) on %s:%d", args.host, args.port)
    else:
        app = _build_sse_app()
        logger.info("Starting GANN MCP remote server (SSE) on %s:%d", args.host, args.port)

    if _AUTH_TOKEN:
        logger.info("Bearer-token auth enabled (GANN_MCP_AUTH_TOKEN is set)")
    else:
        logger.warning("No GANN_MCP_AUTH_TOKEN set — running without auth. Set this env var in production!")

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
