"""HTTP Streaming-based MCP Server for IACS Mail Management"""

import asyncio
import json
import secrets
from typing import Any, Dict

import uvicorn
from mcp.server import NotificationOptions, Server
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from infra.core.logger import get_logger
from modules.mail_iacs.handlers import IACSHandlers
from modules.mail_iacs.db_service import IACSDBService

logger = get_logger(__name__)


class HTTPStreamingIACSServer:
    """HTTP Streaming-based MCP Server for IACS Mail Management"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8003):
        self.host = host
        self.port = port

        # MCP Server
        self.mcp_server = Server("iacs-mail-server")

        # IACS Database Service
        self._initialize_database()

        # MCP Handlers
        self.handlers = IACSHandlers()

        # Active sessions
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # Create Starlette app
        self.app = self._create_app()

        logger.info(f"🚀 HTTP Streaming IACS Server initialized on port {port}")

    def _initialize_database(self):
        """Initialize IACS database schema and check configuration"""
        logger.info("🔍 Initializing IACS database...")

        try:
            db_service = IACSDBService()
            logger.info("✅ IACS database initialized successfully")

            # Log panel information if exists
            panels = db_service.get_all_panel_info()
            if panels:
                logger.info(f"📋 Found {len(panels)} panel(s) configured")
                for panel in panels:
                    logger.info(f"  - {panel.panel_name}: {panel.chair_address}")
            else:
                logger.warning("⚠️  No panels configured yet")

            # Log default panel if set
            default_panel = db_service.get_default_panel_name()
            if default_panel:
                logger.info(f"🎯 Default panel: {default_panel}")
            else:
                logger.warning("⚠️  No default panel set")

        except Exception as e:
            logger.error(f"❌ Failed to initialize database: {e}")
            # Don't exit - let the server start anyway

    async def _send_list_changed_notifications(self, request: Request):
        """Send list changed notifications after initialization"""
        # Wait a bit to ensure client is ready
        await asyncio.sleep(0.1)

        logger.info("📤 Would send notifications/tools/list_changed")
        logger.info("📤 Would send notifications/prompts/list_changed")

    async def _handle_streaming_request(self, request: Request):
        """Handle MCP request - returns single JSON response"""
        # Common headers
        base_headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS, DELETE",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id, MCP-Protocol-Version",
            "Access-Control-Expose-Headers": "Mcp-Session-Id",
        }

        # Bearer token authentication (DCR support)
        from modules.dcr_oauth import verify_bearer_token_middleware

        auth_response = await verify_bearer_token_middleware(request)
        if auth_response:
            # Authentication failed, return error response
            return auth_response

        # Read and parse request
        try:
            body = await request.body()
            if not body:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32700, "message": "Empty request body"},
                    },
                    status_code=400,
                    headers=base_headers,
                )

            try:
                rpc_request = json.loads(body)
            except json.JSONDecodeError as e:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
                    },
                    status_code=400,
                    headers=base_headers,
                )
        except Exception as e:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
                },
                status_code=500,
                headers=base_headers,
            )

        # Extract request details
        method = rpc_request.get("method")
        params = rpc_request.get("params", {}) or {}
        request_id = rpc_request.get("id")

        logger.info(f"📨 Received RPC request: {method} with id: {request_id}")

        # Handle notification (no id) - return 202 with no body
        if request_id is None:
            logger.info(f"📤 Handling notification: {method}")

            # If this is the initialized notification, send list changed notifications
            if method == "notifications/initialized":
                asyncio.create_task(self._send_list_changed_notifications(request))

            return Response(status_code=202, headers=base_headers)

        # Process based on method
        logger.info(f"📤 Processing method: {method} with params: {params}")

        if method == "initialize":
            # Initialize session with standard Mcp-Session-Id
            session_id = secrets.token_urlsafe(24)
            caps = self.mcp_server.get_capabilities(
                notification_options=NotificationOptions(), experimental_capabilities={}
            )

            # Fix null fields to empty objects/lists for spec compliance
            caps_dict = caps.model_dump()
            if caps_dict.get("logging") is None:
                caps_dict["logging"] = {}
            if caps_dict.get("resources") is None:
                caps_dict["resources"] = {"listChanged": False}
            # Fix tools and prompts to show they are available
            if caps_dict.get("tools") is None:
                caps_dict["tools"] = {"listChanged": True}
            if caps_dict.get("prompts") is None:
                caps_dict["prompts"] = {"listChanged": True}
            # Remove completions field if it's null (not supported by this server)
            if caps_dict.get("completions") is None:
                caps_dict.pop("completions", None)

            self.sessions[session_id] = {
                "initialized": True,
                "capabilities": caps_dict,
            }

            # Use the protocol version requested by the client
            requested_version = params.get("protocolVersion", "2025-06-18")

            # Add session header and ensure it's exposed
            headers = base_headers.copy()
            headers["Mcp-Session-Id"] = session_id
            headers["MCP-Protocol-Version"] = requested_version
            headers["Access-Control-Expose-Headers"] = "Mcp-Session-Id, MCP-Protocol-Version"

            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": requested_version,
                    "capabilities": caps_dict,
                    "serverInfo": {
                        "name": "iacs-mail-server",
                        "title": "📧 IACS Mail Server",
                        "version": "1.0.0",
                        "description": "MCP server for IACS mail management",
                    },
                    "instructions": "의장-멤버 간 아젠다 및 응답 메일을 관리하는 MCP 서버입니다.",
                },
            }
            logger.info(f"📤 Sending initialize response: {json.dumps(response, indent=2)}")
            return JSONResponse(response, headers=headers)

        elif method == "tools/list":
            # List tools
            tools = await self.handlers.handle_list_tools()

            # Clean up tool data - remove null fields
            tools_data = []
            for tool in tools:
                tool_dict = tool.model_dump()
                # Remove null fields as per spec
                cleaned_tool = {}
                for key, value in tool_dict.items():
                    if value is not None:
                        cleaned_tool[key] = value
                tools_data.append(cleaned_tool)

            logger.info(f"📤 Returning {len(tools_data)} tools: {[t['name'] for t in tools_data]}")

            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": tools_data},
            }
            return JSONResponse(response, headers=base_headers)

        elif method == "tools/call":
            # Call tool
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            logger.info(f"🔧 [MCP Server] Received tools/call request")
            logger.info(f"  • Tool: {tool_name}")
            logger.info(f"  • Arguments: {json.dumps(tool_args, indent=2, ensure_ascii=False)}")

            # Extract authenticated user_id from request.state (set by auth middleware)
            authenticated_user_id = getattr(request.state, "user_id", None)
            if authenticated_user_id:
                logger.info(f"  • Authenticated user_id: {authenticated_user_id}")

            try:
                results = await self.handlers.handle_call_tool(tool_name, tool_args, authenticated_user_id)

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [content.model_dump() for content in results]},
                }
            except Exception as e:
                logger.error(f"❌ Tool call failed: {str(e)}")
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32603, "message": str(e)},
                }

            return JSONResponse(response, headers=base_headers)

        elif method == "prompts/list":
            # List prompts
            prompts = await self.handlers.handle_list_prompts()

            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"prompts": [prompt.model_dump() for prompt in prompts]},
            }
            return JSONResponse(response, headers=base_headers)

        elif method == "resources/list":
            # Resources not supported, return empty list
            response = {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
            return JSONResponse(response, headers=base_headers)

        elif method == "prompts/get":
            # Get prompt
            prompt_name = params.get("name")
            prompt_args = params.get("arguments", {})

            try:
                prompt_msg = await self.handlers.handle_get_prompt(prompt_name, prompt_args)

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"messages": [prompt_msg.model_dump()]},
                }
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32603, "message": str(e)},
                }

            return JSONResponse(response, headers=base_headers)

        else:
            # Unknown method
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
            return JSONResponse(response, status_code=404, headers=base_headers)

    async def _handle_ping(self, request: Request):
        """MCP ping endpoint for keep-alive as per MCP specification"""
        # Get request ID from headers or body
        request_id = None
        if request.headers.get("content-type") == "application/json":
            try:
                body = await request.json()
                request_id = body.get("id", "ping")
            except:
                request_id = "ping"
        else:
            request_id = request.headers.get("x-request-id", "ping")

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {}
        })

    def _create_app(self):
        """Create Starlette application"""

        async def health_check(request):
            """Health check endpoint"""
            return JSONResponse(
                {
                    "status": "healthy",
                    "server": "iacs-mail-server",
                    "version": "1.0.0",
                    "transport": "http-streaming",
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id, MCP-Protocol-Version",
                    "Access-Control-Expose-Headers": "Mcp-Session-Id",
                },
            )

        async def server_info(request):
            """Server information endpoint"""
            return JSONResponse(
                {
                    "name": "iacs-mail-server",
                    "version": "1.0.0",
                    "protocol": "mcp",
                    "transport": "http-streaming",
                    "endpoints": {
                        "streaming": "/stream",
                        "health": "/health",
                        "info": "/info",
                    },
                }
            )

        # OPTIONS handler for CORS preflight
        async def options_handler(request):
            return Response(
                "",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS, DELETE",
                    "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id, Authorization, MCP-Protocol-Version",
                    "Access-Control-Expose-Headers": "Mcp-Session-Id",
                    "Access-Control-Max-Age": "3600",
                },
            )

        # Root endpoint handler
        async def root_handler(request):
            """Handle root endpoint requests"""
            if request.method == "POST":
                # For POST requests, handle as MCP request
                return await self._handle_streaming_request(request)
            else:
                # For GET/HEAD requests, return server info
                return JSONResponse(
                    {
                        "name": "iacs-mail-server",
                        "version": "1.0.0",
                        "protocol": "mcp",
                        "transport": "http",
                        "endpoints": {"mcp": "/", "health": "/health", "info": "/info"},
                    },
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS, HEAD, DELETE",
                        "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id, Authorization, MCP-Protocol-Version",
                        "Access-Control-Expose-Headers": "Mcp-Session-Id",
                    },
                )

        # Register endpoint - for client registration
        async def register_handler(request):
            """Handle client registration"""
            return JSONResponse(
                {
                    "success": True,
                    "message": "No registration required - this is an open server",
                    "endpoint": "/stream",
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                },
            )

        # Create routes
        routes = [
            # Root endpoint
            Route("/", endpoint=root_handler, methods=["GET", "POST", "HEAD"]),
            Route("/", endpoint=options_handler, methods=["OPTIONS"]),
            # MCP endpoint (alias for root)
            Route("/mcp", endpoint=self._handle_streaming_request, methods=["POST"]),
            Route("/mcp", endpoint=options_handler, methods=["OPTIONS"]),
            # Register endpoint
            Route("/register", endpoint=register_handler, methods=["POST"]),
            Route("/register", endpoint=options_handler, methods=["OPTIONS"]),
            # Health and info endpoints
            Route("/health", endpoint=health_check, methods=["GET"]),
            Route("/info", endpoint=server_info, methods=["GET"]),
            # MCP Ping endpoint
            Route("/ping", endpoint=self._handle_ping, methods=["POST"]),
            # Streaming endpoints
            Route("/stream", endpoint=self._handle_streaming_request, methods=["POST"]),
            Route("/stream", endpoint=options_handler, methods=["OPTIONS"]),
            Route("/health", endpoint=options_handler, methods=["OPTIONS"]),
            Route("/info", endpoint=options_handler, methods=["OPTIONS"]),
            Route("/ping", endpoint=options_handler, methods=["OPTIONS"]),
        ]

        return Starlette(routes=routes)

    def run(self):
        """Run the HTTP streaming MCP server"""
        logger.info(f"🚀 Starting HTTP Streaming IACS Server on http://{self.host}:{self.port}")
        logger.info(f"📧 Streaming endpoint: http://{self.host}:{self.port}/stream")
        logger.info(f"💚 Health check: http://{self.host}:{self.port}/health")
        logger.info(f"ℹ️  Server info: http://{self.host}:{self.port}/info")

        # Run uvicorn
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")
