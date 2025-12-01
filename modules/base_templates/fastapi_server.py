"""
FastAPI HTTP Server Template

FastAPI를 사용한 HTTP 서버 템플릿입니다.
MCP 프로토콜을 HTTP 엔드포인트로 노출합니다.
"""

import os
import json
import uvicorn
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from infra.core.logger import get_logger
from .base_server import BaseServer
from .base_handler import BaseHandler

logger = get_logger(__name__)


class FastAPIServer(BaseServer):
    """FastAPI HTTP 서버 템플릿"""

    def __init__(
        self,
        server_name: str,
        server_version: str = "1.0.0",
        handler: Optional[BaseHandler] = None,
        host: str = "0.0.0.0",
        port: int = 8000,
        enable_cors: bool = True,
        **kwargs
    ):
        """
        FastAPI 서버 초기화

        Args:
            server_name: 서버 이름
            server_version: 서버 버전
            handler: BaseHandler 인스턴스
            host: 서버 호스트
            port: 서버 포트
            enable_cors: CORS 활성화 여부
            **kwargs: 추가 설정
        """
        super().__init__(server_name, server_version, **kwargs)

        self.host = host
        self.port = port

        # FastAPI 앱 생성 (lifespan 이벤트 사용)
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # 시작 시
            await self.initialize()
            logger.info(f"🚀 {self.server_name} FastAPI server started on {self.host}:{self.port}")
            yield
            # 종료 시
            await self.cleanup()
            logger.info(f"🛑 {self.server_name} FastAPI server stopped")

        self.app = FastAPI(
            title=server_name,
            version=server_version,
            lifespan=lifespan
        )

        # 핸들러 설정
        if handler:
            self.set_handler(handler)

        # CORS 설정
        if enable_cors:
            self._setup_cors()

        # 라우트 등록
        self._register_routes()

    def _setup_cors(self):
        """CORS 미들웨어 설정"""
        origins = os.getenv("CORS_ORIGINS", "*").split(",")

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        logger.info(f"CORS enabled for origins: {origins}")

    def _register_routes(self):
        """FastAPI 라우트 등록"""

        @self.app.get("/")
        async def root():
            """루트 엔드포인트"""
            return {
                "name": self.server_name,
                "version": self.server_version,
                "status": "running"
            }

        @self.app.get("/health")
        async def health():
            """헬스 체크 엔드포인트"""
            return {"status": "healthy"}

        @self.app.get("/tools")
        async def list_tools():
            """사용 가능한 도구 목록"""
            if not self.handler:
                raise HTTPException(status_code=500, detail="No handler configured")

            try:
                tools = await self.handler.list_tools()
                # Tool 객체를 dict로 변환
                return {
                    "tools": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.inputSchema
                        }
                        for tool in tools
                    ]
                }
            except Exception as e:
                logger.error(f"Error listing tools: {str(e)}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/tools/{tool_name}")
        async def call_tool(tool_name: str, request: Request):
            """도구 호출"""
            if not self.handler:
                raise HTTPException(status_code=500, detail="No handler configured")

            try:
                # 요청 바디 파싱
                body = await request.json()
                arguments = body.get("arguments", {})

                # 도구 호출
                result = await self.handler.call_tool(tool_name, arguments)

                # TextContent를 dict로 변환
                return {
                    "success": True,
                    "result": [
                        {"type": content.type, "text": content.text}
                        for content in result
                    ]
                }
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON")
            except Exception as e:
                logger.error(f"Error calling tool {tool_name}: {str(e)}")
                return {
                    "success": False,
                    "error": str(e)
                }

        @self.app.get("/help")
        async def get_help():
            """도움말 엔드포인트"""
            if not self.handler:
                return {"help": "No handler configured"}

            if hasattr(self.handler, 'get_help_text'):
                return {"help": self.handler.get_help_text()}
            else:
                return {"help": "No help available"}

    async def start(self):
        """서버 시작 (비동기)"""
        logger.info(f"Starting {self.server_name} FastAPI server on {self.host}:{self.port}")

        # uvicorn 서버 설정
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def stop(self):
        """서버 종료"""
        logger.info(f"Stopping {self.server_name} FastAPI server")
        await self.cleanup()

    def run(self):
        """서버 실행 (동기 진입점)"""
        uvicorn.run(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )