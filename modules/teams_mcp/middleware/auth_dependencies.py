"""
FastAPI DCR OAuth2 Authentication Dependencies

FastAPI 네이티브 의존성 주입을 활용한 DCR 인증
"""

from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from infra.core.logger import get_logger
import os

logger = get_logger(__name__)

# FastAPI Security scheme
security = HTTPBearer(auto_error=False)


class DCRAuthenticator:
    """DCR OAuth2 인증 관리자"""

    def __init__(self, server_name: str = "mail_query"):
        self.server_name = server_name
        self._dcr_service = None

    @property
    def dcr_service(self):
        """DCR 서비스 lazy loading"""
        if self._dcr_service is None:
            from modules.dcr_oauth_module import DCRService
            self._dcr_service = DCRService(module_name=self.server_name)
            logger.info(f"✅ DCR Service initialized with module_name: {self.server_name}, database: auth_{self.server_name}.db")
        return self._dcr_service

    async def verify_token(
        self,
        credentials: Optional[HTTPAuthorizationCredentials],
        request: Request
    ) -> Optional[Dict[str, Any]]:
        """토큰 검증 및 사용자 정보 반환"""

        path = request.url.path
        method = request.method

        # 인증 제외 경로 (OAuth 플로우에 꼭 필요한 경로만)
        excluded_paths = [
            "/.well-known",              # OAuth discovery (필수)
            "/oauth/register",           # DCR 클라이언트 등록 (필수)
            "/oauth/authorize",          # OAuth 인증 시작 (필수)
            "/oauth/azure_callback",     # Azure AD 콜백 (필수)
            "/oauth/token",              # 토큰 발급 (필수)
            "/health",                   # 헬스체크 (모니터링용)
        ]
        # 주의: 아래 경로는 인증 필요
        # - /docs, /redoc, /openapi.json: API 문서 (인증 필요)
        # - /dashboard: 대시보드 (인증 필요)
        # - /info: 서버 정보 (인증 필요)

        # 제외 경로 체크
        for excluded in excluded_paths:
            if path.startswith(excluded):
                logger.debug(f"🔓 Auth skipped for excluded path: {path}")
                return None

        # GET 요청 (discovery) 제외
        if method == "GET" and path == "/":
            logger.debug(f"🔓 Auth skipped for discovery: GET {path}")
            return None

        # OPTIONS 요청 (CORS) 제외
        if method == "OPTIONS":
            logger.debug(f"🔓 Auth skipped for CORS: OPTIONS {path}")
            return None

        # 토큰이 없는 경우
        if not credentials:
            logger.warning(f"⚠️ Missing Bearer token for path: {path}")

            # Get base URL from request for dynamic endpoint discovery
            base_url = f"{request.url.scheme}://{request.url.netloc}"

            # RFC 6750 + OAuth 2.0 Discovery: WWW-Authenticate 헤더에 인증 엔드포인트 정보 포함
            www_authenticate = (
                f'Bearer realm="MCP Server", '
                f'authorization_uri="{base_url}/oauth/authorize", '
                f'token_uri="{base_url}/oauth/token", '
                f'registration_uri="{base_url}/oauth/register"'
            )

            raise HTTPException(
                status_code=401,
                detail={
                    "code": -32001,
                    "message": "Authentication required",
                    "data": {
                        "reason": "Missing Bearer token",
                        "path": path,
                        "hint": "Register client at /oauth/register, then authenticate via /oauth/authorize",
                        "oauth_endpoints": {
                            "registration": f"{base_url}/oauth/register",
                            "authorization": f"{base_url}/oauth/authorize",
                            "token": f"{base_url}/oauth/token",
                            "discovery": f"{base_url}/.well-known/oauth-authorization-server"
                        }
                    }
                },
                headers={
                    "WWW-Authenticate": www_authenticate
                }
            )

        # 토큰 검증
        try:
            token_data = self.dcr_service.verify_bearer_token(credentials.credentials)

            if token_data:
                # 토큰 데이터에서 사용자 정보 추출
                dcr_client_id = token_data["dcr_client_id"]
                azure_object_id = token_data["azure_object_id"]

                # Azure 토큰 정보 가져오기
                azure_tokens = self.dcr_service.get_azure_tokens_by_object_id(azure_object_id)

                if azure_tokens:
                    user_email = azure_tokens.get("user_email", "")
                    user_id = user_email.split("@")[0] if user_email else None
                    azure_token = azure_tokens.get("access_token")
                else:
                    user_id = None
                    user_email = None
                    azure_token = None

                # 성공 로그

                logger.info(f"✅ Token verified for {path} (client: {dcr_client_id}, user: {user_id})")

                return {
                    "dcr_client_id": dcr_client_id,
                    "azure_object_id": azure_object_id,
                    "azure_token": azure_token,
                    "user_id": user_id,
                    "user_email": user_email
                }
            else:
                # 토큰이 유효하지 않은 경우
                logger.warning(f"⚠️ Invalid Bearer token for path: {path}")

                # Get base URL for OAuth endpoint discovery
                base_url = f"{request.url.scheme}://{request.url.netloc}"

                # RFC 6750: WWW-Authenticate with error details and OAuth endpoints
                www_authenticate = (
                    f'Bearer realm="MCP Server", '
                    f'error="invalid_token", '
                    f'error_description="The access token is invalid or expired", '
                    f'authorization_uri="{base_url}/oauth/authorize", '
                    f'token_uri="{base_url}/oauth/token"'
                )

                raise HTTPException(
                    status_code=401,
                    detail={
                        "code": -32001,
                        "message": "Invalid or expired token",
                        "data": {
                            "reason": "Token validation failed",
                            "hint": "Obtain a new token using refresh_token grant or re-authenticate",
                            "oauth_endpoints": {
                                "token": f"{base_url}/oauth/token",
                                "authorization": f"{base_url}/oauth/authorize"
                            }
                        }
                    },
                    headers={
                        "WWW-Authenticate": www_authenticate
                    }
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Token verification failed: {str(e)}")

            raise HTTPException(
                status_code=401,
                detail={
                    "code": -32603,
                    "message": "Internal authentication error",
                    "data": {"detail": str(e)}
                }
            )


# 전역 인증자 인스턴스 (config.json에서 module_name 로드)
def _get_module_name_from_config() -> str:
    """config.json에서 DCR OAuth module_name을 읽어옴"""
    import json
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
                return config.get("dcr_oauth", {}).get("module_name", "mail_query")
        except Exception as e:
            logger.warning(f"config.json 읽기 실패: {e}")
    return "mail_query"

authenticator = DCRAuthenticator(server_name=_get_module_name_from_config())


async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """
    선택적 인증 - 토큰이 있으면 검증, 없어도 통과

    Returns:
        사용자 정보 dict 또는 None
    """
    try:
        user_data = await authenticator.verify_token(credentials, request)

        # request.state에 사용자 정보 저장 (기존 코드와 호환성)
        if user_data:
            request.state.dcr_client_id = user_data["dcr_client_id"]
            request.state.azure_object_id = user_data["azure_object_id"]
            request.state.azure_token = user_data["azure_token"]
            request.state.user_id = user_data["user_id"]

        return user_data
    except HTTPException:
        # 인증이 선택적인 경우 에러를 무시
        return None


async def get_current_user_required(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """
    필수 인증 - 반드시 유효한 토큰이 있어야 함

    Returns:
        사용자 정보 dict

    Raises:
        HTTPException: 인증 실패 시
    """
    user_data = await authenticator.verify_token(credentials, request)

    if user_data:
        # request.state에 사용자 정보 저장 (기존 코드와 호환성)
        request.state.dcr_client_id = user_data["dcr_client_id"]
        request.state.azure_object_id = user_data["azure_object_id"]
        request.state.azure_token = user_data["azure_token"]
        request.state.user_id = user_data["user_id"]

        return user_data

    # 이 경우는 발생하지 않아야 함 (verify_token이 이미 처리)
    raise HTTPException(status_code=401, detail="Authentication required")


# 축약 별칭
optional_auth = get_current_user_optional
required_auth = get_current_user_required