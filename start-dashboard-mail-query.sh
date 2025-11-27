#!/bin/bash
# Mail Query MCP Dashboard & Server Launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration for both servers
DASHBOARD_PID_FILE="/tmp/dashboard_server.pid"
FASTAPI_PID_FILE="/tmp/mail_query_fastapi.pid"
DASHBOARD_LOG_FILE="logs/dashboard.log"
FASTAPI_LOG_FILE="logs/mail_query_fastapi.log"
DASHBOARD_PORT=${DASHBOARD_PORT:-9000}
FASTAPI_PORT=${MAIL_API_PORT:-8001}

# Database configuration
export DCR_DATABASE_PATH="${SCRIPT_DIR}/data/auth_mail_query.db"
export DATABASE_MAIL_QUERY_PATH="${SCRIPT_DIR}/data/mail_query.db"

# Create logs directory if it doesn't exist
mkdir -p logs

# Function to check if dashboard is running
is_dashboard_running() {
    if [ -f "$DASHBOARD_PID_FILE" ]; then
        PID=$(cat "$DASHBOARD_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# Function to check if FastAPI is running
is_fastapi_running() {
    if [ -f "$FASTAPI_PID_FILE" ]; then
        PID=$(cat "$FASTAPI_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0
        fi
    fi
    # Also check if running on port
    if lsof -i :$FASTAPI_PORT > /dev/null 2>&1; then
        return 0
    fi
    return 1
}

# Function to start FastAPI server
start_fastapi() {
    if is_fastapi_running; then
        echo "⚠️  FastAPI server is already running, stopping it first..."
        stop_fastapi
        sleep 2
    fi

    echo "🚀 Starting FastAPI Mail Query Server on port $FASTAPI_PORT..."

    # Kill any existing processes on the port
    lsof -i :$FASTAPI_PORT | grep LISTEN | awk '{print $2}' | xargs -r kill -9 2>/dev/null

    # Kill any orphaned python processes running run_fastapi.py
    pkill -f "run_fastapi.py" 2>/dev/null
    sleep 1

    export DCR_DATABASE_PATH="$DCR_DATABASE_PATH"
    export DATABASE_MAIL_QUERY_PATH="$DATABASE_MAIL_QUERY_PATH"
    nohup python3 modules/mail_query_MCP/entrypoints/run_fastapi.py --port "$FASTAPI_PORT" > "$FASTAPI_LOG_FILE" 2>&1 &
    PID=$!
    echo $PID > "$FASTAPI_PID_FILE"

    sleep 3

    if is_fastapi_running; then
        echo "✅ FastAPI server started successfully!"
        echo "│  MCP Endpoint: http://localhost:$FASTAPI_PORT/"
        echo "│  API Docs: http://localhost:$FASTAPI_PORT/docs"
        echo "│  PID: $PID"
        return 0
    else
        echo "❌ Failed to start FastAPI server"
        echo "Check logs: tail -f $FASTAPI_LOG_FILE"
        return 1
    fi
}

# Function to start dashboard server
start_dashboard() {
    if is_dashboard_running; then
        echo "⚠️  Dashboard server is already running, stopping it first..."
        stop_dashboard
        sleep 2
    fi

    echo "🚀 Starting Dashboard Server on port $DASHBOARD_PORT..."
    nohup python3 modules/web_dashboard/standalone_server.py --port $DASHBOARD_PORT > "$DASHBOARD_LOG_FILE" 2>&1 &
    PID=$!
    echo $PID > "$DASHBOARD_PID_FILE"

    sleep 2

    if is_dashboard_running; then
        echo "✅ Dashboard server started successfully!"
        echo "│  Dashboard URL: http://localhost:$DASHBOARD_PORT/dashboard"
        echo "│  PID: $PID"
        return 0
    else
        echo "❌ Failed to start dashboard server"
        echo "Check logs: tail -f $DASHBOARD_LOG_FILE"
        return 1
    fi
}

# Function to start both servers
start_all() {
    echo "════════════════════════════════════════════════════"
    echo "🚀 Starting Mail Query MCP System"
    echo "════════════════════════════════════════════════════"
    echo ""

    # Start FastAPI first
    start_fastapi
    FASTAPI_STATUS=$?

    echo ""

    # Then start Dashboard
    start_dashboard
    DASHBOARD_STATUS=$?

    echo ""
    echo "════════════════════════════════════════════════════"

    if [ $FASTAPI_STATUS -eq 0 ] && [ $DASHBOARD_STATUS -eq 0 ]; then
        echo "✅ All services started successfully!"
        echo ""
        echo "📌 Service URLs:"
        echo "│"
        echo "├─ 📧 Mail Query MCP API:"
        echo "│   └─ http://localhost:$FASTAPI_PORT/"
        echo "│"
        echo "├─ 📚 API Documentation:"
        echo "│   └─ http://localhost:$FASTAPI_PORT/docs"
        echo "│"
        echo "├─ 🎯 OAuth Authorization:"
        echo "│   └─ http://localhost:$FASTAPI_PORT/auth/login"
        echo "│"
        echo "└─ 📊 Web Dashboard:"
        echo "    └─ http://localhost:$DASHBOARD_PORT/dashboard"
        echo ""
        echo "💡 Logs:"
        echo "   FastAPI: tail -f $FASTAPI_LOG_FILE"
        echo "   Dashboard: tail -f $DASHBOARD_LOG_FILE"
        return 0
    else
        echo "⚠️  Some services failed to start"
        return 1
    fi
}

# Function to stop FastAPI server
stop_fastapi() {
    echo "⏹️  Stopping FastAPI server..."

    # Stop using PID file if exists
    if [ -f "$FASTAPI_PID_FILE" ]; then
        PID=$(cat "$FASTAPI_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            kill "$PID"
            sleep 2
            if ps -p "$PID" > /dev/null 2>&1; then
                kill -9 "$PID"
            fi
        fi
        rm -f "$FASTAPI_PID_FILE"
    fi

    # Also kill any process on the port
    lsof -i :$FASTAPI_PORT | grep LISTEN | awk '{print $2}' | xargs -r kill -9 2>/dev/null

    echo "✅ FastAPI server stopped"
}

# Function to stop dashboard server
stop_dashboard() {
    echo "⏹️  Stopping Dashboard server..."

    if [ -f "$DASHBOARD_PID_FILE" ]; then
        PID=$(cat "$DASHBOARD_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            kill "$PID"
            sleep 2
            if ps -p "$PID" > /dev/null 2>&1; then
                kill -9 "$PID"
            fi
        fi
        rm -f "$DASHBOARD_PID_FILE"
    fi

    echo "✅ Dashboard server stopped"
}

# Function to stop all servers
stop_all() {
    echo "════════════════════════════════════════════════════"
    echo "⏹️  Stopping Mail Query MCP System"
    echo "════════════════════════════════════════════════════"
    echo ""

    stop_fastapi
    stop_dashboard

    echo ""
    echo "════════════════════════════════════════════════════"
    echo "✅ All services stopped"
}

# Function to show status
show_status() {
    echo "════════════════════════════════════════════════════"
    echo "📊 Mail Query MCP System Status"
    echo "════════════════════════════════════════════════════"
    echo ""

    # Check FastAPI status
    echo "🔹 FastAPI Server:"
    if is_fastapi_running; then
        if [ -f "$FASTAPI_PID_FILE" ]; then
            PID=$(cat "$FASTAPI_PID_FILE")
            echo "   ✅ RUNNING (PID: $PID)"
        else
            echo "   ✅ RUNNING (PID unknown)"
        fi
        echo "   │  Port: $FASTAPI_PORT"
        echo "   │  URL: http://localhost:$FASTAPI_PORT/"
        echo "   │  Docs: http://localhost:$FASTAPI_PORT/docs"
    else
        echo "   ❌ NOT RUNNING"
    fi

    echo ""

    # Check Dashboard status
    echo "🔹 Dashboard Server:"
    if is_dashboard_running; then
        PID=$(cat "$DASHBOARD_PID_FILE")
        echo "   ✅ RUNNING (PID: $PID)"
        echo "   │  Port: $DASHBOARD_PORT"
        echo "   │  URL: http://localhost:$DASHBOARD_PORT/dashboard"
    else
        echo "   ❌ NOT RUNNING"
    fi

    echo ""
    echo "════════════════════════════════════════════════════"
}

# Main script
case "${1:-start}" in
    start)
        start_all
        ;;
    start-fastapi)
        start_fastapi
        ;;
    start-dashboard)
        start_dashboard
        ;;
    stop)
        stop_all
        ;;
    stop-fastapi)
        stop_fastapi
        ;;
    stop-dashboard)
        stop_dashboard
        ;;
    restart)
        stop_all
        sleep 2
        start_all
        ;;
    restart-fastapi)
        stop_fastapi
        sleep 2
        start_fastapi
        ;;
    restart-dashboard)
        stop_dashboard
        sleep 2
        start_dashboard
        ;;
    status)
        show_status
        ;;
    logs)
        echo "📜 Showing logs (Ctrl+C to exit)..."
        echo "════════════════════════════════════════════"
        echo "FastAPI logs:"
        tail -f "$FASTAPI_LOG_FILE" 2>/dev/null | sed 's/^/[FASTAPI] /' &
        TAIL1=$!
        echo "Dashboard logs:"
        tail -f "$DASHBOARD_LOG_FILE" 2>/dev/null | sed 's/^/[DASHBOARD] /' &
        TAIL2=$!
        trap "kill $TAIL1 $TAIL2 2>/dev/null" EXIT
        wait
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|start-fastapi|start-dashboard|stop-fastapi|stop-dashboard}"
        echo ""
        echo "Commands:"
        echo "  start              - Start both FastAPI and Dashboard servers"
        echo "  start-fastapi      - Start only FastAPI server"
        echo "  start-dashboard    - Start only Dashboard server"
        echo "  stop               - Stop all servers"
        echo "  stop-fastapi       - Stop only FastAPI server"
        echo "  stop-dashboard     - Stop only Dashboard server"
        echo "  restart            - Restart all servers"
        echo "  restart-fastapi    - Restart only FastAPI server"
        echo "  restart-dashboard  - Restart only Dashboard server"
        echo "  status             - Show server status"
        echo "  logs               - Show live logs from both servers"
        echo ""
        echo "Environment variables:"
        echo "  DASHBOARD_PORT     - Port for dashboard (default: 9000)"
        echo "  MAIL_API_PORT      - Port for FastAPI (default: 8001)"
        echo ""
        echo "Default action: start"
        exit 1
        ;;
esac
