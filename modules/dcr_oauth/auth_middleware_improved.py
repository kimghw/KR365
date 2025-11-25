"""
개선된 DCR OAuth 인증 미들웨어

토큰 누락 문제를 해결하기 위한 개선 사항:
1. 토큰 캐싱 메커니즘
2. 서비스 간 토큰 공유
3. 명확한 에러 메시지
"""

from typing import Optional, Dict
from datetime import datetime, timedelta
from starlette.responses import JSONResponse
from modules.dcr_oauth import DCRService
from infra.core.logger import get_logger
from infra.core.logs_db import get_logs_db_service
import json

logger = get_logger(__name__)


class TokenShareManager:
    """서비스 간 토큰 공유 관리"""

    def __init__(self):
        self._token_map: Dict[str, Dict] = {}  # dcr_client_id -> token_info
        self._service_tokens: Dict[str, str] = {}  # service_path -> dcr_client_id

    def store_token(self, service_path: str, token: str, token_data: Dict):
        """서비스별 토큰 저장"""
        client_id = token_data.get("dcr_client_id")
        if client_id:
            # 토큰 정보 저장
            self._token_map[client_id] = {
                "token": token,
                "data": token_data,
                "timestamp": datetime.now()
            }
            # 서비스-클라이언트 매핑
            base_service = service_path.strip("/").split("/")[0]
            self._service_tokens[base_service] = client_id
            logger.info(f"✅ Token stored for {base_service} (client: {client_id})")

    def get_shared_token(self, service_path: str) -> Optional[tuple]:
        """다른 서비스의 토큰 공유 시도"""
        base_service = service_path.strip("/").split("/")[0]

        # 이미 이 서비스의 토큰이 있는지 확인
        if base_service in self._service_tokens:
            client_id = self._service_tokens[base_service]
            if client_id in self._token_map:
                token_info = self._token_map[client_id]
                # 1시간 이내 토큰만 유효
                if datetime.now() - token_info["timestamp"] < timedelta(hours=1):
                    return token_info["token"], token_info["data"]

        # 다른 서비스의 최신 토큰 찾기
        for other_service, client_id in self._service_tokens.items():
            if other_service != base_service and client_id in self._token_map:
                token_info = self._token_map[client_id]
                if datetime.now() - token_info["timestamp"] < timedelta(minutes=30):
                    logger.info(f"🔄 Sharing token from {other_service} to {base_service}")
                    # 이 서비스도 같은 클라이언트 사용하도록 매핑
                    self._service_tokens[base_service] = client_id
                    return token_info["token"], token_info["data"]

        return None

    def get_authenticated_services(self, client_id: str) -> list:
        """특정 클라이언트가 인증된 서비스 목록"""
        services = []
        for service, cid in self._service_tokens.items():
            if cid == client_id:
                services.append(service)
        return services


# 전역 토큰 공유 매니저
token_share_manager = TokenShareManager()


async def verify_bearer_token_middleware_improved(request, call_next=None):
    """
    개선된 Bearer 토큰 검증 미들웨어
    - 토큰 공유 메커니즘 추가
    - 더 나은 에러 메시지
    """
    logs_db = get_logs_db_service()
    path = request.url.path
    method = request.method

    # Skip authentication for certain paths
    excluded_paths = [
        "/.well-known",
        "/oauth",
        "/health",
        "/dashboard"
    ]

    for excluded in excluded_paths:
        if path.startswith(excluded):
            logs_db.log_dcr_middleware(
                path=path,
                method=method,
                auth_result="skipped",
                error_message=f"Excluded path: {path}"
            )
            return None

    # Skip GET requests (discovery)
    if method == "GET":
        logs_db.log_dcr_middleware(
            path=path,
            method=method,
            auth_result="skipped",
            error_message="GET request - discovery"
        )
        return None

    # Get Authorization header
    auth_header = request.headers.get("Authorization", "")

    # 토큰이 없는 경우
    if not auth_header.startswith("Bearer "):
        # 다른 서비스에서 사용한 토큰 확인
        shared_token = token_share_manager.get_shared_token(path)

        if shared_token:
            token, token_data = shared_token
            logger.info(f"🔄 Using shared token for {path}")

            # 헤더에 토큰 추가 (Starlette의 경우)
            auth_header = f"Bearer {token}"

            # 토큰 검증 진행
        else:
            # 어떤 서비스가 인증되었는지 확인
            authenticated_services = []
            for service in ["onenote", "mail-query", "teams", "calendar"]:
                if service in token_share_manager._service_tokens:
                    authenticated_services.append(service)

            error_msg = "Missing Bearer token"
            if authenticated_services:
                error_msg += f". Other services authenticated: {', '.join(authenticated_services)}"

            logger.warning(f"⚠️ {error_msg} for path: {path}")

            logs_db.log_dcr_middleware(
                path=path,
                method=method,
                auth_result="failed",
                error_message=error_msg
            )

            # 더 자세한 에러 응답
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32001,
                        "message": "Authentication required",
                        "data": {
                            "reason": "Missing Bearer token",
                            "path": path,
                            "authenticated_services": authenticated_services,
                            "hint": "Include Authorization: Bearer <token> header" if not authenticated_services
                            else "Same token should work for all services"
                        }
                    }
                },
                status_code=401,
                headers={
                    "WWW-Authenticate": 'Bearer realm="MCP Server"',
                    "Access-Control-Allow-Origin": "*",
                    "X-Auth-Hint": "Token-Sharing-Enabled"
                }
            )

    # Bearer 토큰 추출
    token = auth_header[7:] if auth_header.startswith("Bearer ") else None

    if not token:
        return JSONResponse(
            {"error": "Invalid authorization header format"},
            status_code=401
        )

    try:
        # Verify token using DCR service
        dcr_service = DCRService()
        token_data = dcr_service.verify_bearer_token(token)

        if token_data:
            # 토큰 공유 매니저에 저장
            token_share_manager.store_token(path, token, token_data)

            # Store DCR client info in request state
            request.state.dcr_client_id = token_data["dcr_client_id"]
            request.state.azure_object_id = token_data["azure_object_id"]
            request.state.azure_token = token_data["azure_token"]
            request.state.user_id = token_data.get("user_email", "").split("@")[0]

            # 성공 로그
            logs_db.log_dcr_middleware(
                path=path,
                method=method,
                dcr_client_id=token_data["dcr_client_id"],
                azure_object_id=token_data["azure_object_id"],
                user_id=request.state.user_id,
                auth_result="success",
                token_valid=True
            )

            logger.info(f"✅ Token verified for {path} (client: {token_data['dcr_client_id']})")
            return None  # Authentication successful

        else:
            # 토큰이 유효하지 않은 경우
            logger.warning(f"⚠️ Invalid Bearer token for path: {path}")

            logs_db.log_dcr_middleware(
                path=path,
                method=method,
                auth_result="failed",
                error_message="Invalid token"
            )

            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32001,
                        "message": "Invalid or expired token",
                        "data": {
                            "hint": "Token may have expired. Please re-authenticate."
                        }
                    }
                },
                status_code=401,
                headers={
                    "WWW-Authenticate": 'Bearer realm="MCP Server", error="invalid_token"',
                    "Access-Control-Allow-Origin": "*"
                }
            )

    except Exception as e:
        logger.error(f"❌ Token verification failed: {str(e)}")

        logs_db.log_dcr_middleware(
            path=path,
            method=method,
            auth_result="failed",
            error_message=f"Verification error: {str(e)}"
        )

        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": "Internal authentication error",
                    "data": {"detail": str(e)}
                }
            },
            status_code=401
        )


# 기존 미들웨어와의 호환성을 위한 별칭
verify_bearer_token_middleware = verify_bearer_token_middleware_improved