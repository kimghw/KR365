"""FastAPI-based MCP Server for OneNote

This server uses FastAPI directly for MCP protocol implementation.
"""

import asyncio
import json
import logging
import secrets
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, Request, Response, Form, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from mcp.server import NotificationOptions, Server
from pydantic import BaseModel, Field

from infra.core.auth_logger import get_auth_logger
from infra.core.logger import get_logger, log_api_request, log_api_response
from ..db_service import OneNoteDBService
from ..handlers import OneNoteHandlers
from ..middleware.auth_dependencies import optional_auth, required_auth

logger = get_logger(__name__)
auth_logger = get_auth_logger()


class FastAPIOneNoteServer:
    """FastAPI-based MCP Server for OneNote"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8003):
        self.host = host
        self.port = port
        # Server name for DCR (config.json에서 로드)
        self.server_name = self._load_server_name_from_config()

        # MCP Server
        self.mcp_server = Server("onenote-mcp-server")

        # Database (OneNote 전용)
        self.db = OneNoteDBService()
        self.db.initialize_tables()

        # MCP Handlers
        self.handlers = OneNoteHandlers()

        # Active sessions
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # Create FastAPI app
        self.app = self._create_app()

        logger.info(f"🚀 FastAPI OneNote Server initialized on port {port}")

    def _load_server_name_from_config(self) -> str:
        """config.json에서 DCR OAuth module_name을 읽어옴"""
        from pathlib import Path
        config_path = Path(__file__).parent.parent / "config.json"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config_data = json.load(f)
                    module_name = config_data.get("dcr_oauth", {}).get("module_name", "onenote")
                    logger.info(f"📋 Loaded DCR module_name from config: {module_name}")
                    return module_name
            except Exception as e:
                logger.warning(f"config.json 읽기 실패: {e}")
        return "onenote"

    async def _send_list_changed_notifications(self):
        """Send list changed notifications after initialization"""
        await asyncio.sleep(0.1)
        logger.info("📤 Would send notifications/tools/list_changed")
        logger.info("📤 Would send notifications/prompts/list_changed")
        logger.info("📤 Would send notifications/resources/list_changed")

    async def _handle_mcp_request(self, request: Request):
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
                asyncio.create_task(self._send_list_changed_notifications())

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
                    # Use fixed capabilities (with logging as empty object)
                    "capabilities": caps_dict,
                    "serverInfo": {
                        "name": "onenote-mcp-server",
                        "title": "📓 OneNote MCP Server",
                        "version": "1.0.0",
                        "description": "MCP server for OneNote management",
                    },
                    "instructions": "OneNote 노트북, 섹션, 페이지를 관리하는 MCP 서버입니다.",
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
            logger.info(f"  • Arguments (before auto-extraction): {json.dumps(tool_args, indent=2, ensure_ascii=False)}")

            # 📧 user_id 자동 주입 (request.state에서 가져오기 - 미들웨어가 이미 설정함)
            if not tool_args.get("user_id"):
                # 미들웨어에서 설정된 request.state.user_id 사용 (DCR 인증 기반)
                if hasattr(request.state, 'user_id') and request.state.user_id:
                    tool_args["user_id"] = request.state.user_id
                    logger.info(f"✅ Auto-injected user_id from authenticated session: {tool_args['user_id']}")
            else:
                logger.info(f"ℹ️  user_id explicitly provided: {tool_args['user_id']}")

            logger.info(f"  • Arguments (after auto-extraction): {json.dumps(tool_args, indent=2, ensure_ascii=False)}")

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
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32603, "message": str(e)},
                }

            return JSONResponse(response, headers=base_headers)

        elif method == "prompts/list":
            # List prompts (OneNote doesn't use prompts, return empty list)
            response = {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}
            return JSONResponse(response, headers=base_headers)

        elif method == "resources/list":
            # Resources not supported, return empty list
            response = {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
            return JSONResponse(response, headers=base_headers)

        else:
            # Unknown method
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
            return JSONResponse(response, status_code=404, headers=base_headers)

    def _create_app(self):
        """Create FastAPI application"""
        from fastapi.middleware.cors import CORSMiddleware
        from modules.onenote_mcp.middleware.request_logger import RequestLoggerMiddleware
        import os

        # Create FastAPI app
        app = FastAPI(
            title="📓 OneNote MCP Server",
            description="""
## OneNote MCP Server

MCP (Model Context Protocol) server for OneNote management.

### Features
- 📓 Notebook listing
- 📑 Section management (create, list)
- 📄 Page management (create, get, update, delete)
- 🔍 Content search in OneNote

### MCP Protocol
This server implements the MCP protocol (JSON-RPC 2.0).
All MCP requests should be sent to the root endpoint `/` as POST requests.

### Tools Available
1. **manage_sections_and_pages** - Manage OneNote sections and pages
2. **manage_page_content** - Manage OneNote page content
            """,
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
        )

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[
                "Mcp-Session-Id",
                "MCP-Protocol-Version",
                "X-Auth-Hint",
                "WWW-Authenticate",
                "X-Trace-Id"
            ]
        )

        # Add request logging middleware (config.json에서 자동 로드)
        app.add_middleware(RequestLoggerMiddleware)
        logger.info(f"📝 Request logging middleware added (uses config.json DCR settings)")

        # Pydantic models for documentation
        class MCPRequest(BaseModel):
            jsonrpc: str = Field("2.0", description="JSON-RPC version")
            method: str = Field(..., description="MCP method name (e.g., 'tools/list', 'tools/call')")
            params: Optional[Dict[str, Any]] = Field(default={}, description="Method parameters")
            id: Optional[int] = Field(None, description="Request ID for correlation")

        class MCPResponse(BaseModel):
            jsonrpc: str = Field("2.0", description="JSON-RPC version")
            result: Optional[Dict[str, Any]] = Field(None, description="Result data")
            error: Optional[Dict[str, Any]] = Field(None, description="Error information")
            id: Optional[int] = Field(None, description="Request ID for correlation")

        # CORS middleware
        @app.options("/{full_path:path}")
        async def options_handler():
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

        # Root endpoint - GET returns server info, POST handles MCP
        @app.get("/", tags=["Info"])
        async def root_get():
            """Server information for GET requests"""
            return {
                "name": "onenote-mcp-server",
                "version": "1.0.0",
                "protocol": "mcp",
                "transport": "http",
                "endpoints": {"mcp": "/", "health": "/health", "info": "/info"},
            }

        @app.post(
            "/",
            response_model=MCPResponse,
            summary="MCP Protocol Endpoint",
            description="Send MCP (Model Context Protocol) requests using JSON-RPC 2.0 format.",
            tags=["MCP Protocol"],
        )
        async def mcp_endpoint(request: Request, user_data: dict = Depends(required_auth)):
            """MCP Protocol endpoint with required DCR authentication"""
            logger.info(f"🔐 Authenticated request from user: {user_data.get('user_id')}")
            request.state.user_id = user_data.get('user_id')
            return await self._handle_mcp_request(request)

        # Alias endpoints for MCP (with required auth)
        @app.post("/mcp", include_in_schema=False)
        async def mcp_alias(request: Request, user_data: dict = Depends(required_auth)):
            """MCP endpoint alias with required DCR authentication"""
            logger.info(f"🔐 Authenticated request from user: {user_data.get('user_id')}")
            request.state.user_id = user_data.get('user_id')
            return await self._handle_mcp_request(request)

        @app.get(
            "/health",
            tags=["Health"],
            summary="Health Check",
            description="Check if the server is running and healthy"
        )
        async def health_check():
            return {
                "status": "healthy",
                "server": "onenote-mcp-server",
                "version": "1.0.0",
                "transport": "http",
            }

        @app.get(
            "/info",
            tags=["Info"],
            summary="Server Information",
            description="Get server information and capabilities"
        )
        async def server_info():
            return {
                "name": "onenote-mcp-server",
                "version": "1.0.0",
                "protocol": "mcp",
                "transport": "http",
                "tools_count": 2,
                "documentation": f"http://{self.host}:{self.port}/docs"
            }

        @app.post(
            "/ping",
            tags=["MCP"],
            summary="MCP Ping - Keep-alive endpoint",
            description="MCP standard ping endpoint for connection health verification"
        )
        async def ping(request: Request):
            """MCP ping endpoint for keep-alive as per MCP specification"""
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

        @app.get(
            "/.well-known/mcp.json",
            tags=["MCP Discovery"],
            summary="MCP Server Discovery",
            description="MCP discovery endpoint"
        )
        async def mcp_discovery():
            """MCP Server Discovery"""
            return {
                "mcp_version": "1.0",
                "name": "OneNote MCP Server",
                "description": "OneNote management service",
                "version": "1.0.0",
                "capabilities": {
                    "tools": True,
                    "resources": False,
                    "prompts": False
                }
            }

        # === DCR OAuth Endpoints (Standard RFC 7591) ===
        from .dcr_endpoints import add_dcr_endpoints
        add_dcr_endpoints(app)
        logger.info("🔐 DCR OAuth endpoints added (/oauth/*)")

        logger.info("📚 FastAPI app created - OpenAPI available at /docs")
        return app

    def run(self):
        """Run the FastAPI MCP server"""
        logger.info(f"🚀 Starting FastAPI OneNote Server on http://{self.host}:{self.port}")
        logger.info(f"📓 MCP endpoint: http://{self.host}:{self.port}/")
        logger.info(f"📚 OpenAPI docs: http://{self.host}:{self.port}/docs")
        logger.info(f"💚 Health check: http://{self.host}:{self.port}/health")
        logger.info(f"ℹ️  Server info: http://{self.host}:{self.port}/info")

        # Run uvicorn with FastAPI app
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")
