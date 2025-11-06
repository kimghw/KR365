"""Web Dashboard for MailQueryWithMCP Management"""

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from infra.core.logger import get_logger
from infra.core.config import get_config

logger = get_logger(__name__)
config = get_config()

PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
ENV_FILE = PROJECT_ROOT / ".env"
UNIFIED_PID_FILE = Path("/tmp/unified_server.pid")
QUICK_TUNNEL_PID_FILE = Path("/tmp/quick_tunnel.pid")


class DashboardService:
    """Service for managing dashboard operations"""

    @staticmethod
    def start_server() -> Dict:
        """Start unified MCP server"""
        try:
            if UNIFIED_PID_FILE.exists():
                pid = int(UNIFIED_PID_FILE.read_text().strip())
                result = subprocess.run(["ps", "-p", str(pid)], capture_output=True)
                if result.returncode == 0:
                    return {"success": False, "error": "Server is already running", "pid": pid}

            # Start server
            server_script = PROJECT_ROOT / "entrypoints" / "production" / "unified_http_server.py"
            log_file = LOG_DIR / "unified_server.log"

            process = subprocess.Popen(
                ["python3", str(server_script), "--host", "0.0.0.0", "--port", "8000"],
                stdout=open(log_file, 'a'),
                stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT
            )

            # Save PID
            UNIFIED_PID_FILE.write_text(str(process.pid))
            logger.info(f"Started unified server with PID: {process.pid}")

            return {"success": True, "pid": process.pid}
        except Exception as e:
            logger.error(f"Error starting server: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def stop_server() -> Dict:
        """Stop unified MCP server"""
        try:
            if not UNIFIED_PID_FILE.exists():
                return {"success": False, "error": "Server is not running"}

            pid = int(UNIFIED_PID_FILE.read_text().strip())

            # Kill process
            try:
                subprocess.run(["kill", str(pid)], check=True)
                import time
                time.sleep(2)

                # Force kill if still running
                result = subprocess.run(["ps", "-p", str(pid)], capture_output=True)
                if result.returncode == 0:
                    subprocess.run(["kill", "-9", str(pid)])

                UNIFIED_PID_FILE.unlink()
                logger.info(f"Stopped unified server (PID: {pid})")
                return {"success": True, "pid": pid}
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": f"Failed to kill process: {e}"}
        except Exception as e:
            logger.error(f"Error stopping server: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def start_tunnel() -> Dict:
        """Start Cloudflare Quick Tunnel"""
        try:
            # Check if already running
            if QUICK_TUNNEL_PID_FILE.exists():
                pid = int(QUICK_TUNNEL_PID_FILE.read_text().strip())
                result = subprocess.run(["ps", "-p", str(pid)], capture_output=True)
                if result.returncode == 0:
                    return {"success": False, "error": "Tunnel is already running", "pid": pid}

            # Check if cloudflared exists
            cloudflared_result = subprocess.run(["which", "cloudflared"], capture_output=True, text=True)
            if cloudflared_result.returncode != 0:
                return {"success": False, "error": "cloudflared not found. Please install it first."}

            cloudflared_bin = cloudflared_result.stdout.strip()
            log_file = LOG_DIR / "quick_tunnel.log"

            # Start tunnel
            process = subprocess.Popen(
                [cloudflared_bin, "tunnel", "--url", "http://localhost:8000"],
                stdout=open(log_file, 'w'),
                stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT
            )

            # Save PID
            QUICK_TUNNEL_PID_FILE.write_text(str(process.pid))
            logger.info(f"Started Cloudflare tunnel with PID: {process.pid}")

            # Wait for URL to appear in log (max 20 seconds)
            import time
            import re
            tunnel_url = None
            for i in range(10):
                time.sleep(2)
                if log_file.exists():
                    log_content = log_file.read_text()
                    match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', log_content)
                    if match:
                        tunnel_url = match.group(0)
                        # Save to .env
                        DashboardService.update_env_variable('CLOUDFLARE_TUNNEL_URL', tunnel_url)
                        DashboardService.update_env_variable('DCR_OAUTH_REDIRECT_URI', f'{tunnel_url}/oauth/azure_callback')
                        DashboardService.update_env_variable('AUTO_REGISTER_OAUTH_REDIRECT_URI', f'{tunnel_url}/enrollment/callback')
                        break

            return {
                "success": True,
                "pid": process.pid,
                "url": tunnel_url,
                "message": "Tunnel started. URL will appear in a few seconds." if not tunnel_url else f"Tunnel started: {tunnel_url}"
            }
        except Exception as e:
            logger.error(f"Error starting tunnel: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def stop_tunnel() -> Dict:
        """Stop Cloudflare Quick Tunnel"""
        try:
            # First try PID file
            if QUICK_TUNNEL_PID_FILE.exists():
                pid = int(QUICK_TUNNEL_PID_FILE.read_text().strip())
            else:
                # Try to find cloudflared process
                result = subprocess.run(
                    ["pgrep", "-f", "cloudflared.*tunnel.*--url"],
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0 or not result.stdout.strip():
                    return {"success": False, "error": "Tunnel is not running"}
                pid = int(result.stdout.strip().split()[0])

            # Kill process
            try:
                subprocess.run(["kill", str(pid)], check=True)
                import time
                time.sleep(2)

                # Force kill if still running
                result = subprocess.run(["ps", "-p", str(pid)], capture_output=True)
                if result.returncode == 0:
                    subprocess.run(["kill", "-9", str(pid)])

                if QUICK_TUNNEL_PID_FILE.exists():
                    QUICK_TUNNEL_PID_FILE.unlink()

                logger.info(f"Stopped Cloudflare tunnel (PID: {pid})")
                return {"success": True, "pid": pid}
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": f"Failed to kill process: {e}"}
        except Exception as e:
            logger.error(f"Error stopping tunnel: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_server_status() -> Dict:
        """Get unified server status"""
        try:
            if UNIFIED_PID_FILE.exists():
                pid = int(UNIFIED_PID_FILE.read_text().strip())
                # Check if process is running
                result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "comm="],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0 and "python" in result.stdout:
                    return {
                        "status": "running",
                        "pid": pid,
                        "endpoint": "http://localhost:8000"
                    }
            return {"status": "stopped"}
        except Exception as e:
            logger.error(f"Error getting server status: {e}")
            return {"status": "unknown", "error": str(e)}

    @staticmethod
    def get_tunnel_status() -> Dict:
        """Get Cloudflare tunnel status"""
        try:
            tunnel_url = None
            pid = None

            # Check PID file
            if QUICK_TUNNEL_PID_FILE.exists():
                pid = int(QUICK_TUNNEL_PID_FILE.read_text().strip())
                result = subprocess.run(
                    ["ps", "-p", str(pid)],
                    capture_output=True
                )
                if result.returncode != 0:
                    pid = None

            # If no PID, try to find cloudflared process
            if not pid:
                result = subprocess.run(
                    ["pgrep", "-f", "cloudflared.*tunnel.*--url"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0 and result.stdout.strip():
                    pid = int(result.stdout.strip().split()[0])

            if pid:
                # Method 1: Try to get URL from log file
                log_file = LOG_DIR / "quick_tunnel.log"
                if log_file.exists():
                    log_content = log_file.read_text()
                    import re
                    match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', log_content)
                    if match:
                        tunnel_url = match.group(0)

                # Method 2: Try to get URL from .env file (DCR_OAUTH_REDIRECT_URI)
                if not tunnel_url and ENV_FILE.exists():
                    env_content = ENV_FILE.read_text()
                    import re
                    # Look for DCR_OAUTH_REDIRECT_URI or AUTO_REGISTER_OAUTH_REDIRECT_URI
                    match = re.search(r'(?:DCR_OAUTH_REDIRECT_URI|AUTO_REGISTER_OAUTH_REDIRECT_URI)=(https://[a-z0-9-]+\.trycloudflare\.com)', env_content)
                    if match:
                        tunnel_url = match.group(1)

                # Method 3: Try to get URL using cloudflared metrics (if available)
                if not tunnel_url:
                    try:
                        # cloudflared exposes metrics on localhost:60123 by default
                        import requests
                        response = requests.get("http://127.0.0.1:60123/metrics", timeout=1)
                        if response.status_code == 200:
                            match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', response.text)
                            if match:
                                tunnel_url = match.group(0)
                    except:
                        pass

                return {
                    "status": "running",
                    "pid": pid,
                    "url": tunnel_url
                }

            return {"status": "stopped"}
        except Exception as e:
            logger.error(f"Error getting tunnel status: {e}")
            return {"status": "unknown", "error": str(e)}

    @staticmethod
    def get_env_variables() -> Dict[str, str]:
        """Get environment variables from .env file"""
        env_vars = {}
        try:
            if ENV_FILE.exists():
                content = ENV_FILE.read_text()
                for line in content.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
        except Exception as e:
            logger.error(f"Error reading .env file: {e}")
        return env_vars

    @staticmethod
    def update_env_variable(key: str, value: str) -> bool:
        """Update or add environment variable"""
        try:
            if not ENV_FILE.exists():
                ENV_FILE.touch()

            content = ENV_FILE.read_text()
            lines = content.split('\n')
            updated = False

            # Update existing key
            for i, line in enumerate(lines):
                if line.strip() and not line.strip().startswith('#'):
                    if '=' in line:
                        existing_key = line.split('=', 1)[0].strip()
                        if existing_key == key:
                            lines[i] = f"{key}={value}"
                            updated = True
                            break

            # Add new key if not found
            if not updated:
                lines.append(f"{key}={value}")

            ENV_FILE.write_text('\n'.join(lines))
            logger.info(f"Updated env variable: {key}")
            return True
        except Exception as e:
            logger.error(f"Error updating env variable: {e}")
            return False

    @staticmethod
    def get_log_files() -> List[Dict]:
        """Get list of available log files"""
        log_files = []
        try:
            if LOG_DIR.exists():
                for log_file in LOG_DIR.glob("*.log"):
                    size = log_file.stat().st_size
                    log_files.append({
                        "name": log_file.name,
                        "path": str(log_file),
                        "size": size,
                        "size_mb": round(size / 1024 / 1024, 2)
                    })
        except Exception as e:
            logger.error(f"Error listing log files: {e}")
        return sorted(log_files, key=lambda x: x['name'])

    @staticmethod
    def get_log_content(log_name: str, lines: int = 100) -> str:
        """Get last N lines from log file"""
        try:
            log_file = LOG_DIR / log_name
            if not log_file.exists():
                return f"Log file not found: {log_name}"

            # Use tail command for efficiency
            result = subprocess.run(
                ["tail", "-n", str(lines), str(log_file)],
                capture_output=True,
                text=True
            )
            return result.stdout
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            return f"Error: {str(e)}"

    @staticmethod
    def get_endpoints_info(tunnel_url: Optional[str] = None) -> Dict:
        """Get information about all endpoints"""
        base_url = tunnel_url or "http://localhost:8000"

        return {
            "base_url": base_url,
            "services": [
                {
                    "name": "Mail Query",
                    "path": "/mail-query/",
                    "url": f"{base_url}/mail-query/",
                    "health": f"{base_url}/mail-query/health"
                },
                {
                    "name": "Enrollment",
                    "path": "/enrollment/",
                    "url": f"{base_url}/enrollment/",
                    "oauth_callback": f"{base_url}/enrollment/callback"
                },
                {
                    "name": "OneNote",
                    "path": "/onenote/",
                    "url": f"{base_url}/onenote/"
                },
                {
                    "name": "OneDrive",
                    "path": "/onedrive/",
                    "url": f"{base_url}/onedrive/"
                },
                {
                    "name": "Teams",
                    "path": "/teams/",
                    "url": f"{base_url}/teams/"
                }
            ],
            "oauth": {
                "authorize": f"{base_url}/oauth/authorize",
                "token": f"{base_url}/oauth/token",
                "register": f"{base_url}/oauth/register",
                "azure_callback": f"{base_url}/oauth/azure_callback"
            },
            "redirect_uris": {
                "DCR_OAUTH_REDIRECT_URI": f"{base_url}/oauth/azure_callback",
                "AUTO_REGISTER_OAUTH_REDIRECT_URI": f"{base_url}/enrollment/callback"
            },
            "health": f"{base_url}/health"
        }

    @staticmethod
    def get_database_list() -> List[Dict]:
        """Get list of available databases"""
        databases = []

        # Main database
        if hasattr(config, 'database_path'):
            db_path = Path(config.database_path)
            if db_path.exists():
                databases.append({
                    "name": "Main Database (graphapi.db)",
                    "path": str(db_path),
                    "size": db_path.stat().st_size,
                    "size_mb": round(db_path.stat().st_size / 1024 / 1024, 2)
                })

        # DCR database
        if hasattr(config, 'dcr_database_path'):
            dcr_db_path = Path(config.dcr_database_path)
            if dcr_db_path.exists():
                databases.append({
                    "name": "DCR Database (dcr.db)",
                    "path": str(dcr_db_path),
                    "size": dcr_db_path.stat().st_size,
                    "size_mb": round(dcr_db_path.stat().st_size / 1024 / 1024, 2)
                })

        return databases

    @staticmethod
    def get_database_tables(db_path: str) -> List[str]:
        """Get list of tables in database"""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            return tables
        except Exception as e:
            logger.error(f"Error getting database tables: {e}")
            return []

    @staticmethod
    def query_database(db_path: str, query: str, limit: Optional[int] = None) -> Dict:
        """Execute SQL query on database"""
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Add LIMIT only if explicitly requested
            if limit and query.strip().upper().startswith('SELECT') and 'LIMIT' not in query.upper():
                query = f"{query.strip().rstrip(';')} LIMIT {limit}"

            cursor.execute(query)

            # Get column names
            columns = [description[0] for description in cursor.description] if cursor.description else []

            # Get rows
            rows = []
            for row in cursor.fetchall():
                rows.append(dict(row))

            conn.close()

            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows)
            }
        except Exception as e:
            logger.error(f"Error querying database: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def get_table_schema(db_path: str, table_name: str) -> List[Dict]:
        """Get schema information for a table"""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            schema = []
            for row in cursor.fetchall():
                schema.append({
                    "cid": row[0],
                    "name": row[1],
                    "type": row[2],
                    "notnull": bool(row[3]),
                    "default_value": row[4],
                    "pk": bool(row[5])
                })
            conn.close()
            return schema
        except Exception as e:
            logger.error(f"Error getting table schema: {e}")
            return []


def create_dashboard_routes() -> List[Route]:
    """Create dashboard routes"""
    service = DashboardService()

    # Main dashboard page
    async def dashboard_page(request):
        """Main dashboard HTML page"""
        html = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MailQueryWithMCP - Management Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .header h1 {
            color: #333;
            font-size: 32px;
            margin-bottom: 10px;
        }
        .header p {
            color: #666;
            font-size: 14px;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: white;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .card h2 {
            color: #333;
            font-size: 20px;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-running {
            background: #10b981;
            color: white;
        }
        .status-stopped {
            background: #ef4444;
            color: white;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }
        .info-row:last-child {
            border-bottom: none;
        }
        .info-label {
            color: #666;
            font-size: 14px;
        }
        .info-value {
            color: #333;
            font-weight: 500;
            font-size: 14px;
            max-width: 60%;
            text-align: right;
            word-break: break-all;
        }
        .url-copy {
            cursor: pointer;
            color: #667eea;
            text-decoration: none;
        }
        .url-copy:hover {
            text-decoration: underline;
        }
        .btn {
            display: inline-block;
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            text-decoration: none;
            color: white;
        }
        .btn-primary {
            background: #667eea;
        }
        .btn-primary:hover {
            background: #5568d3;
        }
        .btn-danger {
            background: #ef4444;
        }
        .btn-danger:hover {
            background: #dc2626;
        }
        .log-viewer {
            background: #1e1e1e;
            color: #d4d4d4;
            border-radius: 8px;
            padding: 20px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .env-editor {
            margin-top: 15px;
        }
        .env-input {
            width: 100%;
            padding: 10px;
            margin: 5px 0;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
        }
        .env-item {
            display: flex;
            gap: 10px;
            align-items: center;
            margin-bottom: 10px;
            padding: 10px;
            background: #f9f9f9;
            border-radius: 6px;
        }
        .env-key {
            font-weight: 600;
            color: #667eea;
            min-width: 200px;
        }
        .env-value {
            flex: 1;
            color: #333;
            font-family: monospace;
        }
        .log-selector {
            margin-bottom: 15px;
        }
        .log-selector select {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
        }
        .refresh-btn {
            margin-top: 10px;
        }
        .full-width {
            grid-column: 1 / -1;
        }
        .toast {
            position: fixed;
            top: 20px;
            right: 20px;
            background: #10b981;
            color: white;
            padding: 15px 25px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.2);
            z-index: 1000;
            animation: slideIn 0.3s ease-out;
        }
        @keyframes slideIn {
            from {
                transform: translateX(400px);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 2px solid #e5e7eb;
        }
        .tab {
            padding: 12px 24px;
            background: transparent;
            border: none;
            border-bottom: 3px solid transparent;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            color: #6b7280;
            transition: all 0.3s;
        }
        .tab:hover {
            color: #667eea;
        }
        .tab.active {
            color: #667eea;
            border-bottom-color: #667eea;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header" style="position: relative;">
            <h1>🚀 MailQueryWithMCP Management Dashboard</h1>
            <p>Unified server management, logs, and configuration</p>
            <a href="https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps"
               target="_blank"
               class="btn btn-primary"
               style="position: absolute; top: 20px; right: 20px; display: inline-flex; align-items: center; gap: 8px;">
                <span>🔐</span>
                <span>Azure AD App Registration</span>
            </a>
        </div>

        <div class="grid">
            <!-- Server Status -->
            <div class="card">
                <h2>🖥️ Unified Server</h2>
                <div id="server-status">Loading...</div>
                <div style="margin-top: 15px; display: flex; gap: 10px;">
                    <button class="btn btn-primary" onclick="startServer()" style="flex: 1;">▶️ Start Server</button>
                    <button class="btn btn-danger" onclick="stopServer()" style="flex: 1;">⏹️ Stop Server</button>
                </div>
            </div>

            <!-- Tunnel Status -->
            <div class="card">
                <h2>🌐 Cloudflare Tunnel</h2>
                <div id="tunnel-status">Loading...</div>
                <div style="margin-top: 15px; display: flex; gap: 10px;">
                    <button class="btn btn-primary" onclick="startTunnel()" style="flex: 1;">▶️ Start Tunnel</button>
                    <button class="btn btn-danger" onclick="stopTunnel()" style="flex: 1;">⏹️ Stop Tunnel</button>
                </div>
            </div>
        </div>

        <!-- Tabs Navigation -->
        <div class="card full-width">
            <div class="tabs">
                <button class="tab active" onclick="switchTab('logs')">📋 Logs</button>
                <button class="tab" onclick="switchTab('endpoints')">🔗 Endpoints</button>
                <button class="tab" onclick="switchTab('database')">💾 Database</button>
                <button class="tab" onclick="switchTab('env')">⚙️ Environment</button>
            </div>

            <!-- Logs Tab -->
            <div id="logs-tab" class="tab-content active">
                <h2 style="margin-bottom: 15px;">📋 Log Viewer</h2>
                <div class="log-selector">
                    <select id="log-select" onchange="loadLog()">
                        <option value="">Select a log file...</option>
                    </select>
                </div>
                <div class="log-viewer" id="log-content">Select a log file to view its contents</div>
                <button class="btn btn-primary refresh-btn" onclick="loadLog()">🔄 Refresh Log</button>
            </div>

            <!-- Endpoints Tab -->
            <div id="endpoints-tab" class="tab-content">
                <h2 style="margin-bottom: 15px;">🔗 Service Endpoints</h2>
                <div id="endpoints-info">Loading...</div>
            </div>

            <!-- Database Tab -->
            <div id="database-tab" class="tab-content">
                <h2 style="margin-bottom: 15px;">💾 Database Viewer</h2>
                <div style="margin-bottom: 15px; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px;">
                    <div>
                        <label style="display: block; margin-bottom: 5px; font-weight: 600; color: #666;">Database</label>
                        <select id="db-select" class="env-input" onchange="loadDatabaseTables()" style="width: 100%;">
                            <option value="">Select database...</option>
                        </select>
                    </div>
                    <div>
                        <label style="display: block; margin-bottom: 5px; font-weight: 600; color: #666;">Table</label>
                        <select id="table-select" class="env-input" onchange="onTableSelect()" style="width: 100%;">
                            <option value="">Select table...</option>
                        </select>
                    </div>
                    <div>
                        <label style="display: block; margin-bottom: 5px; font-weight: 600; color: #666;">Quick Actions</label>
                        <button class="btn btn-primary" onclick="selectAllFromTable()" style="width: 100%;">View All Rows</button>
                    </div>
                </div>

                <div id="query-results">
                    <h3 style="margin-bottom: 10px; color: #667eea;">Results</h3>
                    <div id="results-content" style="background: #f9f9f9; padding: 15px; border-radius: 6px; font-size: 12px; max-height: 500px; overflow: auto;">
                        Select a table to see data
                    </div>
                </div>
            </div>

            <!-- Environment Tab -->
            <div id="env-tab" class="tab-content">
                <h2 style="margin-bottom: 15px;">⚙️ Environment Variables</h2>
                <div class="env-editor">
                    <input type="text" id="new-env-key" class="env-input" placeholder="Variable name (e.g., REDIRECT_URI)">
                    <input type="text" id="new-env-value" class="env-input" placeholder="Value">
                    <button class="btn btn-primary" onclick="addEnvVariable()">Add/Update Variable</button>
                </div>
                <div id="env-variables" style="margin-top: 20px;">Loading...</div>
            </div>
        </div>
    </div>

    <script>
        // Tab switching
        function switchTab(tabName) {
            // Hide all tab contents
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });

            // Remove active class from all tabs
            document.querySelectorAll('.tab').forEach(tab => {
                tab.classList.remove('active');
            });

            // Show selected tab content
            document.getElementById(tabName + '-tab').classList.add('active');

            // Add active class to clicked tab
            event.target.classList.add('active');
        }

        // Copy to clipboard helper
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(() => {
                showToast('Copied to clipboard!');
            });
        }

        // Show toast notification
        function showToast(message) {
            const toast = document.createElement('div');
            toast.className = 'toast';
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }

        // Load server status
        async function loadServerStatus() {
            try {
                const response = await fetch('/dashboard/api/status');
                const data = await response.json();

                const serverHtml = data.server.status === 'running' ? `
                    <span class="status-badge status-running">RUNNING</span>
                    <div class="info-row">
                        <span class="info-label">PID:</span>
                        <span class="info-value">${data.server.pid}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Endpoint:</span>
                        <span class="info-value">
                            <a href="${data.server.endpoint}/health" target="_blank" class="url-copy">
                                ${data.server.endpoint}
                            </a>
                        </span>
                    </div>
                ` : `<span class="status-badge status-stopped">STOPPED</span>`;

                const tunnelHtml = data.tunnel.status === 'running' ? `
                    <span class="status-badge status-running">RUNNING</span>
                    <div class="info-row">
                        <span class="info-label">PID:</span>
                        <span class="info-value">${data.tunnel.pid}</span>
                    </div>
                    ${data.tunnel.url ? `
                    <div class="info-row">
                        <span class="info-label">Public URL:</span>
                        <span class="info-value">
                            <a href="${data.tunnel.url}" target="_blank" class="url-copy" onclick="copyToClipboard('${data.tunnel.url}'); event.preventDefault();">
                                ${data.tunnel.url}
                            </a>
                        </span>
                    </div>
                    ` : ''}
                ` : `<span class="status-badge status-stopped">STOPPED</span>`;

                document.getElementById('server-status').innerHTML = serverHtml;
                document.getElementById('tunnel-status').innerHTML = tunnelHtml;

                // Load endpoints with tunnel URL
                loadEndpoints(data.tunnel.url);
            } catch (error) {
                console.error('Error loading status:', error);
            }
        }

        // Load endpoints
        async function loadEndpoints(tunnelUrl) {
            try {
                const url = tunnelUrl ? `/dashboard/api/endpoints?tunnel_url=${encodeURIComponent(tunnelUrl)}` : '/dashboard/api/endpoints';
                const response = await fetch(url);
                const data = await response.json();

                let html = '';

                // Redirect URIs for Azure AD App Registration - FIRST
                if (data.redirect_uris) {
                    html += '<div style="padding: 15px; background: #fff3cd; border-radius: 8px; border: 1px solid #ffc107;">';
                    html += '<h3 style="margin-bottom: 10px; color: #856404;">🔐 OAuth Redirect URIs (Azure AD App Registration)</h3>';
                    html += '<p style="font-size: 11px; color: #856404; margin-bottom: 15px;">Click to copy these URIs for Azure AD App Registration</p>';
                    html += '<div style="font-size: 12px;">';
                    for (const [key, value] of Object.entries(data.redirect_uris)) {
                        html += `
                            <div style="margin: 10px 0; padding: 10px; background: white; border-radius: 5px; cursor: pointer; transition: all 0.3s;"
                                 onmouseover="this.style.background='#f8f9fa'"
                                 onmouseout="this.style.background='white'"
                                 onclick="copyToClipboard('${value}'); event.preventDefault();">
                                <div style="font-weight: bold; color: #495057; margin-bottom: 5px;">${key}:</div>
                                <div style="font-family: monospace; color: #007bff; word-break: break-all;">
                                    ${value}
                                </div>
                                <div style="font-size: 10px; color: #6c757d; margin-top: 5px;">📋 Click to copy</div>
                            </div>
                        `;
                    }
                    html += '</div></div>';
                }

                // OAuth endpoints - SECOND
                html += '<div style="margin-top: 20px; padding: 15px; background: #f0f9ff; border-radius: 8px;">';
                html += '<h3 style="margin-bottom: 10px; color: #667eea;">OAuth Endpoints</h3>';
                html += '<div style="font-size: 12px;">';
                for (const [key, value] of Object.entries(data.oauth)) {
                    html += `
                        <div style="margin: 5px 0;">
                            <strong>${key}:</strong>
                            <a href="${value}" class="url-copy" onclick="copyToClipboard('${value}'); event.preventDefault();">${value}</a>
                        </div>
                    `;
                }
                html += '</div></div>';

                // Services - THIRD
                html += '<div style="margin-top: 20px; display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px;">';
                data.services.forEach(service => {
                    html += `
                        <div style="padding: 15px; background: #f9f9f9; border-radius: 8px;">
                            <h3 style="margin-bottom: 10px; color: #667eea;">${service.name}</h3>
                            <div style="font-size: 12px;">
                                <div style="margin: 5px 0;">
                                    <a href="${service.url}" target="_blank" class="url-copy" onclick="copyToClipboard('${service.url}'); event.preventDefault();">
                                        ${service.url}
                                    </a>
                                </div>
                            </div>
                        </div>
                    `;
                });
                html += '</div>';

                document.getElementById('endpoints-info').innerHTML = html;
            } catch (error) {
                console.error('Error loading endpoints:', error);
            }
        }

        // Load environment variables
        async function loadEnvVariables() {
            try {
                const response = await fetch('/dashboard/api/env');
                const data = await response.json();

                let html = '';
                for (const [key, value] of Object.entries(data)) {
                    html += `
                        <div class="env-item">
                            <span class="env-key">${key}</span>
                            <span class="env-value">${value}</span>
                        </div>
                    `;
                }
                document.getElementById('env-variables').innerHTML = html || '<p style="color: #666;">No environment variables found</p>';
            } catch (error) {
                console.error('Error loading env variables:', error);
            }
        }

        // Add environment variable
        async function addEnvVariable() {
            const key = document.getElementById('new-env-key').value.trim();
            const value = document.getElementById('new-env-value').value.trim();

            if (!key) {
                showToast('Please enter a variable name');
                return;
            }

            try {
                const response = await fetch('/dashboard/api/env', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({key, value})
                });

                if (response.ok) {
                    showToast('Environment variable updated!');
                    document.getElementById('new-env-key').value = '';
                    document.getElementById('new-env-value').value = '';
                    loadEnvVariables();
                } else {
                    showToast('Failed to update variable');
                }
            } catch (error) {
                console.error('Error updating env variable:', error);
                showToast('Error updating variable');
            }
        }

        // Load log files list
        async function loadLogFiles() {
            try {
                const response = await fetch('/dashboard/api/logs');
                const data = await response.json();

                const select = document.getElementById('log-select');
                select.innerHTML = '<option value="">Select a log file...</option>';

                data.forEach(log => {
                    const option = document.createElement('option');
                    option.value = log.name;
                    option.textContent = `${log.name} (${log.size_mb} MB)`;
                    select.appendChild(option);
                });
            } catch (error) {
                console.error('Error loading log files:', error);
            }
        }

        // Load selected log
        async function loadLog() {
            const logName = document.getElementById('log-select').value;
            if (!logName) return;

            try {
                const response = await fetch(`/dashboard/api/logs/${logName}?lines=200`);
                const text = await response.text();
                document.getElementById('log-content').textContent = text || 'Log file is empty';
            } catch (error) {
                console.error('Error loading log:', error);
                document.getElementById('log-content').textContent = 'Error loading log file';
            }
        }

        // Start server
        async function startServer() {
            try {
                const response = await fetch('/dashboard/api/server/start', {method: 'POST'});
                const data = await response.json();

                if (data.success) {
                    showToast('Server started successfully!');
                    setTimeout(() => loadServerStatus(), 2000);
                } else {
                    showToast('Failed to start server: ' + data.error);
                }
            } catch (error) {
                console.error('Error starting server:', error);
                showToast('Error starting server');
            }
        }

        // Stop server
        async function stopServer() {
            if (!confirm('Are you sure you want to stop the server?')) return;

            try {
                const response = await fetch('/dashboard/api/server/stop', {method: 'POST'});
                const data = await response.json();

                if (data.success) {
                    showToast('Server stopped successfully!');
                    setTimeout(() => loadServerStatus(), 2000);
                } else {
                    showToast('Failed to stop server: ' + data.error);
                }
            } catch (error) {
                console.error('Error stopping server:', error);
                showToast('Error stopping server');
            }
        }

        // Start tunnel
        async function startTunnel() {
            try {
                showToast('Starting tunnel... This may take up to 20 seconds.');
                const response = await fetch('/dashboard/api/tunnel/start', {method: 'POST'});
                const data = await response.json();

                if (data.success) {
                    showToast(data.message || 'Tunnel started successfully!');
                    setTimeout(() => loadServerStatus(), 3000);
                } else {
                    showToast('Failed to start tunnel: ' + data.error);
                }
            } catch (error) {
                console.error('Error starting tunnel:', error);
                showToast('Error starting tunnel');
            }
        }

        // Stop tunnel
        async function stopTunnel() {
            if (!confirm('Are you sure you want to stop the tunnel?')) return;

            try {
                const response = await fetch('/dashboard/api/tunnel/stop', {method: 'POST'});
                const data = await response.json();

                if (data.success) {
                    showToast('Tunnel stopped successfully!');
                    setTimeout(() => loadServerStatus(), 2000);
                } else {
                    showToast('Failed to stop tunnel: ' + data.error);
                }
            } catch (error) {
                console.error('Error stopping tunnel:', error);
                showToast('Error stopping tunnel');
            }
        }

        // Load databases list
        async function loadDatabases() {
            try {
                const response = await fetch('/dashboard/api/databases');
                const data = await response.json();

                const select = document.getElementById('db-select');
                select.innerHTML = '<option value="">Select database...</option>';

                let dcrDbPath = null;
                data.forEach(db => {
                    const option = document.createElement('option');
                    option.value = db.path;
                    option.textContent = `${db.name} (${db.size_mb} MB)`;
                    select.appendChild(option);

                    // Find DCR database path
                    if (db.name.includes('DCR Database') || db.path.includes('dcr.db')) {
                        dcrDbPath = db.path;
                    }
                });

                // Auto-select DCR database and load tables
                if (dcrDbPath) {
                    select.value = dcrDbPath;
                    await loadDatabaseTables();

                    // After tables are loaded, select dcr_azure_app if it exists
                    setTimeout(async () => {
                        const tableSelect = document.getElementById('table-select');
                        if (tableSelect) {
                            // Look for dcr_azure_app option
                            for (let option of tableSelect.options) {
                                if (option.value === 'dcr_azure_app') {
                                    tableSelect.value = 'dcr_azure_app';
                                    // Automatically load the data
                                    await selectAllFromTable();
                                    break;
                                }
                            }
                        }
                    }, 100);
                }
            } catch (error) {
                console.error('Error loading databases:', error);
            }
        }

        // Load tables for selected database
        async function loadDatabaseTables() {
            const dbPath = document.getElementById('db-select').value;
            if (!dbPath) return;

            try {
                const response = await fetch(`/dashboard/api/db/tables?db_path=${encodeURIComponent(dbPath)}`);
                const data = await response.json();

                const select = document.getElementById('table-select');
                select.innerHTML = '<option value="">Select table...</option>';

                data.tables.forEach(table => {
                    const option = document.createElement('option');
                    option.value = table;
                    option.textContent = table;
                    select.appendChild(option);
                });

                // Clear results
                document.getElementById('results-content').innerHTML = 'Select a table to see data';
            } catch (error) {
                console.error('Error loading tables:', error);
            }
        }

        // Called when table is selected
        async function onTableSelect() {
            const tableName = document.getElementById('table-select').value;
            if (tableName) {
                // Automatically load data when table is selected
                await selectAllFromTable();
            }
        }

        // Select all from current table
        async function selectAllFromTable() {
            const dbPath = document.getElementById('db-select').value;
            const tableName = document.getElementById('table-select').value;

            if (!dbPath) {
                showToast('Please select a database');
                return;
            }

            if (!tableName) {
                showToast('Please select a table first');
                return;
            }

            const query = `SELECT * FROM ${tableName}`;

            try {
                const response = await fetch('/dashboard/api/db/query', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({db_path: dbPath, query: query})
                });

                const data = await response.json();

                if (!data.success) {
                    document.getElementById('results-content').innerHTML = `<span style="color: red;">Error: ${data.error}</span>`;
                    return;
                }

                if (data.rows.length === 0) {
                    document.getElementById('results-content').innerHTML = '<p style="color: #666;">No results found</p>';
                    return;
                }

                let html = `<p style="margin-bottom: 10px;"><strong>${data.row_count} rows</strong></p>`;
                // Add scrollable container for large datasets
                html += '<div style="max-height: 600px; overflow: auto; border: 1px solid #ddd; border-radius: 4px; position: relative;">';
                html += '<table style="width: 100%; border-collapse: collapse; font-size: 11px;">';
                html += '<thead style="position: sticky; top: 0; z-index: 10;"><tr style="background: #667eea; color: white;">';

                data.columns.forEach(col => {
                    html += `<th style="padding: 6px; text-align: left; white-space: nowrap;">${col}</th>`;
                });

                html += '</tr></thead><tbody>';

                data.rows.forEach((row, idx) => {
                    html += `<tr style="border-bottom: 1px solid #ddd; ${idx % 2 === 0 ? 'background: #f9f9f9;' : ''}">`;
                    data.columns.forEach(col => {
                        const value = row[col];
                        const displayValue = value === null ? '<em style="color: #999;">NULL</em>' : String(value);
                        html += `<td style="padding: 6px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${String(value)}">${displayValue}</td>`;
                    });
                    html += '</tr>';
                });

                html += '</tbody></table></div>';

                document.getElementById('results-content').innerHTML = html;

                // Add info if there are many rows
                if (data.row_count > 100) {
                    showToast(`Showing all ${data.row_count} rows. Scroll to view more.`, 3000);
                }
            } catch (error) {
                console.error('Error executing query:', error);
                document.getElementById('results-content').innerHTML = `<span style="color: red;">Error: ${error.message}</span>`;
            }
        }

        // Auto-refresh every 5 seconds
        setInterval(() => {
            loadServerStatus();
            const logName = document.getElementById('log-select').value;
            if (logName) loadLog();
        }, 5000);

        // Initial load
        loadServerStatus();
        loadEnvVariables();
        loadLogFiles();
        loadDatabases();
    </script>
</body>
</html>
"""
        return HTMLResponse(html)

    # API: Get status
    async def api_status(request):
        """Get server and tunnel status"""
        server_status = service.get_server_status()
        tunnel_status = service.get_tunnel_status()
        return JSONResponse({
            "server": server_status,
            "tunnel": tunnel_status
        })

    # API: Start server
    async def api_start_server(request):
        """Start unified server"""
        result = service.start_server()
        return JSONResponse(result)

    # API: Stop server
    async def api_stop_server(request):
        """Stop unified server"""
        result = service.stop_server()
        return JSONResponse(result)

    # API: Start tunnel
    async def api_start_tunnel(request):
        """Start Cloudflare tunnel"""
        result = service.start_tunnel()
        return JSONResponse(result)

    # API: Stop tunnel
    async def api_stop_tunnel(request):
        """Stop Cloudflare tunnel"""
        result = service.stop_tunnel()
        return JSONResponse(result)

    # API: Get endpoints
    async def api_endpoints(request):
        """Get endpoints information"""
        tunnel_url = request.query_params.get('tunnel_url')
        endpoints = service.get_endpoints_info(tunnel_url)
        return JSONResponse(endpoints)

    # API: Get environment variables
    async def api_get_env(request):
        """Get environment variables"""
        env_vars = service.get_env_variables()
        return JSONResponse(env_vars)

    # API: Update environment variable
    async def api_update_env(request):
        """Update environment variable"""
        try:
            data = await request.json()
            key = data.get('key')
            value = data.get('value', '')

            if not key:
                return JSONResponse({"error": "Key is required"}, status_code=400)

            success = service.update_env_variable(key, value)
            if success:
                return JSONResponse({"success": True})
            else:
                return JSONResponse({"error": "Failed to update"}, status_code=500)
        except Exception as e:
            logger.error(f"Error updating env: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    # API: Get log files
    async def api_logs(request):
        """Get list of log files"""
        logs = service.get_log_files()
        return JSONResponse(logs)

    # API: Get log content
    async def api_log_content(request):
        """Get log file content"""
        log_name = request.path_params['log_name']
        lines = int(request.query_params.get('lines', 100))
        content = service.get_log_content(log_name, lines)
        return Response(content, media_type="text/plain")

    # API: Get database list
    async def api_databases(request):
        """Get list of databases"""
        databases = service.get_database_list()
        return JSONResponse(databases)

    # API: Get database tables
    async def api_db_tables(request):
        """Get tables in a database"""
        db_path = request.query_params.get('db_path')
        if not db_path:
            return JSONResponse({"error": "db_path required"}, status_code=400)
        tables = service.get_database_tables(db_path)
        return JSONResponse({"tables": tables})

    # API: Get table schema
    async def api_table_schema(request):
        """Get schema for a table"""
        db_path = request.query_params.get('db_path')
        table_name = request.query_params.get('table')
        if not db_path or not table_name:
            return JSONResponse({"error": "db_path and table required"}, status_code=400)
        schema = service.get_table_schema(db_path, table_name)
        return JSONResponse({"schema": schema})

    # API: Query database
    async def api_query_db(request):
        """Execute SQL query"""
        try:
            data = await request.json()
            db_path = data.get('db_path')
            query = data.get('query')
            limit = data.get('limit', None)  # Make limit optional

            if not db_path or not query:
                return JSONResponse({"error": "db_path and query required"}, status_code=400)

            result = service.query_database(db_path, query, limit)
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"Error in query API: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    return [
        Route("/dashboard", endpoint=dashboard_page, methods=["GET"]),
        Route("/dashboard/api/status", endpoint=api_status, methods=["GET"]),
        Route("/dashboard/api/server/start", endpoint=api_start_server, methods=["POST"]),
        Route("/dashboard/api/server/stop", endpoint=api_stop_server, methods=["POST"]),
        Route("/dashboard/api/tunnel/start", endpoint=api_start_tunnel, methods=["POST"]),
        Route("/dashboard/api/tunnel/stop", endpoint=api_stop_tunnel, methods=["POST"]),
        Route("/dashboard/api/endpoints", endpoint=api_endpoints, methods=["GET"]),
        Route("/dashboard/api/env", endpoint=api_get_env, methods=["GET"]),
        Route("/dashboard/api/env", endpoint=api_update_env, methods=["POST"]),
        Route("/dashboard/api/logs", endpoint=api_logs, methods=["GET"]),
        Route("/dashboard/api/logs/{log_name:path}", endpoint=api_log_content, methods=["GET"]),
        Route("/dashboard/api/databases", endpoint=api_databases, methods=["GET"]),
        Route("/dashboard/api/db/tables", endpoint=api_db_tables, methods=["GET"]),
        Route("/dashboard/api/db/schema", endpoint=api_table_schema, methods=["GET"]),
        Route("/dashboard/api/db/query", endpoint=api_query_db, methods=["POST"]),
    ]
