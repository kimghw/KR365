"""
DCR OAuth 인증 미들웨어

모든 MCP 서버에서 공통으로 사용하는 Bearer 토큰 검증 미들웨어
"""

from typing import Optional
from starlette.responses import JSONResponse
from modules.dcr_oauth import DCRService
from infra.core.logger import get_logger

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
    # Skip authentication for certain paths
    path = request.url.path

    # OAuth 엔드포인트와 메타데이터는 인증 제외
    # .well-known은 경로 어디든 포함되면 제외 (MCP discovery 지원)
    if "/.well-known/" in path:
        return None  # Skip authentication for discovery endpoints

    # 특정 경로로 시작하면 제외
    excluded_path_prefixes = [
        "/oauth/",
        "/health",
        "/info",
        "/enrollment/callback",  # Enrollment 서비스의 OAuth 콜백
        "/auth/callback"  # DCR OAuth 콜백
    ]

    if any(path.startswith(excluded) for excluded in excluded_path_prefixes):
        return None  # Skip authentication

    # OPTIONS 요청은 인증 제외
    if request.method == "OPTIONS":
        return None

    # GET/HEAD 요청은 인증 제외 (MCP Discovery)
    # Claude.ai가 초기에 토큰 없이 서버 정보를 확인함
    if request.method in ["GET", "HEAD"]:
        return None

    # Get Authorization header
    auth_header = request.headers.get("Authorization", "")

    # Debug: Log all headers for troubleshooting
    logger.info(f"🔍 Request to {path} - Headers: {dict(request.headers)}")

    # Check Bearer token
    if not auth_header.startswith("Bearer "):
        logger.warning(f"⚠️ Missing Bearer token for path: {path}")
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32001,
                    "message": "Authentication required. Please authenticate using OAuth 2.0"
                },
            },
            status_code=401,
            headers={
                "WWW-Authenticate": 'Bearer realm="MCP Server", error="invalid_token"',
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

            return None  # Authentication successful
        else:
            logger.warning(f"⚠️ Invalid Bearer token for path: {path}")
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32001, "message": "Invalid authentication token"},
                },
                status_code=401,
                headers={
                    "WWW-Authenticate": 'Bearer realm="MCP Server", error="invalid_token"',
                    "Access-Control-Allow-Origin": "*",
                },
            )
    except Exception as e:
        logger.error(f"❌ Token verification failed: {str(e)}")
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32001, "message": f"Authentication error: {str(e)}"},
            },
            status_code=401,
            headers={
                "WWW-Authenticate": 'Bearer realm="MCP Server", error="invalid_token"',
                "Access-Control-Allow-Origin": "*",
            },
        )