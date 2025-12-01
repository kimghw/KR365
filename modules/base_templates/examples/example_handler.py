"""
Example Handler Implementation

템플릿 사용 예제를 보여주는 핸들러 구현입니다.
"""

from typing import Any, Dict, List
from mcp.types import Tool, TextContent

from infra.core.logger import get_logger
from .base_handler import BaseHandler

logger = get_logger(__name__)


class ExampleHandler(BaseHandler):
    """예제 핸들러 구현"""

    def __init__(self):
        """핸들러 초기화"""
        super().__init__()
        self.counter = 0
        logger.info("ExampleHandler initialized")

    async def list_tools(self) -> List[Tool]:
        """사용 가능한 도구 목록 반환"""
        return [
            Tool(
                name="hello",
                description="Say hello to someone",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name to greet"
                        }
                    },
                    "required": ["name"]
                }
            ),
            Tool(
                name="counter",
                description="Get or increment counter",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["get", "increment"],
                            "description": "Action to perform"
                        }
                    },
                    "required": ["action"]
                }
            ),
            Tool(
                name="echo",
                description="Echo back the input",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Message to echo"
                        }
                    },
                    "required": ["message"]
                }
            )
        ]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """도구 호출 처리"""

        if name == "hello":
            name_param = arguments.get("name", "World")
            return [TextContent(
                type="text",
                text=f"Hello, {name_param}! Welcome to the Example Handler."
            )]

        elif name == "counter":
            action = arguments.get("action", "get")
            if action == "increment":
                self.counter += 1
                return [TextContent(
                    type="text",
                    text=f"Counter incremented. New value: {self.counter}"
                )]
            else:  # get
                return [TextContent(
                    type="text",
                    text=f"Current counter value: {self.counter}"
                )]

        elif name == "echo":
            message = arguments.get("message", "")
            return [TextContent(
                type="text",
                text=f"Echo: {message}"
            )]

        else:
            return [TextContent(
                type="text",
                text=f"Error: Unknown tool '{name}'"
            )]

    async def initialize(self) -> None:
        """핸들러 초기화"""
        logger.info("Initializing ExampleHandler resources...")
        # 여기서 DB 연결, 외부 서비스 초기화 등을 수행
        self.counter = 0

    async def cleanup(self) -> None:
        """핸들러 정리"""
        logger.info("Cleaning up ExampleHandler resources...")
        # 여기서 DB 연결 종료, 리소스 해제 등을 수행

    def get_help_text(self) -> str:
        """도움말 텍스트 반환"""
        return """
# Example Handler Help

This is an example handler demonstrating the template system.

## Available Tools:

1. **hello** - Greet someone by name
   - Parameters:
     - name (string): Name to greet

2. **counter** - Manage a simple counter
   - Parameters:
     - action (string): "get" or "increment"

3. **echo** - Echo back a message
   - Parameters:
     - message (string): Message to echo

## Examples:

```json
// Say hello
{
  "tool": "hello",
  "arguments": {"name": "Alice"}
}

// Increment counter
{
  "tool": "counter",
  "arguments": {"action": "increment"}
}

// Echo a message
{
  "tool": "echo",
  "arguments": {"message": "Hello, World!"}
}
```
"""