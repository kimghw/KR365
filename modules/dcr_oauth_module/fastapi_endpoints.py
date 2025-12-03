"""Common DCR OAuth FastAPI Endpoints
This module provides reusable DCR OAuth endpoints that can be added to any FastAPI application.
"""

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from typing import Optional

from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import JSONResponse, HTMLResponse
from modules.dcr_oauth_module import DCRService
from infra.core.logger import get_logger

logger = get_logger(__name__)


def create_dcr_router(db_service, server_type: str = "mail_query") -> APIRouter:
    """
    Create a FastAPI router with DCR OAuth endpoints

    Args:
        db_service: Database service instance (TeamsDBService, OneNoteDBService, or OutlookDBService)
        server_type: Type of server ("teams", "onenote", "outlook", "mail_query")

    Returns:
        APIRouter with DCR OAuth endpoints configured
    """

    router = APIRouter(prefix="/oauth", tags=["OAuth/DCR"])

    # Get module name from config or use server_type
    MODULE_NAME = server_type
    logger.info(f"📋 Creating DCR router for module: {MODULE_NAME}")

    # DCR Registration endpoint
    @router.post("/register")
    async def dcr_register(request: Request):
        """RFC 7591: Dynamic Client Registration"""
        try:
            body = await request.body()
            request_data = json.loads(body) if body else {}

            dcr_service = DCRService(module_name=MODULE_NAME)
            response = await dcr_service.register_client(request_data)

            logger.info(f"✅ DCR client registered: {response['client_id']}")

            return JSONResponse(
                response,
                status_code=201,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                    "Cache-Control": "no-store",
                }
            )

        except Exception as e:
            logger.error(f"❌ DCR registration failed: {str(e)}")
            return JSONResponse(
                {"error": "invalid_client_metadata", "error_description": str(e)},
                status_code=400
            )

    # DCR Client endpoint
    @router.get("/clients/{client_id}")
    @router.delete("/clients/{client_id}")
    async def dcr_client_handler(client_id: str, request: Request):
        """RFC 7591: Client Configuration Endpoint"""
        dcr_service = DCRService(module_name=MODULE_NAME)

        if request.method == "GET":
            client = dcr_service.get_client(client_id)
            if not client:
                return JSONResponse(
                    {"error": "invalid_client_id"},
                    status_code=404
                )
            return JSONResponse(client)

        elif request.method == "DELETE":
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    {"error": "invalid_token"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"}
                )

            registration_token = auth_header[7:]
            success = await dcr_service.delete_client(client_id, registration_token)

            if not success:
                return JSONResponse(
                    {"error": "invalid_token"},
                    status_code=401
                )

            return Response(status_code=204)

    # OAuth Authorization endpoint
    @router.get("/authorize")
    async def oauth_authorize(
        client_id: str,
        redirect_uri: str,
        response_type: str = "code",
        scope: str = None,
        state: str = None,
        code_challenge: str = None,  # PKCE support
        code_challenge_method: str = "S256",  # PKCE support
        request: Request = None
    ):
        """OAuth Authorization Endpoint - Azure AD proxy with PKCE support"""
        if not client_id or not redirect_uri:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "Missing required parameters"},
                status_code=400
            )

        dcr_service = DCRService(module_name=MODULE_NAME)
        client = dcr_service.get_client(client_id)

        if not client:
            return JSONResponse(
                {"error": "invalid_client"},
                status_code=401
            )

        # Set default scope based on server type if not provided
        if not scope:
            # Use DCR_OAUTH_SCOPE from environment if available
            env_scope = os.getenv("DCR_OAUTH_SCOPE")
            if env_scope:
                scope = env_scope
                logger.info(f"📋 Using scope from DCR_OAUTH_SCOPE: {scope}")
            else:
                # Fallback to hardcoded defaults only if env var not set
                default_scopes = {
                    "teams": "Chat.Read Chat.ReadWrite User.Read",
                    "onenote": "Notes.Read Notes.ReadWrite User.Read",
                    "outlook": "Mail.Read Mail.ReadWrite User.Read",
                    "mail_query": "Mail.Read Mail.ReadWrite User.Read",
                }
                scope = default_scopes.get(server_type, "User.Read")
                logger.info(f"📋 Using default scope for {server_type}: {scope}")

        # Azure AD authorization URL
        try:
            azure_tenant_id = dcr_service.azure_tenant_id
            azure_client_id = dcr_service.azure_application_id
        except AttributeError:
            return JSONResponse(
                {"error": "server_error", "error_description": "Azure configuration not available"},
                status_code=500
            )

        azure_redirect_uri = dcr_service.azure_redirect_uri
        if not azure_redirect_uri:
            logger.error("Azure redirect URI not configured")
            return JSONResponse(
                {"error": "server_error", "error_description": "Azure redirect URI not configured"},
                status_code=500
            )

        # Store original request for callback (with PKCE support)
        auth_code = dcr_service.create_authorization_code(
            dcr_client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )

        # Build Azure AD authorization URL
        azure_scope = f"offline_access {scope}" if "offline_access" not in scope else scope
        logger.info(f"🔐 Azure AD authorization request - Server: {server_type}, Final scope: {azure_scope}")

        azure_params = {
            "client_id": azure_client_id,
            "response_type": "code",
            "redirect_uri": azure_redirect_uri,
            "response_mode": "query",
            "scope": azure_scope,
            "state": auth_code,  # Use our code as state
        }

        azure_auth_url = (
            f"https://login.microsoftonline.com/{azure_tenant_id}/oauth2/v2.0/authorize?"
            f"{urlencode(azure_params)}"
        )

        logger.info(f"🔐 Redirecting to Azure AD for authorization")

        return Response(
            status_code=302,
            headers={
                "Location": azure_auth_url,
                "Access-Control-Allow-Origin": "*",
            }
        )

    # Azure callback endpoint
    @router.get("/callback")
    async def oauth_callback(
        code: str = None,
        state: str = None,  # This is our auth_code
        error: str = None,
        request: Request = None
    ):
        """Azure AD Callback - intermediate processing with user info extraction"""
        if error:
            logger.error(f"❌ Azure AD error: {error}")
            return JSONResponse({"error": error}, status_code=400)

        if not code or not state:
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        dcr_service = DCRService(module_name=MODULE_NAME)

        # Get authorization code metadata
        metadata = dcr_service.db_service.fetch_one(
            f"SELECT metadata FROM {dcr_service._get_table_name('dcr_tokens')} WHERE dcr_token_type = 'authorization_code' AND dcr_token_value = ?",
            (state,)
        )

        if metadata and metadata[0]:
            metadata_dict = json.loads(metadata[0])
        else:
            metadata_dict = {}

        # Store Azure authorization code
        metadata_dict["azure_auth_code"] = code

        # Exchange Azure code for tokens to get user info
        try:
            from infra.core.oauth_client import get_oauth_client
            import httpx

            oauth_client = get_oauth_client()
            azure_redirect_uri = dcr_service.azure_redirect_uri

            # Exchange Azure code for access token
            token_info = await oauth_client.exchange_code_for_tokens_with_account_config(
                authorization_code=code,
                client_id=dcr_service.azure_application_id,
                client_secret=dcr_service.azure_client_secret,
                tenant_id=dcr_service.azure_tenant_id,
                redirect_uri=azure_redirect_uri,
            )

            # Store token information in metadata
            serializable_token_info = {}
            for key, value in token_info.items():
                if isinstance(value, datetime):
                    serializable_token_info[key] = value.isoformat()
                else:
                    serializable_token_info[key] = value
            metadata_dict["azure_tokens"] = serializable_token_info
            metadata_dict["azure_user_info"] = {
                "object_id": None,
                "email": None,
                "display_name": None
            }

            # Fetch user info from Microsoft Graph API
            max_retries = 3
            retry_delay = 1
            last_error = None

            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        headers = {"Authorization": f"Bearer {token_info['access_token']}"}
                        response = await client.get("https://graph.microsoft.com/v1.0/me", headers=headers)

                        if response.status_code == 200:
                            user_info = response.json()
                            azure_object_id = user_info.get("id")
                            user_email = user_info.get("mail") or user_info.get("userPrincipalName")
                            display_name = user_info.get("displayName")

                            if not azure_object_id or not user_email:
                                logger.error(f"❌ Missing critical user info")
                                return JSONResponse(
                                    {
                                        "error": "user_info_incomplete",
                                        "error_description": "Required user information is missing"
                                    },
                                    status_code=500
                                )

                            # Store user info in metadata
                            metadata_dict["azure_user_info"] = {
                                "object_id": azure_object_id,
                                "email": user_email,
                                "display_name": display_name
                            }

                            # Update authorization code
                            dcr_service.update_auth_code_with_object_id(state, azure_object_id, user_email, display_name)
                            logger.info(f"✅ Updated auth code with user: {user_email}")

                            # Save account to database with tokens
                            token_expiry = datetime.now(timezone.utc) + timedelta(seconds=token_info.get("expires_in", 3600))

                            # Get Azure app info from DCR service
                            oauth_client_id = dcr_service.azure_application_id
                            oauth_tenant_id = dcr_service.azure_tenant_id
                            oauth_redirect_uri = dcr_service.azure_redirect_uri
                            oauth_client_secret = dcr_service.azure_client_secret

                            # Get scopes/permissions from token
                            scopes = token_info.get("scope", "").split() if token_info.get("scope") else []
                            delegated_permissions = " ".join(scopes) if scopes else None

                            # Determine default permissions based on server type
                            if not delegated_permissions:
                                default_permissions = {
                                    "teams": "Chat.Read Chat.ReadWrite User.Read",
                                    "onenote": "Notes.Read Notes.ReadWrite User.Read",
                                    "outlook": "Mail.Read Mail.ReadWrite User.Read",
                                    "mail_query": "Mail.Read Mail.ReadWrite User.Read",
                                }
                                delegated_permissions = default_permissions.get(server_type, "User.Read")

                            # Extract user_id from email (part before @)
                            user_id = user_email.split('@')[0] if '@' in user_email else user_email

                            # Update account with complete information
                            db_service.execute_query("""
                                INSERT INTO accounts (
                                    user_id, user_name, email,
                                    oauth_client_id, oauth_client_secret, oauth_tenant_id, oauth_redirect_uri,
                                    delegated_permissions, auth_type, status,
                                    access_token, refresh_token, token_expiry,
                                    is_active, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                                ON CONFLICT(user_id) DO UPDATE SET
                                    user_name = COALESCE(excluded.user_name, user_name),
                                    email = COALESCE(excluded.email, email),
                                    oauth_client_id = COALESCE(excluded.oauth_client_id, oauth_client_id),
                                    oauth_client_secret = COALESCE(excluded.oauth_client_secret, oauth_client_secret),
                                    oauth_tenant_id = COALESCE(excluded.oauth_tenant_id, oauth_tenant_id),
                                    oauth_redirect_uri = COALESCE(excluded.oauth_redirect_uri, oauth_redirect_uri),
                                    delegated_permissions = COALESCE(excluded.delegated_permissions, delegated_permissions),
                                    auth_type = 'DCR OAuth',
                                    status = 'active',
                                    access_token = excluded.access_token,
                                    refresh_token = excluded.refresh_token,
                                    token_expiry = excluded.token_expiry,
                                    is_active = TRUE,
                                    updated_at = datetime('now')
                            """, (
                                user_id,
                                display_name or user_email,
                                user_email,
                                oauth_client_id,
                                oauth_client_secret,
                                oauth_tenant_id,
                                oauth_redirect_uri,
                                delegated_permissions,
                                'DCR OAuth',
                                'active',
                                token_info["access_token"],
                                token_info.get("refresh_token"),
                                token_expiry.isoformat(),
                                True
                            ))

                            logger.info(f"✅ Updated account in {server_type} database: {user_email}")
                            break  # Success, exit retry loop

                        elif response.status_code in [429, 500, 502, 503, 504]:
                            last_error = f"HTTP {response.status_code}"
                            if attempt < max_retries - 1:
                                import asyncio
                                await asyncio.sleep(retry_delay * (2 ** attempt))
                                continue
                            else:
                                return JSONResponse(
                                    {"error": "graph_api_error", "error_description": last_error},
                                    status_code=500
                                )
                        else:
                            return JSONResponse(
                                {"error": "graph_api_error", "error_description": f"HTTP {response.status_code}"},
                                status_code=500
                            )

                except Exception as e:
                    if attempt < max_retries - 1:
                        import asyncio
                        await asyncio.sleep(retry_delay * (2 ** attempt))
                        continue
                    else:
                        return JSONResponse(
                            {"error": "graph_api_error", "error_description": str(e)},
                            status_code=500
                        )

        except Exception as e:
            logger.error(f"❌ Failed to extract user info: {str(e)}")
            return JSONResponse(
                {"error": "user_info_fetch_error", "error_description": str(e)},
                status_code=500
            )

        # Update metadata with Azure code
        dcr_service.db_service.execute_query(
            f"UPDATE {dcr_service._get_table_name('dcr_tokens')} SET metadata = ? WHERE dcr_token_type = 'authorization_code' AND dcr_token_value = ?",
            (json.dumps(metadata_dict), state)
        )

        # Redirect to client with our authorization code
        client_redirect_uri = metadata_dict.get("redirect_uri", "")
        client_state = metadata_dict.get("state")

        params = {"code": state}
        if client_state:
            params["state"] = client_state

        redirect_url = f"{client_redirect_uri}?{urlencode(params)}"
        logger.info(f"✅ Redirecting back to client: {redirect_url}")

        return Response(
            status_code=302,
            headers={
                "Location": redirect_url,
                "Access-Control-Allow-Origin": "*",
            }
        )

    # OAuth Token endpoint
    @router.post("/token")
    async def oauth_token(
        grant_type: str = Form(...),
        client_id: str = Form(...),
        client_secret: str = Form(...),
        code: str = Form(None),
        redirect_uri: str = Form(None),
        code_verifier: str = Form(None),  # PKCE support
        refresh_token: str = Form(None),
        client_name: str = Form(None),  # For auto-registration
        request: Request = None
    ):
        """OAuth Token Endpoint - RFC 6749 compliant with auto-registration"""
        from infra.core.oauth_client import get_oauth_client

        dcr_service = DCRService(module_name=MODULE_NAME)

        logger.info(f"📨 Token request: grant_type={grant_type}, client_id={client_id}")

        # Check if client exists
        client = dcr_service.get_client(client_id)

        if not client:
            # Auto-register client if not exists (only for authorization_code grant)
            if grant_type == "authorization_code" and redirect_uri:
                logger.info(f"🔄 Auto-registering client {client_id}")

                # Use DCR_OAUTH_SCOPE from environment if available
                env_scope = os.getenv("DCR_OAUTH_SCOPE")
                if env_scope:
                    default_scope = env_scope
                else:
                    # Fallback to hardcoded defaults only if env var not set
                    default_scopes = {
                        "teams": "Chat.Read Chat.ReadWrite User.Read",
                        "onenote": "Notes.Read Notes.ReadWrite User.Read",
                        "outlook": "Mail.Read Mail.ReadWrite User.Read",
                        "mail_query": "Mail.Read Mail.ReadWrite User.Read",
                    }
                    default_scope = default_scopes.get(server_type, "User.Read")

                registration_data = {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "client_name": client_name or f"Auto-registered client {client_id}",
                    "redirect_uris": [redirect_uri],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "scope": default_scope
                }

                try:
                    registered_client = await dcr_service.register_client(registration_data)
                    logger.info(f"✅ Auto-registered client: {client_id}")
                except Exception as e:
                    logger.error(f"❌ Auto-registration failed: {str(e)}")
                    return JSONResponse(
                        {"error": "invalid_client", "error_description": str(e)},
                        status_code=401
                    )
            else:
                return JSONResponse(
                    {"error": "invalid_client", "error_description": "Client not found"},
                    status_code=401
                )
        else:
            # Verify client credentials
            if not dcr_service.verify_client_credentials(client_id, client_secret):
                return JSONResponse(
                    {"error": "invalid_client", "error_description": "Invalid client credentials"},
                    status_code=401
                )

        # Authorization code grant
        if grant_type == "authorization_code":
            if not all([code, redirect_uri]):
                return JSONResponse(
                    {"error": "invalid_request", "error_description": "Missing required parameters"},
                    status_code=400
                )

            # Verify authorization code (with PKCE support)
            code_data = dcr_service.verify_authorization_code(
                code, client_id, redirect_uri, code_verifier
            )
            if not code_data:
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "Invalid or expired authorization code"},
                    status_code=400
                )

            # Get Azure tokens from metadata
            auth_code_result = dcr_service.db_service.fetch_one(
                f"SELECT metadata FROM {dcr_service._get_table_name('dcr_tokens')} "
                f"WHERE dcr_token_type = 'authorization_code' AND dcr_token_value = ?",
                (code,)
            )

            if auth_code_result and auth_code_result[0]:
                metadata = json.loads(auth_code_result[0])
                azure_tokens = metadata.get("azure_tokens")
            else:
                azure_tokens = None

            if not azure_tokens or not azure_tokens.get("access_token"):
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "Azure tokens not found"},
                    status_code=400
                )

            # Generate our own tokens
            access_token = secrets.token_urlsafe(32)
            new_refresh_token = secrets.token_urlsafe(32)

            # Get user info from metadata
            user_info_metadata = azure_tokens.get("azure_user_info") if "azure_user_info" in azure_tokens else metadata.get("azure_user_info", {})
            azure_object_id = user_info_metadata.get("object_id")
            user_email = user_info_metadata.get("email")
            user_name = user_info_metadata.get("display_name")

            if not azure_object_id:
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "User not authenticated"},
                    status_code=400
                )

            # Store token mapping
            from datetime import datetime, timedelta, timezone
            token_info = {
                "access_token": azure_tokens["access_token"],
                "refresh_token": azure_tokens.get("refresh_token"),
                "scope": azure_tokens.get("scope"),
                "expiry": (datetime.now(timezone.utc) + timedelta(seconds=azure_tokens.get("expires_in", 3600))).isoformat()
            }
            azure_expiry = datetime.fromisoformat(token_info["expiry"])

            # Store tokens
            dcr_service.store_tokens(
                dcr_client_id=client_id,
                dcr_access_token=access_token,
                dcr_refresh_token=new_refresh_token,
                expires_in=dcr_service.dcr_bearer_ttl_seconds,
                scope=code_data["scope"],
                azure_object_id=azure_object_id,
                azure_access_token=token_info["access_token"],
                azure_refresh_token=token_info.get("refresh_token"),
                azure_expires_at=azure_expiry,
                user_email=user_email,
                user_name=user_name,
            )

            # Extract user_id from email
            token_user_id = user_email.split('@')[0] if '@' in user_email else user_email

            # Update database with new tokens
            db_service.upsert_account(
                user_id=token_user_id,
                access_token=token_info["access_token"],
                refresh_token=token_info.get("refresh_token"),
                token_expiry=azure_expiry,
                scopes=code_data["scope"].split() if code_data.get("scope") else [],
                is_active=True
            )

            logger.info(f"✅ Token issued for DCR client: {client_id}")

            return JSONResponse(
                {
                    "access_token": access_token,
                    "token_type": "Bearer",
                    "expires_in": dcr_service.dcr_bearer_ttl_seconds,
                    "refresh_token": new_refresh_token,
                    "scope": code_data["scope"],
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                }
            )

        # Refresh token grant
        elif grant_type == "refresh_token":
            if not refresh_token:
                return JSONResponse(
                    {"error": "invalid_request", "error_description": "refresh_token is required"},
                    status_code=400
                )

            # Verify DCR refresh token
            refresh_data = dcr_service.verify_refresh_token(refresh_token, client_id)
            if not refresh_data:
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "Invalid or expired refresh token"},
                    status_code=400
                )

            azure_object_id = refresh_data["azure_object_id"]
            scope = refresh_data["scope"]

            # Get Azure tokens
            azure_tokens = dcr_service.get_azure_tokens_by_object_id(azure_object_id)
            if not azure_tokens or not azure_tokens.get("refresh_token"):
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "Azure refresh token not found"},
                    status_code=400
                )

            # Refresh Azure tokens
            oauth_client = get_oauth_client()
            scope_list = scope.split() if scope else None

            new_azure_tokens = await oauth_client.refresh_access_token(
                refresh_token=azure_tokens["refresh_token"],
                client_id=dcr_service.azure_application_id,
                client_secret=dcr_service.azure_client_secret,
                tenant_id=dcr_service.azure_tenant_id,
                scopes=scope_list,
            )

            # Generate new DCR access token only
            new_access_token = secrets.token_urlsafe(32)

            # Parse Azure token expiry
            expiry_value = new_azure_tokens.get("expiry") or new_azure_tokens.get("expiry_time")
            if isinstance(expiry_value, str):
                azure_expiry = datetime.fromisoformat(expiry_value)
            else:
                azure_expiry = expiry_value

            # Store new tokens
            dcr_service.store_tokens(
                dcr_client_id=client_id,
                dcr_access_token=new_access_token,
                dcr_refresh_token=None,  # Keep existing DCR refresh token
                expires_in=dcr_service.dcr_bearer_ttl_seconds,
                scope=scope,
                azure_object_id=azure_object_id,
                azure_access_token=new_azure_tokens["access_token"],
                azure_refresh_token=new_azure_tokens.get("refresh_token", azure_tokens["refresh_token"]),
                azure_expires_at=azure_expiry,
                user_email=azure_tokens.get("user_email"),
                user_name=refresh_data.get("user_name"),
            )

            # Extract user_id from email
            refresh_user_email = azure_tokens.get("user_email") or refresh_data.get("user_email")
            refresh_user_id = refresh_user_email.split('@')[0] if refresh_user_email and '@' in refresh_user_email else refresh_user_email

            # Update database with refreshed tokens
            db_service.upsert_account(
                user_id=refresh_user_id,
                access_token=new_azure_tokens["access_token"],
                refresh_token=new_azure_tokens.get("refresh_token", azure_tokens["refresh_token"]),
                token_expiry=azure_expiry,
                scopes=scope.split() if scope else [],
                is_active=True
            )

            logger.info(f"✅ Token refreshed for DCR client: {client_id}")

            return JSONResponse(
                {
                    "access_token": new_access_token,
                    "token_type": "Bearer",
                    "expires_in": dcr_service.dcr_bearer_ttl_seconds,
                    "refresh_token": refresh_token,
                    "scope": scope,
                },
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                }
            )

        else:
            return JSONResponse(
                {"error": "unsupported_grant_type"},
                status_code=400
            )

    # OAuth Discovery endpoints
    @router.get("/.well-known/oauth-authorization-server")
    async def oauth_authorization_server(request: Request):
        """RFC 8414 OAuth 2.0 Authorization Server Metadata"""
        base_url = f"{request.url.scheme}://{request.url.netloc}"

        return JSONResponse({
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/oauth/authorize",
            "token_endpoint": f"{base_url}/oauth/token",
            "registration_endpoint": f"{base_url}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "scopes_supported": ["Mail.Read", "Mail.ReadWrite", "User.Read", "Notes.Read", "Notes.ReadWrite", "Chat.Read", "Chat.ReadWrite"],
            "code_challenge_methods_supported": ["S256"],
        })

    @router.get("/.well-known/oauth-protected-resource")
    async def oauth_protected_resource(request: Request):
        """RFC 8707 OAuth 2.0 Protected Resource Metadata"""
        base_url = f"{request.url.scheme}://{request.url.netloc}"

        return JSONResponse({
            "resource": base_url,
            "authorization_servers": [base_url],
            "bearer_methods_supported": ["header"],
            "resource_documentation": f"{base_url}/docs",
            "scopes_supported": ["Mail.Read", "Mail.ReadWrite", "User.Read", "Notes.Read", "Notes.ReadWrite", "Chat.Read", "Chat.ReadWrite"],
        })

    logger.info(f"✅ DCR OAuth router created for {server_type}")
    return router


def add_dcr_endpoints(app, db_service, server_type: str = "mail_query"):
    """
    Add DCR OAuth endpoints to an existing FastAPI app

    Args:
        app: FastAPI application instance
        db_service: Database service instance
        server_type: Type of server ("teams", "onenote", "outlook", "mail_query")
    """
    router = create_dcr_router(db_service, server_type)
    app.include_router(router)

    # Also add the .well-known endpoints at root level
    @app.get("/.well-known/oauth-authorization-server", tags=["OAuth/DCR"])
    async def oauth_authorization_server(request: Request):
        base_url = f"{request.url.scheme}://{request.url.netloc}"
        return JSONResponse({
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/oauth/authorize",
            "token_endpoint": f"{base_url}/oauth/token",
            "registration_endpoint": f"{base_url}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "scopes_supported": ["Mail.Read", "Mail.ReadWrite", "User.Read", "Notes.Read", "Notes.ReadWrite", "Chat.Read", "Chat.ReadWrite"],
            "code_challenge_methods_supported": ["S256"],
        })

    @app.get("/.well-known/oauth-protected-resource", tags=["OAuth/DCR"])
    async def oauth_protected_resource(request: Request):
        base_url = f"{request.url.scheme}://{request.url.netloc}"
        return JSONResponse({
            "resource": base_url,
            "authorization_servers": [base_url],
            "bearer_methods_supported": ["header"],
            "resource_documentation": f"{base_url}/docs",
            "scopes_supported": ["Mail.Read", "Mail.ReadWrite", "User.Read", "Notes.Read", "Notes.ReadWrite", "Chat.Read", "Chat.ReadWrite"],
        })

    logger.info(f"✅ DCR OAuth endpoints added to FastAPI app for {server_type}")