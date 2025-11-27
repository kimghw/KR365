"""FastAPI-based MCP Server for Mail Attachments

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
from .database_manager import get_mail_query_database
from ..mcp_server.handlers import MCPHandlers
from ..middleware.auth_dependencies import optional_auth, required_auth

logger = get_logger(__name__)
auth_logger = get_auth_logger()


class FastAPIMailAttachmentServer:
    """FastAPI-based MCP Server for Mail Attachments"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8001):
        self.host = host
        self.port = port
        # Server name for DCR (config.json에서 로드)
        self.server_name = self._load_server_name_from_config()

        # MCP Server
        self.mcp_server = Server("email-mcp-server")

        # Database (Mail Query 전용)
        self.db = get_mail_query_database()

        # Initialize database connection and check authentication
        self._initialize_and_check_auth()

        # MCP Handlers
        self.handlers = MCPHandlers()

        # Active sessions
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # Create FastAPI app
        self.app = self._create_app()

        logger.info(f"🚀 FastAPI Mail Attachment Server initialized on port {port}")

    def _load_server_name_from_config(self) -> str:
        """config.json에서 DCR OAuth module_name을 읽어옴"""
        from pathlib import Path
        config_path = Path(__file__).parent.parent / "config.json"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config_data = json.load(f)
                    module_name = config_data.get("dcr_oauth", {}).get("module_name", "mail_query")
                    logger.info(f"📋 Loaded DCR module_name from config: {module_name}")
                    return module_name
            except Exception as e:
                logger.warning(f"config.json 읽기 실패: {e}")
        return "mail_query"

    def _initialize_and_check_auth(self):
        """Initialize database connection and check authentication status"""
        logger.info("🔍 Initializing database and checking authentication...")

        try:
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
                caps_dict["prompts"] = {"listChanged": True}
            # Remove completions field if it's null (not supported by this server)
            if caps_dict.get("completions") is None:
                caps_dict.pop("completions", None)

            self.sessions[session_id] = {
                "initialized": True,
                "capabilities": caps_dict,
                "query_count": 0,  # 쿼리 횟수 추적
                "last_query_params": {}  # 마지막 쿼리 파라미터 저장
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
                        "name": "email-mcp-server",
                        "title": "📧 Email MCP Server",
                        "version": "2.0.0",
                        "description": "MCP server for email attachment handling",
                    },
                    "instructions": "이메일과 첨부파일을 조회하고 텍스트로 변환하는 MCP 서버입니다.",
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
            if not tool_args.get("user_id") and not tool_args.get("use_recent_account"):
                # 1순위: 미들웨어에서 설정된 request.state.user_id 사용 (DCR 인증 기반)
                if hasattr(request.state, 'user_id') and request.state.user_id:
                    tool_args["user_id"] = request.state.user_id
                    logger.info(f"✅ Auto-injected user_id from authenticated session: {tool_args['user_id']}")
                else:
                    # 2순위: accounts 테이블에서 기본 계정 조회 (인증 없이 접근하는 경우)
                    logger.info("🔍 No authenticated user, attempting fallback to default account...")
                    try:
                        from ..mcp_server.handlers import get_default_user_id
                        auto_user_id = get_default_user_id()

                        if auto_user_id:
                            tool_args["user_id"] = auto_user_id
                            logger.info(f"✅ Auto-set user_id from default account: {auto_user_id}")
                        else:
                            logger.warning("⚠️  No default account available")
                    except Exception as e:
                        logger.warning(f"⚠️  Failed to get default user_id: {str(e)}")
            else:
                if tool_args.get("user_id"):
                    logger.info(f"ℹ️  user_id explicitly provided: {tool_args['user_id']}")
                if tool_args.get("use_recent_account"):
                    logger.info(f"ℹ️  use_recent_account=true, will use recent account logic")

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

    def _create_app(self):
        """Create FastAPI application"""
        from fastapi.middleware.cors import CORSMiddleware
        from modules.outlook_mcp.middleware.request_logger import RequestLoggerMiddleware
        import os

        # Create FastAPI app
        app = FastAPI(
            title="📧 Mail Query MCP Server",
            description="""
## Mail Query MCP Server

MCP (Model Context Protocol) server for email and attachment management.

### Features
- 📧 Email query and filtering
- 📎 Attachment download and conversion
- 🔍 Full-text search in emails
- 📄 Document format conversion (PDF, DOCX, etc.)

### MCP Protocol
This server implements the MCP protocol (JSON-RPC 2.0).
All MCP requests should be sent to the root endpoint `/` as POST requests.

### Tools Available
1. **query_email** - Query emails with filters
2. **attachmentManager** - Download and manage attachments
3. **help** - Get detailed help for all tools
4. **query_email_help** - Get help for email query syntax
            """,
            version="2.0.0",
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
                                "name": "query_email",
                                "arguments": {
                                    "user_id": "kimghw",
                                    "days_back": 7,
                                    "max_results": 10
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
                "name": "email-mcp-server",
                "version": "2.0.0",
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

**Common Methods:**
- `initialize` - Initialize MCP session
- `tools/list` - List available tools
- `tools/call` - Call a specific tool
- `prompts/list` - List available prompts
- `prompts/get` - Get a specific prompt

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
        async def mcp_endpoint(request: Request):
            """MCP Protocol endpoint (auth handled by middleware)"""
            # 인증은 auth_dependencies 미들웨어에서 처리
            # POST /는 인증 제외됨 (로컬/내부망 사용)
            user_id = getattr(request.state, 'user_id', None)
            if user_id:
                logger.info(f"🔐 Authenticated request from user: {user_id}")
            # request.state에 사용자 정보 저장 (핸들러에서 사용)
            request.state.user_id = user_id
            return await self._handle_mcp_request(request)

        # Alias endpoints for MCP (with required auth)
        @app.post("/mcp", include_in_schema=False)
        async def mcp_alias(request: Request):
            """MCP endpoint alias (auth handled by middleware)"""
            user_id = getattr(request.state, 'user_id', None)
            if user_id:
                logger.info(f"🔐 Authenticated request from user: {user_id}")
            request.state.user_id = user_id
            return await self._handle_mcp_request(request)

        @app.post("/stream", include_in_schema=False)
        async def stream_alias(request: Request):
            """Stream endpoint alias (auth handled by middleware)"""
            user_id = getattr(request.state, 'user_id', None)
            if user_id:
                logger.info(f"🔐 Authenticated request from user: {user_id}")
            request.state.user_id = user_id
            return await self._handle_mcp_request(request)

        @app.post("/steam", include_in_schema=False)
        async def steam_alias(request: Request):
            """Steam endpoint alias (auth handled by middleware)"""
            user_id = getattr(request.state, 'user_id', None)
            if user_id:
                logger.info(f"🔐 Authenticated request from user: {user_id}")
            request.state.user_id = user_id
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
                "server": "email-mcp-server",
                "version": "2.0.0",
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
                "name": "email-mcp-server",
                "version": "2.0.0",
                "protocol": "mcp",
                "transport": "http",
                "tools_count": 4,
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
                "name": "Mail Query MCP Server",
                "description": "Email attachment management and query service",
                "version": "1.0.0",
                "capabilities": {
                    "tools": True,
                    "resources": False,
                    "prompts": False
                }
            }

        # === LEGACY OAuth Endpoints (for direct browser login) ===
        # These endpoints are for manual browser-based login flow.
        # MCP Connector should use DCR standard endpoints (/oauth/*) instead.

        # OAuth login endpoint to start authentication flow
        @app.get("/auth/login", tags=["Legacy OAuth"])
        async def auth_login_handler(user_id: str = None):
            """[LEGACY] Start OAuth authentication flow - Use /oauth/authorize for DCR flow"""
            from modules.outlook_mcp.implementations.auth_session_store import AuthSessionStore
            from fastapi.responses import RedirectResponse

            # Create session store (Mail Query 전용 DB)
            db = get_mail_query_database()
            session_store = AuthSessionStore(db)

            # Use default user if no user_id provided
            if not user_id:
                user_id = "default"
                logger.info(f"🔐 No user_id provided, using default: {user_id}")

            # Create a new session with state
            state = session_store.create_session(user_id=user_id, ttl_seconds=600)

            # Azure AD configuration
            client_id = "88f1daa2-a6cc-4c7b-b575-b76bf0a6435b"
            tenant_id = "2da6fff9-9e75-4088-b510-a5d769de35f8"
            redirect_uri = f"http://localhost:{self.port}/auth/callback"
            scope = "User.Read Mail.Read offline_access"

            # Build authorization URL
            auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
            params = {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "response_mode": "query",
                "scope": scope,
                "state": state
            }

            # Build query string
            query_string = "&".join([f"{k}={v.replace(' ', '%20')}" for k, v in params.items()])
            full_url = f"{auth_url}?{query_string}"

            logger.info(f"🔐 Starting OAuth flow for user: {user_id}, state: {state[:10]}...")

            # Redirect to Azure AD
            return RedirectResponse(url=full_url, status_code=302)

        # OAuth callback endpoint
        @app.get("/auth/callback", tags=["Legacy OAuth"])
        async def oauth_callback_handler(request: Request):
            """[LEGACY] Handle OAuth callback from Azure AD and exchange code for tokens - Use /oauth/azure_callback for DCR flow"""
            from infra.core.oauth_client import get_oauth_client
            from infra.core.token_service import get_token_service
            from modules.enrollment.account import AccountCryptoHelpers
            from modules.enrollment import get_auth_orchestrator

            # Get query parameters
            params = dict(request.query_params)

            logger.info(f"🔐 OAuth callback received: {list(params.keys())}")

            # Check for error
            if "error" in params:
                error = params.get("error")
                error_description = params.get("error_description", "")
                logger.error(f"❌ OAuth error: {error} - {error_description}")

                html = f"""
                <html>
                <head><title>Authentication Error</title></head>
                <body>
                    <h1>❌ Authentication Error</h1>
                    <p><strong>Error:</strong> {error}</p>
                    <p><strong>Description:</strong> {error_description}</p>
                    <p>Please close this window and try again.</p>
                </body>
                </html>
                """
                return HTMLResponse(html, status_code=400)

            # Check for authorization code
            code = params.get("code")
            state = params.get("state")

            if code:
                logger.info(f"✅ Authorization code received, state: {state}")

                # Exchange code for tokens
                try:
                    # Use AuthSessionStore to validate state
                    from modules.outlook_mcp.implementations.auth_session_store import AuthSessionStore

                    db = get_mail_query_database()
                    session_store = AuthSessionStore(db)
                    user_id = None

                    # Validate state from database
                    session_info = session_store.validate_session(state) if state else None
                    if session_info:
                        user_id = session_info.get("user_id")
                        logger.info(f"✅ Valid session found for user_id: {user_id}")
                        # Delete session after use
                        session_store.delete_session(state)
                    else:
                        # Try legacy methods as fallback
                        try:
                            from modules.enrollment.auth import auth_decode_state_token
                            _, decoded_user_id = auth_decode_state_token(state)
                            if decoded_user_id:
                                user_id = decoded_user_id
                                logger.info(f"✅ User ID decoded from state (legacy): {user_id}")
                        except:
                            pass

                        if not user_id:
                            # Last resort: check query params
                            user_id = params.get("user_id")
                            if user_id:
                                logger.warning(f"⚠️  Using user_id from query params: {user_id}")

                    if not user_id:
                        logger.error(f"❌ Could not determine user_id from state: {state}")
                        html = """
                        <html>
                        <head><title>Authentication Error</title></head>
                        <body>
                            <h1>❌ 인증 오류</h1>
                            <p>인증 세션을 찾을 수 없습니다. 인증 프로세스를 다시 시작해주세요.</p>
                            <p>You can close this window now.</p>
                        </body>
                        </html>
                        """
                        return HTMLResponse(html, status_code=400)

                    # Get account OAuth config from database (Mail Query 전용)
                    db = get_mail_query_database()
                    account = db.fetch_one(
                        """
                        SELECT oauth_client_id, oauth_client_secret, oauth_tenant_id, oauth_redirect_uri
                        FROM accounts
                        WHERE user_id = ? AND is_active = 1
                        """,
                        (user_id,),
                    )

                    if not account:
                        logger.error(f"❌ Account not found: {user_id}")
                        html = f"""
                        <html>
                        <head><title>인증 오류</title></head>
                        <body>
                            <h1>❌ 인증 오류</h1>
                            <p>계정을 찾을 수 없습니다: {user_id}</p>
                            <p>이 창을 닫으셔도 됩니다.</p>
                        </body>
                        </html>
                        """
                        return HTMLResponse(html, status_code=400)

                    account_dict = dict(account)

                    # Decrypt client secret
                    crypto_helper = AccountCryptoHelpers()
                    decrypted_secret = crypto_helper.account_decrypt_sensitive_data(
                        account_dict["oauth_client_secret"]
                    )

                    # Exchange code for tokens using account config
                    oauth_client = get_oauth_client()
                    token_info = await oauth_client.exchange_code_for_tokens_with_account_config(
                        authorization_code=code,
                        client_id=account_dict["oauth_client_id"],
                        client_secret=decrypted_secret,
                        tenant_id=account_dict["oauth_tenant_id"],
                        redirect_uri=account_dict["oauth_redirect_uri"],
                    )

                    # Store tokens in database
                    token_service = get_token_service()
                    await token_service.store_tokens(
                        user_id=user_id,
                        token_info=token_info
                    )

                    # Update session status if exists
                    # NOTE: orchestrator is not available in this context
                    # This code block is commented out as it references undefined orchestrator
                    # if state and state in orchestrator.auth_sessions:
                    #     session = orchestrator.auth_sessions[state]
                    #     from modules.enrollment.auth import AuthState
                    #     session.status = AuthState.COMPLETED
                    #     logger.info(f"✅ Session status updated to COMPLETED")

                    logger.info(f"✅ Tokens saved successfully for user: {user_id}")

                    # Fetch user info from Microsoft Graph API and store in dcr_azure_users
                    try:
                        import httpx
                        from datetime import datetime, timedelta

                        async with httpx.AsyncClient() as client:
                            headers = {"Authorization": f"Bearer {token_info['access_token']}"}
                            response = await client.get("https://graph.microsoft.com/v1.0/me", headers=headers)

                            if response.status_code != 200:
                                logger.error(f"❌ Graph API request failed: {response.status_code} - {response.text}")
                                html = f"""
                                <html>
                                <head><title>인증 오류</title></head>
                                <body>
                                    <h1>❌ 사용자 정보 조회 실패</h1>
                                    <p>Microsoft Graph API에서 사용자 정보를 가져올 수 없습니다.</p>
                                    <p><strong>상태 코드:</strong> {response.status_code}</p>
                                    <p><strong>오류:</strong> {response.text}</p>
                                    <p>이 창을 닫고 다시 시도해주세요.</p>
                                </body>
                                </html>
                                """
                                return HTMLResponse(html, status_code=500)

                            user_info = response.json()
                            object_id = user_info.get("id")
                            user_email = user_info.get("mail") or user_info.get("userPrincipalName")
                            user_name = user_info.get("displayName")

                            # Validate critical user info
                            if not object_id or not user_email:
                                logger.error(f"❌ Missing critical user info: object_id={object_id}, email={user_email}")
                                html = """
                                <html>
                                <head><title>인증 오류</title></head>
                                <body>
                                    <h1>❌ 사용자 정보 불완전</h1>
                                    <p>필수 사용자 정보(ID 또는 이메일)를 가져올 수 없습니다.</p>
                                    <p>Azure AD 계정 설정을 확인해주세요.</p>
                                </body>
                                </html>
                                """
                                return HTMLResponse(html, status_code=500)

                            # Store in dcr_azure_users table using DCRService pattern
                            try:
                                from modules.dcr_oauth_module import DCRService
                                dcr_service = DCRService(module_name=self.server_name)

                                # Calculate token expiry
                                expires_in = token_info.get("expires_in", 3600)
                                expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

                                # Use DCRService's save_azure_tokens_and_sync method pattern
                                dcr_service.save_azure_tokens_and_sync(
                                    azure_object_id=object_id,
                                    azure_access_token=token_info['access_token'],
                                    azure_refresh_token=token_info.get('refresh_token'),
                                    scope=token_info.get("scope", "User.Read Mail.Read offline_access"),
                                    user_email=user_email,
                                    user_name=user_name,
                                    azure_expires_at=expires_at,
                                    sync_accounts=False  # We already saved to graphapi.db
                                )
                                logger.info(f"✅ Azure user tokens stored in dcr_azure_users: {user_email} (object_id: {object_id})")

                            except Exception as dcr_error:
                                logger.error(f"❌ Failed to store user in DCR table: {str(dcr_error)}")
                                import traceback
                                traceback.print_exc()
                                html = f"""
                                <html>
                                <head><title>인증 오류</title></head>
                                <body>
                                    <h1>❌ 사용자 정보 저장 실패</h1>
                                    <p>DCR 데이터베이스에 사용자 정보를 저장할 수 없습니다.</p>
                                    <p><strong>오류:</strong> {str(dcr_error)}</p>
                                    <p>이 창을 닫고 다시 시도해주세요.</p>
                                </body>
                                </html>
                                """
                                return HTMLResponse(html, status_code=500)

                    except Exception as user_fetch_error:
                        logger.error(f"❌ Graph API request exception: {str(user_fetch_error)}")
                        import traceback
                        traceback.print_exc()
                        html = f"""
                        <html>
                        <head><title>인증 오류</title></head>
                        <body>
                            <h1>❌ 사용자 정보 조회 실패</h1>
                            <p>Microsoft Graph API 요청 중 오류가 발생했습니다.</p>
                            <p><strong>오류:</strong> {str(user_fetch_error)}</p>
                            <p>이 창을 닫고 다시 시도해주세요.</p>
                        </body>
                        </html>
                        """
                        return HTMLResponse(html, status_code=500)

                    html = f"""
                    <html>
                    <head><title>인증 성공</title></head>
                    <body>
                        <h1>✅ 인증 성공</h1>
                        <p><strong>{user_id}</strong> 계정의 토큰이 성공적으로 저장되었습니다.</p>
                        <p><strong>이제 이 창을 닫으셔도 됩니다.</strong></p>
                        <script>
                            setTimeout(function() {{ window.close(); }}, 3000);
                        </script>
                    </body>
                    </html>
                    """
                    return HTMLResponse(html)

                except Exception as e:
                    logger.error(f"❌ Token exchange failed: {str(e)}")
                    import traceback
                    traceback.print_exc()

                    html = f"""
                    <html>
                    <head><title>인증 오류</title></head>
                    <body>
                        <h1>❌ 토큰 교환 실패</h1>
                        <p><strong>오류:</strong> {str(e)}</p>
                        <p>이 창을 닫고 다시 시도해주세요.</p>
                    </body>
                    </html>
                    """
                    return HTMLResponse(html, status_code=500)

            return Response("Missing authorization code", status_code=400)

        # === DCR OAuth Endpoints (Standard RFC 7591) ===
        # These are the standard endpoints for MCP Connector OAuth2 flow
        from .dcr_endpoints import add_dcr_endpoints
        add_dcr_endpoints(app)
        logger.info("🔐 DCR OAuth endpoints added (/oauth/*)")

        # Add /callback as an alias for /auth/callback (for OAuth compatibility)
        @app.get("/callback", tags=["Legacy OAuth"])
        async def oauth_callback_alias(request: Request):
            """[LEGACY] Alias for /auth/callback to support standard OAuth callback paths"""
            return await oauth_callback_handler(request)

        # Initialize OpenAI wrapper
        from modules.openai_wrapper import MCPOpenAIWrapper
        self.openai_wrapper = MCPOpenAIWrapper(
            mcp_server=self,
            server_name="mail-query",
            model_id="mcp-mail-query"
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
        logger.info(f"🚀 Starting FastAPI Mail Attachment Server on http://{self.host}:{self.port}")
        logger.info(f"📧 MCP endpoint: http://{self.host}:{self.port}/")
        logger.info(f"📚 OpenAPI docs: http://{self.host}:{self.port}/docs")
        logger.info(f"💚 Health check: http://{self.host}:{self.port}/health")
        logger.info(f"ℹ️  Server info: http://{self.host}:{self.port}/info")

        # Run uvicorn with FastAPI app
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")