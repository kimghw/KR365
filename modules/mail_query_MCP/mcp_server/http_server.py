"""HTTP Streaming-based MCP Server for Mail Attachments

This server uses Starlette for MCP protocol implementation and FastAPI for OpenAPI documentation.
"""

import asyncio
import json
import logging
import secrets
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.responses import JSONResponse as FastAPIJSONResponse
from mcp.server import NotificationOptions, Server
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, Mount

from infra.core.auth_logger import get_auth_logger
from infra.core.database import get_database_manager
from infra.core.logger import get_logger
from .handlers import MCPHandlers

logger = get_logger(__name__)
auth_logger = get_auth_logger()


class HTTPStreamingMailAttachmentServer:
    """HTTP Streaming-based MCP Server for Mail Attachments"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8002):
        self.host = host
        self.port = port

        # MCP Server
        self.mcp_server = Server("email-mcp-server")

        # Database
        self.db = get_database_manager()

        # Initialize database connection and check authentication
        self._initialize_and_check_auth()

        # MCP Handlers
        self.handlers = MCPHandlers()

        # Active sessions
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # Create Starlette app (actual MCP server)
        self.starlette_app = self._create_app()

        # Create FastAPI wrapper (for OpenAPI documentation)
        self.app = self._create_fastapi_wrapper()

        logger.info(f"🚀 HTTP Streaming Mail Attachment Server initialized on port {port}")
    
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
    
    async def _send_list_changed_notifications(self, request: Request):
        """Send list changed notifications after initialization"""
        # Wait a bit to ensure client is ready
        await asyncio.sleep(0.1)
        
        # Note: In a real implementation, we would need to track the client's SSE connection
        # For now, we'll just log that we would send these
        logger.info("📤 Would send notifications/tools/list_changed")
        logger.info("📤 Would send notifications/prompts/list_changed")
        logger.info("📤 Would send notifications/resources/list_changed")
    
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

        # Bearer token authentication handled by unified_http_server middleware
        # request.state.azure_token is available if ENABLE_OAUTH_AUTH=true

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
                        from .handlers import get_default_user_id
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
        """Create Starlette application"""
        
        async def health_check(request):
            """Health check endpoint"""
            return JSONResponse(
                {
                    "status": "healthy",
                    "server": "email-mcp-server",
                    "version": "2.0.0",
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
                    "name": "email-mcp-server",
                    "version": "2.0.0",
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
                        "name": "email-mcp-server",
                        "version": "2.0.0",
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
        
        # OAuth callback endpoint
        async def oauth_callback_handler(request):
            """Handle OAuth callback from Azure AD and exchange code for tokens"""
            from infra.core.database import get_database_manager
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
                return Response(html, media_type="text/html", status_code=400)

            # Check for authorization code
            code = params.get("code")
            state = params.get("state")

            if code:
                logger.info(f"✅ Authorization code received, state: {state}")

                # Exchange code for tokens
                try:
                    # Find user_id from state token (user_id is encoded in state)
                    from modules.enrollment.auth import auth_decode_state_token

                    orchestrator = get_auth_orchestrator()
                    user_id = None

                    # Decode user_id from state
                    _, decoded_user_id = auth_decode_state_token(state)
                    if decoded_user_id:
                        user_id = decoded_user_id
                        logger.info(f"✅ User ID decoded from state: {user_id}")
                    else:
                        # Fallback: search for session by state
                        if state and state in orchestrator.auth_sessions:
                            session = orchestrator.auth_sessions[state]
                            user_id = session.user_id
                            logger.info(f"✅ Found session for user_id: {user_id}")
                        else:
                            logger.warning(f"⚠️  No session found for state: {state}")
                            # Try to find user_id from query params as last resort
                            user_id = params.get("user_id")

                    if not user_id:
                        logger.error("❌ Could not determine user_id from state or params")
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
                        return Response(html, media_type="text/html", status_code=400)

                    # Get account OAuth config from database
                    db = get_database_manager()
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
                        return Response(html, media_type="text/html", status_code=400)

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
                    if state and state in orchestrator.auth_sessions:
                        session = orchestrator.auth_sessions[state]
                        from modules.enrollment.auth import AuthState
                        session.status = AuthState.COMPLETED
                        logger.info(f"✅ Session status updated to COMPLETED")

                    logger.info(f"✅ Tokens saved successfully for user: {user_id}")

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
                    return Response(html, media_type="text/html")

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
                    return Response(html, media_type="text/html", status_code=500)

            return Response("Missing authorization code", status_code=400)

        # OAuth discovery endpoints - RFC 8414 compliant
        async def oauth_authorization_server(request):
            """RFC 8414 OAuth 2.0 Authorization Server Metadata with DCR support"""
            # Build base URL from request
            base_url = f"{request.url.scheme}://{request.url.netloc}"

            return JSONResponse(
                {
                    "issuer": base_url,
                    "authorization_endpoint": f"{base_url}/oauth/authorize",
                    "token_endpoint": f"{base_url}/oauth/token",
                    "registration_endpoint": f"{base_url}/oauth/register",  # DCR endpoint
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
                    "scopes_supported": ["Mail.Read", "Mail.ReadWrite", "User.Read"],
                    "code_challenge_methods_supported": ["S256"],
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
            )

        async def oauth_protected_resource(request):
            """OAuth protected resource metadata - returns empty to indicate no auth"""
            # Return 404 to indicate this resource is not OAuth protected
            return JSONResponse(
                {"error": "This resource does not require authentication"},
                status_code=404,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
            )

        # MCP Discovery handler REMOVED - now handled by FastAPI wrapper only
        # This prevents Starlette from overriding FastAPI's OAuth-free response

        # DCR endpoints
        async def dcr_register_handler(request):
            """RFC 7591: Dynamic Client Registration"""
            from modules.dcr_oauth import DCRService

            try:
                body = await request.body()
                request_data = json.loads(body) if body else {}

                dcr_service = DCRService()
                response = await dcr_service.register_client(request_data)

                logger.info(f"✅ DCR client registered: {response['client_id']}")

                return JSONResponse(
                    response,
                    status_code=201,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Content-Type": "application/json",
                        "Cache-Control": "no-store",
                    },
                )

            except Exception as e:
                logger.error(f"❌ DCR registration failed: {str(e)}")
                return JSONResponse(
                    {"error": "invalid_client_metadata", "error_description": str(e)},
                    status_code=400,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Content-Type": "application/json",
                    },
                )

        async def dcr_client_handler(request):
            """RFC 7591: Client Configuration Endpoint"""
            from modules.dcr_oauth import DCRService

            client_id = request.path_params.get("client_id")
            dcr_service = DCRService()

            # GET - Read client configuration
            if request.method == "GET":
                client = dcr_service.get_client(client_id)
                if not client:
                    return JSONResponse(
                        {"error": "invalid_client_id"},
                        status_code=404,
                        headers={"Access-Control-Allow-Origin": "*"},
                    )

                return JSONResponse(client, headers={"Access-Control-Allow-Origin": "*"})

            # DELETE - Delete client
            elif request.method == "DELETE":
                auth_header = request.headers.get("Authorization", "")
                if not auth_header.startswith("Bearer "):
                    return JSONResponse(
                        {"error": "invalid_token"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )

                registration_token = auth_header[7:]
                success = await dcr_service.delete_client(client_id, registration_token)

                if not success:
                    return JSONResponse(
                        {"error": "invalid_token"},
                        status_code=401,
                        headers={"Access-Control-Allow-Origin": "*"},
                    )

                return Response(status_code=204, headers={"Access-Control-Allow-Origin": "*"})

        async def oauth_authorize_handler(request):
            """OAuth Authorization Endpoint - Azure AD 프록시"""
            from modules.dcr_oauth import DCRService

            # Query parameters
            client_id = request.query_params.get("client_id")
            redirect_uri = request.query_params.get("redirect_uri")
            response_type = request.query_params.get("response_type", "code")
            scope = request.query_params.get("scope", "Mail.Read User.Read")
            state = request.query_params.get("state")

            if not client_id or not redirect_uri:
                return JSONResponse(
                    {"error": "invalid_request", "error_description": "Missing required parameters"},
                    status_code=400,
                )

            # Verify client
            dcr_service = DCRService()
            client = dcr_service.get_client(client_id)

            if not client:
                return JSONResponse(
                    {"error": "invalid_client"},
                    status_code=401,
                )

            # Azure AD authorization URL
            azure_tenant_id = client["azure_tenant_id"]
            azure_client_id = client["azure_client_id"]

            # Map to Azure AD redirect URI (our callback)
            base_url = f"{request.url.scheme}://{request.url.netloc}"
            azure_redirect_uri = f"{base_url}/oauth/azure_callback"

            # Store original request for callback
            auth_code = dcr_service.create_authorization_code(
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=scope,
                state=state,
            )

            # Build Azure AD authorization URL
            from urllib.parse import urlencode

            azure_params = {
                "client_id": azure_client_id,
                "response_type": "code",
                "redirect_uri": azure_redirect_uri,
                "response_mode": "query",
                "scope": "offline_access User.Read Mail.Read",
                "state": auth_code,  # Use our code as state
            }

            azure_auth_url = (
                f"https://login.microsoftonline.com/{azure_tenant_id}/oauth2/v2.0/authorize?"
                f"{urlencode(azure_params)}"
            )

            logger.info(f"🔐 Redirecting to Azure AD for authorization")

            # Redirect to Azure AD
            return Response(
                status_code=302,
                headers={
                    "Location": azure_auth_url,
                    "Access-Control-Allow-Origin": "*",
                },
            )

        async def oauth_azure_callback_handler(request):
            """Azure AD Callback - 중간 처리"""
            from modules.dcr_oauth import DCRService

            code = request.query_params.get("code")
            state = request.query_params.get("state")  # This is our auth_code
            error = request.query_params.get("error")

            if error:
                logger.error(f"❌ Azure AD error: {error}")
                return JSONResponse(
                    {"error": error},
                    status_code=400,
                )

            if not code or not state:
                return JSONResponse(
                    {"error": "invalid_request"},
                    status_code=400,
                )

            # Get original request from our auth_code
            dcr_service = DCRService()
            # state is our authorization code
            # We'll exchange Azure code for token and then redirect back to client

            # Store Azure code temporarily (새 스키마 사용)
            import json

            # Get existing metadata
            existing_data = dcr_service.db.fetch_one(
                "SELECT metadata FROM dcr_oauth WHERE token_type = 'auth_code' AND token_value = ?",
                (state,),
            )

            if existing_data and existing_data[0]:
                metadata = json.loads(existing_data[0])
            else:
                metadata = {}

            metadata["azure_auth_code"] = code

            query = """
            UPDATE dcr_oauth
            SET metadata = ?
            WHERE token_type = 'auth_code' AND token_value = ?
            """
            dcr_service.db.execute_query(query, (json.dumps(metadata), state))

            # Now redirect to client with our authorization code
            auth_code_data = dcr_service.db.fetch_one(
                "SELECT metadata FROM dcr_oauth WHERE token_type = 'auth_code' AND token_value = ?",
                (state,),
            )

            if not auth_code_data or not auth_code_data[0]:
                return JSONResponse({"error": "invalid_state"}, status_code=400)

            # Extract redirect_uri and state from metadata
            metadata = json.loads(auth_code_data[0])
            client_redirect_uri = metadata.get("redirect_uri", "")
            client_state = metadata.get("state")

            # Build redirect URL to client
            from urllib.parse import urlencode, urlparse, parse_qs

            params = {"code": state}  # Our authorization code
            if client_state:
                params["state"] = client_state

            redirect_url = f"{client_redirect_uri}?{urlencode(params)}"

            logger.info(f"✅ Redirecting back to client: {redirect_url}")

            return Response(
                status_code=302,
                headers={
                    "Location": redirect_url,
                    "Access-Control-Allow-Origin": "*",
                },
            )

        async def oauth_token_handler(request):
            """OAuth Token Endpoint - RFC 6749 준수 (authorization_code + refresh_token)"""
            from modules.dcr_oauth import DCRService
            from infra.core.oauth_client import get_oauth_client

            try:
                # Parse form data
                form = await request.form()
                grant_type = form.get("grant_type")
                client_id = form.get("client_id")
                client_secret = form.get("client_secret")

                # Verify client credentials (both grant types require this)
                dcr_service = DCRService()
                if not dcr_service.verify_client_credentials(client_id, client_secret):
                    return JSONResponse(
                        {"error": "invalid_client"},
                        status_code=401,
                    )

                # ========== Grant Type: authorization_code (최초 로그인) ==========
                if grant_type == "authorization_code":
                    code = form.get("code")
                    redirect_uri = form.get("redirect_uri")

                    if not all([code, redirect_uri]):
                        return JSONResponse(
                            {"error": "invalid_request"},
                            status_code=400,
                        )

                    # Verify authorization code
                    code_data = dcr_service.verify_authorization_code(code, client_id, redirect_uri)
                    if not code_data:
                        return JSONResponse(
                            {"error": "invalid_grant"},
                            status_code=400,
                        )

                    # Get Azure auth code (새 스키마 사용)
                    auth_code_result = dcr_service.db.fetch_one(
                        "SELECT metadata FROM dcr_oauth WHERE token_type = 'auth_code' AND token_value = ?",
                        (code,),
                    )

                    if auth_code_result and auth_code_result[0]:
                        import json
                        metadata = json.loads(auth_code_result[0])
                        azure_auth_code = metadata.get("azure_auth_code")
                    else:
                        azure_auth_code = None

                    azure_code_result = (azure_auth_code,) if azure_auth_code else None

                    if not azure_code_result or not azure_code_result[0]:
                        return JSONResponse(
                            {"error": "invalid_grant", "error_description": "Azure code not found"},
                            status_code=400,
                        )

                    azure_auth_code = azure_code_result[0]

                    # Get client Azure config
                    client = dcr_service.get_client(client_id)

                    # Exchange Azure code for tokens
                    base_url = f"{request.url.scheme}://{request.url.netloc}"
                    azure_redirect_uri = f"{base_url}/oauth/azure_callback"

                    oauth_client = get_oauth_client()
                    token_info = await oauth_client.exchange_code_for_tokens_with_account_config(
                        authorization_code=azure_auth_code,
                        client_id=client["azure_application_id"],
                        client_secret=client["azure_client_secret"],
                        tenant_id=client["azure_tenant_id"],
                        redirect_uri=azure_redirect_uri,
                    )

                    # Generate our own access token
                    access_token = secrets.token_urlsafe(32)
                    refresh_token = secrets.token_urlsafe(32)

                    # Store token mapping
                    from datetime import datetime, timedelta

                    azure_expiry = datetime.fromisoformat(token_info["expiry"])

                    # Get user info from code_data
                    azure_object_id = code_data.get("azure_object_id")
                    if not azure_object_id:
                        return JSONResponse(
                            {"error": "invalid_grant", "error_description": "User not authenticated"},
                            status_code=400,
                        )

                    # Get user email from dcr_clients
                    client_info = dcr_service.get_client(client_id)
                    user_email = client_info.get("user_email")
                    user_name = client_info.get("user_name")

                    # Store tokens (fixed: store_token → store_tokens)
                    dcr_service.store_tokens(
                        dcr_client_id=client_id,
                        dcr_access_token=access_token,
                        dcr_refresh_token=refresh_token,
                        expires_in=3600,
                        scope=code_data["scope"],
                        azure_object_id=azure_object_id,
                        azure_access_token=token_info["access_token"],
                        azure_refresh_token=token_info.get("refresh_token"),
                        azure_expires_at=azure_expiry,
                        user_email=user_email,
                        user_name=user_name,
                    )

                    logger.info(f"✅ Token issued for DCR client: {client_id}")

                    # RFC 6749 token response
                    return JSONResponse(
                        {
                            "access_token": access_token,
                            "token_type": "Bearer",
                            "expires_in": 3600,
                            "refresh_token": refresh_token,
                            "scope": code_data["scope"],
                        },
                        headers={
                            "Access-Control-Allow-Origin": "*",
                            "Cache-Control": "no-store",
                            "Pragma": "no-cache",
                        },
                    )

                # ========== Grant Type: refresh_token (토큰 갱신) ==========
                elif grant_type == "refresh_token":
                    refresh_token = form.get("refresh_token")

                    if not refresh_token:
                        return JSONResponse(
                            {"error": "invalid_request", "error_description": "refresh_token is required"},
                            status_code=400,
                        )

                    # Verify DCR refresh token
                    refresh_data = dcr_service.verify_refresh_token(refresh_token, client_id)
                    if not refresh_data:
                        return JSONResponse(
                            {"error": "invalid_grant", "error_description": "Invalid or expired refresh token"},
                            status_code=400,
                        )

                    azure_object_id = refresh_data["azure_object_id"]
                    scope = refresh_data["scope"]

                    # Get Azure tokens by object_id
                    azure_tokens = dcr_service.get_azure_tokens_by_object_id(azure_object_id)
                    if not azure_tokens or not azure_tokens.get("refresh_token"):
                        return JSONResponse(
                            {"error": "invalid_grant", "error_description": "Azure refresh token not found"},
                            status_code=400,
                        )

                    # Get client Azure config
                    client = dcr_service.get_client(client_id)

                    # Refresh Azure tokens
                    oauth_client = get_oauth_client()

                    # Parse scope string to list
                    scope_list = scope.split() if scope else None

                    new_azure_tokens = await oauth_client.refresh_access_token(
                        refresh_token=azure_tokens["refresh_token"],
                        client_id=client["azure_application_id"],
                        client_secret=client["azure_client_secret"],
                        tenant_id=client["azure_tenant_id"],
                        scopes=scope_list,
                    )

                    # Generate new DCR tokens
                    new_access_token = secrets.token_urlsafe(32)
                    new_refresh_token = secrets.token_urlsafe(32)

                    # Parse Azure token expiry
                    from datetime import datetime, timedelta

                    # new_azure_tokens["expiry"] is datetime object or ISO string
                    if isinstance(new_azure_tokens["expiry"], str):
                        azure_expiry = datetime.fromisoformat(new_azure_tokens["expiry"])
                    else:
                        azure_expiry = new_azure_tokens["expiry"]

                    # Store new tokens
                    dcr_service.store_tokens(
                        dcr_client_id=client_id,
                        dcr_access_token=new_access_token,
                        dcr_refresh_token=new_refresh_token,
                        expires_in=3600,
                        scope=scope,
                        azure_object_id=azure_object_id,
                        azure_access_token=new_azure_tokens["access_token"],
                        azure_refresh_token=new_azure_tokens.get("refresh_token", azure_tokens["refresh_token"]),
                        azure_expires_at=azure_expiry,
                        user_email=azure_tokens.get("user_email"),
                        user_name=refresh_data.get("user_name"),
                    )

                    logger.info(f"✅ Token refreshed for DCR client: {client_id}")

                    # RFC 6749 token response
                    return JSONResponse(
                        {
                            "access_token": new_access_token,
                            "token_type": "Bearer",
                            "expires_in": 3600,
                            "refresh_token": new_refresh_token,
                            "scope": scope,
                        },
                        headers={
                            "Access-Control-Allow-Origin": "*",
                            "Cache-Control": "no-store",
                            "Pragma": "no-cache",
                        },
                    )

                else:
                    return JSONResponse(
                        {"error": "unsupported_grant_type", "error_description": f"Grant type '{grant_type}' is not supported"},
                        status_code=400,
                    )

            except Exception as e:
                logger.error(f"❌ Token exchange failed: {str(e)}")
                import traceback
                traceback.print_exc()

                return JSONResponse(
                    {"error": "server_error", "error_description": str(e)},
                    status_code=500,
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
            # OAuth callback endpoint
            Route("/auth/callback", endpoint=oauth_callback_handler, methods=["GET"]),
            # Health and info endpoints
            Route("/health", endpoint=health_check, methods=["GET"]),
            Route("/info", endpoint=server_info, methods=["GET"]),
            # Streaming endpoints (both /stream and /steam for compatibility)
            Route("/stream", endpoint=self._handle_streaming_request, methods=["POST"]),
            Route("/steam", endpoint=self._handle_streaming_request, methods=["POST", "GET", "HEAD"]),
            Route("/stream", endpoint=options_handler, methods=["OPTIONS"]),
            Route("/steam", endpoint=options_handler, methods=["OPTIONS"]),
            Route("/health", endpoint=options_handler, methods=["OPTIONS"]),
            Route("/info", endpoint=options_handler, methods=["OPTIONS"]),
            # MCP Discovery - REMOVED from Starlette, now handled by FastAPI wrapper
            # This ensures FastAPI's OAuth-free discovery endpoint takes precedence
            # OAuth endpoints removed - now handled by unified_http_server at root level
            # All OAuth flows should go through:
            #   - /.well-known/mcp.json (root level)
            #   - /oauth/register (root level)
            #   - /oauth/authorize (root level)
            #   - /oauth/token (root level)
        ]
        
        return Starlette(routes=routes)

    def _create_fastapi_wrapper(self):
        """Create FastAPI wrapper for OpenAPI documentation

        This wraps the Starlette MCP server with FastAPI to provide:
        - /docs - Swagger UI documentation
        - /redoc - ReDoc documentation
        - /openapi.json - OpenAPI schema

        The actual MCP protocol is still handled by Starlette.
        """
        from pydantic import BaseModel, Field

        # Create FastAPI app
        fastapi_app = FastAPI(
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

        # Define FastAPI routes BEFORE mounting Starlette
        # (routes take precedence over mounted apps)

        @fastapi_app.get(
            "/.well-known/mcp.json",
            tags=["MCP Discovery"],
            summary="MCP Server Discovery",
            description="MCP discovery endpoint (OAuth handled at root level)"
        )
        async def mcp_discovery():
            """MCP Server Discovery - OAuth handled by unified server"""
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

        @fastapi_app.post(
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
        async def mcp_endpoint(request: FastAPIRequest):
            """MCP Protocol endpoint - delegates to Starlette app"""
            # Forward to Starlette MCP server
            from starlette.datastructures import Headers
            starlette_request = Request(request.scope, request.receive)
            response = await self._handle_streaming_request(starlette_request)
            return response

        @fastapi_app.get(
            "/health",
            tags=["Health"],
            summary="Health Check",
            description="Check if the server is running and healthy"
        )
        async def health_check():
            return {"status": "healthy", "server": "email-mcp-server"}

        @fastapi_app.get(
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

        # Mount Starlette MCP app AFTER defining routes
        # (this ensures FastAPI routes take precedence)
        fastapi_app.mount("/mcp", self.starlette_app)

        # Initialize OpenAI wrapper
        from modules.openai_wrapper import MCPOpenAIWrapper
        self.openai_wrapper = MCPOpenAIWrapper(
            mcp_server=self,
            server_name="mail-query",
            model_id="mcp-mail-query"
        )

        # OpenAI-compatible endpoints
        @fastapi_app.post(
            "/v1/chat/completions",
            tags=["OpenAI Compatible"],
            summary="Chat Completions",
            description="OpenAI-compatible chat completions endpoint exposing MCP tools"
        )
        async def chat_completions(request: FastAPIRequest):
            """Handle OpenAI chat completions request"""
            from modules.openai_wrapper.schemas import ChatCompletionRequest
            body = await request.json()
            chat_request = ChatCompletionRequest(**body)
            response = await self.openai_wrapper.handle_chat_completions(chat_request)
            return response.model_dump(exclude_none=True)

        @fastapi_app.get(
            "/v1/models",
            tags=["OpenAI Compatible"],
            summary="List Models",
            description="List available models (MCP server as a model)"
        )
        async def list_models():
            """Handle OpenAI list models request"""
            response = await self.openai_wrapper.handle_list_models()
            return response.model_dump()

        logger.info("📚 FastAPI wrapper created - OpenAPI available at /docs")
        return fastapi_app

    def run(self):
        """Run the HTTP streaming MCP server"""
        logger.info(f"🚀 Starting HTTP Streaming Mail Attachment Server on http://{self.host}:{self.port}")
        logger.info(f"📧 MCP endpoint: http://{self.host}:{self.port}/")
        logger.info(f"📚 OpenAPI docs: http://{self.host}:{self.port}/docs")
        logger.info(f"💚 Health check: http://{self.host}:{self.port}/health")
        logger.info(f"ℹ️  Server info: http://{self.host}:{self.port}/info")

        # Run uvicorn with FastAPI app (which wraps Starlette)
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")