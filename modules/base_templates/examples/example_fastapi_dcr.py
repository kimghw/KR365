#!/usr/bin/env python3
"""
Example FastAPI Server with DCR OAuth

DCR OAuth 인증을 사용하는 FastAPI 서버 예제입니다.
"""

import sys
import os
import argparse
from pathlib import Path
from typing import Dict, Any

# 프로젝트 루트 경로 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import Depends, HTTPException
from modules.base_templates import FastAPIServer
from modules.base_templates.dcr_auth_mixin import DCRAuthMixin
from modules.base_templates.examples.example_handler import ExampleHandler


class FastAPIServerWithDCR(FastAPIServer, DCRAuthMixin):
    """DCR OAuth를 지원하는 FastAPI 서버"""

    def __init__(self, *args, **kwargs):
        # 서버 초기화
        super().__init__(*args, **kwargs)

        # DCR 인증 초기화
        DCRAuthMixin.__init__(self, server_name=self.server_name)

        # DCR 라우트 등록
        self.register_dcr_routes(self.app)

        # 보호된 엔드포인트 추가
        self._register_protected_routes()

    def _register_protected_routes(self):
        """DCR 인증이 필요한 보호된 엔드포인트 등록"""

        @self.app.get("/protected/user")
        async def get_current_user(auth_info: Dict[str, Any] = Depends(self.verify_token)):
            """현재 인증된 사용자 정보 반환"""
            is_valid, info = auth_info
            return {
                "authenticated": True,
                "user": info.get("user_email"),
                "client_id": info.get("client_id"),
                "expires_at": info.get("expires_at")
            }

        @self.app.post("/protected/tools/{tool_name}")
        async def call_tool_protected(
            tool_name: str,
            request: Dict[str, Any],
            auth_info: Dict[str, Any] = Depends(self.verify_token)
        ):
            """보호된 도구 호출 (인증 필요)"""
            is_valid, info = auth_info

            if not self.handler:
                raise HTTPException(status_code=500, detail="No handler configured")

            try:
                # 사용자 정보를 arguments에 추가
                arguments = request.get("arguments", {})
                arguments["__user__"] = info.get("user_email")

                # 도구 호출
                result = await self.handler.call_tool(tool_name, arguments)

                return {
                    "success": True,
                    "user": info.get("user_email"),
                    "result": [
                        {"type": content.type, "text": content.text}
                        for content in result
                    ]
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e)
                }


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="Example FastAPI MCP Server with DCR OAuth")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8000")),
        help="Server port (default: 8000)"
    )
    parser.add_argument(
        "--host",
        default=os.getenv("HOST", "0.0.0.0"),
        help="Server host (default: 0.0.0.0)"
    )

    args = parser.parse_args()

    # 핸들러 생성
    handler = ExampleHandler()

    # DCR OAuth를 지원하는 FastAPI 서버 생성
    server = FastAPIServerWithDCR(
        server_name="example-fastapi-dcr",
        server_version="1.0.0",
        handler=handler,
        host=args.host,
        port=args.port,
        enable_cors=True
    )

    # 서버 실행
    print(f"🚀 Starting Example FastAPI Server with DCR OAuth on {args.host}:{args.port}")
    print(f"📝 API Docs: http://{args.host}:{args.port}/docs")
    print(f"🔐 OAuth Login: http://{args.host}:{args.port}/oauth/login?client_id=YOUR_CLIENT_ID")
    print(f"📋 Register Client: POST http://{args.host}:{args.port}/oauth/register")
    server.run()


if __name__ == "__main__":
    main()