"""FastAPI-based MCP Server for Teams Chat

This server uses FastAPI directly for MCP protocol implementation with DCR OAuth support.
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
from .database_manager import get_teams_database
from ..handlers import TeamsHandlers
from ..middleware.auth_dependencies import optional_auth, required_auth

logger = get_logger(__name__)
auth_logger = get_auth_logger()


class FastAPITeamsServer:
    """FastAPI-based MCP Server for Teams Chat"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8003):
        self.host = host
        self.port = port
        # Server name for DCR (config.json에서 로드)
        self.server_name = self._load_server_name_from_config()

        # MCP Server
        self.mcp_server = Server("teams-mcp-server")

        # Database (Teams 전용)
        self.db = get_teams_database()

        # Initialize database connection and check authentication
        self._initialize_and_check_auth()

        # MCP Handlers
        self.handlers = TeamsHandlers()

        # Active sessions
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # Create FastAPI app
        self.app = self._create_app()

        logger.info(f"🚀 FastAPI Teams Server initialized on port {port}")

    def _load_server_name_from_config(self) -> str:
        """config.json에서 DCR OAuth module_name을 읽어옴"""
        from pathlib import Path
        config_path = Path(__file__).parent.parent / "config.json"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config_data = json.load(f)
                    module_name = config_data.get("dcr_oauth", {}).get("module_name", "teams")
                    logger.info(f"📋 Loaded DCR module_name from config: {module_name}")
                    return module_name
            except Exception as e:
                logger.warning(f"config.json 읽기 실패: {e}")
        return "teams"

    def _initialize_and_check_auth(self):
        """Initialize database connection and check authentication status"""
        logger.info("🔍 Initializing database and checking authentication...")

        try:
            # Initialize DCR client if not exists
            self._ensure_dcr_client_registered()

            # Force database connection initialization
            query = "SELECT COUNT(*) FROM accounts WHERE is_active = 1"
            result = self.db.fetch_one(query)
            active_accounts = result[0] if result else 0

            logger.info(f"✅ Database connection successful")
            logger.info(f"📊 Active accounts found: {active_accounts}")

            # Check authentication status for all active accounts
            if active_accounts > 0:
                auth_query = """
                SELECT user_id,
                       CASE
                           WHEN access_token IS NOT NULL AND token_expiry > datetime('now') THEN 'VALID'
                           WHEN refresh_token IS NOT NULL THEN 'REFRESH_NEEDED'
                           ELSE 'EXPIRED'
                       END as auth_status
                FROM accounts
                WHERE is_active = 1
                ORDER BY user_id
                """
                auth_results = self.db.fetch_all(auth_query)

                logger.info("🔐 Authentication status:")

                # Count by status
                valid_count = sum(1 for row in auth_results if row[1] == "VALID")
                refresh_count = sum(1 for row in auth_results if row[1] == "REFRESH_NEEDED")
                expired_count = sum(1 for row in auth_results if row[1] == "EXPIRED")

                for row in auth_results:
                    user_id, status = row
                    status_emoji = "✅" if status == "VALID" else "⚠️" if status == "REFRESH_NEEDED" else "❌"
                    logger.info(f"   {status_emoji} {user_id}: {status}")
                    auth_logger.log_authentication(user_id, status, "server startup check")

                # Log batch check summary
                auth_logger.log_batch_auth_check(
                    active_accounts, valid_count, refresh_count, expired_count
                )
            else:
                logger.warning("⚠️ No active accounts found in database")

        except Exception as e:
            logger.error(f"❌ Failed to initialize database or check auth: {str(e)}")
            raise

    def _ensure_dcr_client_registered(self):
        """서버 시작 시 DCR Azure 앱 정보가 등록되어 있는지 확인하고, 환경변수에서 로드"""
        import os
        from modules.dcr_oauth_module.dcr_service import DCRService

        try:
            dcr_service = DCRService(module_name=self.server_name)

            # 환경변수에서 Azure 설정 읽기
            env_app_id = os.getenv("DCR_AZURE_CLIENT_ID")
            env_secret = os.getenv("DCR_AZURE_CLIENT_SECRET")
            env_tenant = os.getenv("DCR_AZURE_TENANT_ID", "common")
            env_redirect = os.getenv("DCR_OAUTH_REDIRECT_URI")

            if not env_app_id or not env_secret:
                logger.warning("⚠️ DCR_AZURE_CLIENT_ID or DCR_AZURE_CLIENT_SECRET not set in environment")
                logger.warning("⚠️ OAuth authentication will not be available")
                return

            # DB에 Azure 앱 정보가 있는지 확인
            existing_app = dcr_service._fetch_one(
                "SELECT application_id FROM dcr_azure_app LIMIT 1"
            )

            if not existing_app:
                logger.info(f"🔧 No Azure app found in DB. Creating from environment variables...")

                # Azure 앱 정보를 DB에 저장
                encrypted_secret = dcr_service.crypto.account_encrypt_sensitive_data(env_secret)

                dcr_service._execute(
                    """
                    INSERT INTO dcr_azure_app
                    (application_id, client_secret, tenant_id, redirect_uri, created_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (env_app_id, encrypted_secret, env_tenant, env_redirect)
                )

                logger.info(f"✅ Created Azure app in DB: {env_app_id}")
                logger.info(f"   Tenant: {env_tenant}")
                logger.info(f"   Redirect URI: {env_redirect}")
            else:
                logger.info(f"✅ Azure app already registered in DB: {existing_app[0]}")

                # 환경변수가 다르면 업데이트
                if env_app_id != existing_app[0]:
                    logger.info(f"🔄 Updating Azure app from environment variables...")
                    encrypted_secret = dcr_service.crypto.account_encrypt_sensitive_data(env_secret)

                    dcr_service._execute(
                        """
                        UPDATE dcr_azure_app
                        SET application_id = ?, client_secret = ?, tenant_id = ?,
                            redirect_uri = ?, updated_at = CURRENT_TIMESTAMP
                        """,
                        (env_app_id, encrypted_secret, env_tenant, env_redirect)
                    )

                    logger.info(f"✅ Updated Azure app in DB: {env_app_id}")

        except Exception as e:
            logger.warning(f"⚠️ Failed to ensure DCR Azure app registration: {e}")
            # 서버 시작을 막지 않음

    async def _send_list_changed_notifications(self):
        """Send list changed notifications after initialization"""
        # Wait a bit to ensure client is ready
        await asyncio.sleep(0.1)

        # Note: In a real implementation, we would need to track the client's SSE connection
        # For now, we'll just log that we would send these
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
                # Send tools list changed notification after a short delay
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
                caps_dict["prompts"] = {"listChanged": False}
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
                        "name": "teams-mcp-server",
                        "title": "💬 Teams Chat MCP Server",
                        "version": "1.0.0",
                        "description": "MCP server for Microsoft Teams chat management",
                    },
                    "instructions": "Microsoft Teams 1:1 채팅 및 그룹 채팅을 관리하는 MCP 서버입니다.",
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

            # Debug: Log the actual tool data being sent
            logger.info(f"📤 Tool data details: {json.dumps(tools_data, indent=2)}")

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
                # 1순위: 미들웨어에서 설정된 request.state.user_id 사용 (DCR 인증 기반)
                if hasattr(request.state, 'user_id') and request.state.user_id:
                    tool_args["user_id"] = request.state.user_id
                    logger.info(f"✅ Auto-injected user_id from authenticated session: {tool_args['user_id']}")
                else:
                    # 2순위: accounts 테이블에서 기본 계정 조회 (인증 없이 접근하는 경우)
                    logger.info("🔍 No authenticated user, attempting fallback to default account...")
                    try:
                        default_user = self.db.fetch_one(
                            "SELECT user_id FROM accounts WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
                        )
                        if default_user:
                            auto_user_id = default_user[0]
                            tool_args["user_id"] = auto_user_id
                            logger.info(f"✅ Auto-set user_id from default account: {auto_user_id}")
                        else:
                            logger.warning("⚠️  No default account available")
                    except Exception as e:
                        logger.warning(f"⚠️  Failed to get default user_id: {str(e)}")
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
            # No prompts supported
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"prompts": []},
            }
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
        from modules.teams_mcp.middleware.request_logger import RequestLoggerMiddleware
        import os

        # Create FastAPI app
        app = FastAPI(
            title="💬 Teams Chat MCP Server",
            description="""
## Teams Chat MCP Server

MCP (Model Context Protocol) server for Microsoft Teams chat management.

### Features
- 💬 Chat listing (1:1 and group chats)
- 📬 Message reading
- 📤 Message sending
- 🔐 DCR OAuth authentication

### MCP Protocol
This server implements the MCP protocol (JSON-RPC 2.0).
All MCP requests should be sent to the root endpoint `/` as POST requests.

### Tools Available
1. **teams_list_chats** - List user's chats (1:1 and group)
2. **teams_get_chat_messages** - Get messages from a chat
3. **teams_send_chat_message** - Send message to a chat
4. **teams_search_messages** - Search messages by keyword
5. **teams_save_korean_name** - Save Korean names for chats
            """,
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
        )

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # 모든 origin 허용 (프로덕션에서는 제한 필요)
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

            class Config:
                json_schema_extra = {
                    "examples": [
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/list",
                            "params": {}
                        },
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/call",
                            "params": {
                                "name": "teams_list_chats",
                                "arguments": {
                                    "user_id": "user@example.com"
                                }
                            }
                        }
                    ]
                }

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
                "name": "teams-mcp-server",
                "version": "1.0.0",
                "protocol": "mcp",
                "transport": "http",
                "endpoints": {"mcp": "/", "health": "/health", "info": "/info"},
            }

        @app.post(
            "/",
            response_model=MCPResponse,
            summary="MCP Protocol Endpoint",
            description="""
Send MCP (Model Context Protocol) requests using JSON-RPC 2.0 format.

**Authentication Required:** Bearer token in Authorization header

**Common Methods:**
- `initialize` - Initialize MCP session
- `tools/list` - List available tools
- `tools/call` - Call a specific tool
- `prompts/list` - List available prompts

**Example Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {}
}
```
            """,
            tags=["MCP Protocol"],
        )
        async def mcp_endpoint(request: Request, user_data: dict = Depends(required_auth)):
            """MCP Protocol endpoint - requires authentication"""
            user_id = user_data.get('user_id')
            logger.info(f"🔐 Authenticated MCP request from user: {user_id}")
            # request.state는 이미 required_auth에서 설정됨
            return await self._handle_mcp_request(request)

        # Alias endpoints for MCP (with required auth)
        @app.post("/mcp", include_in_schema=False)
        async def mcp_alias(request: Request, user_data: dict = Depends(required_auth)):
            """MCP endpoint alias - requires authentication"""
            user_id = user_data.get('user_id')
            logger.info(f"🔐 Authenticated MCP request from user: {user_id}")
            return await self._handle_mcp_request(request)

        @app.post("/stream", include_in_schema=False)
        async def stream_alias(request: Request, user_data: dict = Depends(required_auth)):
            """Stream endpoint alias - requires authentication"""
            user_id = user_data.get('user_id')
            logger.info(f"🔐 Authenticated MCP request from user: {user_id}")
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
                "server": "teams-mcp-server",
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
                "name": "teams-mcp-server",
                "version": "1.0.0",
                "protocol": "mcp",
                "transport": "http",
                "tools_count": 5,
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
                "name": "Teams Chat MCP Server",
                "description": "Microsoft Teams chat management service",
                "version": "1.0.0",
                "capabilities": {
                    "tools": True,
                    "resources": False,
                    "prompts": False
                }
            }

        # === DCR OAuth Endpoints (Standard RFC 7591) ===
        # These are the standard endpoints for MCP Connector OAuth2 flow
        from .dcr_endpoints import add_dcr_endpoints
        add_dcr_endpoints(app)
        logger.info("🔐 DCR OAuth endpoints added (/oauth/*)")

        # Initialize OpenAI wrapper
        from modules.openai_wrapper import MCPOpenAIWrapper
        self.openai_wrapper = MCPOpenAIWrapper(
            mcp_server=self,
            server_name="teams",
            model_id="mcp-teams"
        )

        # OpenAI-compatible endpoints
        @app.post(
            "/v1/chat/completions",
            tags=["OpenAI Compatible"],
            summary="Chat Completions",
            description="OpenAI-compatible chat completions endpoint exposing MCP tools (requires authentication)"
        )
        async def chat_completions(request: Request, user_data: dict = Depends(required_auth)):
            """Handle OpenAI chat completions request with required DCR authentication"""
            logger.info(f"🔐 OpenAI API request from authenticated user: {user_data.get('user_id')}")
            from modules.openai_wrapper.schemas import ChatCompletionRequest
            body = await request.json()
            chat_request = ChatCompletionRequest(**body)
            response = await self.openai_wrapper.handle_chat_completions(chat_request)
            return response.model_dump(exclude_none=True)

        @app.get(
            "/v1/models",
            tags=["OpenAI Compatible"],
            summary="List Models",
            description="List available models (MCP server as a model)"
        )
        async def list_models():
            """Handle OpenAI list models request"""
            response = await self.openai_wrapper.handle_list_models()
            return response.model_dump()

        logger.info("📚 FastAPI app created - OpenAPI available at /docs")
        return app

    def run(self):
        """Run the FastAPI MCP server"""
        logger.info(f"🚀 Starting FastAPI Teams Server on http://{self.host}:{self.port}")
        logger.info(f"💬 MCP endpoint: http://{self.host}:{self.port}/")
        logger.info(f"📚 OpenAPI docs: http://{self.host}:{self.port}/docs")
        logger.info(f"💚 Health check: http://{self.host}:{self.port}/health")
        logger.info(f"ℹ️  Server info: http://{self.host}:{self.port}/info")

        # Run uvicorn with FastAPI app
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")
