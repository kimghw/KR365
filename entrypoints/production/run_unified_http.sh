#!/bin/bash
# Unified MCP HTTP Server - Production script for Render.com
# Serves multiple MCP servers on different paths:
# - /mail-query/* - Mail Query MCP Server
# - /enrollment/* - Enrollment MCP Server
# - /onenote/* - OneNote MCP Server

set -e

# Get the project root directory (2 levels up from this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Activate virtual environment if it exists
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
    echo "✅ Virtual environment activated"
fi

# Load .env file if it exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "📄 Loading environment variables from .env file..."
    set -a  # automatically export all variables
    source "$PROJECT_ROOT/.env"
    set +a  # turn off automatic export
    echo "✅ Environment variables loaded from .env"
else
    echo "⚠️ No .env file found at $PROJECT_ROOT/.env"
fi

# Set environment variables
export PYTHONPATH="$PROJECT_ROOT"
export PYTHONDONTWRITEBYTECODE=1

# Default port (can be overridden by environment variable or command line argument)
# Render.com sets PORT automatically
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--port PORT] [--host HOST]"
            exit 1
            ;;
    esac
done

echo "=================================="
echo "🚀 Starting Unified MCP Server"
echo "=================================="
echo "📍 Server URL: http://$HOST:$PORT"
echo "📧 Mail Query: http://$HOST:$PORT/mail-query/"
echo "🔐 Enrollment: http://$HOST:$PORT/enrollment/"
echo "📝 OneNote:    http://$HOST:$PORT/onenote/"
echo "💚 Health:     http://$HOST:$PORT/health"
echo "ℹ️  Info:       http://$HOST:$PORT/info"
echo "=================================="
echo ""

# Create data directory if it doesn't exist (for SQLite databases)
mkdir -p "$PROJECT_ROOT/data"
echo "✅ Data directory: $PROJECT_ROOT/data"

# Verify environment
echo "✅ Python path: $PYTHONPATH"
echo "✅ Working directory: $(pwd)"
echo "🐍 Python executable: $(which python3)"
echo "🐍 Python version: $(python3 --version)"
echo "📦 Python site-packages:"
python3 -c "import sys; print('\n'.join(sys.path))"
echo ""

# Check if required environment variables are set
if [ -z "$ENCRYPTION_KEY" ]; then
    echo "⚠️  WARNING: ENCRYPTION_KEY not set (will be auto-generated)"
fi

# Check DCR environment variables
echo ""
echo "🔍 DCR Configuration Check:"
if [ -n "$DCR_AZURE_CLIENT_ID" ]; then
    echo "✅ DCR_AZURE_CLIENT_ID is set: ${DCR_AZURE_CLIENT_ID:0:8}..."
else
    echo "⚠️ DCR_AZURE_CLIENT_ID is not set"
fi

if [ -n "$DCR_AZURE_CLIENT_SECRET" ]; then
    echo "✅ DCR_AZURE_CLIENT_SECRET is set: ***MASKED***"
else
    echo "⚠️ DCR_AZURE_CLIENT_SECRET is not set"
fi

if [ -n "$DCR_AZURE_TENANT_ID" ]; then
    echo "✅ DCR_AZURE_TENANT_ID is set: ${DCR_AZURE_TENANT_ID:0:8}..."
else
    echo "⚠️ DCR_AZURE_TENANT_ID is not set"
fi

if [ -n "$DCR_OAUTH_REDIRECT_URI" ]; then
    echo "✅ DCR_OAUTH_REDIRECT_URI is set: $DCR_OAUTH_REDIRECT_URI"
else
    echo "⚠️ DCR_OAUTH_REDIRECT_URI is not set"
fi

# Run the unified server
echo "🔥 Starting HTTP server..."
exec python3 "$PROJECT_ROOT/entrypoints/production/unified_http_server.py" \
    --host "$HOST" \
    --port "$PORT"
