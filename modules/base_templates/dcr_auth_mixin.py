"""
DCR Authentication Mixin

DCR OAuth 인증을 제공하는 믹스인 클래스입니다.
FastAPI 서버에서 DCR 인증을 사용할 때 활용합니다.
"""

import os
from typing import Optional, Dict, Any, Tuple
from fastapi import HTTPException, Header, Request
from fastapi.responses import RedirectResponse, HTMLResponse

from infra.core.logger import get_logger
from modules.dcr_oauth_module import DCRService

logger = get_logger(__name__)


class DCRAuthMixin:
    """DCR OAuth 인증 믹스인"""

    def __init__(self, module_name: str = "default"):
        """
        DCR 인증 믹스인 초기화

        Args:
            module_name: 모듈 이름 (테이블 접미사 및 redirect URI 생성용)
        """
        self.dcr_service = DCRService(module_name=module_name)
        self.module_name = module_name
        logger.info(f"DCR Auth initialized for module: {module_name}")

    def register_dcr_routes(self, app):
        """
        FastAPI 앱에 DCR OAuth 라우트 등록

        Args:
            app: FastAPI 앱 인스턴스
        """

        @app.get("/oauth/login")
        async def oauth_login(request: Request):
            """OAuth 로그인 시작"""
            try:
                # 클라이언트 ID와 state 파라미터 가져오기
                client_id = request.query_params.get("client_id")
                state = request.query_params.get("state")

                if not client_id:
                    raise HTTPException(status_code=400, detail="Missing client_id parameter")

                # DCR 클라이언트 확인
                client_info = self.dcr_service.get_client_info(client_id)
                if not client_info:
                    raise HTTPException(status_code=404, detail="Client not found")

                # Azure OAuth URL 생성
                auth_url = self.dcr_service.get_azure_auth_url(client_id, state)
                if not auth_url:
                    raise HTTPException(status_code=500, detail="Failed to generate auth URL")

                logger.info(f"Redirecting to Azure OAuth: {auth_url}")
                return RedirectResponse(url=auth_url)

            except Exception as e:
                logger.error(f"OAuth login error: {str(e)}")
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/oauth/callback")
        async def oauth_callback(request: Request):
            """OAuth 콜백 처리"""
            try:
                # 쿼리 파라미터 추출
                code = request.query_params.get("code")
                state = request.query_params.get("state")
                error = request.query_params.get("error")
                error_description = request.query_params.get("error_description")

                if error:
                    logger.error(f"OAuth error: {error} - {error_description}")
                    return HTMLResponse(
                        content=f"""
                        <html>
                        <body>
                            <h2>Authentication Failed</h2>
                            <p>Error: {error}</p>
                            <p>{error_description or ''}</p>
                        </body>
                        </html>
                        """,
                        status_code=400
                    )

                if not code or not state:
                    raise HTTPException(status_code=400, detail="Missing code or state parameter")

                # state에서 client_id 추출
                client_id = state.split(":")[0] if ":" in state else state

                # DCR 클라이언트 확인
                client_info = self.dcr_service.get_client_info(client_id)
                if not client_info:
                    raise HTTPException(status_code=404, detail="Client not found")

                # PKCE 검증 및 토큰 교환
                result = self.dcr_service.handle_azure_callback(code, state, client_id)

                if result.get("success"):
                    # 성공 페이지 표시
                    return HTMLResponse(
                        content=f"""
                        <html>
                        <head>
                            <style>
                                body {{
                                    font-family: Arial, sans-serif;
                                    display: flex;
                                    justify-content: center;
                                    align-items: center;
                                    height: 100vh;
                                    margin: 0;
                                    background-color: #f0f0f0;
                                }}
                                .container {{
                                    text-align: center;
                                    padding: 2rem;
                                    background: white;
                                    border-radius: 8px;
                                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                                }}
                                .success {{
                                    color: #28a745;
                                }}
                                .token-info {{
                                    margin-top: 1rem;
                                    padding: 1rem;
                                    background: #f8f9fa;
                                    border-radius: 4px;
                                    text-align: left;
                                }}
                                code {{
                                    background: #e9ecef;
                                    padding: 0.2rem 0.4rem;
                                    border-radius: 3px;
                                    font-size: 0.9em;
                                }}
                            </style>
                        </head>
                        <body>
                            <div class="container">
                                <h1 class="success">✅ Authentication Successful!</h1>
                                <p>You have been successfully authenticated.</p>
                                <div class="token-info">
                                    <p><strong>User:</strong> {result.get('user_email', 'Unknown')}</p>
                                    <p><strong>Client ID:</strong> <code>{client_id}</code></p>
                                    <p><strong>Bearer Token:</strong></p>
                                    <code style="word-break: break-all;">{result.get('dcr_token', 'N/A')}</code>
                                    <p style="margin-top: 1rem;">Use this Bearer token in your API requests:</p>
                                    <code>Authorization: Bearer {result.get('dcr_token', 'TOKEN')}</code>
                                </div>
                                <p style="margin-top: 2rem;">You can now close this window.</p>
                            </div>
                        </body>
                        </html>
                        """,
                        status_code=200
                    )
                else:
                    error_msg = result.get("error", "Unknown error")
                    return HTMLResponse(
                        content=f"""
                        <html>
                        <body>
                            <h2>Authentication Failed</h2>
                            <p>Error: {error_msg}</p>
                        </body>
                        </html>
                        """,
                        status_code=400
                    )

            except Exception as e:
                logger.error(f"OAuth callback error: {str(e)}")
                return HTMLResponse(
                    content=f"""
                    <html>
                    <body>
                        <h2>Authentication Error</h2>
                        <p>{str(e)}</p>
                    </body>
                    </html>
                    """,
                    status_code=500
                )

        @app.post("/oauth/register")
        async def register_client(request: Request):
            """DCR 클라이언트 등록"""
            try:
                body = await request.json()
                client_name = body.get("client_name", f"client_{self.server_name}")

                # 클라이언트 등록
                result = self.dcr_service.register_client(client_name)

                if result:
                    logger.info(f"Client registered: {result['client_id']}")
                    return {
                        "success": True,
                        "client_id": result["client_id"],
                        "client_secret": result["client_secret"],
                        "message": "Client registered successfully"
                    }
                else:
                    raise HTTPException(status_code=500, detail="Failed to register client")

            except Exception as e:
                logger.error(f"Client registration error: {str(e)}")
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/oauth/status")
        async def oauth_status(authorization: Optional[str] = Header(None)):
            """인증 상태 확인"""
            try:
                if not authorization:
                    return {
                        "authenticated": False,
                        "message": "No authorization header"
                    }

                # Bearer 토큰 추출
                if not authorization.startswith("Bearer "):
                    return {
                        "authenticated": False,
                        "message": "Invalid authorization format"
                    }

                token = authorization[7:]

                # 토큰 검증
                is_valid, info = self.dcr_service.verify_dcr_token(token)

                if is_valid:
                    return {
                        "authenticated": True,
                        "user": info.get("user_email"),
                        "client_id": info.get("client_id"),
                        "expires_at": info.get("expires_at")
                    }
                else:
                    return {
                        "authenticated": False,
                        "message": info.get("error", "Invalid token")
                    }

            except Exception as e:
                logger.error(f"Status check error: {str(e)}")
                return {
                    "authenticated": False,
                    "error": str(e)
                }

    def verify_token(self, authorization: Optional[str] = Header(None)) -> Tuple[bool, Dict[str, Any]]:
        """
        Bearer 토큰 검증 (Dependency Injection용)

        Args:
            authorization: Authorization 헤더

        Returns:
            Tuple[bool, Dict]: (검증 성공 여부, 사용자 정보)

        Raises:
            HTTPException: 인증 실패 시
        """
        if not authorization:
            raise HTTPException(
                status_code=401,
                detail="Authorization header required",
                headers={"WWW-Authenticate": "Bearer"}
            )

        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Invalid authorization format",
                headers={"WWW-Authenticate": "Bearer"}
            )

        token = authorization[7:]
        is_valid, info = self.dcr_service.verify_dcr_token(token)

        if not is_valid:
            raise HTTPException(
                status_code=401,
                detail=info.get("error", "Invalid token"),
                headers={"WWW-Authenticate": "Bearer"}
            )

        return True, info

    def get_azure_token(self, user_id: str) -> Optional[str]:
        """
        사용자의 Azure 액세스 토큰 가져오기

        Args:
            user_id: 사용자 ID

        Returns:
            Optional[str]: Azure 액세스 토큰
        """
        return self.dcr_service.get_azure_token_for_user(user_id)