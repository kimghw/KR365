#!/usr/bin/env python3
"""Mail Query MCP - HTTP MCP Server

Entry point for running the Mail Query MCP server in HTTP mode.
"""

import sys
import os
import argparse
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.mail_query_MCP.implementations.starlette_server import HTTPStreamingMailAttachmentServer
from infra.core.logger import get_logger

logger = get_logger(__name__)


def main():
    """Main entry point for HTTP MCP server"""
    parser = argparse.ArgumentParser(description="Mail Query MCP HTTP Server")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT") or os.getenv("PORT") or "8001"),
        help="Port for HTTP server (default: 8001, or MCP_PORT/PORT env var)"
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST") or "0.0.0.0",
        help="Host for HTTP server (default: 0.0.0.0, or MCP_HOST env var)"
    )

    args = parser.parse_args()

    logger.info("🚀 Starting Mail Query MCP HTTP Server")
    logger.info(f"📁 Project root: {PROJECT_ROOT}")
    logger.info(f"🌐 Server will listen on {args.host}:{args.port}")

    # Create and run server
    server = HTTPStreamingMailAttachmentServer(host=args.host, port=args.port)
    server.run()


if __name__ == "__main__":
    main()
