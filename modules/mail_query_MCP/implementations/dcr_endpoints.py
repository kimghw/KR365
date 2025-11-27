"""DCR OAuth Endpoints for FastAPI Server

This module contains all DCR (Dynamic Client Registration) OAuth endpoints
that can be added to the FastAPI server.
"""

from fastapi import Request, Form, Response
from fastapi.responses import JSONResponse, HTMLResponse
from modules.dcr_oauth_module import DCRService
from infra.core.logger import get_logger
import json
import secrets
from pathlib import Path
from urllib.parse import urlencode

logger = get_logger(__name__)


def _get_module_name_from_config() -> str:
    """config.json에서 DCR OAuth module_name을 읽어옴"""
    config_path = Path(__file__).parent.parent / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
                return config.get("dcr_oauth", {}).get("module_name", "mail_query")
        except Exception as e:
            logger.warning(f"config.json 읽기 실패: {e}")
    return "mail_query"


def add_dcr_endpoints(app):
    """Add DCR OAuth endpoints to FastAPI app"""

    # 모듈 이름을 한 번만 로드
    MODULE_NAME = _get_module_name_from_config()
    logger.info(f"📋 DCR endpoints using module_name: {MODULE_NAME}")

    # DCR Registration endpoint
    @app.post("/oauth/register", tags=["OAuth/DCR"])
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
    @app.get("/oauth/clients/{client_id}", tags=["OAuth/DCR"])
    @app.delete("/oauth/clients/{client_id}", tags=["OAuth/DCR"])
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
    @app.get("/oauth/authorize", tags=["OAuth/DCR"])
    async def oauth_authorize(
        client_id: str,
        redirect_uri: str,
        response_type: str = "code",
        scope: str = "Mail.Read User.Read",
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

        # Azure AD authorization URL - Get Azure config from DCR service
        # DCRService loads Azure config during init, accessible via properties
        try:
            azure_tenant_id = dcr_service.azure_tenant_id
            azure_client_id = dcr_service.azure_application_id
        except AttributeError:
            return JSONResponse(
                {"error": "server_error", "error_description": "Azure configuration not available"},
                status_code=500
            )

        # Map to Azure AD redirect URI (our callback)
        # Use localhost:8001 to match Azure AD app registration
        azure_redirect_uri = "http://localhost:8001/oauth/azure_callback"

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
            }
        )

    # Azure callback endpoint
    @app.get("/oauth/azure_callback", tags=["OAuth/DCR"])
    async def oauth_azure_callback(
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
            azure_redirect_uri = "http://localhost:8001/oauth/azure_callback"

            # Exchange Azure code for access token
            token_info = await oauth_client.exchange_code_for_tokens_with_account_config(
                authorization_code=code,
                client_id=dcr_service.azure_application_id,
                client_secret=dcr_service.azure_client_secret,
                tenant_id=dcr_service.azure_tenant_id,
                redirect_uri=azure_redirect_uri,
            )

            # Store token information in metadata for later use
            metadata_dict["azure_tokens"] = {
                "access_token": token_info.get("access_token"),
                "refresh_token": token_info.get("refresh_token"),
                "expires_in": token_info.get("expires_in"),
                "scope": token_info.get("scope"),
            }
            # Store user info for later use (will be needed in /oauth/token)
            metadata_dict["azure_user_info"] = {
                "object_id": None,  # Will be set after fetching user info
                "email": None,
                "display_name": None
            }
            logger.info(f"✅ Stored Azure tokens in metadata for auth code {state[:10]}...")

            # Fetch user info from Microsoft Graph API with retry logic
            max_retries = 3
            retry_delay = 1  # seconds
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

                            # 필수 사용자 정보 검증
                            if not azure_object_id or not user_email:
                                logger.error(f"❌ Missing critical user info: object_id={azure_object_id}, email={user_email}")
                                return JSONResponse(
                                    {
                                        "error": "user_info_incomplete",
                                        "error_description": "Required user information (object_id or email) is missing from Microsoft Graph API response"
                                    },
                                    status_code=500
                                )

                            # Store user info in metadata
                            metadata_dict["azure_user_info"] = {
                                "object_id": azure_object_id,
                                "email": user_email,
                                "display_name": display_name
                            }

                            # Update authorization code (no need to set azure_object_id in tokens table)
                            dcr_service.update_auth_code_with_object_id(state, azure_object_id, user_email, display_name)
                            logger.info(f"✅ Updated auth code {state[:10]}... with user: {user_email} (object_id: {azure_object_id})")
                            break  # Success, exit retry loop

                        # Retry on rate limit or server errors
                        elif response.status_code in [429, 500, 502, 503, 504]:
                            last_error = f"HTTP {response.status_code} - {response.text}"
                            logger.warning(f"⚠️ Graph API request failed (attempt {attempt + 1}/{max_retries}): {last_error}")

                            if attempt < max_retries - 1:
                                import asyncio
                                # Exponential backoff
                                await asyncio.sleep(retry_delay * (2 ** attempt))
                                continue
                            else:
                                # Final attempt failed
                                logger.error(f"❌ Graph API request failed after {max_retries} attempts: {last_error}")
                                return JSONResponse(
                                    {
                                        "error": "graph_api_error",
                                        "error_description": f"Failed to fetch user info after {max_retries} retries: {last_error}"
                                    },
                                    status_code=500
                                )
                        else:
                            # Non-retryable error (e.g., 401, 403)
                            logger.error(f"❌ Graph API request failed: {response.status_code} - {response.text}")
                            return JSONResponse(
                                {
                                    "error": "graph_api_error",
                                    "error_description": f"Failed to fetch user info from Microsoft Graph API: HTTP {response.status_code}"
                                },
                                status_code=500
                            )

                except httpx.TimeoutException as te:
                    last_error = f"Timeout: {str(te)}"
                    logger.warning(f"⚠️ Graph API timeout (attempt {attempt + 1}/{max_retries}): {last_error}")
                    if attempt < max_retries - 1:
                        import asyncio
                        await asyncio.sleep(retry_delay * (2 ** attempt))
                        continue
                    else:
                        logger.error(f"❌ Graph API timeout after {max_retries} attempts")
                        return JSONResponse(
                            {
                                "error": "graph_api_timeout",
                                "error_description": f"Graph API request timed out after {max_retries} attempts"
                            },
                            status_code=504
                        )

                except httpx.RequestError as re:
                    last_error = f"Request error: {str(re)}"
                    logger.warning(f"⚠️ Graph API request error (attempt {attempt + 1}/{max_retries}): {last_error}")
                    if attempt < max_retries - 1:
                        import asyncio
                        await asyncio.sleep(retry_delay * (2 ** attempt))
                        continue
                    else:
                        logger.error(f"❌ Graph API request error after {max_retries} attempts")
                        return JSONResponse(
                            {
                                "error": "graph_api_request_error",
                                "error_description": f"Network error after {max_retries} attempts: {last_error}"
                            },
                            status_code=502
                        )

        except Exception as e:
            logger.error(f"❌ Failed to extract user info: {str(e)}")
            return JSONResponse(
                {
                    "error": "user_info_fetch_error",
                    "error_description": f"Exception while fetching user info: {str(e)}"
                },
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
            }
        )

    # OAuth Token endpoint
    @app.post("/oauth/token", tags=["OAuth/DCR"])
    async def oauth_token(
        grant_type: str = Form(...),
        client_id: str = Form(...),
        client_secret: str = Form(...),
        code: str = Form(None),
        redirect_uri: str = Form(None),
        code_verifier: str = Form(None),  # PKCE support
        refresh_token: str = Form(None),
        request: Request = None
    ):
        """OAuth Token Endpoint - RFC 6749 compliant"""
        from infra.core.oauth_client import get_oauth_client
        from datetime import datetime

        dcr_service = DCRService(module_name=MODULE_NAME)

        # Verify client credentials
        if not dcr_service.verify_client_credentials(client_id, client_secret):
            return JSONResponse(
                {"error": "invalid_client"},
                status_code=401
            )

        # Authorization code grant
        if grant_type == "authorization_code":
            if not all([code, redirect_uri]):
                return JSONResponse(
                    {"error": "invalid_request"},
                    status_code=400
                )

            # Verify authorization code (with PKCE support)
            code_data = dcr_service.verify_authorization_code(
                code, client_id, redirect_uri, code_verifier
            )
            if not code_data:
                return JSONResponse(
                    {"error": "invalid_grant"},
                    status_code=400
                )

            # Get Azure auth code
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
                    {"error": "invalid_grant", "error_description": "Azure tokens not found in metadata"},
                    status_code=400
                )

            # Use tokens from metadata (already exchanged in azure_callback)
            from datetime import datetime, timedelta, timezone
            token_info = {
                "access_token": azure_tokens["access_token"],
                "refresh_token": azure_tokens.get("refresh_token"),
                "scope": azure_tokens.get("scope"),
                "expiry": (datetime.now(timezone.utc) + timedelta(seconds=azure_tokens.get("expires_in", 3600))).isoformat()
            }
            logger.info(f"✅ Using Azure tokens from metadata (already exchanged in azure_callback)")

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
                    {"error": "invalid_grant", "error_description": "User not authenticated - azure_object_id not found in metadata"},
                    status_code=400
                )

            # Store token mapping
            azure_expiry = datetime.fromisoformat(token_info["expiry"])

            # Store tokens (user_email and user_name already set from metadata above)
            dcr_service.store_tokens(
                dcr_client_id=client_id,
                dcr_access_token=access_token,
                dcr_refresh_token=new_refresh_token,
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

            return JSONResponse(
                {
                    "access_token": access_token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
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

            # Get Azure config from DCR service properties

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

            # Generate new DCR tokens
            new_access_token = secrets.token_urlsafe(32)
            new_refresh_token = secrets.token_urlsafe(32)

            # Parse Azure token expiry
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
                }
            )

        else:
            return JSONResponse(
                {"error": "unsupported_grant_type", "error_description": f"Grant type '{grant_type}' is not supported"},
                status_code=400
            )

    # OAuth Discovery endpoints
    @app.get("/.well-known/oauth-authorization-server", tags=["OAuth/DCR"])
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
            "scopes_supported": ["Mail.Read", "Mail.ReadWrite", "User.Read"],
            "code_challenge_methods_supported": ["S256"],
        })

    logger.info("✅ DCR OAuth endpoints added to FastAPI app")