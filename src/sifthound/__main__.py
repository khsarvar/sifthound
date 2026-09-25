import argparse
import logging

import anyio
import uvicorn

from .app import create_app, service_context
from .config import get_settings
from .mcp_server import build_mcp


def run_mcp_stdio() -> None:
    """Serve the MCP tools over stdin/stdout for local MCP clients (Claude Desktop, Cursor, ...)."""
    settings = get_settings()
    holder = {}
    mcp = build_mcp(lambda: holder["service"], settings)

    async def main() -> None:
        async with service_context(settings) as holder["service"]:
            await mcp.run_stdio_async()

    anyio.run(main)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Sifthound API server.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["serve", "mcp"],
        default="serve",
        help="'serve' (default) runs the HTTP API with MCP at /mcp; 'mcp' serves MCP over stdio.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    # Logs go to stderr, which matters for `mcp`: stdout carries the protocol.
    logging.basicConfig(level=logging.INFO)
    if args.command == "mcp":
        run_mcp_stdio()
    else:
        uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
