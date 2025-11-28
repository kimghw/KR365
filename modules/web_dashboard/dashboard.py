"""Web Dashboard for MailQueryWithMCP Management"""

import json
import os
import secrets
import sqlite3
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from infra.core.config import get_config
from infra.core.logger import get_logger

logger = get_logger(__name__)
config = get_config()

# Session storage (in-memory for simplicity)
dashboard_sessions = (
    {}
)  # {session_token: {"username": "admin", "created_at": timestamp}}

PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
ENV_FILE = PROJECT_ROOT / ".env"
MAIL_QUERY_PID_FILE = Path("/tmp/mail_query_fastapi.pid")
ONENOTE_PID_FILE = Path("/tmp/onenote_fastapi.pid")
TEAMS_PID_FILE = Path("/tmp/teams_fastapi.pid")
QUICK_TUNNEL_PID_FILE = Path("/tmp/quick_tunnel.pid")
CLOUDFLARE_TUNNEL_PID_FILE = Path("/tmp/cloudflare_tunnel.pid")

# MCP Server configurations
MCP_SERVERS = {
    "mail_query": {
        "name": "Mail Query",
        "icon": "email",
        "script": PROJECT_ROOT
        / "modules"
        / "outlook_mcp"
        / "entrypoints"
        / "run_fastapi.py",
        "pid_file": MAIL_QUERY_PID_FILE,
        "log_file": LOG_DIR / "mail_query_fastapi.log",
        "default_port": 8001,
        "env_port_var": "MAIL_API_PORT",
    },
    "onenote": {
        "name": "OneNote",
        "icon": "note",
        "script": PROJECT_ROOT
        / "modules"
        / "onenote_mcp"
        / "entrypoints"
        / "run_fastapi.py",
        "pid_file": ONENOTE_PID_FILE,
        "log_file": LOG_DIR / "onenote_fastapi.log",
        "default_port": 8002,
        "env_port_var": "ONENOTE_SERVER_PORT",
    },
    "teams": {
        "name": "Teams",
        "icon": "chat",
        "script": PROJECT_ROOT
        / "modules"
        / "teams_mcp"
        / "entrypoints"
        / "run_fastapi.py",
        "pid_file": TEAMS_PID_FILE,
        "log_file": LOG_DIR / "teams_fastapi.log",
        "default_port": 8003,
        "env_port_var": "TEAMS_API_PORT",
    },
}


class DashboardAuth:
    """Dashboard authentication service"""

    @staticmethod
    def verify_credentials(username: str, password: str) -> bool:
        """Verify admin credentials from environment variables"""
        admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME", "admin")
        admin_password = os.getenv("DASHBOARD_ADMIN_PASSWORD", "")

        if not admin_password:
            logger.warning("DASHBOARD_ADMIN_PASSWORD not set in .env file")
            return False

        return username == admin_username and password == admin_password

    @staticmethod
    def create_session(username: str) -> str:
        """Create a new session and return session token"""
        import time

        session_token = secrets.token_urlsafe(32)
        dashboard_sessions[session_token] = {
            "username": username,
            "created_at": time.time(),
        }
        logger.info(f"Dashboard session created for user: {username}")
        return session_token

    @staticmethod
    def verify_session(session_token: str) -> bool:
        """Verify if session token is valid"""
        if not session_token:
            return False

        session_data = dashboard_sessions.get(session_token)
        if not session_data:
            return False

        # Check session expiry (24 hours)
        import time

        session_age = time.time() - session_data["created_at"]
        if session_age > 86400:  # 24 hours
            del dashboard_sessions[session_token]
            return False

        return True

    @staticmethod
    def delete_session(session_token: str):
        """Delete a session (logout)"""
        if session_token in dashboard_sessions:
            del dashboard_sessions[session_token]
            logger.info("Dashboard session deleted")


class DashboardService:
    """Service for managing dashboard operations"""

    @staticmethod
    def start_server(server_type: str = "mail_query") -> Dict:
        """Start MCP server

        Args:
            server_type: Type of server to start ("mail_query" or "onenote")
        """
        try:
            if server_type not in MCP_SERVERS:
                return {
                    "success": False,
                    "error": f"Unknown server type: {server_type}",
                }

            config = MCP_SERVERS[server_type]
            pid_file = config["pid_file"]

            if pid_file.exists():
                pid = int(pid_file.read_text().strip())
                result = subprocess.run(["ps", "-p", str(pid)], capture_output=True)
                if result.returncode == 0:
                    return {
                        "success": False,
                        "error": f"{config['name']} server is already running",
                        "pid": pid,
                    }

            # Load environment variables from .env file
            env = os.environ.copy()
            if ENV_FILE.exists():
                with open(ENV_FILE) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            env[key.strip()] = value.strip()
                logger.info(
                    f"✅ Loaded environment variables from {ENV_FILE} for server process"
                )

            # Get port from environment or use default
            server_port = os.getenv(config["env_port_var"], str(config["default_port"]))

            process = subprocess.Popen(
                [
                    "python3",
                    str(config["script"]),
                    "--host",
                    "0.0.0.0",
                    "--port",
                    server_port,
                ],
                stdout=open(config["log_file"], "a"),
                stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT,
                env=env,
            )

            # Save PID
            pid_file.write_text(str(process.pid))
            logger.info(f"Started {config['name']} MCP server with PID: {process.pid}")

            return {
                "success": True,
                "pid": process.pid,
                "server_type": server_type,
                "port": server_port,
            }
        except Exception as e:
            logger.error(f"Error starting server: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def stop_server(server_type: str = "mail_query") -> Dict:
        """Stop MCP server

        Args:
            server_type: Type of server to stop ("mail_query" or "onenote")
        """
        try:
            if server_type not in MCP_SERVERS:
                return {
                    "success": False,
                    "error": f"Unknown server type: {server_type}",
                }

            config = MCP_SERVERS[server_type]
            pid_file = config["pid_file"]

            if not pid_file.exists():
                return {
                    "success": False,
                    "error": f"{config['name']} server is not running",
                }

            pid = int(pid_file.read_text().strip())

            # Kill process
            try:
                subprocess.run(["kill", str(pid)], check=True)
                import time

                time.sleep(2)

                # Force kill if still running
                result = subprocess.run(["ps", "-p", str(pid)], capture_output=True)
                if result.returncode == 0:
                    subprocess.run(["kill", "-9", str(pid)])

                pid_file.unlink()
                logger.info(f"Stopped {config['name']} MCP server (PID: {pid})")
                return {"success": True, "pid": pid, "server_type": server_type}
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": f"Failed to kill process: {e}"}
        except Exception as e:
            logger.error(f"Error stopping server: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def start_tunnel(port: int = None) -> Dict:
        """Start Cloudflare Quick Tunnel

        Args:
            port: Port number to tunnel (default: 8001 for Mail Query MCP server)
        """
        try:
            # Use default port 8001 if not specified
            tunnel_port = port if port else int(os.getenv("MAIL_API_PORT", "8001"))

            # Check if already running
            if QUICK_TUNNEL_PID_FILE.exists():
                pid = int(QUICK_TUNNEL_PID_FILE.read_text().strip())
                result = subprocess.run(["ps", "-p", str(pid)], capture_output=True)
                if result.returncode == 0:
                    return {
                        "success": False,
                        "error": f"Tunnel is already running (PID: {pid})",
                        "pid": pid,
                    }

            # Check if cloudflared exists
            cloudflared_result = subprocess.run(
                ["which", "cloudflared"], capture_output=True, text=True
            )
            if cloudflared_result.returncode != 0:
                return {
                    "success": False,
                    "error": "cloudflared not found. Please install it first.",
                }

            cloudflared_bin = cloudflared_result.stdout.strip()
            log_file = LOG_DIR / "quick_tunnel.log"

            # Start tunnel with specified port
            logger.info(f"Starting Cloudflare tunnel for port {tunnel_port}")
            process = subprocess.Popen(
                [cloudflared_bin, "tunnel", "--url", f"http://localhost:{tunnel_port}"],
                stdout=open(log_file, "w"),
                stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT,
            )

            # Save PID
            QUICK_TUNNEL_PID_FILE.write_text(str(process.pid))
            logger.info(f"Started Cloudflare tunnel with PID: {process.pid}")

            # Wait for URL to appear in log (max 20 seconds)
            import re
            import time

            tunnel_url = None
            for i in range(10):
                time.sleep(2)
                if log_file.exists():
                    log_content = log_file.read_text()
                    match = re.search(
                        r"https://[a-z0-9-]+\.trycloudflare\.com", log_content
                    )
                    if match:
                        tunnel_url = match.group(0)
                        # Save to .env
                        DashboardService.update_env_variable(
                            "CLOUDFLARE_TUNNEL_URL", tunnel_url
                        )
                        DashboardService.update_env_variable(
                            "DCR_OAUTH_REDIRECT_URI", f"{tunnel_url}/auth/callback"
                        )
                        DashboardService.update_env_variable(
                            "AUTO_REGISTER_OAUTH_REDIRECT_URI",
                            f"{tunnel_url}/enrollment/callback",
                        )
                        break

            return {
                "success": True,
                "pid": process.pid,
                "port": tunnel_port,
                "url": tunnel_url,
                "message": (
                    f"Tunnel started on port {tunnel_port}. URL will appear in a few seconds."
                    if not tunnel_url
                    else f"Tunnel started on port {tunnel_port}: {tunnel_url}"
                ),
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
                    text=True,
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
        """Get all MCP servers status"""
        try:
            servers_status = {}

            for server_type, config in MCP_SERVERS.items():
                port = int(
                    os.getenv(config["env_port_var"], str(config["default_port"]))
                )
                pid_file = config["pid_file"]

                # Check if server is responding on its port
                import socket

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(("localhost", port))
                sock.close()

                if result == 0:
                    # Server is running, try to get PID
                    pid = None
                    if pid_file.exists():
                        try:
                            pid = int(pid_file.read_text().strip())
                            # Verify PID is valid
                            subprocess.run(
                                ["ps", "-p", str(pid)], check=True, capture_output=True
                            )
                        except:
                            pid = None

                    servers_status[server_type] = {
                        "status": "running",
                        "pid": pid if pid else "unknown",
                        "endpoint": f"http://localhost:{port}",
                        "port": port,
                    }
                else:
                    # If not running on port, check PID file
                    if pid_file.exists():
                        pid = int(pid_file.read_text().strip())
                        # Check if process is running
                        result = subprocess.run(
                            ["ps", "-p", str(pid), "-o", "comm="],
                            capture_output=True,
                            text=True,
                        )
                        if result.returncode == 0 and "python" in result.stdout:
                            servers_status[server_type] = {
                                "status": "starting",
                                "pid": pid,
                                "endpoint": f"http://localhost:{port}",
                                "port": port,
                            }
                        else:
                            servers_status[server_type] = {
                                "status": "stopped",
                                "port": port,
                            }
                    else:
                        servers_status[server_type] = {
                            "status": "stopped",
                            "port": port,
                        }

            return servers_status
        except Exception as e:
            logger.error(f"Error getting server status: {e}")
            return {"error": str(e)}

    @staticmethod
    def get_tunnel_status() -> Dict:
        """Get Cloudflare tunnel status"""
        try:
            tunnel_url = None
            pid = None

            # Check PID file
            if QUICK_TUNNEL_PID_FILE.exists():
                pid = int(QUICK_TUNNEL_PID_FILE.read_text().strip())
                result = subprocess.run(["ps", "-p", str(pid)], capture_output=True)
                if result.returncode != 0:
                    pid = None

            # If no PID, try to find cloudflared process
            if not pid:
                result = subprocess.run(
                    ["pgrep", "-f", "cloudflared.*tunnel.*--url"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0 and result.stdout.strip():
                    pid = int(result.stdout.strip().split()[0])

            if pid:
                # Try to extract port from process info
                tunnel_port = None
                try:
                    ps_result = subprocess.run(
                        ["ps", "-p", str(pid), "-o", "args="],
                        capture_output=True,
                        text=True,
                    )
                    if ps_result.returncode == 0:
                        # Extract port from command like: cloudflared tunnel --url http://localhost:8001
                        import re

                        port_match = re.search(
                            r"--url\s+https?://localhost:(\d+)", ps_result.stdout
                        )
                        if port_match:
                            tunnel_port = int(port_match.group(1))
                except:
                    pass

                # Method 1: Try to get URL from log file
                log_file = LOG_DIR / "quick_tunnel.log"
                if log_file.exists():
                    log_content = log_file.read_text()
                    import re

                    match = re.search(
                        r"https://[a-z0-9-]+\.trycloudflare\.com", log_content
                    )
                    if match:
                        tunnel_url = match.group(0)

                # Method 2: Try to get URL from .env file (DCR_OAUTH_REDIRECT_URI)
                if not tunnel_url and ENV_FILE.exists():
                    env_content = ENV_FILE.read_text()
                    import re

                    # Look for DCR_OAUTH_REDIRECT_URI or AUTO_REGISTER_OAUTH_REDIRECT_URI
                    match = re.search(
                        r"(?:DCR_OAUTH_REDIRECT_URI|AUTO_REGISTER_OAUTH_REDIRECT_URI)=(https://[a-z0-9-]+\.trycloudflare\.com)",
                        env_content,
                    )
                    if match:
                        tunnel_url = match.group(1)

                # Method 3: Try to get URL using cloudflared metrics (if available)
                if not tunnel_url:
                    try:
                        # cloudflared exposes metrics on localhost:60123 by default
                        import requests

                        response = requests.get(
                            "http://127.0.0.1:60123/metrics", timeout=1
                        )
                        if response.status_code == 200:
                            match = re.search(
                                r"https://[a-z0-9-]+\.trycloudflare\.com", response.text
                            )
                            if match:
                                tunnel_url = match.group(0)
                    except:
                        pass

                return {
                    "status": "running",
                    "pid": pid,
                    "port": tunnel_port if tunnel_port else "unknown",
                    "url": tunnel_url,
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
                for line in content.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
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
            lines = content.split("\n")
            updated = False

            # Update existing key
            for i, line in enumerate(lines):
                if line.strip() and not line.strip().startswith("#"):
                    if "=" in line:
                        existing_key = line.split("=", 1)[0].strip()
                        if existing_key == key:
                            lines[i] = f"{key}={value}"
                            updated = True
                            break

            # Add new key if not found
            if not updated:
                lines.append(f"{key}={value}")

            ENV_FILE.write_text("\n".join(lines))
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
                    log_files.append(
                        {
                            "name": log_file.name,
                            "path": str(log_file),
                            "size": size,
                            "size_mb": round(size / 1024 / 1024, 2),
                        }
                    )
        except Exception as e:
            logger.error(f"Error listing log files: {e}")
        return sorted(log_files, key=lambda x: x["name"])

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
                text=True,
            )
            return result.stdout
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            return f"Error: {str(e)}"

    @staticmethod
    def get_endpoints_info(tunnel_url: Optional[str] = None) -> Dict:
        """Get information about all endpoints"""
        # Use MAIL_API_PORT from environment or default to 8001
        default_port = os.getenv("MAIL_API_PORT", "8001")
        base_url = tunnel_url or f"http://localhost:{default_port}"

        return {
            "base_url": base_url,
            "services": [
                {
                    "name": "Mail Query",
                    "path": "/mail-query/",
                    "url": f"{base_url}/mail-query/",
                    "health": f"{base_url}/mail-query/health",
                },
                {
                    "name": "Enrollment",
                    "path": "/enrollment/",
                    "url": f"{base_url}/enrollment/",
                    "oauth_callback": f"{base_url}/enrollment/callback",
                },
                {"name": "OneNote", "path": "/onenote/", "url": f"{base_url}/onenote/"},
                {
                    "name": "OneDrive",
                    "path": "/onedrive/",
                    "url": f"{base_url}/onedrive/",
                },
                {"name": "Teams", "path": "/teams/", "url": f"{base_url}/teams/"},
            ],
            "oauth": {
                "authorize": f"{base_url}/oauth/authorize",
                "token": f"{base_url}/oauth/token",
                "register": f"{base_url}/oauth/register",
                "azure_callback": f"{base_url}/oauth/azure_callback",
            },
            "redirect_uris": {
                "DCR_OAUTH_REDIRECT_URI": f"{base_url}/oauth/azure_callback",
                "AUTO_REGISTER_OAUTH_REDIRECT_URI": f"{base_url}/enrollment/callback",
            },
            "health": f"{base_url}/health",
        }

    @staticmethod
    def get_database_list() -> List[Dict]:
        """Get list of available databases"""
        databases = []

        # Main database
        if hasattr(config, "database_path"):
            db_path = Path(config.database_path)
            logger.info(
                f"[OnRender Debug] Main DB path: {db_path}, exists: {db_path.exists()}"
            )
            if db_path.exists():
                databases.append(
                    {
                        "name": "Main Database (graphapi.db)",
                        "path": str(db_path),
                        "size": db_path.stat().st_size,
                        "size_mb": round(db_path.stat().st_size / 1024 / 1024, 2),
                    }
                )
            else:
                # 경로가 존재하지 않아도 리스트에 추가하여 문제 파악
                databases.append(
                    {
                        "name": "Main Database (graphapi.db) - NOT FOUND",
                        "path": str(db_path),
                        "size": 0,
                        "size_mb": 0,
                        "error": f"File not exists at {db_path}",
                    }
                )

        # DCR database
        if hasattr(config, "dcr_database_path"):
            dcr_db_path = Path(config.dcr_database_path)
            logger.info(
                f"[OnRender Debug] DCR DB path: {dcr_db_path}, exists: {dcr_db_path.exists()}"
            )
            if dcr_db_path.exists():
                databases.append(
                    {
                        "name": "DCR Database (dcr.db)",
                        "path": str(dcr_db_path),
                        "size": dcr_db_path.stat().st_size,
                        "size_mb": round(dcr_db_path.stat().st_size / 1024 / 1024, 2),
                    }
                )
            else:
                # 경로가 존재하지 않아도 리스트에 추가하여 문제 파악
                databases.append(
                    {
                        "name": "DCR Database (dcr.db) - NOT FOUND",
                        "path": str(dcr_db_path),
                        "size": 0,
                        "size_mb": 0,
                        "error": f"File not exists at {dcr_db_path}",
                    }
                )

        # Logs database
        # logs.db 경로 결정 (LogsDBService와 동일한 로직 사용)
        import os

        if os.getenv("RENDER"):
            # OnRender 환경
            logs_db_path = Path("/opt/render/project/src/data/logs.db")
        else:
            # 로컬 환경
            project_root = Path(__file__).parent.parent.parent
            logs_db_path = project_root / "data" / "logs.db"

        logger.info(
            f"[OnRender Debug] Logs DB path: {logs_db_path}, exists: {logs_db_path.exists()}"
        )

        if logs_db_path.exists():
            databases.append(
                {
                    "name": "Logs Database (logs.db)",
                    "path": str(logs_db_path),
                    "size": logs_db_path.stat().st_size,
                    "size_mb": round(logs_db_path.stat().st_size / 1024 / 1024, 2),
                }
            )
        else:
            databases.append(
                {
                    "name": "Logs Database (logs.db) - NOT FOUND",
                    "path": str(logs_db_path),
                    "size": 0,
                    "size_mb": 0,
                    "error": f"File not exists at {logs_db_path}",
                }
            )

        # OnRender 환경 디버깅 정보 추가
        databases.append(
            {
                "name": "Debug Info",
                "path": f"CWD: {os.getcwd()}",
                "size": 0,
                "size_mb": 0,
                "info": {
                    "RENDER": os.getenv("RENDER", "Not set"),
                    "PWD": os.getenv("PWD", "Not set"),
                    "HOME": os.getenv("HOME", "Not set"),
                },
            }
        )

        return databases

    @staticmethod
    def get_database_tables(db_path: str) -> List[str]:
        """Get list of tables in database"""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
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
            # 데이터베이스 파일이 없으면 생성
            db_path_obj = Path(db_path)
            if not db_path_obj.exists():
                logger.warning(f"Database not exists, creating: {db_path}")
                db_path_obj.parent.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Add LIMIT only if explicitly requested
            if (
                limit
                and query.strip().upper().startswith("SELECT")
                and "LIMIT" not in query.upper()
            ):
                query = f"{query.strip().rstrip(';')} LIMIT {limit}"

            cursor.execute(query)

            # Get column names
            columns = (
                [description[0] for description in cursor.description]
                if cursor.description
                else []
            )

            # Get rows
            rows = []
            for row in cursor.fetchall():
                rows.append(dict(row))

            conn.close()

            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            }
        except Exception as e:
            logger.error(f"Error querying database: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_table_schema(db_path: str, table_name: str) -> List[Dict]:
        """Get schema information for a table"""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            schema = []
            for row in cursor.fetchall():
                schema.append(
                    {
                        "cid": row[0],
                        "name": row[1],
                        "type": row[2],
                        "notnull": bool(row[3]),
                        "default_value": row[4],
                        "pk": bool(row[5]),
                    }
                )
            conn.close()
            return schema
        except Exception as e:
            logger.error(f"Error getting table schema: {e}")
            return []

    @staticmethod
    def clear_log_file(log_name: str) -> Dict:
        """Clear (truncate) a specific log file"""
        try:
            log_file = LOG_DIR / log_name
            if not log_file.exists():
                return {"success": False, "error": f"Log file not found: {log_name}"}

            # Truncate the file
            with open(log_file, "w") as f:
                f.truncate(0)

            logger.info(f"Cleared log file: {log_name}")
            return {"success": True, "message": f"Cleared {log_name}"}
        except Exception as e:
            logger.error(f"Error clearing log file: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def clear_all_logs() -> Dict:
        """Clear all log files"""
        try:
            cleared_files = []
            failed_files = []

            if LOG_DIR.exists():
                for log_file in LOG_DIR.glob("*.log"):
                    try:
                        with open(log_file, "w") as f:
                            f.truncate(0)
                        cleared_files.append(log_file.name)
                    except Exception as e:
                        failed_files.append({"file": log_file.name, "error": str(e)})

            logger.info(f"Cleared {len(cleared_files)} log files")

            return {
                "success": True,
                "cleared": cleared_files,
                "failed": failed_files,
                "message": f"Cleared {len(cleared_files)} log files",
            }
        except Exception as e:
            logger.error(f"Error clearing all logs: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def clear_database(db_path: str) -> Dict:
        """Clear all data from database (delete all records from all tables)"""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Get all table names
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables = [row[0] for row in cursor.fetchall()]

            cleared_tables = []
            failed_tables = []

            for table in tables:
                try:
                    cursor.execute(f"DELETE FROM {table}")
                    cleared_tables.append(table)
                except Exception as e:
                    failed_tables.append({"table": table, "error": str(e)})

            conn.commit()
            conn.close()

            logger.info(f"Cleared {len(cleared_tables)} tables in database: {db_path}")

            return {
                "success": True,
                "cleared_tables": cleared_tables,
                "failed_tables": failed_tables,
                "message": f"Cleared {len(cleared_tables)} tables",
            }
        except Exception as e:
            logger.error(f"Error clearing database: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def reset_database(db_path: str) -> Dict:
        """Completely reset database (drop all tables)"""
        try:
            # Use isolation_level=None for autocommit mode
            conn = sqlite3.connect(db_path, isolation_level=None)
            cursor = conn.cursor()

            # Disable foreign key constraints to allow dropping tables
            cursor.execute("PRAGMA foreign_keys = OFF")

            # Get all table names (exclude SQLite internal tables)
            cursor.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table'
                AND name NOT LIKE 'sqlite_%'
                AND name NOT IN ('sqlite_sequence', 'sqlite_stat1', 'sqlite_stat2', 'sqlite_stat3', 'sqlite_stat4')
            """
            )
            tables = [row[0] for row in cursor.fetchall()]

            # Also get views and triggers to drop them first
            cursor.execute("SELECT name FROM sqlite_master WHERE type='view'")
            views = [row[0] for row in cursor.fetchall()]

            cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
            triggers = [row[0] for row in cursor.fetchall()]

            dropped_items = []
            failed_items = []

            # Drop triggers first
            for trigger in triggers:
                try:
                    cursor.execute(f"DROP TRIGGER IF EXISTS '{trigger}'")
                    dropped_items.append(f"trigger:{trigger}")
                    logger.debug(f"Dropped trigger: {trigger}")
                except Exception as e:
                    failed_items.append({"item": f"trigger:{trigger}", "error": str(e)})
                    logger.error(f"Failed to drop trigger {trigger}: {e}")

            # Drop views
            for view in views:
                try:
                    cursor.execute(f"DROP VIEW IF EXISTS '{view}'")
                    dropped_items.append(f"view:{view}")
                    logger.debug(f"Dropped view: {view}")
                except Exception as e:
                    failed_items.append({"item": f"view:{view}", "error": str(e)})
                    logger.error(f"Failed to drop view {view}: {e}")

            # Drop tables - sometimes need multiple passes due to foreign key dependencies
            max_attempts = 3
            for attempt in range(max_attempts):
                remaining_tables = []
                for table in tables:
                    if not any(item.endswith(f":{table}") for item in dropped_items):
                        try:
                            cursor.execute(f"DROP TABLE IF EXISTS '{table}'")
                            dropped_items.append(f"table:{table}")
                            logger.debug(f"Dropped table: {table}")
                        except Exception as e:
                            remaining_tables.append(table)
                            if attempt == max_attempts - 1:
                                failed_items.append(
                                    {"item": f"table:{table}", "error": str(e)}
                                )
                                logger.error(
                                    f"Failed to drop table {table} after {max_attempts} attempts: {e}"
                                )
                tables = remaining_tables
                if not tables:
                    break

            # Vacuum to clean up the database
            cursor.execute("VACUUM")

            # Re-enable foreign key constraints
            cursor.execute("PRAGMA foreign_keys = ON")

            conn.close()

            # Count only tables from dropped_items
            dropped_tables = [
                item for item in dropped_items if item.startswith("table:")
            ]
            logger.info(
                f"Dropped {len(dropped_tables)} tables, {len(dropped_items)} total items in database: {db_path}"
            )

            return {
                "success": True,
                "dropped_items": dropped_items,
                "failed_items": failed_items,
                "message": f"Dropped {len(dropped_tables)} tables, {len(dropped_items)} total database objects",
            }
        except Exception as e:
            logger.error(f"Error resetting database: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_dcr_config() -> Dict:
        """Get current DCR configuration from database"""
        try:
            # Check if this is the DCR database
            dcr_db_path = Path(config.dcr_database_path)
            if not dcr_db_path.exists():
                return {"success": False, "error": "DCR database not found"}

            conn = sqlite3.connect(dcr_db_path)
            cursor = conn.cursor()

            # Get Azure app config
            cursor.execute(
                """
                SELECT application_id, tenant_id, redirect_uri
                FROM dcr_azure_app
                LIMIT 1
            """
            )
            result = cursor.fetchone()
            conn.close()

            if result:
                return {
                    "success": True,
                    "application_id": result[0],
                    "tenant_id": result[1],
                    "redirect_uri": result[2],
                    "env_redirect_uri": os.getenv("DCR_OAUTH_REDIRECT_URI"),
                }
            else:
                return {
                    "success": False,
                    "error": "No DCR configuration found in database",
                }
        except Exception as e:
            logger.error(f"Error getting DCR config: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def update_dcr_redirect_uri(new_redirect_uri: str) -> Dict:
        """Update DCR redirect URI in database and .env file"""
        try:
            if not new_redirect_uri:
                return {"success": False, "error": "Redirect URI is required"}

            # Update in database
            dcr_db_path = Path(config.dcr_database_path)
            if dcr_db_path.exists():
                conn = sqlite3.connect(dcr_db_path)
                cursor = conn.cursor()

                # Check if dcr_azure_app exists
                cursor.execute("SELECT COUNT(*) FROM dcr_azure_app")
                count = cursor.fetchone()[0]

                if count > 0:
                    cursor.execute(
                        """
                        UPDATE dcr_azure_app
                        SET redirect_uri = ?
                        WHERE 1=1
                    """,
                        (new_redirect_uri,),
                    )
                    conn.commit()
                    conn.close()

                    # Also update .env file
                    DashboardService.update_env_variable(
                        "DCR_OAUTH_REDIRECT_URI", new_redirect_uri
                    )

                    logger.info(f"Updated DCR redirect URI to: {new_redirect_uri}")
                    return {
                        "success": True,
                        "message": f"DCR redirect URI updated to: {new_redirect_uri}",
                    }
                else:
                    conn.close()
                    return {
                        "success": False,
                        "error": "No DCR configuration found in database",
                    }
            else:
                return {"success": False, "error": "DCR database not found"}

        except Exception as e:
            logger.error(f"Error updating DCR redirect URI: {e}")
            return {"success": False, "error": str(e)}


def create_dashboard_routes() -> List[Route]:
    """Create dashboard routes"""
    service = DashboardService()
    auth = DashboardAuth()

    # Login page
    async def login_page(request):
        """Login page for dashboard"""
        html = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Login</title>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style>
        .material-icons {
            vertical-align: middle;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 0;
        }
        .login-container {
            background: white;
            border-radius: 16px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            padding: 50px;
            width: 100%;
            max-width: 420px;
        }
        .login-header {
            text-align: center;
            margin-bottom: 40px;
        }
        .login-header h1 {
            color: #333;
            font-size: 28px;
            margin-bottom: 10px;
        }
        .login-header p {
            color: #666;
            font-size: 14px;
        }
        .form-group {
            margin-bottom: 25px;
        }
        .form-group label {
            display: block;
            color: #333;
            font-weight: 600;
            margin-bottom: 8px;
            font-size: 14px;
        }
        .form-group input {
            width: 100%;
            padding: 14px;
            border: 2px solid #e5e7eb;
            border-radius: 8px;
            font-size: 15px;
            transition: all 0.3s;
        }
        .form-group input:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn-login {
            width: 100%;
            padding: 14px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        .btn-login:hover {
            background: #5568d3;
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }
        .error-message {
            background: #fee;
            color: #c33;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
            display: none;
        }
        .error-message.show {
            display: block;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            <h1><span class="material-icons">lock</span> Dashboard Login</h1>
            <p>MailQueryWithMCP Management</p>
        </div>
        <div id="error-message" class="error-message"></div>
        <form id="login-form">
            <div class="form-group">
                <label>Username</label>
                <input type="text" id="username" name="username" required autocomplete="username">
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" id="password" name="password" required autocomplete="current-password">
            </div>
            <button type="submit" class="btn-login">Login</button>
        </form>
    </div>

    <script>
        document.getElementById('login-form').addEventListener('submit', async (e) => {
            e.preventDefault();

            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const errorDiv = document.getElementById('error-message');

            try {
                const response = await fetch('/dashboard/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password})
                });

                const data = await response.json();

                if (data.success) {
                    // Redirect to dashboard
                    window.location.href = '/dashboard';
                } else {
                    errorDiv.textContent = data.error || 'Invalid credentials';
                    errorDiv.classList.add('show');
                }
            } catch (error) {
                errorDiv.textContent = 'Login failed. Please try again.';
                errorDiv.classList.add('show');
            }
        });
    </script>
</body>
</html>
"""
        return HTMLResponse(html)

    # Login API
    async def api_login(request):
        """Handle login request"""
        try:
            data = await request.json()
            username = data.get("username", "")
            password = data.get("password", "")

            if auth.verify_credentials(username, password):
                session_token = auth.create_session(username)

                # Set cookie
                response = JSONResponse({"success": True})
                response.set_cookie(
                    key="dashboard_session",
                    value=session_token,
                    httponly=True,
                    max_age=86400,  # 24 hours
                    samesite="lax",
                )
                return response
            else:
                logger.warning(f"Failed login attempt for username: {username}")
                return JSONResponse(
                    {"success": False, "error": "Invalid username or password"},
                    status_code=401,
                )
        except Exception as e:
            logger.error(f"Login error: {e}")
            return JSONResponse(
                {"success": False, "error": "Login failed"}, status_code=500
            )

    # Logout API
    async def api_logout(request):
        """Handle logout request"""
        session_token = request.cookies.get("dashboard_session")
        if session_token:
            auth.delete_session(session_token)

        response = RedirectResponse(url="/dashboard/login", status_code=302)
        response.delete_cookie("dashboard_session")
        return response

    # Check session helper
    def check_session(request) -> bool:
        """Check if user is authenticated"""
        session_token = request.cookies.get("dashboard_session")
        return auth.verify_session(session_token)

    # Main dashboard page
    async def dashboard_page(request):
        """Main dashboard HTML page"""
        # Check authentication
        if not check_session(request):
            return RedirectResponse(url="/dashboard/login", status_code=302)

        html = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MailQueryWithMCP - Management Dashboard</title>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        .material-icons {
            vertical-align: middle;
            font-size: 20px;
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
            transition: background 0.3s;
        }
        .env-item:hover {
            background: #f0f0f0;
        }
        .env-key {
            font-weight: 600;
            color: #667eea;
            min-width: 200px;
            word-break: break-all;
        }
        .env-value {
            flex: 1;
            color: #333;
            font-family: monospace;
            font-size: 12px;
            word-break: break-all;
            padding: 5px 10px;
            background: white;
            border-radius: 4px;
            border: 1px solid #e0e0e0;
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
            <h1><span class="material-icons" style="font-size: 32px; vertical-align: bottom;">rocket_launch</span> MailQueryWithMCP Management Dashboard</h1>
            <p>Unified server management, logs, and configuration</p>
            <div style="position: absolute; top: 20px; right: 20px; display: flex; gap: 10px;">
                <a href="https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps"
                   target="_blank"
                   class="btn btn-primary"
                   style="display: inline-flex; align-items: center; gap: 8px;">
                    <span class="material-icons">lock</span>
                    <span>Azure AD App</span>
                </a>
                <a href="/dashboard/logout"
                   class="btn btn-danger"
                   style="display: inline-flex; align-items: center; gap: 8px;">
                    <span class="material-icons">logout</span>
                    <span>Logout</span>
                </a>
            </div>
        </div>

        <div class="grid">
            <!-- Mail Query Server Status -->
            <div class="card">
                <h2><span class="material-icons">email</span> Mail Query MCP Server</h2>
                <div id="mail-query-server-status">Loading...</div>
                <div style="margin-top: 15px; display: flex; gap: 10px;">
                    <button class="btn btn-primary" onclick="startServer('mail_query')" style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">play_arrow</span> Start</button>
                    <button class="btn btn-danger" onclick="stopServer('mail_query')" style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">stop</span> Stop</button>
                </div>
            </div>

            <!-- OneNote Server Status -->
            <div class="card">
                <h2><span class="material-icons">note</span> OneNote MCP Server</h2>
                <div id="onenote-server-status">Loading...</div>
                <div style="margin-top: 15px; display: flex; gap: 10px;">
                    <button class="btn btn-primary" onclick="startServer('onenote')" style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">play_arrow</span> Start</button>
                    <button class="btn btn-danger" onclick="stopServer('onenote')" style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">stop</span> Stop</button>
                </div>
            </div>

            <!-- Teams Server Status -->
            <div class="card">
                <h2><span class="material-icons">chat</span> Teams MCP Server</h2>
                <div id="teams-server-status">Loading...</div>
                <div style="margin-top: 15px; display: flex; gap: 10px;">
                    <button class="btn btn-primary" onclick="startServer('teams')" style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">play_arrow</span> Start</button>
                    <button class="btn btn-danger" onclick="stopServer('teams')" style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">stop</span> Stop</button>
                </div>
            </div>

            <!-- Tunnel Status -->
            <div class="card">
                <h2><span class="material-icons">public</span> Cloudflare Tunnel</h2>
                <div id="tunnel-status">Loading...</div>
                <div style="margin-top: 15px;">
                    <label for="tunnel-port" style="display: block; margin-bottom: 5px;">Tunnel Port:</label>
                    <input type="number" id="tunnel-port" value="8001" min="1" max="65535" style="width: 100%; padding: 8px; margin-bottom: 10px; border: 1px solid #ddd; border-radius: 4px;">
                    <div style="display: flex; gap: 10px;">
                        <button class="btn btn-primary" onclick="startTunnelWithPort()" style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">play_arrow</span> Start Tunnel</button>
                        <button class="btn btn-danger" onclick="stopTunnel()" style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">stop</span> Stop Tunnel</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Tabs Navigation -->
        <div class="card full-width">
            <div class="tabs">
                <button class="tab active" onclick="switchTab('logs')"><span class="material-icons">description</span> Logs</button>
                <button class="tab" onclick="switchTab('endpoints')"><span class="material-icons">link</span> Endpoints</button>
                <button class="tab" onclick="switchTab('database')"><span class="material-icons">storage</span> Database</button>
                <button class="tab" onclick="switchTab('env')"><span class="material-icons">settings</span> Environment</button>
            </div>

            <!-- Logs Tab -->
            <div id="logs-tab" class="tab-content active">
                <h2 style="margin-bottom: 15px;"><span class="material-icons">description</span> Log Viewer</h2>
                <div class="log-selector">
                    <select id="log-select" onchange="loadLog()">
                        <option value="">Select a log file...</option>
                    </select>
                </div>
                <div class="log-viewer" id="log-content">Select a log file to view its contents</div>
                <div style="display: flex; gap: 10px; margin-top: 10px;">
                    <button class="btn btn-primary" onclick="loadLog()" style="display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">refresh</span> Refresh Log</button>
                    <button class="btn btn-danger" onclick="clearCurrentLog()" style="display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">delete</span> Clear Current Log</button>
                    <button class="btn btn-danger" onclick="clearAllLogs()" style="display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">warning</span> Clear All Logs</button>
                </div>
            </div>

            <!-- Endpoints Tab -->
            <div id="endpoints-tab" class="tab-content">
                <h2 style="margin-bottom: 15px;"><span class="material-icons">link</span> Service Endpoints</h2>
                <div id="endpoints-info">Loading...</div>
            </div>

            <!-- Database Tab -->
            <div id="database-tab" class="tab-content">
                <h2 style="margin-bottom: 15px;"><span class="material-icons">storage</span> Database Viewer</h2>

                <!-- DCR Configuration Section -->
                <div id="dcr-config-section" style="display: none; padding: 15px; background: #f0f9ff; border-radius: 8px; margin-bottom: 20px;">
                    <h3 style="margin-bottom: 15px; color: #667eea; display: flex; align-items: center; gap: 8px;"><span class="material-icons">lock</span> DCR OAuth Configuration</h3>
                    <div style="display: grid; grid-template-columns: 1fr 2fr; gap: 10px; margin-bottom: 15px;">
                        <div>
                            <label style="display: block; margin-bottom: 5px; font-weight: 600; color: #666;">Application ID:</label>
                            <div id="dcr-app-id" style="padding: 10px; background: white; border-radius: 5px; font-family: monospace; font-size: 12px;">Loading...</div>
                        </div>
                        <div>
                            <label style="display: block; margin-bottom: 5px; font-weight: 600; color: #666;">Tenant ID:</label>
                            <div id="dcr-tenant-id" style="padding: 10px; background: white; border-radius: 5px; font-family: monospace; font-size: 12px;">Loading...</div>
                        </div>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <label style="display: block; margin-bottom: 5px; font-weight: 600; color: #666;">Redirect URI (DB):</label>
                        <div style="display: flex; gap: 10px;">
                            <input type="text" id="dcr-redirect-uri" class="env-input" style="flex: 1; font-family: monospace; font-size: 12px;" placeholder="https://example.trycloudflare.com/oauth/azure_callback">
                            <button class="btn btn-primary" onclick="updateDcrRedirectUri()" style="display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">save</span> Save</button>
                        </div>
                        <div id="dcr-env-uri" style="margin-top: 5px; padding: 5px; font-size: 11px; color: #666;">
                            <strong>ENV:</strong> <span id="dcr-env-value">Loading...</span>
                        </div>
                    </div>
                    <div style="padding: 10px; background: #fff3cd; border-radius: 5px; border: 1px solid #ffc107;">
                        <strong><span class="material-icons" style="font-size: 16px; vertical-align: text-bottom;">warning</span> Important:</strong> The redirect URI must match exactly with Azure AD App Registration.
                        <br>After changing, update Azure Portal and restart the server.
                    </div>
                </div>

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

                <div style="margin-bottom: 15px; display: flex; gap: 10px;">
                    <button class="btn btn-danger" onclick="clearDatabase()" style="display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">delete</span> Clear Database (Delete Data)</button>
                    <button class="btn btn-danger" onclick="resetDatabase()" style="display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">warning</span> Reset Database (Drop Tables)</button>
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
                <h2 style="margin-bottom: 15px;"><span class="material-icons">settings</span> Environment Variables</h2>
                <div class="env-editor">
                    <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 10px;">
                        <select id="env-select" class="env-input" style="flex: 1;" onchange="onEnvSelect()">
                            <option value="">Select a variable to edit or enter new...</option>
                        </select>
                        <button class="btn btn-primary" onclick="loadEnvVariables()" style="display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">refresh</span> Refresh</button>
                    </div>
                    <input type="text" id="new-env-key" class="env-input" placeholder="Variable name (e.g., REDIRECT_URI)">
                    <input type="text" id="new-env-value" class="env-input" placeholder="Value">
                    <div style="display: flex; gap: 10px; margin-top: 10px;">
                        <button class="btn btn-primary" onclick="addEnvVariable()" style="display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">save</span> Add/Update Variable</button>
                        <button class="btn btn-danger" onclick="clearEnvForm()" style="display: flex; align-items: center; justify-content: center; gap: 5px;"><span class="material-icons">clear</span> Clear Form</button>
                    </div>
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
            // Note: event.target might be the span inside the button, so we need to find the closest button
            const tabButton = event.target.closest('.tab');
            if (tabButton) {
                tabButton.classList.add('active');
            }
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

                // Render Mail Query server status
                const mailQueryServer = data.server.mail_query || {status: 'stopped'};
                const mailQueryHtml = mailQueryServer.status === 'running' ? `
                    <span class="status-badge status-running">RUNNING</span>
                    <div class="info-row">
                        <span class="info-label">PID:</span>
                        <span class="info-value">${mailQueryServer.pid}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Endpoint:</span>
                        <span class="info-value">
                            <a href="${mailQueryServer.endpoint}/health" target="_blank" class="url-copy">
                                ${mailQueryServer.endpoint}
                            </a>
                        </span>
                    </div>
                ` : mailQueryServer.status === 'starting' ? `
                    <span class="status-badge" style="background: #f59e0b;">STARTING</span>
                    <div class="info-row">
                        <span class="info-label">PID:</span>
                        <span class="info-value">${mailQueryServer.pid}</span>
                    </div>
                ` : `<span class="status-badge status-stopped">STOPPED</span>`;

                // Render OneNote server status
                const onenoteServer = data.server.onenote || {status: 'stopped'};
                const onenoteHtml = onenoteServer.status === 'running' ? `
                    <span class="status-badge status-running">RUNNING</span>
                    <div class="info-row">
                        <span class="info-label">PID:</span>
                        <span class="info-value">${onenoteServer.pid}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Endpoint:</span>
                        <span class="info-value">
                            <a href="${onenoteServer.endpoint}/health" target="_blank" class="url-copy">
                                ${onenoteServer.endpoint}
                            </a>
                        </span>
                    </div>
                ` : onenoteServer.status === 'starting' ? `
                    <span class="status-badge" style="background: #f59e0b;">STARTING</span>
                    <div class="info-row">
                        <span class="info-label">PID:</span>
                        <span class="info-value">${onenoteServer.pid}</span>
                    </div>
                ` : `<span class="status-badge status-stopped">STOPPED</span>`;

                // Render Teams server status
                const teamsServer = data.server.teams || {status: 'stopped'};
                const teamsHtml = teamsServer.status === 'running' ? `
                    <span class="status-badge status-running">RUNNING</span>
                    <div class="info-row">
                        <span class="info-label">PID:</span>
                        <span class="info-value">${teamsServer.pid}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Endpoint:</span>
                        <span class="info-value">
                            <a href="${teamsServer.endpoint}/health" target="_blank" class="url-copy">
                                ${teamsServer.endpoint}
                            </a>
                        </span>
                    </div>
                ` : teamsServer.status === 'starting' ? `
                    <span class="status-badge" style="background: #f59e0b;">STARTING</span>
                    <div class="info-row">
                        <span class="info-label">PID:</span>
                        <span class="info-value">${teamsServer.pid}</span>
                    </div>
                ` : `<span class="status-badge status-stopped">STOPPED</span>`;

                const tunnelHtml = data.tunnel.status === 'running' ? `
                    <span class="status-badge status-running">RUNNING</span>
                    <div class="info-row">
                        <span class="info-label">PID:</span>
                        <span class="info-value">${data.tunnel.pid}</span>
                    </div>
                    ${data.tunnel.port ? `
                    <div class="info-row">
                        <span class="info-label">Port:</span>
                        <span class="info-value">${data.tunnel.port}</span>
                    </div>` : ''}
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

                document.getElementById('mail-query-server-status').innerHTML = mailQueryHtml;
                document.getElementById('onenote-server-status').innerHTML = onenoteHtml;
                document.getElementById('teams-server-status').innerHTML = teamsHtml;
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
                    html += '<h3 style="margin-bottom: 10px; color: #856404; display: flex; align-items: center; gap: 8px;"><span class="material-icons">lock</span> OAuth Redirect URIs (Azure AD App Registration)</h3>';
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
                                <div style="font-size: 10px; color: #6c757d; margin-top: 5px; display: flex; align-items: center; gap: 4px;"><span class="material-icons" style="font-size: 12px;">content_copy</span> Click to copy</div>
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

                // Update dropdown
                const select = document.getElementById('env-select');
                select.innerHTML = '<option value="">Select a variable to edit or enter new...</option>';

                let html = '';
                for (const [key, value] of Object.entries(data)) {
                    // Add to dropdown
                    const option = document.createElement('option');
                    option.value = key;
                    option.textContent = key;
                    option.setAttribute('data-value', value);
                    select.appendChild(option);

                    // Add to display list with edit button
                    html += `
                        <div class="env-item">
                            <span class="env-key">${key}</span>
                            <span class="env-value">${value}</span>
                            <button class="btn btn-primary" style="margin-left: auto; padding: 5px 10px; font-size: 12px; display: flex; align-items: center; gap: 4px;"
                                    onclick="editEnvVariable('${key}', '${value.replace(/'/g, "\\'")}')"><span class="material-icons" style="font-size: 14px;">edit</span> Edit</button>
                        </div>
                    `;
                }
                document.getElementById('env-variables').innerHTML = html || '<p style="color: #666;">No environment variables found</p>';
            } catch (error) {
                console.error('Error loading env variables:', error);
            }
        }

        // Handle environment variable selection
        function onEnvSelect() {
            const select = document.getElementById('env-select');
            const selectedOption = select.options[select.selectedIndex];

            if (selectedOption.value) {
                const value = selectedOption.getAttribute('data-value');
                document.getElementById('new-env-key').value = selectedOption.value;
                document.getElementById('new-env-value').value = value;
            }
        }

        // Edit environment variable
        function editEnvVariable(key, value) {
            document.getElementById('new-env-key').value = key;
            document.getElementById('new-env-value').value = value;

            // Update dropdown selection
            const select = document.getElementById('env-select');
            select.value = key;

            // Scroll to editor
            document.getElementById('env-tab').scrollIntoView({ behavior: 'smooth' });
        }

        // Clear environment form
        function clearEnvForm() {
            document.getElementById('new-env-key').value = '';
            document.getElementById('new-env-value').value = '';
            document.getElementById('env-select').value = '';
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
        async function startServer(serverType) {
            try {
                const response = await fetch('/dashboard/api/server/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({server_type: serverType})
                });
                const data = await response.json();

                if (data.success) {
                    showToast(`${serverType === 'mail_query' ? 'Mail Query' : 'OneNote'} server started successfully!`);
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
        async function stopServer(serverType) {
            if (!confirm(`Are you sure you want to stop the ${serverType === 'mail_query' ? 'Mail Query' : 'OneNote'} server?`)) return;

            try {
                const response = await fetch('/dashboard/api/server/stop', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({server_type: serverType})
                });
                const data = await response.json();

                if (data.success) {
                    showToast(`${serverType === 'mail_query' ? 'Mail Query' : 'OneNote'} server stopped successfully!`);
                    setTimeout(() => loadServerStatus(), 2000);
                } else {
                    showToast('Failed to stop server: ' + data.error);
                }
            } catch (error) {
                console.error('Error stopping server:', error);
                showToast('Error stopping server');
            }
        }

        // Start tunnel with specified port
        async function startTunnelWithPort() {
            try {
                const port = document.getElementById('tunnel-port').value;
                showToast(`Starting tunnel on port ${port}... This may take up to 20 seconds.`);

                const response = await fetch('/dashboard/api/tunnel/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({port: parseInt(port)})
                });
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

        // Backward compatibility
        async function startTunnel() {
            startTunnelWithPort();
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

                    // Load DCR config when DCR database is selected
                    loadDcrConfig();

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

                // Check if DCR database is selected
                if (dbPath.includes('dcr.db')) {
                    // Show DCR config section
                    document.getElementById('dcr-config-section').style.display = 'block';
                    loadDcrConfig();
                } else {
                    // Hide DCR config section
                    document.getElementById('dcr-config-section').style.display = 'none';
                }

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

        // Clear current log
        async function clearCurrentLog() {
            const logName = document.getElementById('log-select').value;
            if (!logName) {
                showToast('Please select a log file first');
                return;
            }

            if (!confirm(`Are you sure you want to clear the log file "${logName}"?`)) return;

            try {
                const response = await fetch(`/dashboard/api/logs/${logName}/clear`, {method: 'POST'});
                const data = await response.json();

                if (data.success) {
                    showToast(data.message || `Cleared ${logName}`);
                    loadLog(); // Reload the log to show it's empty
                } else {
                    showToast('Failed to clear log: ' + data.error);
                }
            } catch (error) {
                console.error('Error clearing log:', error);
                showToast('Error clearing log');
            }
        }

        // Clear all logs
        async function clearAllLogs() {
            if (!confirm('Are you sure you want to clear ALL log files? This action cannot be undone!')) return;

            try {
                const response = await fetch('/dashboard/api/logs/clear-all', {method: 'POST'});
                const data = await response.json();

                if (data.success) {
                    showToast(data.message || 'All logs cleared');
                    loadLog(); // Reload current log
                    loadLogFiles(); // Refresh log list
                } else {
                    showToast('Failed to clear logs: ' + data.error);
                }
            } catch (error) {
                console.error('Error clearing all logs:', error);
                showToast('Error clearing all logs');
            }
        }

        // Clear database (delete data)
        async function clearDatabase() {
            const dbPath = document.getElementById('db-select').value;
            if (!dbPath) {
                showToast('Please select a database first');
                return;
            }

            const dbName = document.getElementById('db-select').options[document.getElementById('db-select').selectedIndex].text;
            if (!confirm(`Are you sure you want to DELETE ALL DATA from "${dbName}"? This will remove all records but keep the table structure.`)) return;

            try {
                const response = await fetch('/dashboard/api/db/clear', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({db_path: dbPath})
                });

                const data = await response.json();

                if (data.success) {
                    showToast(data.message || 'Database cleared');
                    // Clear the results view
                    document.getElementById('results-content').innerHTML = '<p style="color: #666;">Database cleared. Select a table to see empty structure.</p>';
                    // Reload current table if selected
                    const tableName = document.getElementById('table-select').value;
                    if (tableName) {
                        selectAllFromTable();
                    }
                } else {
                    showToast('Failed to clear database: ' + data.error);
                }
            } catch (error) {
                console.error('Error clearing database:', error);
                showToast('Error clearing database');
            }
        }

        // Reset database (drop tables)
        async function resetDatabase() {
            const dbPath = document.getElementById('db-select').value;
            if (!dbPath) {
                showToast('Please select a database first');
                return;
            }

            const dbName = document.getElementById('db-select').options[document.getElementById('db-select').selectedIndex].text;
            if (!confirm(`⚠️ WARNING: Are you sure you want to COMPLETELY RESET "${dbName}"? This will DROP ALL TABLES and cannot be undone!`)) return;
            if (!confirm(`This is your final warning! All tables and data in "${dbName}" will be permanently deleted. Continue?`)) return;

            try {
                const response = await fetch('/dashboard/api/db/reset', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({db_path: dbPath})
                });

                const data = await response.json();

                if (data.success) {
                    showToast(data.message || 'Database reset');
                    // Clear everything
                    document.getElementById('table-select').innerHTML = '<option value="">Select table...</option>';
                    document.getElementById('results-content').innerHTML = '<p style="color: #666;">Database has been reset. All tables have been dropped.</p>';
                    // Reload tables (should be empty)
                    loadDatabaseTables();
                } else {
                    showToast('Failed to reset database: ' + data.error);
                }
            } catch (error) {
                console.error('Error resetting database:', error);
                showToast('Error resetting database');
            }
        }

        // Load DCR configuration
        async function loadDcrConfig() {
            try {
                const response = await fetch('/dashboard/api/dcr/config');
                const data = await response.json();

                if (data.success) {
                    document.getElementById('dcr-app-id').textContent = data.application_id || 'Not configured';
                    document.getElementById('dcr-tenant-id').textContent = data.tenant_id || 'common';
                    document.getElementById('dcr-redirect-uri').value = data.redirect_uri || '';

                    // Show environment value
                    if (data.env_redirect_uri) {
                        document.getElementById('dcr-env-value').textContent = data.env_redirect_uri;
                        document.getElementById('dcr-env-value').style.color = '#28a745';
                    } else {
                        document.getElementById('dcr-env-value').textContent = 'Not set in .env';
                        document.getElementById('dcr-env-value').style.color = '#dc3545';
                    }
                } else {
                    document.getElementById('dcr-app-id').textContent = 'Not configured';
                    document.getElementById('dcr-tenant-id').textContent = 'Not configured';
                    document.getElementById('dcr-redirect-uri').value = '';
                    document.getElementById('dcr-env-value').textContent = data.error || 'Configuration not found';
                }
            } catch (error) {
                console.error('Error loading DCR config:', error);
                document.getElementById('dcr-app-id').textContent = 'Error loading';
                document.getElementById('dcr-tenant-id').textContent = 'Error loading';
            }
        }

        // Update DCR redirect URI
        async function updateDcrRedirectUri() {
            const newUri = document.getElementById('dcr-redirect-uri').value.trim();

            if (!newUri) {
                showToast('Please enter a redirect URI');
                return;
            }

            if (!newUri.startsWith('http://') && !newUri.startsWith('https://')) {
                showToast('Redirect URI must start with http:// or https://');
                return;
            }

            if (!confirm(`Update DCR redirect URI to:\n${newUri}\n\nThis will update both the database and .env file.`)) {
                return;
            }

            try {
                const response = await fetch('/dashboard/api/dcr/redirect-uri', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({redirect_uri: newUri})
                });

                const data = await response.json();

                if (data.success) {
                    showToast(data.message || 'DCR redirect URI updated');
                    // Reload the configuration
                    loadDcrConfig();
                    // Also reload env variables
                    loadEnvVariables();
                } else {
                    showToast('Failed to update: ' + data.error);
                }
            } catch (error) {
                console.error('Error updating DCR redirect URI:', error);
                showToast('Error updating DCR redirect URI');
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

    # Require authentication wrapper
    def require_auth(handler):
        """Decorator to require authentication for API endpoints"""

        async def wrapper(request):
            if not check_session(request):
                return JSONResponse(
                    {"error": "Authentication required"}, status_code=401
                )
            return await handler(request)

        return wrapper

    # API: Get status
    async def api_status(request):
        """Get server and tunnel status"""
        if not check_session(request):
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        server_status = service.get_server_status()
        tunnel_status = service.get_tunnel_status()
        return JSONResponse({"server": server_status, "tunnel": tunnel_status})

    # API: Start server
    async def api_start_server(request):
        """Start MCP server"""
        try:
            body = (
                await request.json()
                if request.headers.get("content-type") == "application/json"
                else {}
            )
            server_type = body.get("server_type", "mail_query")
            result = service.start_server(server_type=server_type)
        except:
            result = service.start_server()
        return JSONResponse(result)

    # API: Stop server
    async def api_stop_server(request):
        """Stop MCP server"""
        try:
            body = (
                await request.json()
                if request.headers.get("content-type") == "application/json"
                else {}
            )
            server_type = body.get("server_type", "mail_query")
            result = service.stop_server(server_type=server_type)
        except:
            result = service.stop_server()
        return JSONResponse(result)

    # API: Start tunnel
    async def api_start_tunnel(request):
        """Start Cloudflare tunnel with optional port"""
        try:
            # Get port from request body if provided
            body = (
                await request.json()
                if request.headers.get("content-type") == "application/json"
                else {}
            )
            port = body.get("port")
            result = service.start_tunnel(port=port)
        except:
            # Fallback to default if no port provided
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
        tunnel_url = request.query_params.get("tunnel_url")
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
            key = data.get("key")
            value = data.get("value", "")

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
        log_name = request.path_params["log_name"]
        lines = int(request.query_params.get("lines", 100))
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
        db_path = request.query_params.get("db_path")
        if not db_path:
            return JSONResponse({"error": "db_path required"}, status_code=400)
        tables = service.get_database_tables(db_path)
        return JSONResponse({"tables": tables})

    # API: Get table schema
    async def api_table_schema(request):
        """Get schema for a table"""
        db_path = request.query_params.get("db_path")
        table_name = request.query_params.get("table")
        if not db_path or not table_name:
            return JSONResponse(
                {"error": "db_path and table required"}, status_code=400
            )
        schema = service.get_table_schema(db_path, table_name)
        return JSONResponse({"schema": schema})

    # API: Query database
    async def api_query_db(request):
        """Execute SQL query"""
        try:
            data = await request.json()
            db_path = data.get("db_path")
            query = data.get("query")
            limit = data.get("limit", None)  # Make limit optional

            if not db_path or not query:
                return JSONResponse(
                    {"error": "db_path and query required"}, status_code=400
                )

            result = service.query_database(db_path, query, limit)
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"Error in query API: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    # API: Clear log file
    async def api_clear_log(request):
        """Clear a specific log file"""
        log_name = request.path_params["log_name"]
        result = service.clear_log_file(log_name)
        return JSONResponse(result)

    # API: Clear all logs
    async def api_clear_all_logs(request):
        """Clear all log files"""
        result = service.clear_all_logs()
        return JSONResponse(result)

    # API: Clear database
    async def api_clear_database(request):
        """Clear all data from database"""
        try:
            data = await request.json()
            db_path = data.get("db_path")
            if not db_path:
                return JSONResponse({"error": "db_path required"}, status_code=400)
            result = service.clear_database(db_path)
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"Error clearing database: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    # API: Reset database
    async def api_reset_database(request):
        """Completely reset database (drop all tables)"""
        try:
            data = await request.json()
            db_path = data.get("db_path")
            if not db_path:
                return JSONResponse({"error": "db_path required"}, status_code=400)
            result = service.reset_database(db_path)
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"Error resetting database: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    # API: Get DCR configuration
    async def api_get_dcr_config(request):
        """Get current DCR configuration"""
        result = service.get_dcr_config()
        return JSONResponse(result)

    # API: Get DCR database logs
    async def api_get_dcr_logs(request):
        """Get DCR database operation logs"""
        try:
            from modules.dcr_oauth_module.dcr_db_logger import get_dcr_db_logger

            dcr_logger = get_dcr_db_logger()

            # Get query parameters
            limit = int(request.query_params.get("limit", 100))
            operation = request.query_params.get("operation", None)

            logs = dcr_logger.get_recent_logs(limit, operation)

            return JSONResponse({"success": True, "count": len(logs), "logs": logs})

        except Exception as e:
            logger.error(f"Error getting DCR logs: {e}")
            return JSONResponse({"success": False, "error": str(e)})

    # API: Get DCR database log statistics
    async def api_get_dcr_log_stats(request):
        """Get DCR database operation statistics"""
        try:
            from modules.dcr_oauth_module.dcr_db_logger import get_dcr_db_logger

            dcr_logger = get_dcr_db_logger()
            stats = dcr_logger.get_statistics()

            return JSONResponse({"success": True, "statistics": stats})

        except Exception as e:
            logger.error(f"Error getting DCR log stats: {e}")
            return JSONResponse({"success": False, "error": str(e)})

    # API: Update DCR redirect URI
    async def api_update_dcr_redirect_uri(request):
        """Update DCR redirect URI"""
        try:
            data = await request.json()
            new_redirect_uri = data.get("redirect_uri")
            if not new_redirect_uri:
                return JSONResponse({"error": "redirect_uri required"}, status_code=400)
            result = service.update_dcr_redirect_uri(new_redirect_uri)
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"Error updating DCR redirect URI: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    return [
        # Authentication routes (no auth required)
        Route("/dashboard/login", endpoint=login_page, methods=["GET"]),
        Route("/dashboard/login", endpoint=api_login, methods=["POST"]),
        Route("/dashboard/logout", endpoint=api_logout, methods=["GET"]),
        # Dashboard routes (auth required)
        Route("/dashboard", endpoint=dashboard_page, methods=["GET"]),
        Route("/dashboard/api/status", endpoint=api_status, methods=["GET"]),
        Route(
            "/dashboard/api/server/start", endpoint=api_start_server, methods=["POST"]
        ),
        Route("/dashboard/api/server/stop", endpoint=api_stop_server, methods=["POST"]),
        Route(
            "/dashboard/api/tunnel/start", endpoint=api_start_tunnel, methods=["POST"]
        ),
        Route("/dashboard/api/tunnel/stop", endpoint=api_stop_tunnel, methods=["POST"]),
        Route("/dashboard/api/endpoints", endpoint=api_endpoints, methods=["GET"]),
        Route("/dashboard/api/env", endpoint=api_get_env, methods=["GET"]),
        Route("/dashboard/api/env", endpoint=api_update_env, methods=["POST"]),
        Route("/dashboard/api/logs", endpoint=api_logs, methods=["GET"]),
        Route(
            "/dashboard/api/logs/{log_name:path}",
            endpoint=api_log_content,
            methods=["GET"],
        ),
        Route("/dashboard/api/databases", endpoint=api_databases, methods=["GET"]),
        Route("/dashboard/api/db/tables", endpoint=api_db_tables, methods=["GET"]),
        Route("/dashboard/api/db/schema", endpoint=api_table_schema, methods=["GET"]),
        Route("/dashboard/api/db/query", endpoint=api_query_db, methods=["POST"]),
        Route(
            "/dashboard/api/logs/{log_name:path}/clear",
            endpoint=api_clear_log,
            methods=["POST"],
        ),
        Route(
            "/dashboard/api/logs/clear-all",
            endpoint=api_clear_all_logs,
            methods=["POST"],
        ),
        Route("/dashboard/api/db/clear", endpoint=api_clear_database, methods=["POST"]),
        Route("/dashboard/api/db/reset", endpoint=api_reset_database, methods=["POST"]),
        Route(
            "/dashboard/api/dcr/config", endpoint=api_get_dcr_config, methods=["GET"]
        ),
        Route(
            "/dashboard/api/dcr/redirect-uri",
            endpoint=api_update_dcr_redirect_uri,
            methods=["POST"],
        ),
        Route("/dashboard/api/dcr/logs", endpoint=api_get_dcr_logs, methods=["GET"]),
        Route(
            "/dashboard/api/dcr/logs/stats",
            endpoint=api_get_dcr_log_stats,
            methods=["GET"],
        ),
    ]
