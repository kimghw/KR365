"""
DCR OAuth 인증 미들웨어

모든 MCP 서버에서 공통으로 사용하는 Bearer 토큰 검증 미들웨어
"""

from typing import Optional
from starlette.responses import JSONResponse
from modules.dcr_oauth import DCRService
from infra.core.logger import get_logger
from infra.core.logs_db import get_logs_db_service

logger = get_logger(__name__)


def get_user_id_from_azure_object_id(azure_object_id: str) -> Optional[str]:
    """
    Azure Object ID로부터 user_id를 조회합니다.

    조회 경로:
    azure_object_id → dcr_azure_users.user_email → accounts.user_id

    Args:
        azure_object_id: Azure User Object ID

    Returns:
        user_id 또는 None
    """
    try:
        # DCR DB에서 user_email 조회
        from modules.dcr_oauth import DCRService
        dcr_service = DCRService()

        email_result = dcr_service._fetch_one(
            "SELECT user_email FROM dcr_azure_users WHERE object_id = ?",
            (azure_object_id,)
        )

        if not email_result:
            logger.warning(f"⚠️ Azure Object ID에 해당하는 이메일을 찾을 수 없음: {azure_object_id}")
            return None

        user_email = email_result[0]

        # accounts DB에서 user_id 조회
        from infra.core.database import get_database_manager
        accounts_db = get_database_manager()

        user_result = accounts_db.fetch_one(
            "SELECT user_id FROM accounts WHERE email = ? AND is_active = 1",
            (user_email,)
        )

        if not user_result:
            logger.warning(f"⚠️ 이메일에 해당하는 활성 계정을 찾을 수 없음: {user_email}")
            return None

        user_id = user_result[0]
        logger.info(f"✅ Azure Object ID → user_id 매핑 성공: {azure_object_id} → {user_id}")
        return user_id

    except Exception as e:
        logger.error(f"❌ user_id 조회 실패: {str(e)}", exc_info=True)
        return None


async def verify_bearer_token_middleware(request, call_next=None):
    """
    Bearer 토큰 검증 미들웨어

    Returns:
        - None if authentication succeeds (token stored in request.state.azure_token)
        - JSONResponse with 401 if authentication fails
    """
    # 로그 DB 서비스
    logs_db = get_logs_db_service()

    # Skip authentication for certain paths
    path = request.url.path
    method = request.method

    # Get base URL for resource_metadata
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    resource_metadata_url = f"{base_url}/.well-known/oauth-protected-resource"

    # OAuth 엔드포인트와 메타데이터는 인증 제외
    # .well-known은 경로 어디든 포함되면 제외 (MCP discovery 지원)
    if "/.well-known/" in path:
        # 인증 제외 로그 기록
        logs_db.log_dcr_middleware(
            path=path,
            method=method,
            dcr_client_id=None,
            azure_object_id=None,
            user_id=None,
            auth_result="skipped",
            token_valid=False,
            error_message="Discovery endpoint"
        )
        return None  # Skip authentication for discovery endpoints

    # 특정 경로로 시작하면 제외
    excluded_path_prefixes = [
        "/oauth/",
        "/health",
        "/info",
        "/enrollment/callback",  # Enrollment 서비스의 OAuth 콜백
        "/auth/callback",  # DCR OAuth 콜백
        "/dashboard"  # Dashboard uses session-based authentication (dashboard_session cookie)
    ]

    if any(path.startswith(excluded) for excluded in excluded_path_prefixes):
        # 인증 제외 로그 기록
        logs_db.log_dcr_middleware(
            path=path,
            method=method,
            dcr_client_id=None,
            azure_object_id=None,
            user_id=None,
            auth_result="skipped",
            token_valid=False,
            error_message=f"Excluded path: {path}"
        )
        return None  # Skip authentication

    # OPTIONS 요청은 인증 제외
    if request.method == "OPTIONS":
        logs_db.log_dcr_middleware(
            path=path,
            method=method,
            dcr_client_id=None,
            azure_object_id=None,
            user_id=None,
            auth_result="skipped",
            token_valid=False,
            error_message="OPTIONS request"
        )
        return None

    # GET/HEAD 요청은 인증 제외 (MCP Discovery)
    # Claude.ai가 초기에 토큰 없이 서버 정보를 확인함
    if request.method in ["GET", "HEAD"]:
        logs_db.log_dcr_middleware(
            path=path,
            method=method,
            dcr_client_id=None,
            azure_object_id=None,
            user_id=None,
            auth_result="skipped",
            token_valid=False,
            error_message=f"{method} request - discovery"
        )
        return None

    # Get Authorization header
    auth_header = request.headers.get("Authorization", "")

    # Debug: Log all headers for troubleshooting
    logger.info(f"🔍 Request to {path} - Headers: {dict(request.headers)}")

    # Check Bearer token
    if not auth_header.startswith("Bearer "):
        logger.warning(f"⚠️ Missing Bearer token for path: {path}")

        # 인증 실패 로그 기록
        logs_db.log_dcr_middleware(
            path=path,
            method=method,
            dcr_client_id=None,
            azure_object_id=None,
            user_id=None,
            auth_result="failed",
            token_valid=False,
            error_message="Missing Bearer token"
        )

        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32001,
                    "message": "Authentication required"
                },
            },
            status_code=401,
            headers={
                "WWW-Authenticate": f'Bearer resource_metadata="{resource_metadata_url}"',
                "Access-Control-Allow-Origin": "*",
            },
        )

    token = auth_header[7:]  # Remove "Bearer " prefix

    try:
        # Verify token using DCR service
        dcr_service = DCRService()
        token_data = dcr_service.verify_bearer_token(token)

        if token_data:
            # Store DCR client info in request state
            request.state.dcr_client_id = token_data["dcr_client_id"]
            request.state.azure_object_id = token_data["azure_object_id"]

            # Azure Object ID로부터 user_id 조회 및 저장
            user_id = get_user_id_from_azure_object_id(token_data["azure_object_id"])
            if user_id:
                request.state.user_id = user_id
                logger.info(f"✅ Authenticated DCR client: {token_data['dcr_client_id']} (user: {user_id}) for {path}")
            else:
                logger.warning(f"⚠️ DCR 인증 성공했으나 user_id 조회 실패: {token_data['azure_object_id']}")
                request.state.user_id = None

            # 인증 성공 로그 기록
            logs_db.log_dcr_middleware(
                path=path,
                method=method,
                dcr_client_id=token_data["dcr_client_id"],
                azure_object_id=token_data["azure_object_id"],
                user_id=user_id,
                auth_result="success",
                token_valid=True
            )

            return None  # Authentication successful
        else:
            logger.warning(f"⚠️ Invalid Bearer token for path: {path}")

            # 인증 실패 로그 기록
            logs_db.log_dcr_middleware(
                path=path,
                method=method,
                dcr_client_id=None,
                azure_object_id=None,
                user_id=None,
                auth_result="failed",
                token_valid=False,
                error_message="Invalid token"
            )

            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32001,
                        "message": "Invalid or expired authentication token"
                    },
                },
                status_code=401,
                headers={
                    "WWW-Authenticate": f'Bearer error="invalid_token", resource_metadata="{resource_metadata_url}", error_description="Token is expired or invalid. Use refresh_token to obtain a new access token"',
                    "Access-Control-Allow-Origin": "*",
                },
            )
    except Exception as e:
        logger.error(f"❌ Token verification failed: {str(e)}")

        # 인증 실패 로그 기록
        logs_db.log_dcr_middleware(
            path=path,
            method=method,
            dcr_client_id=None,
            azure_object_id=None,
            user_id=None,
            auth_result="failed",
            token_valid=False,
            error_message=str(e)
        )

        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32001, "message": f"Authentication error: {str(e)}"},
            },
            status_code=401,
            headers={
                "WWW-Authenticate": f'Bearer error="invalid_token", resource_metadata="{resource_metadata_url}"',
                "Access-Control-Allow-Origin": "*",
            },
        )