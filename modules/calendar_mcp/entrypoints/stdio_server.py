"""
Calendar MCP stdio 서버
Claude Desktop과 통합 - MCP 표준 구조
"""

# CRITICAL: MCP stdio 모드 - stdout은 JSON-RPC 전용
# 다른 모든 import 전에 환경 변수 설정

import sys
import os

# 환경 변수 설정 (다른 모듈 import 전에!)
os.environ['MCP_STDIO_MODE'] = '1'  # logging_config에서 stderr 사용하도록 지시
os.environ['NO_COLOR'] = '1'
os.environ['TERM'] = 'dumb'
os.environ['PYTHONUNBUFFERED'] = '1'

# 로깅 기본 설정 (stderr로)
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
    force=True
)

# 이제 다른 모듈 import
import asyncio

from mcp.server.models import InitializationOptions
from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server

from infra.core.logger import get_logger
from modules.calendar_mcp.handlers import CalendarHandlers

logger = get_logger(__name__)

# MCP 서버 및 핸들러 인스턴스 생성
app = Server("calendar-mcp-server")
handlers = CalendarHandlers()


@app.list_tools()
async def handle_list_tools():
    """사용 가능한 도구 목록 반환 - Handler 위임"""
    return await handlers.handle_list_tools()


@app.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    """도구 호출 처리 - Handler 위임"""
    return await handlers.handle_call_tool(name, arguments)


async def main():
    """메인 함수"""
    logger.info("Calendar MCP stdio 서버 시작")

    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="calendar-mcp-server",
                    server_version="1.0.0",
                    capabilities=app.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
    except Exception as e:
        logger.error(f"서버 실행 오류: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
