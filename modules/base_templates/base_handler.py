"""
Base Handler Interface

모든 MCP 핸들러가 구현해야 할 기본 인터페이스를 정의합니다.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from mcp.types import Tool, TextContent


class BaseHandler(ABC):
    """기본 핸들러 인터페이스"""

    @abstractmethod
    async def list_tools(self) -> List[Tool]:
        """
        사용 가능한 도구 목록을 반환합니다.

        Returns:
            List[Tool]: MCP Tool 객체 목록
        """
        pass

    @abstractmethod
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """
        도구를 호출하고 결과를 반환합니다.

        Args:
            name: 도구 이름
            arguments: 도구 인자

        Returns:
            List[TextContent]: 도구 실행 결과
        """
        pass

    async def initialize(self) -> None:
        """
        핸들러 초기화 (선택적)

        리소스 초기화, DB 연결 등을 수행합니다.
        """
        pass

    async def cleanup(self) -> None:
        """
        핸들러 정리 (선택적)

        리소스 해제, DB 연결 종료 등을 수행합니다.
        """
        pass

    def get_help_text(self) -> str:
        """
        도구 사용법 안내 텍스트를 반환합니다 (선택적)

        Returns:
            str: 도움말 텍스트
        """
        return "No help available for this handler"