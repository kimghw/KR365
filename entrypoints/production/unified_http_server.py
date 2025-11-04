#!/usr/bin/env python3
"""Unified MCP HTTP Server

Single HTTP server instance serving multiple MCP servers on different paths:
- /mail-query/* - Mail Query MCP Server
- /enrollment/* - Enrollment MCP Server
- /onenote/* - OneNote MCP Server
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ Loaded environment variables from {env_file}")

from modules.mail_query_MCP.mcp_server.http_server import HTTPStreamingMailAttachmentServer
from modules.enrollment.mcp_server.http_server import HTTPStreamingAuthServer
from modules.onenote_mcp.mcp_server.http_server import HTTPStreamingOneNoteServer
from modules.onedrive_mcp.mcp_server.http_server import HTTPStreamingOneDriveServer
from modules.teams_mcp.mcp_server.http_server import HTTPStreamingTeamsServer
from modules.enrollment.auth import get_auth_orchestrator
from modules.enrollment.auth.auth_callback_processor import AuthCallbackProcessor
from infra.core.logger import get_logger
from infra.core.config import get_config
from infra.utils.datetime_utils import utc_now, parse_iso_to_utc
from modules.dcr_oauth import DCRService

logger = get_logger(__name__)
config = get_config()


class UnifiedMCPServer:
    """Unified HTTP server hosting multiple MCP servers on different paths"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.host = host
        self.port = port

        logger.info("🚀 Initializing Unified MCP Server")

        # Initialize individual MCP servers (don't run them, just get their apps)
        logger.info("📧 Initializing Mail Query MCP Server...")
        self.mail_query_server = HTTPStreamingMailAttachmentServer(host=host, port=port)

        logger.info("🔐 Initializing Enrollment MCP Server...")
        self.enrollment_server = HTTPStreamingAuthServer(host=host, port=port)

        logger.info("📝 Initializing OneNote MCP Server...")
        self.onenote_server = HTTPStreamingOneNoteServer(host=host, port=port)

        logger.info("📁 Initializing OneDrive MCP Server...")
        self.onedrive_server = HTTPStreamingOneDriveServer(host=host, port=port)

        logger.info("👥 Initializing Teams MCP Server...")
        self.teams_server = HTTPStreamingTeamsServer(host=host, port=port)

        # Root only handles OAuth authentication
        # Individual MCP servers expose their own /v1/chat/completions and /v1/models endpoints

        # Initialize Auth Callback Processor for OAuth callback handling
        logger.info("🔐 Initializing Auth Callback Processor for OAuth callbacks...")
        self.callback_processor = AuthCallbackProcessor()
        # Set session store from auth orchestrator
        orchestrator = get_auth_orchestrator()
        self.callback_processor.set_session_store(orchestrator.auth_sessions)

        # Initialize DCR schema (환경변수 → DB 저장은 DCRService.__init__에서 자동 처리)
        self._ensure_dcr_schema_only()

        # Ensure DCR Azure config is synced from env at startup
        try:
            logger.info("🔧 Syncing DCR Azure config from environment on startup...")
            _ = DCRService()
            logger.info("✅ DCR Azure config sync completed")
        except Exception as e:
            logger.warning(f"⚠️ DCR Azure config sync skipped due to error: {e}")

        # Create unified Starlette app
        self.app = self._create_unified_app()

        logger.info("✅ Unified MCP Server initialized")

    def _ensure_dcr_schema_only(self):
        """DCR V3 스키마만 초기화 (Azure 설정은 DCRService에서 처리)"""
        import sqlite3
        from infra.core.config import get_config

        try:
            config = get_config()
            conn = sqlite3.connect(config.dcr_database_path)

            # 스키마 파일 읽기
            schema_path = PROJECT_ROOT / "modules" / "dcr_oauth" / "migrations" / "dcr_schema_v3.sql"
            with open(schema_path, 'r') as f:
                schema_sql = f.read()

            conn.executescript(schema_sql)
            conn.commit()
            conn.close()
            logger.info("✅ DCR V3 schema initialized (Azure config will be loaded by DCRService)")
        except Exception as e:
            logger.error(f"❌ DCR V3 schema initialization failed: {e}")
            raise

    def _create_unified_app(self):
        """Create unified Starlette application with multiple MCP servers"""

        # Health check endpoint
        async def unified_health(request):
            return JSONResponse(
                {
                    "status": "healthy",
                    "server": "unified-mcp-server",
                    "version": "1.0.0",
                    "services": {
                        "mail-query": "running",
                        "enrollment": "running",
                        "onenote": "running",
                        "onedrive": "running",
                        "teams": "running",
                    },
                    "endpoints": {
                        "mail-query": "/mail-query/",
                        "enrollment": "/enrollment/",
                        "onenote": "/onenote/",
                        "onedrive": "/onedrive/",
                        "teams": "/teams/",
                    },
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id, MCP-Protocol-Version",
                },
            )

        # Server info endpoint
        async def unified_info(request):
            return JSONResponse(
                {
                    "name": "unified-mcp-server",
                    "version": "1.0.0",
                    "protocol": "mcp",
                    "transport": "http",
                    "services": [
                        {
                            "name": "mail-query-server",
                            "path": "/mail-query",
                            "description": "Email and attachment management",
                        },
                        {
                            "name": "enrollment-server",
                            "path": "/enrollment",
                            "description": "Account registration and authentication",
                        },
                        {
                            "name": "onenote-server",
                            "path": "/onenote",
                            "description": "OneNote notebooks, sections, and pages management",
                        },
                        {
                            "name": "onedrive-server",
                            "path": "/onedrive",
                            "description": "OneDrive file management (read/write)",
                        },
                        {
                            "name": "teams-server",
                            "path": "/teams",
                            "description": "Microsoft Teams chat (1:1 and group chats)",
                        },
                    ],
                    "endpoints": {
                        "health": "/health",
                        "info": "/info",
                    },
                }
            )

        # Root endpoint
        async def root_handler(request):
            return JSONResponse(
                {
                    "name": "unified-mcp-server",
                    "version": "1.0.0",
                    "message": "Unified MCP Server - Multiple MCP services on different paths",
                    "services": {
                        "mail-query": "/mail-query/",
                        "enrollment": "/enrollment/",
                        "onenote": "/onenote/",
                        "onedrive": "/onedrive/",
                        "teams": "/teams/",
                    },
                    "endpoints": {
                        "health": "/health",
                        "info": "/info",
                    },
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                },
            )

        # Unified MCP Discovery endpoint
        async def unified_mcp_discovery_handler(request):
            """Unified MCP Discovery - Single OAuth for all services"""
            base_url = f"{request.url.scheme}://{request.url.netloc}"

            return JSONResponse(
                {
                    "mcp_version": "1.0",
                    "name": "Unified Microsoft 365 MCP Services",
                    "description": "Single OAuth authentication for all Microsoft 365 MCP services",
                    "version": "1.0.0",
                    "oauth": {
                        "authorization_endpoint": f"{base_url}/oauth/authorize",
                        "token_endpoint": f"{base_url}/oauth/token",
                        "registration_endpoint": f"{base_url}/oauth/register",
                        "scopes_supported": [
                            "Mail.Read",
                            "Mail.ReadWrite",
                            "Notes.Read",
                            "Notes.ReadWrite",
                            "Files.Read",
                            "Files.ReadWrite",
                            "Chat.Read",
                            "Chat.ReadWrite",
                            "User.Read"
                        ],
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                        "code_challenge_methods_supported": ["S256"]
                    },
                    "services": [
                        {
                            "name": "Mail Query",
                            "path": "/mail-query",
                            "description": "Email attachment management and query",
                            "scopes": config.dcr_oauth_scopes
                        },
                        {
                            "name": "OneNote",
                            "path": "/onenote",
                            "description": "OneNote notebook and page management",
                            "scopes": config.dcr_oauth_scopes
                        },
                        {
                            "name": "OneDrive",
                            "path": "/onedrive",
                            "description": "OneDrive file management",
                            "scopes": config.dcr_oauth_scopes
                        },
                        {
                            "name": "Teams",
                            "path": "/teams",
                            "description": "Microsoft Teams chat service",
                            "scopes": config.dcr_oauth_scopes
                        },
                        {
                            "name": "Enrollment",
                            "path": "/enrollment",
                            "description": "Account management and authentication",
                            "scopes": config.dcr_oauth_scopes
                        }
                    ],
                    "capabilities": {
                        "tools": True,
                        "resources": False,
                        "prompts": False
                    }
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
            )

        # OPTIONS handler for CORS
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

        # OAuth callback handler
        async def auth_callback_handler(request):
            """Handle OAuth callback from Microsoft"""
            import asyncio
            try:
                # Get query parameters
                params = dict(request.query_params)

                # Run synchronous callback in executor to avoid event loop conflicts
                loop = asyncio.get_running_loop()
                html_response = await loop.run_in_executor(
                    None,
                    self.callback_processor.process_callback,
                    params
                )

                return Response(
                    html_response,
                    media_type="text/html",
                    headers={
                        "Access-Control-Allow-Origin": "*",
                    }
                )
            except Exception as e:
                logger.error(f"OAuth callback failed: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                error_html = f"""
                <!DOCTYPE html>
                <html>
                <head><title>Authentication Error</title></head>
                <body>
                    <h1>❌ Authentication Failed</h1>
                    <p>Error: {str(e)}</p>
                    <p>You can close this window.</p>
                </body>
                </html>
                """
                return Response(
                    error_html,
                    media_type="text/html",
                    status_code=500
                )

        # DCR OAuth metadata endpoint (proxy to mail-query server)
        async def oauth_metadata_handler(request):
            """RFC 8414 OAuth 2.0 Authorization Server Metadata"""
            base_url = f"{request.url.scheme}://{request.url.netloc}"

            return JSONResponse(
                {
                    "issuer": base_url,
                    "authorization_endpoint": f"{base_url}/oauth/authorize",
                    "token_endpoint": f"{base_url}/oauth/token",
                    "registration_endpoint": f"{base_url}/oauth/register",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
                    "scopes_supported": config.dcr_oauth_scopes,
                    "code_challenge_methods_supported": ["S256", "plain"],
                    "pkce_required": False,  # PKCE is optional but supported
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
            )

        # RFC 8707 OAuth 2.0 Protected Resource Metadata
        async def oauth_protected_resource_handler(request):
            """RFC 8707: Resource Server Metadata"""
            base_url = f"{request.url.scheme}://{request.url.netloc}"

            return JSONResponse(
                {
                    "resource": base_url,
                    "authorization_servers": [base_url],
                    "bearer_methods_supported": ["header"],
                    "resource_signing_alg_values_supported": ["none"],
                    "scopes_supported": ["Mail.Read", "Mail.ReadWrite", "User.Read"]
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
            )

        async def enrollment_mcp_discovery_handler(request):
            """MCP Discovery for Enrollment Service"""
            base_url = f"{request.url.scheme}://{request.url.netloc}"

            return JSONResponse(
                {
                    "mcp_version": "1.0",
                    "name": "Enrollment MCP Server",
                    "description": "Authentication and account management service",
                    "version": "1.0.0",
                    "oauth": {
                        "authorization_endpoint": f"{base_url}/oauth/authorize",
                        "token_endpoint": f"{base_url}/oauth/token",
                        "registration_endpoint": f"{base_url}/oauth/register",
                        "scopes_supported": config.dcr_oauth_scopes,
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                        "code_challenge_methods_supported": ["S256"]
                    },
                    "capabilities": {
                        "tools": True,
                        "resources": False,
                        "prompts": False
                    }
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
            )

        async def mail_query_mcp_discovery_handler(request):
            """MCP Discovery for Mail Query Service - Points to root OAuth endpoints"""
            base_url = f"{request.url.scheme}://{request.url.netloc}"

            return JSONResponse(
                {
                    "mcp_version": "1.0",
                    "name": "Mail Query MCP Server",
                    "description": "Email attachment management and query service",
                    "version": "1.0.0",
                    "oauth": {
                        "authorization_endpoint": f"{base_url}/oauth/authorize",
                        "token_endpoint": f"{base_url}/oauth/token",
                        "registration_endpoint": f"{base_url}/oauth/register",
                        "scopes_supported": config.dcr_oauth_scopes,
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                        "code_challenge_methods_supported": ["S256"]
                    },
                    "capabilities": {
                        "tools": True,
                        "resources": False,
                        "prompts": False
                    }
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
            )

        async def onenote_mcp_discovery_handler(request):
            """MCP Discovery for OneNote Service - Points to root OAuth endpoints"""
            base_url = f"{request.url.scheme}://{request.url.netloc}"

            return JSONResponse(
                {
                    "mcp_version": "1.0",
                    "name": "OneNote MCP Server",
                    "description": "OneNote notebooks, sections, and pages management service",
                    "version": "1.0.0",
                    "oauth": {
                        "authorization_endpoint": f"{base_url}/oauth/authorize",
                        "token_endpoint": f"{base_url}/oauth/token",
                        "registration_endpoint": f"{base_url}/oauth/register",
                        "scopes_supported": ["Notes.Read", "Notes.ReadWrite", "User.Read"],
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                        "code_challenge_methods_supported": ["S256"]
                    },
                    "capabilities": {
                        "tools": True,
                        "resources": False,
                        "prompts": False
                    }
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
            )

        async def onedrive_mcp_discovery_handler(request):
            """MCP Discovery for OneDrive Service - Points to root OAuth endpoints"""
            base_url = f"{request.url.scheme}://{request.url.netloc}"

            return JSONResponse(
                {
                    "mcp_version": "1.0",
                    "name": "OneDrive MCP Server",
                    "description": "OneDrive file management service with read/write capabilities",
                    "version": "1.0.0",
                    "oauth": {
                        "authorization_endpoint": f"{base_url}/oauth/authorize",
                        "token_endpoint": f"{base_url}/oauth/token",
                        "registration_endpoint": f"{base_url}/oauth/register",
                        "scopes_supported": ["Files.Read", "Files.ReadWrite", "User.Read"],
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                        "code_challenge_methods_supported": ["S256"]
                    },
                    "capabilities": {
                        "tools": True,
                        "resources": False,
                        "prompts": False
                    }
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
            )

        async def teams_mcp_discovery_handler(request):
            """MCP Discovery for Teams Chat Service - Points to root OAuth endpoints"""
            base_url = f"{request.url.scheme}://{request.url.netloc}"

            return JSONResponse(
                {
                    "mcp_version": "1.0",
                    "name": "Teams Chat MCP Server",
                    "description": "Microsoft Teams 1:1 and group chat service",
                    "version": "1.0.0",
                    "oauth": {
                        "authorization_endpoint": f"{base_url}/oauth/authorize",
                        "token_endpoint": f"{base_url}/oauth/token",
                        "registration_endpoint": f"{base_url}/oauth/register",
                        "scopes_supported": ["Chat.Read", "Chat.ReadWrite", "User.Read"],
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                        "code_challenge_methods_supported": ["S256"]
                    },
                    "capabilities": {
                        "tools": True,
                        "resources": False,
                        "prompts": False
                    }
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
            )

        # DCR Register endpoint
        async def dcr_register_handler(request):
            """RFC 7591: Dynamic Client Registration"""
            try:
                body = await request.body()
                import json
                request_data = json.loads(body) if body else {}

                # 세션 ID 추출 (우선순위: mcp-session-id > x-claude-session-id > traceparent)
                logger.info(f"📋 DCR Register Headers: {dict(request.headers)}")
                session_id = request.headers.get("mcp-session-id") or request.headers.get("x-claude-session-id")

                # traceparent에서 trace-id 추출 (형식: version-trace_id-parent_id-flags)
                if not session_id:
                    traceparent = request.headers.get("traceparent")
                    if traceparent:
                        parts = traceparent.split("-")
                        if len(parts) >= 2:
                            session_id = parts[1]  # trace_id 사용
                            logger.info(f"🔍 Using traceparent trace_id as session_id: {session_id}")

                logger.info(f"🔍 Extracted session_id: {session_id}")

                dcr_service = DCRService()
                response = await dcr_service.register_client(request_data, mcp_session_id=session_id)

                if session_id:
                    session_type = "MCP" if request.headers.get("mcp-session-id") else "Claude"
                    logger.info(f"✅ DCR client registered: {response['client_id']} ({session_type} session: {session_id})")
                else:
                    logger.info(f"✅ DCR client registered: {response['client_id']}")

                return JSONResponse(
                    response,
                    status_code=201,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Content-Type": "application/json",
                    },
                )
            except Exception as e:
                logger.error(f"❌ DCR registration failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return JSONResponse(
                    {"error": "invalid_client_metadata", "error_description": str(e)},
                    status_code=400,
                )

        # OAuth Authorize endpoint
        async def oauth_authorize_handler(request):
            """OAuth Authorization Endpoint - Azure AD 프록시"""
            try:
                import urllib.parse

                # Get query parameters
                params = dict(request.query_params)
                client_id = params.get("client_id")
                redirect_uri = params.get("redirect_uri")
                # DCR_OAUTH_SCOPE 환경변수 사용, offline_access 포함 보장
                default_scope = os.getenv("DCR_OAUTH_SCOPE", "offline_access User.Read Mail.ReadWrite")
                requested_scope = params.get("scope", "")

                # offline_access가 없으면 추가
                if requested_scope and "offline_access" not in requested_scope:
                    scope = f"offline_access {requested_scope}"
                elif requested_scope:
                    scope = requested_scope
                else:
                    scope = default_scope

                logger.info(f"📋 OAuth scope: {scope}")
                state = params.get("state")
                response_type = params.get("response_type", "code")
                # PKCE parameters (RFC 7636)
                code_challenge = params.get("code_challenge")
                code_challenge_method = params.get("code_challenge_method", "plain" if code_challenge else None)

                if not client_id or not redirect_uri:
                    return JSONResponse(
                        {"error": "invalid_request", "error_description": "Missing client_id or redirect_uri"},
                        status_code=400,
                    )

                # DCR 클라이언트 조회
                dcr_service = DCRService()
                client = dcr_service.get_client(client_id)

                if not client:
                    # 클라이언트가 없으면 에러 반환 (OAuth 표준 동작)
                    logger.error(f"❌ Client not found: {client_id}")
                    return JSONResponse(
                        {"error": "invalid_client", "error_description": f"Client {client_id} not found. Please register first."},
                        status_code=401,
                    )

                # Redirect URI 검증
                if redirect_uri not in client["dcr_redirect_uris"]:
                    logger.error(
                        f"❌ REDIRECT_URI_MISMATCH:\n"
                        f"  Requested: {redirect_uri}\n"
                        f"  Allowed:   {client['dcr_redirect_uris']}\n"
                        f"  Client:    {client_id}\n"
                        f"  Hint: Set DCR_OAUTH_REDIRECT_URI environment variable or update Azure app registration"
                    )
                    return JSONResponse(
                        {
                            "error": "invalid_request",
                            "error_description": f"Invalid redirect_uri. Requested: {redirect_uri}, Allowed: {client['dcr_redirect_uris']}"
                        },
                        status_code=400,
                    )

                # Check if we already have an active Bearer token for this client
                import json
                existing_token_query = """
                SELECT dcr_token_value, azure_object_id
                FROM dcr_tokens
                WHERE dcr_client_id = ?
                  AND dcr_token_type = 'Bearer'
                  AND dcr_status = 'active'
                  AND expires_at > CURRENT_TIMESTAMP
                LIMIT 1
                """
                existing_token = dcr_service._fetch_one(existing_token_query, (client_id,))

                if existing_token:
                    # We have a valid token, create authorization code and redirect immediately
                    import secrets
                    from datetime import timedelta

                    auth_code = secrets.token_urlsafe(32)
                    code_expiry = utc_now() + timedelta(minutes=10)

                    # Store auth code with metadata for token exchange
                    metadata = {
                        "redirect_uri": redirect_uri,
                        "state": state,
                        "scope": scope,
                        "skip_azure": True  # Mark that we're skipping Azure AD
                    }
                    if code_challenge:
                        metadata["code_challenge"] = code_challenge
                        metadata["code_challenge_method"] = code_challenge_method

                    # Delete old authorization codes for this client (keep only the newest)
                    dcr_service._execute_query(
                        """
                        DELETE FROM dcr_tokens
                        WHERE dcr_client_id = ?
                          AND dcr_token_type = 'authorization_code'
                        """,
                        (client_id,)
                    )

                    dcr_service._execute_query(
                        """
                        INSERT INTO dcr_tokens (
                            dcr_token_value, dcr_client_id, dcr_token_type,
                            azure_object_id, expires_at, dcr_status, metadata
                        ) VALUES (?, ?, 'authorization_code', ?, ?, 'active', ?)
                        """,
                        (
                            auth_code,
                            client_id,
                            existing_token[1],  # azure_object_id
                            code_expiry,
                            json.dumps(metadata)
                        ),
                    )

                    # Redirect back to Claude with authorization code
                    callback_url = f"{redirect_uri}?code={auth_code}&state={state}"
                    logger.info(f"♻️ Reusing existing session for client {client_id}, redirecting with auth code")

                    from starlette.responses import RedirectResponse
                    return RedirectResponse(url=callback_url)

                # Authorization code 생성 (Azure AD callback용, PKCE 지원)
                auth_code = dcr_service.create_authorization_code(
                    dcr_client_id=client_id,
                    redirect_uri=redirect_uri,
                    scope=scope,
                    state=state,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method
                )

                if code_challenge:
                    logger.info(f"📝 PKCE enabled for authorization: method={code_challenge_method}")

                # Azure AD 인증 URL 직접 생성
                azure_tenant_id = client["azure_tenant_id"]
                azure_application_id = client["azure_application_id"]
                # Azure AD에 등록된 redirect URI
                azure_redirect_uri = client.get("azure_redirect_uri")

                logger.info(
                    f"🔐 Starting Azure OAuth flow:\n"
                    f"  Client ID: {client_id}\n"
                    f"  Azure App ID: {azure_application_id}\n"
                    f"  Azure Redirect URI: {azure_redirect_uri}\n"
                    f"  Claude Redirect URI: {redirect_uri}\n"
                    f"  Scope: {scope}"
                )

                # state에 내부 auth_code 포함 (DCR 서버에서 매핑에 사용)
                internal_state = f"{auth_code}:{state}" if state else auth_code

                # Azure AD authorization endpoint
                import urllib.parse
                azure_auth_url = (
                    f"https://login.microsoftonline.com/{azure_tenant_id}/oauth2/v2.0/authorize?"
                    f"client_id={azure_application_id}&"
                    f"response_type=code&"
                    f"redirect_uri={urllib.parse.quote(azure_redirect_uri)}&"
                    f"response_mode=query&"
                    f"scope={urllib.parse.quote(scope)}&"
                    f"state={urllib.parse.quote(internal_state)}"
                )

                from starlette.responses import RedirectResponse
                return RedirectResponse(url=azure_auth_url)

            except Exception as e:
                logger.error(f"❌ OAuth authorize failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return JSONResponse(
                    {"error": "server_error", "error_description": str(e)},
                    status_code=500,
                )

        # OAuth Token endpoint
        async def oauth_token_handler(request):
            """OAuth Token Endpoint - Azure AD 토큰 교환"""
            try:
                import secrets
                from datetime import datetime, timedelta
                from infra.core.oauth_client import OAuthClient

                # Parse form data
                form_data = await request.form()
                grant_type = form_data.get("grant_type")
                client_id = form_data.get("client_id")
                client_secret = form_data.get("client_secret")
                code_verifier = form_data.get("code_verifier")  # PKCE

                # HTTP Basic Auth 지원 (client_id:client_secret를 Authorization 헤더로 전송)
                if not client_id:
                    auth_header = request.headers.get("Authorization", "")
                    if auth_header.startswith("Basic "):
                        import base64
                        try:
                            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                            if ":" in decoded:
                                client_id, client_secret = decoded.split(":", 1)
                                logger.info(f"📝 Client credentials from HTTP Basic Auth")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to decode Basic Auth: {e}")

                # Debug log
                logger.info(f"📝 Token request - grant_type: {grant_type}, client_id: {client_id}, has_secret: {bool(client_secret)}, has_verifier: {bool(code_verifier)}")

                if grant_type not in ["authorization_code", "refresh_token"]:
                    return JSONResponse(
                        {"error": "unsupported_grant_type"},
                        status_code=400,
                    )

                # 클라이언트 인증
                dcr_service = DCRService()

                # PKCE: code_verifier가 있으면 Public Client (client_secret 불필요)
                # Confidential Client: client_secret 필수
                if code_verifier:
                    # Public Client with PKCE
                    logger.info(f"🔐 PKCE authentication for client: {client_id}")
                    # client_id만 존재하면 OK (PKCE는 나중에 code_verifier로 검증)
                    client_exists = dcr_service._fetch_one(
                        "SELECT dcr_client_id FROM dcr_clients WHERE dcr_client_id = ?",
                        (client_id,)
                    )
                    if not client_exists:
                        return JSONResponse(
                            {"error": "invalid_client"},
                            status_code=401,
                        )
                else:
                    # Confidential Client (client_secret 필수)
                    logger.info(f"🔐 Client credentials authentication for client: {client_id}")
                    if not dcr_service.verify_client_credentials(client_id, client_secret):
                        return JSONResponse(
                            {"error": "invalid_client"},
                            status_code=401,
                        )

                # === Grant Type: refresh_token ===
                if grant_type == "refresh_token":
                    refresh_token_value = form_data.get("refresh_token")
                    if not refresh_token_value:
                        return JSONResponse(
                            {"error": "invalid_request", "error_description": "refresh_token required"},
                            status_code=400,
                        )

                    logger.info(f"🔄 Processing refresh_token grant")

                    # Verify refresh token
                    from modules.enrollment.account import AccountCryptoHelpers
                    crypto = AccountCryptoHelpers()

                    # Query all active refresh tokens for this client
                    query = """
                    SELECT dcr_token_value, dcr_client_id, azure_object_id, expires_at
                    FROM dcr_tokens
                    WHERE dcr_client_id = ? AND dcr_token_type = 'refresh' AND dcr_status = 'active'
                    """
                    results = dcr_service._fetch_all(query, (client_id,))

                    found_token = None
                    for row in results:
                        encrypted_token, stored_client_id, azure_object_id, expires_at = row

                        # Decrypt and compare token value
                        try:
                            decrypted_token = crypto.account_decrypt_sensitive_data(encrypted_token)
                            if not secrets.compare_digest(decrypted_token, refresh_token_value):
                                continue  # Token mismatch
                        except Exception as e:
                            logger.error(f"Token decryption error: {e}")
                            continue

                        # Check expiration
                        expiry_dt = parse_iso_to_utc(expires_at)
                        if expiry_dt < utc_now():
                            logger.warning(f"Refresh token expired")
                            continue

                        found_token = (azure_object_id, expires_at)
                        break

                    if not found_token:
                        logger.error(f"❌ Invalid or expired refresh token")
                        return JSONResponse(
                            {"error": "invalid_grant", "error_description": "Invalid or expired refresh token"},
                            status_code=400,
                        )

                    azure_object_id, refresh_expires_at = found_token
                    logger.info(f"✅ Refresh token verified for object_id: {azure_object_id}")

                    # Get Azure tokens (조회만, 재발행 없음)
                    azure_tokens = dcr_service.get_azure_tokens_by_object_id(azure_object_id)
                    if not azure_tokens:
                        logger.error(f"❌ Azure token not found")
                        return JSONResponse(
                            {"error": "invalid_grant", "error_description": "Azure token not found"},
                            status_code=400,
                        )

                    # Generate new DCR access token
                    new_access_token = secrets.token_urlsafe(32)
                    expires_in = dcr_service.dcr_bearer_ttl_seconds
                    token_expiry = utc_now() + timedelta(seconds=expires_in)

                    # Delete existing Bearer token for this client + object_id + token_type (prevent duplicates)
                    dcr_service._execute_query(
                        """
                        DELETE FROM dcr_tokens
                        WHERE dcr_client_id = ? AND azure_object_id = ? AND dcr_token_type = 'Bearer' AND dcr_status = 'active'
                        """,
                        (client_id, azure_object_id),
                    )

                    # Store new access token
                    dcr_service._execute_query(
                        """
                        INSERT INTO dcr_tokens (
                            dcr_token_value, dcr_client_id, dcr_token_type, azure_object_id, expires_at, dcr_status
                        ) VALUES (?, ?, 'Bearer', ?, ?, 'active')
                        """,
                        (crypto.account_encrypt_sensitive_data(new_access_token), client_id, azure_object_id, token_expiry),
                    )

                    # Reuse existing refresh token (이미 검증된 유효한 토큰 재사용)
                    logger.info(f"♻️ Reusing existing refresh token (expires: {refresh_expires_at})")

                    logger.info(f"✅ New access token issued via refresh_token grant (refresh token reused)")

                    return JSONResponse(
                        {
                            "access_token": new_access_token,
                            "token_type": "Bearer",
                            "expires_in": expires_in,
                            "refresh_token": refresh_token_value,  # Reuse existing refresh token
                            "scope": azure_tokens.get("scope", ""),
                        },
                        headers={
                            "Access-Control-Allow-Origin": "*",
                            "Content-Type": "application/json",
                        },
                    )

                # === Grant Type: authorization_code ===
                code = form_data.get("code")
                redirect_uri = form_data.get("redirect_uri")
                # code_verifier already extracted above

                # Authorization code 검증 (DCR auth_code, PKCE 지원)
                logger.info(f"🔍 Verifying authorization code: {code[:20]}...")
                if code_verifier:
                    logger.info(f"📝 PKCE verification requested")

                auth_data = dcr_service.verify_authorization_code(
                    code=code,
                    dcr_client_id=client_id,
                    redirect_uri=redirect_uri,
                    code_verifier=code_verifier
                )
                if not auth_data:
                    error_desc = "PKCE verification failed" if code_verifier else "Invalid authorization code"
                    logger.error(f"❌ {error_desc}")
                    return JSONResponse(
                        {"error": "invalid_grant", "error_description": error_desc},
                        status_code=400,
                    )
                logger.info(f"✅ Authorization code verified")

                # DCR 클라이언트 정보 조회
                client = dcr_service.get_client(client_id)
                if not client:
                    logger.error(f"❌ Client not found: {client_id}")
                    return JSONResponse(
                        {"error": "invalid_client"},
                        status_code=401,
                    )

                # Check if this is a skip_azure authorization (reusing existing session)
                skip_azure = auth_data.get("skip_azure", False)

                # azure_object_id로 Azure 토큰 조회
                azure_object_id = auth_data.get("azure_object_id")
                if not azure_object_id:
                    logger.error(f"❌ No azure_object_id in authorization code")
                    return JSONResponse(
                        {"error": "invalid_grant", "error_description": "No user identity in authorization code"},
                        status_code=400,
                    )

                if skip_azure:
                    # Skipping Azure verification for existing session reuse
                    logger.info(f"♻️ Skipping Azure token lookup (reusing existing session)")
                    azure_tokens = {
                        "access_token": "reused_session",  # Placeholder
                        "expires_in": 3600,
                        "user_email": "existing_session",
                        "scope": auth_data.get("scope", "Mail.Read User.Read"),
                        "azure_expires_at": None,
                    }
                else:
                    logger.info(f"🔍 Looking for Azure tokens for object_id: {azure_object_id}...")
                    azure_tokens = dcr_service.get_azure_tokens_by_object_id(azure_object_id)
                    if not azure_tokens:
                        logger.error(f"❌ Azure token not found for object_id: {azure_object_id}")
                        return JSONResponse(
                            {"error": "invalid_grant", "error_description": "Azure token not found"},
                            status_code=400,
                        )
                    logger.info(f"✅ Azure token found for user: {azure_tokens.get('user_email')}")

                azure_access_token = azure_tokens["access_token"]
                azure_refresh_token = azure_tokens.get("refresh_token", "")
                dcr_expires_in = dcr_service.dcr_bearer_ttl_seconds
                user_email = azure_tokens.get("user_email")

                # Check for existing active Bearer token first
                existing_token_query = """
                SELECT dcr_token_value, expires_at
                FROM dcr_tokens
                WHERE dcr_client_id = ?
                  AND azure_object_id = ?
                  AND dcr_token_type = 'Bearer'
                  AND dcr_status = 'active'
                  AND expires_at > CURRENT_TIMESTAMP
                """
                existing_token = dcr_service._fetch_one(existing_token_query, (client_id, azure_object_id))

                # Import crypto helper (needed for both cases)
                from modules.enrollment.account import AccountCryptoHelpers
                crypto = AccountCryptoHelpers()

                if existing_token:
                    # Reuse existing token (decrypt from DB)
                    encrypted_access_token = existing_token[0]
                    access_token = crypto.account_decrypt_sensitive_data(encrypted_access_token)
                    refresh_token = secrets.token_urlsafe(32)  # Generate new refresh token
                    logger.info(f"♻️ Reusing existing Bearer token for client: {client_id}, user: {azure_object_id}")
                    existing_expiry_str = existing_token[1]
                    try:
                        existing_expiry_dt = parse_iso_to_utc(existing_expiry_str)
                        expires_in = max(int((existing_expiry_dt - utc_now()).total_seconds()), 0)
                    except Exception:
                        logger.warning("⚠️ Failed to parse existing Bearer expiry. Returning 0 seconds remaining.")
                        expires_in = 0
                else:
                    # Generate new tokens
                    access_token = secrets.token_urlsafe(32)
                    refresh_token = secrets.token_urlsafe(32)
                    token_expiry = utc_now() + timedelta(seconds=dcr_expires_in)
                    expires_in = dcr_expires_in

                    # Store new access token (암호화 - 보안)
                    encrypted_access_token = dcr_service.crypto.account_encrypt_sensitive_data(access_token)
                    dcr_service._execute_query(
                        """
                        INSERT INTO dcr_tokens (
                            dcr_token_value, dcr_client_id, dcr_token_type, azure_object_id, expires_at, dcr_status
                        ) VALUES (?, ?, 'Bearer', ?, ?, 'active')
                        """,
                        (
                            encrypted_access_token,  # 암호화된 토큰 저장
                            client_id,
                            azure_object_id,
                            token_expiry,
                        ),
                    )
                    logger.info(f"✨ Created new Bearer token (encrypted) for client: {client_id}, user: {azure_object_id}")

                # Delete existing refresh token for this client + object_id + token_type (prevent duplicates)
                dcr_service._execute_query(
                    """
                    DELETE FROM dcr_tokens
                    WHERE dcr_client_id = ? AND azure_object_id = ? AND dcr_token_type = 'refresh' AND dcr_status = 'active'
                    """,
                    (client_id, azure_object_id),
                )

                # Store refresh token (30 days validity)
                refresh_token_expiry = utc_now() + timedelta(days=30)
                dcr_service._execute_query(
                    """
                    INSERT INTO dcr_tokens (
                        dcr_token_value, dcr_client_id, dcr_token_type, azure_object_id, expires_at, dcr_status
                    ) VALUES (?, ?, 'refresh', ?, ?, 'active')
                    """,
                    (
                        crypto.account_encrypt_sensitive_data(refresh_token),  # Store encrypted for security
                        client_id,
                        azure_object_id,
                        refresh_token_expiry,
                    ),
                )

                logger.info(f"🗑️ Deleted old tokens for client: {client_id}")

                logger.info(f"✅ DCR access & refresh tokens stored for client: {client_id}, linked to object_id: {azure_object_id}")

                return JSONResponse(
                    {
                        "access_token": access_token,
                        "token_type": "Bearer",
                        "expires_in": expires_in,
                        "refresh_token": refresh_token,
                        "scope": auth_data["scope"],
                    },
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Content-Type": "application/json",
                    },
                )

            except Exception as e:
                logger.error(f"❌ OAuth token exchange failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return JSONResponse(
                    {"error": "server_error", "error_description": str(e)},
                    status_code=500,
                )

        # Azure AD Callback endpoint
        async def oauth_azure_callback_handler(request):
            """Azure AD OAuth Callback - 토큰 교환 및 저장"""
            try:
                import urllib.parse

                # Get query parameters
                params = dict(request.query_params)
                azure_code = params.get("code")
                state = params.get("state")
                error = params.get("error")

                if error:
                    logger.error(f"❌ Azure AD error: {error}")
                    return Response(
                        f"""
                        <!DOCTYPE html>
                        <html>
                        <head><title>Authentication Error</title></head>
                        <body>
                            <h1>❌ Authentication Failed</h1>
                            <p>Error: {error}</p>
                            <p>You can close this window.</p>
                        </body>
                        </html>
                        """,
                        media_type="text/html",
                        status_code=400,
                    )

                if not azure_code or not state:
                    return Response(
                        """
                        <!DOCTYPE html>
                        <html>
                        <head><title>Invalid Request</title></head>
                        <body>
                            <h1>❌ Invalid Request</h1>
                            <p>Missing code or state parameter</p>
                        </body>
                        </html>
                        """,
                        media_type="text/html",
                        status_code=400,
                    )

                # Extract internal auth code from state
                if ":" in state:
                    auth_code, original_state = state.split(":", 1)
                else:
                    auth_code = state
                    original_state = None

                # DCR 서비스에서 auth_code 검증 및 클라이언트 정보 조회
                dcr_service = DCRService()

                # auth_code로부터 클라이언트 정보 조회 (V3 스키마)
                query = """
                SELECT dcr_client_id, metadata
                FROM dcr_tokens
                WHERE dcr_token_type = 'authorization_code'
                  AND dcr_token_value = ?
                  AND dcr_status = 'active'
                  AND expires_at > datetime('now')
                """
                result = dcr_service._fetch_one(query, (auth_code,))

                if not result:
                    logger.error(f"❌ Invalid auth_code: {auth_code}")
                    return Response(
                        """
                        <!DOCTYPE html>
                        <html>
                        <head><title>Authentication Error</title></head>
                        <body>
                            <h1>❌ Authentication Failed</h1>
                            <p>Invalid authorization code</p>
                        </body>
                        </html>
                        """,
                        media_type="text/html",
                        status_code=400,
                    )

                client_id, metadata_json = result

                # metadata에서 redirect_uri와 scope 추출
                import json
                metadata = json.loads(metadata_json) if metadata_json else {}
                redirect_uri = metadata.get('redirect_uri', '')
                scope = metadata.get('scope', 'Mail.Read User.Read')

                # 클라이언트 정보로 Azure 토큰 교환
                client = dcr_service.get_client(client_id)
                if not client:
                    logger.error(f"❌ Client not found: {client_id}")
                    return Response(
                        """
                        <!DOCTYPE html>
                        <html>
                        <head><title>Authentication Error</title></head>
                        <body>
                            <h1>❌ Authentication Failed</h1>
                            <p>Client not found</p>
                        </body>
                        </html>
                        """,
                        media_type="text/html",
                        status_code=400,
                    )

                # Azure AD에서 토큰 교환
                import httpx
                async with httpx.AsyncClient() as http_client:
                    token_url = f"https://login.microsoftonline.com/{client['azure_tenant_id']}/oauth2/v2.0/token"
                    azure_redirect = client.get("azure_redirect_uri")
                    token_data = {
                        "client_id": client["azure_application_id"],
                        "client_secret": client["azure_client_secret"],
                        "code": azure_code,
                        "redirect_uri": azure_redirect,
                        "grant_type": "authorization_code",
                        "scope": scope or os.getenv("DCR_OAUTH_SCOPE", "offline_access User.Read Mail.ReadWrite")
                    }

                    logger.info(f"🔄 Exchanging Azure token with redirect_uri: {azure_redirect}")

                    response = await http_client.post(token_url, data=token_data)
                    if response.status_code != 200:
                        error_details = response.text
                        logger.error(
                            f"❌ AZURE_TOKEN_EXCHANGE_FAILED:\n"
                            f"  Status: {response.status_code}\n"
                            f"  Redirect URI used: {azure_redirect}\n"
                            f"  Request URL: {request.url}\n"
                            f"  Error: {error_details}\n"
                            f"  Hint: Check if redirect_uri matches Azure Portal configuration"
                        )

                        # Check if it's a redirect_uri mismatch error
                        error_hint = ""
                        if "redirect_uri" in error_details.lower() or "AADSTS50011" in error_details:
                            error_hint = "<p><strong>⚠️ Redirect URI Mismatch:</strong> The redirect_uri does not match Azure Portal configuration.</p>"

                        return Response(
                            f"""
                            <!DOCTYPE html>
                            <html>
                            <head><title>Authentication Error</title></head>
                            <body>
                                <h1>❌ Authentication Failed</h1>
                                <p>Failed to exchange Azure token</p>
                                {error_hint}
                                <details>
                                    <summary>Error Details</summary>
                                    <pre>Status: {response.status_code}
Redirect URI: {azure_redirect}
Error: {error_details}</pre>
                                </details>
                            </body>
                            </html>
                            """,
                            media_type="text/html",
                            status_code=400,
                        )

                    azure_token_data = response.json()
                    logger.info(f"✅ Got Azure token, expires_in: {azure_token_data.get('expires_in')}")

                    # 사용자 정보 가져오기 (Microsoft Graph API)
                    user_info_response = await http_client.get(
                        "https://graph.microsoft.com/v1.0/me",
                        headers={"Authorization": f"Bearer {azure_token_data.get('access_token')}"}
                    )

                    # 사용자 정보 추출
                    user_email = "unknown"
                    user_name = None
                    principal_id = None

                    if user_info_response.status_code == 200:
                        user_info = user_info_response.json()
                        user_email = user_info.get("mail") or user_info.get("userPrincipalName", "")
                        user_name = user_info.get("displayName")
                        azure_object_id = user_info.get("id")  # Azure AD User Object ID
                        logger.info(f"🔍 User login: {user_email} (name: {user_name}, object_id: {azure_object_id})")

                        # 사용자 허용 여부 확인
                        if not dcr_service.is_user_allowed(user_email):
                            logger.warning(f"❌ User {user_email} is not in allowed users list")
                            return Response(
                                f"""
                                <!DOCTYPE html>
                                <html>
                                <head><title>Access Denied</title></head>
                                <body>
                                    <h1>❌ Access Denied</h1>
                                    <p>User <b>{user_email}</b> is not authorized to access this service.</p>
                                    <p>Please contact your administrator for access.</p>
                                </body>
                                </html>
                                """,
                                media_type="text/html",
                                status_code=403,
                            )
                    else:
                        logger.warning("⚠️ Could not fetch user info from Microsoft Graph")

                # Azure 토큰 저장 및 accounts 동기화 (중앙 처리)
                logger.info(f"💾 Saving Azure token and syncing accounts for client: {client_id}")

                # 토큰 만료 시간 계산
                from datetime import timedelta
                expires_in = azure_token_data.get("expires_in", 3600)
                azure_expiry = utc_now() + timedelta(seconds=expires_in)

                enable_account_sync = os.getenv("ENABLE_DCR_ACCOUNT_SYNC", "true").lower() == "true"
                dcr_service.save_azure_tokens_and_sync(
                    azure_object_id=azure_object_id,
                    azure_access_token=azure_token_data.get("access_token"),
                    azure_refresh_token=azure_token_data.get("refresh_token") or None,
                    scope=scope,
                    user_email=user_email,
                    user_name=user_name,
                    azure_expires_at=azure_expiry,
                    sync_accounts=enable_account_sync,
                )
                if enable_account_sync:
                    logger.info(f"✅ Azure token saved and accounts synced for object_id: {azure_object_id}")
                else:
                    logger.info(f"✅ Azure token saved (account sync disabled) for object_id: {azure_object_id}")

                # authorization code에 azure_object_id 업데이트 (토큰 교환 시 사용)
                if azure_object_id:
                    update_auth_code_query = """
                    UPDATE dcr_tokens
                    SET azure_object_id = ?
                    WHERE dcr_token_value = ? AND dcr_token_type = 'authorization_code'
                    """
                    dcr_service._execute_query(update_auth_code_query, (azure_object_id, auth_code))
                    logger.info(f"✅ Authorization code updated with object_id: {azure_object_id}")

                    # 클라이언트에 사용자 정보 연결 (중요!)
                    # redirect_uri 추출 (metadata에서 가져오기)
                    final_client_id = dcr_service.update_client_user(
                        dcr_client_id=client_id,
                        azure_object_id=azure_object_id,
                        user_email=user_email,
                        redirect_uri=redirect_uri
                    )

                    # 만약 기존 클라이언트로 교체되었다면, auth_code의 client_id도 업데이트
                    if final_client_id != client_id:
                        update_auth_code_client_query = """
                        UPDATE dcr_tokens
                        SET dcr_client_id = ?
                        WHERE dcr_token_value = ? AND dcr_token_type = 'authorization_code'
                        """
                        dcr_service._execute_query(update_auth_code_client_query, (final_client_id, auth_code))
                        logger.info(f"✅ Authorization code updated to use existing client: {final_client_id}")

                # Claude로 리다이렉트 (원본 auth_code와 state 포함)
                redirect_params = {
                    "code": auth_code,
                }
                if original_state:
                    redirect_params["state"] = original_state

                redirect_url = f"{redirect_uri}?{urllib.parse.urlencode(redirect_params)}"

                from starlette.responses import RedirectResponse
                return RedirectResponse(url=redirect_url)

            except Exception as e:
                logger.error(f"❌ Azure callback failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return Response(
                    f"""
                    <!DOCTYPE html>
                    <html>
                    <head><title>Authentication Error</title></head>
                    <body>
                        <h1>❌ Authentication Failed</h1>
                        <p>Error: {str(e)}</p>
                    </body>
                    </html>
                    """,
                    media_type="text/html",
                    status_code=500,
                )

        # Root does NOT expose OpenAI endpoints
        # Each MCP server exposes its own /v1/chat/completions and /v1/models at their subpath

        # Create routes
        routes = [
            # Unified endpoints
            Route("/health", endpoint=unified_health, methods=["GET"]),
            Route("/info", endpoint=unified_info, methods=["GET"]),
            Route("/", endpoint=root_handler, methods=["GET", "HEAD"]),
            Route("/", endpoint=options_handler, methods=["OPTIONS"]),
            # DCR OAuth endpoints (at root for Claude Connector compatibility)
            Route("/.well-known/oauth-authorization-server", endpoint=oauth_metadata_handler, methods=["GET"]),
            Route("/.well-known/oauth-protected-resource", endpoint=oauth_protected_resource_handler, methods=["GET"]),
            Route("/.well-known/mcp.json", endpoint=unified_mcp_discovery_handler, methods=["GET"]),  # Unified MCP Discovery
            Route("/oauth/register", endpoint=dcr_register_handler, methods=["POST"]),
            Route("/oauth/authorize", endpoint=oauth_authorize_handler, methods=["GET"]),
            Route("/oauth/token", endpoint=oauth_token_handler, methods=["POST"]),
            Route("/oauth/azure_callback", endpoint=oauth_azure_callback_handler, methods=["GET"]),
            Route("/auth/callback", endpoint=oauth_azure_callback_handler, methods=["GET"]),  # Azure AD redirect (alternative path)
            # OAuth callback (enrollment service)
            Route("/enrollment/callback", endpoint=auth_callback_handler, methods=["GET"]),
            # MCP Discovery endpoints (before Mount to take precedence)
            Route("/enrollment/.well-known/mcp.json", endpoint=enrollment_mcp_discovery_handler, methods=["GET"]),
            Route("/mail-query/.well-known/mcp.json", endpoint=mail_query_mcp_discovery_handler, methods=["GET"]),
            Route("/onenote/.well-known/mcp.json", endpoint=onenote_mcp_discovery_handler, methods=["GET"]),
            Route("/onedrive/.well-known/mcp.json", endpoint=onedrive_mcp_discovery_handler, methods=["GET"]),
            Route("/teams/.well-known/mcp.json", endpoint=teams_mcp_discovery_handler, methods=["GET"]),
            # Mount MCP servers on specific paths (trailing slash needed to avoid redirects)
            Mount("/mail-query/", app=self.mail_query_server.app),
            Mount("/enrollment/", app=self.enrollment_server.app),
            Mount("/onenote/", app=self.onenote_server.app),
            Mount("/onedrive/", app=self.onedrive_server.app),
            Mount("/teams/", app=self.teams_server.app),
        ]

        # Create Starlette app
        app = Starlette(routes=routes)

        # OAuth 인증 미들웨어 적용 (환경변수로 제어)
        enable_oauth = os.getenv("ENABLE_OAUTH_AUTH", "false").lower() == "true"

        # 모든 요청 헤더 로깅 미들웨어 (디버깅용)
        from starlette.middleware.base import BaseHTTPMiddleware

        class HeaderLoggingMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                # Claude.ai에서 오는 요청만 로깅 (user-agent 체크)
                user_agent = request.headers.get("user-agent", "")
                if "Claude" in user_agent or "python-httpx" in user_agent:
                    logger.info(f"🌐 [{request.method}] {request.url.path} - Headers: {dict(request.headers)}")
                return await call_next(request)

        app.add_middleware(HeaderLoggingMiddleware)

        logger.info("=" * 80)
        if enable_oauth:
            from modules.dcr_oauth.auth_middleware import verify_bearer_token_middleware

            class OAuth2Middleware(BaseHTTPMiddleware):
                async def dispatch(self, request, call_next):
                    # 인증 검증
                    auth_response = await verify_bearer_token_middleware(request)
                    if auth_response:  # 인증 실패 시 에러 응답 반환
                        return auth_response
                    # 인증 성공 시 다음 핸들러로 진행
                    return await call_next(request)

            app.add_middleware(OAuth2Middleware)
            logger.info("🔐 OAuth 인증 미들웨어: 활성화됨 (ENABLE_OAUTH_AUTH=true)")
            logger.info("   → 모든 MCP 요청에 Bearer 토큰 필요")
            logger.info("   → 제외 경로: /oauth/, /health, /info, /.well-known/")
        else:
            logger.warning("⚠️  OAuth 인증 미들웨어: 비활성화됨 (ENABLE_OAUTH_AUTH=false)")
            logger.warning("   → 각 MCP 서버가 자체 인증 방식 사용")
            logger.warning("   → Enrollment: Mcp-Session-Id 기반 인증")
            logger.warning("   → Mail-Query/OneNote/OneDrive/Teams: 자체 토큰 인증")
        logger.info("=" * 80)

        return app

    def run(self):
        """Run the unified HTTP server"""
        logger.info("=" * 80)
        logger.info(f"🚀 Starting Unified MCP Server on http://{self.host}:{self.port}")
        logger.info("=" * 80)
        logger.info(f"📧 Mail Query MCP: http://{self.host}:{self.port}/mail-query/")
        logger.info(f"🔐 Enrollment MCP: http://{self.host}:{self.port}/enrollment/")
        logger.info(f"📝 OneNote MCP: http://{self.host}:{self.port}/onenote/")
        logger.info(f"📁 OneDrive MCP: http://{self.host}:{self.port}/onedrive/")
        logger.info(f"👥 Teams MCP: http://{self.host}:{self.port}/teams/")
        logger.info("-" * 80)
        logger.info(f"💚 Health check: http://{self.host}:{self.port}/health")
        logger.info(f"ℹ️  Server info: http://{self.host}:{self.port}/info")
        logger.info("=" * 80)

        # Run uvicorn
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")


def main():
    """Main entry point for unified HTTP MCP server"""
    parser = argparse.ArgumentParser(description="Unified MCP HTTP Server")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT") or os.getenv("PORT") or "8000"),
        help="Port for HTTP server (default: 8000, or MCP_PORT/PORT env var)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST") or "0.0.0.0",
        help="Host for HTTP server (default: 0.0.0.0, or MCP_HOST env var)",
    )

    args = parser.parse_args()

    logger.info("🚀 Starting Unified MCP HTTP Server")
    logger.info(f"📁 Project root: {PROJECT_ROOT}")
    logger.info(f"🌐 Server will listen on {args.host}:{args.port}")

    # Create and run unified server
    server = UnifiedMCPServer(host=args.host, port=args.port)
    server.run()


if __name__ == "__main__":
    main()
