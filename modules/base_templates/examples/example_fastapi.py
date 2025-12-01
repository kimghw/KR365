#!/usr/bin/env python3
"""
Example FastAPI Server

FastAPI 서버 템플릿 사용 예제입니다.
HTTP API로 MCP 기능을 제공합니다.
"""

import sys
import os
import argparse
from pathlib import Path

# 프로젝트 루트 경로 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.base_templates import FastAPIServer
from modules.base_templates.examples.example_handler import ExampleHandler

def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="Example FastAPI MCP Server")
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

    # FastAPI 서버 생성
    server = FastAPIServer(
        server_name="example-fastapi-server",
        server_version="1.0.0",
        handler=handler,
        host=args.host,
        port=args.port,
        enable_cors=True
    )

    # 서버 실행
    print(f"🚀 Starting Example FastAPI Server on {args.host}:{args.port}")
    print(f"📝 API Docs: http://{args.host}:{args.port}/docs")
    server.run()


if __name__ == "__main__":
    main()