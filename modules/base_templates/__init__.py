"""
Base Templates for MCP Services

이 패키지는 MCP, HTTP, Local 서버를 쉽게 구성할 수 있는 템플릿을 제공합니다.

Components:
- BaseHandler: 핸들러 인터페이스 정의
- BaseServer: 서버 기본 클래스
- MCPStdioServer: MCP stdio 서버 템플릿
- FastAPIServer: FastAPI HTTP 서버 템플릿
- LocalServer: 로컬 실행 서버 템플릿
- DCRAuthMixin: DCR OAuth 인증 믹스인
"""

from .base_handler import BaseHandler
from .base_server import BaseServer
from .mcp_stdio_server import MCPStdioServer
from .fastapi_server import FastAPIServer
from .local_server import LocalServer
from .dcr_auth_mixin import DCRAuthMixin

__all__ = [
    "BaseHandler",
    "BaseServer",
    "MCPStdioServer",
    "FastAPIServer",
    "LocalServer",
    "DCRAuthMixin"
]