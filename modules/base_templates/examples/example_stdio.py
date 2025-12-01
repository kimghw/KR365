#!/usr/bin/env python3
"""
Example MCP Stdio Server

MCP stdio 서버 템플릿 사용 예제입니다.
Claude Desktop과 통합됩니다.
"""

import sys
import os
from pathlib import Path

# 프로젝트 루트 경로 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.base_templates import MCPStdioServer
from modules.base_templates.examples.example_handler import ExampleHandler

def main():
    """메인 함수"""
    # 핸들러 생성
    handler = ExampleHandler()

    # MCP stdio 서버 생성
    server = MCPStdioServer(
        server_name="example-mcp-server",
        server_version="1.0.0",
        handler=handler
    )

    # 서버 실행
    server.run()


if __name__ == "__main__":
    main()