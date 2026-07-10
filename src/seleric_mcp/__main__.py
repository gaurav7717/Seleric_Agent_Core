"""CLI entrypoint.

  seleric-mcp --transport stdio            # local IDE agents (Claude Code, Cursor)
  seleric-mcp --transport http --port 8765 # remote hosts (Claude.ai, ChatGPT)

Both transports register the identical tool surface.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import structlog

from .config import load_settings
from .observability.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="seleric-mcp")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--skip-drift-check", action="store_true")
    args = parser.parse_args()

    configure_logging(logging.INFO)
    logger = structlog.get_logger()
    settings = load_settings()

    from .gateway.server import build_server

    mcp = build_server(settings)
    ctx = mcp._seleric_ctx  # type: ignore[attr-defined]

    if not args.skip_drift_check:
        from .catalogue_service.validate import validate_against_cube
        from .semantic_layer.cube_client import CubeClient

        async def _drift_check() -> dict:
            # Dedicated client, created AND closed inside this throwaway loop.
            # Reusing ctx.cube here would bind its connection pool to a loop
            # that closes before the server starts ("Event loop is closed" on
            # the first real query).
            tmp = CubeClient(settings)
            try:
                return await validate_against_cube(ctx.catalogue, tmp)
            finally:
                await tmp.aclose()

        drift = asyncio.run(_drift_check())
        logger.info("catalogue_drift_check", **drift)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn

        from .gateway.auth import BearerTokenMiddleware

        if not settings.mcp_service_token:
            raise SystemExit(
                "MCP_SERVICE_TOKEN must be set for the http transport "
                "(stdio is the only unauthenticated mode)."
            )
        app = mcp.streamable_http_app()
        app = BearerTokenMiddleware(app, settings.mcp_service_token)
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
