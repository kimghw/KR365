#!/bin/bash
# Stop all MCP dashboard and FastAPI services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "════════════════════════════════════════════════════"
echo "🛑 Stopping ALL MCP Services"
echo "════════════════════════════════════════════════════"
echo ""

# Stop all FastAPI servers
echo "⏹️  Stopping all FastAPI servers..."

# Kill all FastAPI processes by script name
pkill -f "run_fastapi.py" 2>/dev/null

# Kill processes on known ports
for port in 8001 8002 8003 8004 8005; do
    if lsof -i :$port > /dev/null 2>&1; then
        echo "   Stopping service on port $port..."
        lsof -i :$port | grep LISTEN | awk '{print $2}' | xargs -r kill -9 2>/dev/null
    fi
done

# Remove PID files
rm -f /tmp/*_fastapi.pid 2>/dev/null

echo "✅ All FastAPI servers stopped"
echo ""

# Stop dashboard server
echo "⏹️  Stopping Dashboard server..."

# Kill dashboard process
pkill -f "standalone_server.py" 2>/dev/null
pkill -f "dashboard_enhanced.py" 2>/dev/null

# Kill process on dashboard port
if lsof -i :8000 > /dev/null 2>&1; then
    lsof -i :8000 | grep LISTEN | awk '{print $2}' | xargs -r kill -9 2>/dev/null
fi

# Remove dashboard PID file
rm -f /tmp/dashboard_server.pid 2>/dev/null

echo "✅ Dashboard server stopped"
echo ""

# Check for any remaining Python processes
echo "🔍 Checking for remaining services..."
REMAINING=0

# Check common ports
for port in 8000 8001 8002 8003; do
    if lsof -i :$port > /dev/null 2>&1; then
        echo "   ⚠️  Port $port still in use"
        REMAINING=$((REMAINING + 1))
    fi
done

# Check for specific processes
if pgrep -f "run_fastapi.py" > /dev/null 2>&1; then
    echo "   ⚠️  Some FastAPI processes still running"
    REMAINING=$((REMAINING + 1))
fi

if pgrep -f "standalone_server.py" > /dev/null 2>&1; then
    echo "   ⚠️  Dashboard process still running"
    REMAINING=$((REMAINING + 1))
fi

echo ""
echo "════════════════════════════════════════════════════"
if [ $REMAINING -eq 0 ]; then
    echo "✅ All MCP services have been stopped successfully!"
else
    echo "⚠️  Some services may still be running."
    echo "   Run 'ps aux | grep python' to check manually."
fi
echo "════════════════════════════════════════════════════"
echo ""

# Show what services can be started
echo "💡 To start services, use:"
echo "   ./start-dashboard-mcp.sh start-all        # Start Outlook MCP"
echo "   SERVER_TYPE=onenote ./start-dashboard-mcp.sh start-all  # Start OneNote MCP"
echo "   SERVER_TYPE=teams ./start-dashboard-mcp.sh start-all    # Start Teams MCP"
echo ""
echo "💡 To check status:"
echo "   ./start-dashboard-mcp.sh status"
echo "   SERVER_TYPE=onenote ./start-dashboard-mcp.sh status"
echo "   SERVER_TYPE=teams ./start-dashboard-mcp.sh status"