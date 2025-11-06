#!/usr/bin/env python3
"""Standalone Web Dashboard Server for MailQueryWithMCP Management

This server runs independently from the unified MCP server and provides
a web interface for managing the system.
"""

import argparse
import os
import sys
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.web_dashboard.dashboard import create_dashboard_routes
from infra.core.logger import get_logger

logger = get_logger(__name__)


def create_standalone_app():
    """Create standalone dashboard application"""
    # Get dashboard routes
    dashboard_routes = create_dashboard_routes()

    # Create Starlette app
    app = Starlette(routes=dashboard_routes)

    return app


def main():
    """Main entry point for standalone dashboard server"""
    parser = argparse.ArgumentParser(description="Standalone Web Dashboard Server")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("DASHBOARD_PORT", "9000")),
        help="Port for dashboard server (default: 9000)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("DASHBOARD_HOST", "0.0.0.0"),
        help="Host for dashboard server (default: 0.0.0.0)",
    )

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info(f"🚀 Starting Standalone Web Dashboard Server")
    logger.info(f"📁 Project root: {PROJECT_ROOT}")
    logger.info(f"🌐 Server will listen on http://{args.host}:{args.port}")
    logger.info("=" * 80)
    logger.info(f"📊 Dashboard: http://{args.host}:{args.port}/dashboard")
    logger.info("=" * 80)

    # Create and run app
    app = create_standalone_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
