#!/bin/bash
# Standalone Web Dashboard Server Launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="/tmp/dashboard_server.pid"
LOG_FILE="logs/dashboard.log"
PORT=${DASHBOARD_PORT:-9000}

# Create logs directory if it doesn't exist
mkdir -p logs

# Function to check if server is running
is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# Function to start server
start_server() {
    if is_running; then
        echo "❌ Dashboard server is already running (PID: $(cat $PID_FILE))"
        return 1
    fi

    echo "🚀 Starting Dashboard Server on port $PORT..."
    nohup python3 modules/web_dashboard/standalone_server.py --port $PORT > "$LOG_FILE" 2>&1 &
    PID=$!
    echo $PID > "$PID_FILE"

    sleep 2

    if is_running; then
        echo "✅ Dashboard server started successfully!"
        echo "│"
        echo "│ Dashboard URL:"
        echo "│   http://localhost:$PORT/dashboard"
        echo "│"
        echo "│ PID: $PID"
        echo "│ Log: $LOG_FILE"
        echo "│"
        return 0
    else
        echo "❌ Failed to start dashboard server"
        echo "Check logs: $LOG_FILE"
        return 1
    fi
}

# Function to stop server
stop_server() {
    if ! is_running; then
        echo "❌ Dashboard server is not running"
        return 1
    fi

    PID=$(cat "$PID_FILE")
    echo "⏹️  Stopping Dashboard Server (PID: $PID)..."

    kill "$PID"
    sleep 2

    # Force kill if still running
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️  Force killing..."
        kill -9 "$PID"
    fi

    rm -f "$PID_FILE"
    echo "✅ Dashboard server stopped"
}

# Function to show status
show_status() {
    if is_running; then
        PID=$(cat "$PID_FILE")
        echo "✅ Dashboard server is RUNNING"
        echo "│  PID: $PID"
        echo "│  Port: $PORT"
        echo "│  URL: http://localhost:$PORT/dashboard"
        return 0
    else
        echo "❌ Dashboard server is NOT running"
        return 1
    fi
}

# Main script
case "${1:-start}" in
    start)
        start_server
        ;;
    stop)
        stop_server
        ;;
    restart)
        stop_server
        sleep 2
        start_server
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        echo ""
        echo "Commands:"
        echo "  start    - Start the dashboard server"
        echo "  stop     - Stop the dashboard server"
        echo "  restart  - Restart the dashboard server"
        echo "  status   - Show server status"
        echo ""
        echo "Environment variables:"
        echo "  DASHBOARD_PORT - Port for dashboard (default: 9000)"
        exit 1
        ;;
esac
