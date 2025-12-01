"""
MCP Stdio Server Template

MCP 프로토콜을 통해 stdio로 통신하는 서버 템플릿입니다.
Claude Desktop과 통합됩니다.
"""

import sys
import os
import asyncio
from typing import Optional

# MCP stdio 모드 설정
os.environ['MCP_STDIO_MODE'] = '1'
os.environ['NO_COLOR'] = '1'
os.environ['TERM'] = 'dumb'
os.environ['PYTHONUNBUFFERED'] = '1'

# 로깅 설정 (stderr로)
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
    force=True
)

from mcp.server.models import InitializationOptions
from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server

from infra.core.logger import get_logger
from .base_server import BaseServer
from .base_handler import BaseHandler

logger = get_logger(__name__)


class MCPStdioServer(BaseServer):
    """MCP Stdio 서버 템플릿"""

    def __init__(
        self,
        server_name: str,
        server_version: str = "1.0.0",
        handler: Optional[BaseHandler] = None,
        **kwargs
    ):
        """
        MCP Stdio 서버 초기화

        Args:
            server_name: 서버 이름
            server_version: 서버 버전
            handler: BaseHandler 인스턴스
            **kwargs: 추가 설정
        """
        super().__init__(server_name, server_version, **kwargs)

        # MCP 서버 인스턴스 생성
        self.app = Server(server_name)

        # 핸들러 설정
        if handler:
            self.set_handler(handler)

        # MCP 엔드포인트 등록
        self._register_endpoints()

    def _register_endpoints(self):
        """MCP 엔드포인트 등록"""

        @self.app.list_tools()
        async def handle_list_tools():
            """사용 가능한 도구 목록 반환"""
            if not self.handler:
                logger.error("No handler set")
                return []

            try:
                return await self.handler.list_tools()
            except Exception as e:
                logger.error(f"Error listing tools: {str(e)}")
                return []

        @self.app.call_tool()
        async def handle_call_tool(name: str, arguments: dict):
            """도구 호출 처리"""
            if not self.handler:
                logger.error("No handler set")
                return [{"type": "text", "text": "Error: No handler configured"}]

            try:
                return await self.handler.call_tool(name, arguments)
            except Exception as e:
                logger.error(f"Error calling tool {name}: {str(e)}")
                return [{"type": "text", "text": f"Error: {str(e)}"}]

    async def start(self):
        """서버 시작"""
        logger.info(f"Starting {self.server_name} MCP stdio server")

        # 핸들러 초기화
        await self.initialize()

        try:
            async with stdio_server() as (read_stream, write_stream):
                await self.app.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name=self.server_name,
                        server_version=self.server_version,
                        capabilities=self.app.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={},
                        ),
                    ),
                )
        except Exception as e:
            logger.error(f"Server error: {str(e)}")
            raise
        finally:
            await self.cleanup()

    async def stop(self):
        """서버 종료"""
        logger.info(f"Stopping {self.server_name} MCP stdio server")
        await self.cleanup()

    def run(self):
        """서버 실행 (동기 진입점)"""
        asyncio.run(self.start())