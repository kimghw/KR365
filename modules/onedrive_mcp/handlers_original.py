"""
OneDrive MCP Handlers
MCP 프로토콜 핸들러 레이어 - HTTP/stdio 공통 로직
"""

import json
from typing import Any, Dict, List, Optional
from mcp.types import Tool, TextContent

from infra.core.logger import get_logger
from .onedrive_handler import OneDriveHandler
from .schemas import (
    ListFilesRequest,
    ListFilesResponse,
    ReadFileRequest,
    ReadFileResponse,
    WriteFileRequest,
    WriteFileResponse,
    DeleteFileRequest,
    DeleteFileResponse,
)

logger = get_logger(__name__)


class OneDriveHandlers:
    """OneDrive MCP Protocol Handlers"""

    def __init__(self):
        """Initialize handlers with OneDrive handler instance"""
        self.onedrive_handler = OneDriveHandler()
        logger.info("✅ OneDriveHandlers initialized")

    # ========================================================================
    # MCP Protocol: list_tools
    # ========================================================================

    async def handle_list_tools(self) -> List[Tool]:
        """List available MCP tools (OneDrive only)"""
        logger.info("🔧 [MCP Handler] list_tools() called")

        # Define OneDrive-specific tools
        onedrive_tools = [
            Tool(
                name="list_files",
                description="OneDrive 파일 및 폴더 목록을 조회합니다. folder_path를 지정하면 해당 폴더의 파일을 조회하고, search를 지정하면 검색을 수행합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "folder_path": {
                            "type": "string",
                            "description": "폴더 경로 (예: Documents/MyFolder, 생략 시 루트)"
                        },
                        "search": {
                            "type": "string",
                            "description": "검색어"
                        }
                    },
                    "required": []
                }
            ),
            Tool(
                name="read_file",
                description="OneDrive 파일의 내용을 읽어옵니다. 텍스트 파일은 텍스트로, 바이너리 파일은 Base64 인코딩으로 반환합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "file_path": {
                            "type": "string",
                            "description": "파일 경로 또는 파일 ID (예: Documents/myfile.txt)"
                        }
                    },
                    "required": ["file_path"]
                }
            ),
            Tool(
                name="write_file",
                description="OneDrive에 파일을 생성하거나 덮어씁니다. 기본적으로 기존 파일을 덮어쓰며, overwrite=false로 설정하면 덮어쓰기를 방지합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "file_path": {
                            "type": "string",
                            "description": "파일 경로 (예: Documents/myfile.txt)"
                        },
                        "content": {
                            "type": "string",
                            "description": "파일 내용"
                        },
                        "overwrite": {
                            "type": "boolean",
                            "description": "덮어쓰기 여부 (기본값: true)"
                        }
                    },
                    "required": ["file_path", "content"]
                }
            ),
            Tool(
                name="delete_file",
                description="OneDrive에서 파일 또는 폴더를 삭제합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "file_path": {
                            "type": "string",
                            "description": "파일 경로 또는 파일 ID"
                        }
                    },
                    "required": ["file_path"]
                }
            ),
            Tool(
                name="create_folder",
                description="OneDrive에 새 폴더를 생성합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "folder_path": {
                            "type": "string",
                            "description": "생성할 폴더 이름"
                        },
                        "parent_path": {
                            "type": "string",
                            "description": "부모 폴더 경로 (생략 시 루트)"
                        }
                    },
                    "required": ["folder_path"]
                }
            ),
        ]

        # Return OneDrive tools only
        return onedrive_tools

    # ========================================================================
    # MCP Protocol: call_tool
    # ========================================================================

    def _get_authenticated_user_id(self, arguments: Dict[str, Any], authenticated_user_id: Optional[str]) -> str:
        """인증된 user_id를 반환합니다 (공통 헬퍼 래퍼)"""
        from infra.core.auth_helpers import get_authenticated_user_id
        return get_authenticated_user_id(arguments, authenticated_user_id)

    async def handle_call_tool(
        self, name: str, arguments: Dict[str, Any], authenticated_user_id: Optional[str] = None
    ) -> List[TextContent]:
        """Handle MCP tool calls (OneDrive only)"""
        logger.info(f"🔨 [MCP Handler] call_tool({name}) with args: {arguments}")

        try:
            # Handle OneDrive-specific tools
            if name == "list_files":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                folder_path = arguments.get("folder_path")
                search = arguments.get("search")

                result = await self.onedrive_handler.list_files(user_id, folder_path, search)

                # 사용자 친화적인 출력 포맷 추가
                if result.get("success") and result.get("files"):
                    files = result["files"]
                    output_lines = [f"📁 총 {len(files)}개 파일/폴더 조회됨\n"]

                    for file_item in files:
                        name_str = file_item.get("name", "Unknown")
                        file_id = file_item.get("id", "")
                        is_folder = "folder" in file_item
                        size = file_item.get("size", 0)

                        icon = "📁" if is_folder else "📄"
                        output_lines.append(f"{icon} {name_str}")
                        if not is_folder:
                            output_lines.append(f"   크기: {size:,} bytes")
                        output_lines.append(f"   ID: {file_id}")
                        output_lines.append("")

                    formatted_output = "\n".join(output_lines) + "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                    return [TextContent(type="text", text=formatted_output)]

                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "read_file":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                file_path = arguments.get("file_path")

                result = await self.onedrive_handler.read_file(user_id, file_path)
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "write_file":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                file_path = arguments.get("file_path")
                content = arguments.get("content")
                overwrite = arguments.get("overwrite", True)

                result = await self.onedrive_handler.write_file(user_id, file_path, content, overwrite)
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "delete_file":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                file_path = arguments.get("file_path")

                result = await self.onedrive_handler.delete_file(user_id, file_path)
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "create_folder":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                folder_path = arguments.get("folder_path")
                parent_path = arguments.get("parent_path")

                result = await self.onedrive_handler.create_folder(user_id, folder_path, parent_path)
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            else:
                error_msg = f"알 수 없는 도구: {name}"
                logger.error(error_msg)
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"success": False, "message": error_msg}, indent=2
                        ),
                    )
                ]

        except Exception as e:
            logger.error(f"❌ Tool 실행 오류: {name}, {str(e)}", exc_info=True)
            error_response = {"success": False, "message": f"오류 발생: {str(e)}"}
            return [
                TextContent(type="text", text=json.dumps(error_response, indent=2))
            ]

    # ========================================================================
    # Helper: Convert to dict (for HTTP responses)
    # ========================================================================

    async def call_tool_as_dict(
        self, name: str, arguments: Dict[str, Any], authenticated_user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        HTTP API용 헬퍼: call_tool 결과를 dict로 반환
        """
        try:
            # Handle OneDrive-specific tools
            if name == "list_files":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                folder_path = arguments.get("folder_path")
                search = arguments.get("search")
                result = await self.onedrive_handler.list_files(user_id, folder_path, search)
                return result

            elif name == "read_file":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                file_path = arguments.get("file_path")
                result = await self.onedrive_handler.read_file(user_id, file_path)
                return result

            elif name == "write_file":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                file_path = arguments.get("file_path")
                content = arguments.get("content")
                overwrite = arguments.get("overwrite", True)
                result = await self.onedrive_handler.write_file(user_id, file_path, content, overwrite)
                return result

            elif name == "delete_file":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                file_path = arguments.get("file_path")
                result = await self.onedrive_handler.delete_file(user_id, file_path)
                return result

            elif name == "create_folder":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                folder_path = arguments.get("folder_path")
                parent_path = arguments.get("parent_path")
                result = await self.onedrive_handler.create_folder(user_id, folder_path, parent_path)
                return result

            else:
                raise ValueError(f"알 수 없는 도구: {name}")

        except Exception as e:
            logger.error(f"❌ Tool 실행 오류: {name}, {str(e)}", exc_info=True)
            raise
