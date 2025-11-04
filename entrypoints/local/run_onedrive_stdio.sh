#!/bin/bash
# OneDrive MCP Server - STDIO mode for Claude Desktop

# Get the project root directory (2 levels up from this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Set environment variables
export PYTHONPATH="$PROJECT_ROOT"
export PYTHONDONTWRITEBYTECODE=1
export ENABLE_CONSOLE_LOGGING=false

# Run the OneDrive MCP server in STDIO mode
exec python3 "$PROJECT_ROOT/modules/onedrive_mcp/entrypoints/stdio_server.py"
