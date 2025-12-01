#!/usr/bin/env python3
"""
Example Local Server

로컬 실행 서버 템플릿 사용 예제입니다.
CLI 도구로 사용할 수 있습니다.
"""

import sys
import os
import json
import argparse
from pathlib import Path

# 프로젝트 루트 경로 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.base_templates import LocalServer
from modules.base_templates.examples.example_handler import ExampleHandler


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="Example Local MCP Server")

    # 서브 명령 정의
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # interactive 명령
    subparsers.add_parser("interactive", help="Run in interactive mode")

    # list 명령
    subparsers.add_parser("list", help="List available tools")

    # call 명령
    call_parser = subparsers.add_parser("call", help="Call a specific tool")
    call_parser.add_argument("tool", help="Tool name")
    call_parser.add_argument("--args", default="{}", help="Tool arguments as JSON")

    # help 명령
    subparsers.add_parser("help", help="Show help text")

    args = parser.parse_args()

    # 핸들러 생성
    handler = ExampleHandler()

    # 로컬 서버 생성
    server = LocalServer(
        server_name="example-local-server",
        server_version="1.0.0",
        handler=handler
    )

    # 명령 처리
    if args.command == "interactive" or args.command is None:
        # 대화형 모드
        print("Starting interactive mode...")
        server.run()

    elif args.command == "list":
        # 도구 목록 출력
        import asyncio

        async def list_tools():
            await server.initialize()
            tools = await server.list_tools()
            print("\nAvailable tools:")
            for tool in tools:
                print(f"  - {tool['name']}: {tool['description']}")
            await server.cleanup()

        asyncio.run(list_tools())

    elif args.command == "call":
        # 도구 실행
        try:
            arguments = json.loads(args.args)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON arguments: {e}")
            sys.exit(1)

        result = server.run_once(args.tool, arguments)

        if result["success"]:
            print("\nResult:")
            for item in result["result"]:
                print(item["text"])
        else:
            print(f"\nError: {result['error']}")
            sys.exit(1)

    elif args.command == "help":
        # 도움말 출력
        import asyncio

        async def show_help():
            await server.initialize()
            if handler:
                print(handler.get_help_text())
            await server.cleanup()

        asyncio.run(show_help())

    else:
        parser.print_help()


if __name__ == "__main__":
    main()