"""
Local Server Template

로컬에서 직접 실행하는 서버 템플릿입니다.
CLI 도구나 스크립트에서 사용할 수 있습니다.
"""

import asyncio
from typing import Optional, Dict, Any, List

from infra.core.logger import get_logger
from .base_server import BaseServer
from .base_handler import BaseHandler

logger = get_logger(__name__)


class LocalServer(BaseServer):
    """로컬 실행 서버 템플릿"""

    def __init__(
        self,
        server_name: str,
        server_version: str = "1.0.0",
        handler: Optional[BaseHandler] = None,
        **kwargs
    ):
        """
        로컬 서버 초기화

        Args:
            server_name: 서버 이름
            server_version: 서버 버전
            handler: BaseHandler 인스턴스
            **kwargs: 추가 설정
        """
        super().__init__(server_name, server_version, **kwargs)

        # 핸들러 설정
        if handler:
            self.set_handler(handler)

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        사용 가능한 도구 목록 반환

        Returns:
            List[Dict]: 도구 정보 목록
        """
        if not self.handler:
            logger.error("No handler set")
            return []

        try:
            tools = await self.handler.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema
                }
                for tool in tools
            ]
        except Exception as e:
            logger.error(f"Error listing tools: {str(e)}")
            return []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        도구 호출

        Args:
            name: 도구 이름
            arguments: 도구 인자

        Returns:
            Dict: 실행 결과
        """
        if not self.handler:
            logger.error("No handler set")
            return {"success": False, "error": "No handler configured"}

        try:
            result = await self.handler.call_tool(name, arguments)
            return {
                "success": True,
                "result": [
                    {"type": content.type, "text": content.text}
                    for content in result
                ]
            }
        except Exception as e:
            logger.error(f"Error calling tool {name}: {str(e)}")
            return {"success": False, "error": str(e)}

    async def interactive_loop(self):
        """
        대화형 루프 (CLI용)

        사용자 입력을 받아 도구를 실행합니다.
        """
        logger.info(f"Starting interactive mode for {self.server_name}")
        logger.info("Type 'help' for available commands, 'quit' to exit")

        while True:
            try:
                # 입력 받기
                command = input(f"\n{self.server_name}> ").strip()

                if command.lower() == 'quit':
                    break
                elif command.lower() == 'help':
                    await self._show_help()
                elif command.lower() == 'list':
                    await self._list_tools_interactive()
                elif command.startswith('call '):
                    await self._call_tool_interactive(command)
                else:
                    print(f"Unknown command: {command}")
                    print("Type 'help' for available commands")

            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                logger.error(f"Error in interactive loop: {str(e)}")

    async def _show_help(self):
        """도움말 표시"""
        print("\nAvailable commands:")
        print("  help  - Show this help message")
        print("  list  - List available tools")
        print("  call <tool> <args>  - Call a tool with JSON arguments")
        print("  quit  - Exit the program")

        if self.handler and hasattr(self.handler, 'get_help_text'):
            print("\n" + self.handler.get_help_text())

    async def _list_tools_interactive(self):
        """도구 목록 표시 (대화형)"""
        tools = await self.list_tools()
        if tools:
            print("\nAvailable tools:")
            for tool in tools:
                print(f"  - {tool['name']}: {tool['description']}")
        else:
            print("No tools available")

    async def _call_tool_interactive(self, command: str):
        """도구 호출 (대화형)"""
        import json

        parts = command.split(None, 2)
        if len(parts) < 2:
            print("Usage: call <tool_name> [arguments_json]")
            return

        tool_name = parts[1]
        arguments = {}

        if len(parts) > 2:
            try:
                arguments = json.loads(parts[2])
            except json.JSONDecodeError as e:
                print(f"Invalid JSON arguments: {e}")
                return

        result = await self.call_tool(tool_name, arguments)

        if result["success"]:
            print("\nResult:")
            for item in result["result"]:
                print(item["text"])
        else:
            print(f"\nError: {result['error']}")

    async def start(self):
        """서버 시작"""
        logger.info(f"Starting {self.server_name} local server")

        # 핸들러 초기화
        await self.initialize()

        try:
            # 대화형 모드 실행
            await self.interactive_loop()
        except Exception as e:
            logger.error(f"Server error: {str(e)}")
            raise
        finally:
            await self.cleanup()

    async def stop(self):
        """서버 종료"""
        logger.info(f"Stopping {self.server_name} local server")
        await self.cleanup()

    def run(self):
        """서버 실행 (동기 진입점)"""
        asyncio.run(self.start())

    def run_once(self, tool_name: str, arguments: Dict[str, Any] = None):
        """
        도구를 한 번만 실행하고 종료

        Args:
            tool_name: 도구 이름
            arguments: 도구 인자
        """
        async def _run():
            await self.initialize()
            try:
                result = await self.call_tool(tool_name, arguments or {})
                return result
            finally:
                await self.cleanup()

        return asyncio.run(_run())