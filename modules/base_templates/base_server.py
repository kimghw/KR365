"""
Base Server Class

모든 서버 타입(MCP, FastAPI, Local)의 기본 클래스입니다.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from infra.core.logger import get_logger

logger = get_logger(__name__)


class BaseServer(ABC):
    """기본 서버 클래스"""

    def __init__(
        self,
        server_name: str,
        server_version: str = "1.0.0",
        **kwargs
    ):
        """
        서버 초기화

        Args:
            server_name: 서버 이름
            server_version: 서버 버전
            **kwargs: 추가 설정
        """
        self.server_name = server_name
        self.server_version = server_version
        self.config = kwargs
        self.handler = None

        logger.info(f"Initializing {self.__class__.__name__}: {server_name} v{server_version}")

    def set_handler(self, handler):
        """
        핸들러 설정

        Args:
            handler: BaseHandler를 구현한 핸들러 인스턴스
        """
        self.handler = handler
        logger.info(f"Handler set: {handler.__class__.__name__}")

    @abstractmethod
    async def start(self):
        """서버 시작"""
        pass

    @abstractmethod
    async def stop(self):
        """서버 종료"""
        pass

    async def initialize(self):
        """
        서버 초기화 (선택적)

        핸들러 초기화 등을 수행합니다.
        """
        if self.handler and hasattr(self.handler, 'initialize'):
            await self.handler.initialize()
            logger.info("Handler initialized")

    async def cleanup(self):
        """
        서버 정리 (선택적)

        핸들러 정리 등을 수행합니다.
        """
        if self.handler and hasattr(self.handler, 'cleanup'):
            await self.handler.cleanup()
            logger.info("Handler cleaned up")