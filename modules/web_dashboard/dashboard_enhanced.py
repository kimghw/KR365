"""Enhanced Dashboard Extension for MCP Servers"""

import json
from typing import Dict, List
from pathlib import Path
import httpx
import asyncio
from infra.core.logger import get_logger

logger = get_logger(__name__)

class MCPServerMonitor:
    """Monitor and manage MCP servers with enhanced features"""

    MCP_SERVERS_CONFIG = {
        "outlook": {
            "name": "Outlook MCP",
            "icon": "email",
            "port": 8001,
            "health_endpoint": "/health",
            "docs_endpoint": "/docs",
            "oauth_endpoints": {
                "register": "/oauth/register",
                "authorize": "/oauth/authorize",
                "token": "/oauth/token",
                "discovery": "/.well-known/oauth-authorization-server"
            },
            "features": [
                "Email Query & Search",
                "Attachment Management",
                "DCR OAuth Authentication",
                "Email Prompts & Templates"
            ],
            "auth_db": "auth_outlook.db",
            "data_db": "mail_query.db"
        },
        "onenote": {
            "name": "OneNote MCP",
            "icon": "note",
            "port": 8002,
            "health_endpoint": "/health",
            "docs_endpoint": "/docs",
            "oauth_endpoints": {
                "register": "/oauth/register",
                "authorize": "/oauth/authorize",
                "token": "/oauth/token",
                "discovery": "/.well-known/oauth-authorization-server"
            },
            "features": [
                "Notebook Management",
                "Page CRUD Operations",
                "Content Editing (append/prepend/insert)",
                "Recent Items Tracking"
            ],
            "auth_db": "auth_onenote.db",
            "data_db": "onenote.db"
        },
        "teams": {
            "name": "Teams MCP",
            "icon": "chat",
            "port": 8003,
            "health_endpoint": "/health",
            "docs_endpoint": "/docs",
            "oauth_endpoints": {
                "register": "/oauth/register",
                "authorize": "/oauth/authorize",
                "token": "/oauth/token",
                "discovery": "/.well-known/oauth-authorization-server"
            },
            "features": [
                "1:1 & Group Chat Management",
                "Message Reading & Sending",
                "Message Search",
                "Korean Name Mapping"
            ],
            "auth_db": "auth_teams.db",
            "data_db": "teams.db"
        }
    }

    @staticmethod
    async def get_server_detailed_status(server_type: str) -> Dict:
        """Get detailed status of a specific MCP server"""
        config = MCPServerMonitor.MCP_SERVERS_CONFIG.get(server_type)
        if not config:
            return {"error": f"Unknown server type: {server_type}"}

        status = {
            "name": config["name"],
            "type": server_type,
            "icon": config["icon"],
            "port": config["port"],
            "features": config["features"],
            "running": False,
            "health": "unknown",
            "docs_url": None,
            "oauth_status": {},
            "dcr_clients": 0,
            "active_accounts": 0
        }

        base_url = f"http://localhost:{config['port']}"

        try:
            # Check health
            async with httpx.AsyncClient(timeout=2.0) as client:
                health_resp = await client.get(f"{base_url}{config['health_endpoint']}")
                if health_resp.status_code == 200:
                    status["running"] = True
                    status["health"] = "healthy"
                    status["docs_url"] = f"{base_url}{config['docs_endpoint']}"

                    # Check OAuth discovery
                    try:
                        oauth_resp = await client.get(f"{base_url}{config['oauth_endpoints']['discovery']}")
                        if oauth_resp.status_code == 200:
                            oauth_data = oauth_resp.json()
                            status["oauth_status"] = {
                                "configured": True,
                                "issuer": oauth_data.get("issuer"),
                                "registration": f"{base_url}{config['oauth_endpoints']['register']}",
                                "authorization": f"{base_url}{config['oauth_endpoints']['authorize']}"
                            }
                    except:
                        pass

                    # Check database status
                    project_root = Path(__file__).parent.parent.parent
                    auth_db = project_root / "data" / config["auth_db"]
                    data_db = project_root / "data" / config["data_db"]

                    status["databases"] = {
                        "auth": {
                            "path": str(auth_db),
                            "exists": auth_db.exists(),
                            "size_mb": round(auth_db.stat().st_size / 1024 / 1024, 2) if auth_db.exists() else 0
                        },
                        "data": {
                            "path": str(data_db),
                            "exists": data_db.exists(),
                            "size_mb": round(data_db.stat().st_size / 1024 / 1024, 2) if data_db.exists() else 0
                        }
                    }

                    # Count DCR clients if auth DB exists
                    if auth_db.exists():
                        try:
                            import sqlite3
                            conn = sqlite3.connect(auth_db)
                            cursor = conn.cursor()

                            # Try to count DCR clients
                            try:
                                cursor.execute(f"SELECT COUNT(*) FROM dcr_clients_{server_type}")
                                status["dcr_clients"] = cursor.fetchone()[0]
                            except:
                                pass

                            # Try to count active accounts
                            try:
                                cursor.execute(f"SELECT COUNT(*) FROM dcr_azure_users WHERE user_email IS NOT NULL")
                                status["active_accounts"] = cursor.fetchone()[0]
                            except:
                                pass

                            conn.close()
                        except:
                            pass

        except httpx.TimeoutException:
            status["health"] = "timeout"
        except httpx.ConnectError:
            status["health"] = "stopped"
        except Exception as e:
            status["health"] = "error"
            status["error"] = str(e)

        return status

    @staticmethod
    async def get_all_servers_status() -> Dict:
        """Get status of all MCP servers"""
        tasks = []
        for server_type in MCPServerMonitor.MCP_SERVERS_CONFIG.keys():
            tasks.append(MCPServerMonitor.get_server_detailed_status(server_type))

        results = await asyncio.gather(*tasks)

        servers_status = {}
        for server_type, status in zip(MCPServerMonitor.MCP_SERVERS_CONFIG.keys(), results):
            servers_status[server_type] = status

        # Summary
        running_count = sum(1 for s in servers_status.values() if s.get("running"))
        total_count = len(servers_status)

        return {
            "servers": servers_status,
            "summary": {
                "total": total_count,
                "running": running_count,
                "stopped": total_count - running_count
            }
        }

    @staticmethod
    def generate_dashboard_card_html(server_status: Dict) -> str:
        """Generate HTML for a server status card"""
        icon_map = {
            "email": "📧",
            "note": "📓",
            "chat": "💬"
        }

        status_badge = "🟢" if server_status.get("running") else "🔴"
        icon = icon_map.get(server_status.get("icon", ""), "📦")

        features_html = "<ul style='margin: 10px 0; padding-left: 20px;'>"
        for feature in server_status.get("features", []):
            features_html += f"<li style='font-size: 12px; color: #666;'>{feature}</li>"
        features_html += "</ul>"

        oauth_html = ""
        if server_status.get("oauth_status", {}).get("configured"):
            oauth_html = f"""
            <div style='margin-top: 10px; padding: 10px; background: #f0f9ff; border-radius: 6px;'>
                <div style='font-size: 12px; color: #0369a1;'>
                    <strong>OAuth DCR:</strong> ✅ Configured<br>
                    <strong>Clients:</strong> {server_status.get('dcr_clients', 0)}<br>
                    <strong>Accounts:</strong> {server_status.get('active_accounts', 0)}
                </div>
            </div>
            """

        docs_link = ""
        if server_status.get("docs_url"):
            docs_link = f"""
            <a href="{server_status['docs_url']}" target="_blank"
               style="display: inline-block; margin-top: 10px; padding: 8px 16px;
                      background: #667eea; color: white; text-decoration: none;
                      border-radius: 6px; font-size: 12px;">
                📚 API Documentation
            </a>
            """

        return f"""
        <div style='border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; background: white;'>
            <h3 style='margin: 0 0 15px 0; display: flex; align-items: center; gap: 10px;'>
                <span style='font-size: 24px;'>{icon}</span>
                {server_status.get('name', 'Unknown')}
                <span style='margin-left: auto;'>{status_badge}</span>
            </h3>

            <div style='color: #6b7280; font-size: 14px;'>
                <strong>Port:</strong> {server_status.get('port', 'N/A')}<br>
                <strong>Status:</strong> {server_status.get('health', 'unknown')}
            </div>

            {features_html}
            {oauth_html}
            {docs_link}
        </div>
        """

    @staticmethod
    async def generate_dashboard_summary() -> str:
        """Generate complete dashboard HTML summary"""
        status = await MCPServerMonitor.get_all_servers_status()

        cards_html = ""
        for server_type, server_status in status["servers"].items():
            cards_html += MCPServerMonitor.generate_dashboard_card_html(server_status)

        summary = status["summary"]

        return f"""
        <div style='padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 8px; margin-bottom: 20px;'>
            <h2 style='margin: 0 0 10px 0;'>MCP Servers Overview</h2>
            <div style='font-size: 18px;'>
                <strong>{summary['running']}</strong> of <strong>{summary['total']}</strong> servers running
            </div>
        </div>

        <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px;'>
            {cards_html}
        </div>
        """

# Export function to integrate with existing dashboard
async def get_enhanced_server_status():
    """Get enhanced server status for dashboard API"""
    monitor = MCPServerMonitor()
    return await monitor.get_all_servers_status()

def enhance_dashboard_routes(routes: List):
    """Add enhanced routes to existing dashboard"""
    from starlette.routing import Route
    from starlette.responses import JSONResponse, HTMLResponse

    async def api_enhanced_status(request):
        """Enhanced server status API endpoint"""
        status = await get_enhanced_server_status()
        return JSONResponse(status)

    async def dashboard_enhanced_view(request):
        """Enhanced dashboard view"""
        html_content = await MCPServerMonitor.generate_dashboard_summary()
        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>MCP Servers Dashboard</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; background: #f3f4f6;'>
            <div style='max-width: 1400px; margin: 0 auto;'>
                {html_content}
            </div>
        </body>
        </html>
        """
        return HTMLResponse(full_html)

    # Add new routes
    routes.extend([
        Route("/dashboard/api/enhanced/status", endpoint=api_enhanced_status, methods=["GET"]),
        Route("/dashboard/enhanced", endpoint=dashboard_enhanced_view, methods=["GET"])
    ])

    return routes