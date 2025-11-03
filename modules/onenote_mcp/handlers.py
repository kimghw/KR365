"""
OneNote MCP Handlers
MCP 프로토콜 핸들러 레이어 - HTTP/stdio 공통 로직
"""

import json
from typing import Any, Dict, List, Optional
from mcp.types import Tool, TextContent

from infra.core.logger import get_logger
from .onenote_handler import OneNoteHandler
from .db_service import OneNoteDBService
from .schemas import (
    ListNotebooksRequest,
    ListNotebooksResponse,
    GetPageContentRequest,
    GetPageContentResponse,
    CreatePageRequest,
    CreatePageResponse,
    UpdatePageRequest,
    UpdatePageResponse,
)

logger = get_logger(__name__)


class OneNoteHandlers:
    """OneNote MCP Protocol Handlers"""

    def __init__(self):
        """Initialize handlers with OneNote handler instance"""
        self.onenote_handler = OneNoteHandler()
        self.db_service = OneNoteDBService()
        self.db_service.initialize_tables()
        logger.info("✅ OneNoteHandlers initialized")

    # ========================================================================
    # MCP Protocol: list_tools
    # ========================================================================

    async def handle_list_tools(self) -> List[Tool]:
        """List available MCP tools (OneNote only)"""
        logger.info("🔧 [MCP Handler] list_tools() called")

        # Define OneNote-specific tools
        onenote_tools = [
            Tool(
                name="manage_sections_and_pages",
                description="OneNote 섹션과 페이지를 관리합니다. action 파라미터로 동작을 지정: create_section(섹션 생성), list_sections(섹션 목록 조회), list_pages(페이지 목록 조회)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["create_section", "list_sections", "list_pages"],
                            "description": "수행할 작업: create_section(섹션 생성), list_sections(섹션 목록), list_pages(페이지 목록)"
                        },
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "notebook_id": {
                            "type": "string",
                            "description": "노트북 ID (create_section 시 필수)"
                        },
                        "section_name": {
                            "type": "string",
                            "description": "섹션 이름 (create_section: 생성할 이름, list_sections: 필터링용, list_pages: DB에서 section_id 조회용)"
                        },
                        "section_id": {
                            "type": "string",
                            "description": "섹션 ID (list_pages: 특정 섹션의 페이지만 조회)"
                        },
                        "page_title": {
                            "type": "string",
                            "description": "페이지 제목 (list_pages: 필터링용)"
                        }
                    },
                    "required": ["action"]
                }
            ),
            Tool(
                name="manage_page_content",
                description="OneNote 페이지 내용을 관리합니다. action 파라미터로 동작을 지정: get(내용 조회), create(페이지 생성), delete(페이지 삭제)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["get", "create", "delete"],
                            "description": "수행할 작업: get(내용 조회), create(페이지 생성), delete(페이지 삭제)"
                        },
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "page_id": {
                            "type": "string",
                            "description": "페이지 ID (get, delete 시 필수)"
                        },
                        "section_id": {
                            "type": "string",
                            "description": "섹션 ID (create 시 필수)"
                        },
                        "title": {
                            "type": "string",
                            "description": "페이지 제목 (create 시 필수)"
                        },
                        "content": {
                            "type": "string",
                            "description": "페이지 내용 (HTML) (create 시 필수)"
                        }
                    },
                    "required": ["action"]
                }
            ),
            Tool(
                name="edit_page",
                description="OneNote 페이지 내용을 편집합니다 (내용 추가/append).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "page_id": {
                            "type": "string",
                            "description": "OneNote 페이지 ID"
                        },
                        "content": {
                            "type": "string",
                            "description": "추가할 내용 (HTML)"
                        }
                    },
                    "required": ["page_id", "content"]
                }
            ),
            Tool(
                name="db_onenote_update",
                description="OneNote 섹션 또는 페이지 정보를 데이터베이스에 저장/업데이트합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "section_id": {
                            "type": "string",
                            "description": "섹션 ID (섹션 저장 시 필수)"
                        },
                        "section_name": {
                            "type": "string",
                            "description": "섹션 이름 (섹션 저장 시 필수)"
                        },
                        "notebook_id": {
                            "type": "string",
                            "description": "노트북 ID (섹션 저장 시 선택)"
                        },
                        "notebook_name": {
                            "type": "string",
                            "description": "노트북 이름 (섹션 저장 시 선택)"
                        },
                        "page_id": {
                            "type": "string",
                            "description": "페이지 ID (페이지 저장 시 필수)"
                        },
                        "page_title": {
                            "type": "string",
                            "description": "페이지 제목 (페이지 저장 시 필수)"
                        }
                    },
                    "required": []
                }
            ),
        ]

        # Return OneNote tools only
        return onenote_tools

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
        """Handle MCP tool calls (OneNote only)"""
        logger.info(f"🔨 [MCP Handler] call_tool({name}) with args: {arguments}")

        try:
            # Handle OneNote-specific tools
            if name == "manage_sections_and_pages":
                action = arguments.get("action")
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)

                if action == "create_section":
                    notebook_id = arguments.get("notebook_id")
                    section_name = arguments.get("section_name")
                    result = await self.onenote_handler.create_section(user_id, notebook_id, section_name)

                    # DB에 섹션 자동 저장
                    if result.get("success") and result.get("section"):
                        section = result["section"]
                        section_id = section.get("id")
                        section_display_name = section.get("displayName", section_name)

                        if section_id:
                            self.db_service.save_section(
                                user_id, notebook_id, section_id, section_display_name,
                                notebook_name=None,
                                mark_as_recent=False,
                                update_accessed=True
                            )
                            logger.info(f"✅ 생성된 섹션 DB 저장: {section_display_name}")

                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif action == "list_sections":
                    filter_section_name = arguments.get("section_name")  # 선택적 필터

                    result = await self.onenote_handler.list_sections(user_id)

                    # DB에 섹션들 저장 및 필터링
                    if result.get("success") and result.get("sections"):
                        sections = result["sections"]

                        for section in sections:
                            section_id = section.get("id")
                            section_name = section.get("displayName") or section.get("name")
                            # parentNotebook에서 notebook 정보 추출
                            parent_notebook = section.get("parentNotebook", {})
                            notebook_id = parent_notebook.get("id", "")
                            notebook_name = parent_notebook.get("displayName", "")

                            if section_id and section_name:
                                self.db_service.save_section(
                                    user_id, notebook_id, section_id, section_name,
                                    notebook_name=notebook_name,
                                    update_accessed=True  # 조회 시 last_accessed 업데이트
                                )
                                logger.info(f"✅ 섹션 자동 저장: {section_name}")

                        # section_name 필터링
                        if filter_section_name:
                            sections = [s for s in sections if filter_section_name.lower() in (s.get("displayName") or s.get("name") or "").lower()]
                            result["sections"] = sections
                            logger.info(f"🔍 섹션 이름 필터 적용: '{filter_section_name}' -> {len(sections)}개")

                        # 사용자 친화적인 출력 포맷 추가
                        output_lines = [f"📁 총 {len(sections)}개 섹션 조회됨\n"]
                        for section in sections:
                            section_name = section.get("displayName") or section.get("name")
                            section_id = section.get("id")
                            web_url = section.get("links", {}).get("oneNoteWebUrl", {}).get("href")
                            output_lines.append(f"• {section_name}")
                            output_lines.append(f"  ID: {section_id}")
                            if web_url:
                                output_lines.append(f"  🔗 {web_url}")
                            output_lines.append("")

                        formatted_output = "\n".join(output_lines) + "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                        return [TextContent(type="text", text=formatted_output)]

                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif action == "list_pages":
                    section_id = arguments.get("section_id")
                    section_name_filter = arguments.get("section_name")
                    page_title_filter = arguments.get("page_title")

                    # section_name으로 section_id 조회
                    if section_name_filter and not section_id:
                        section_info = self.db_service.get_section(user_id, section_name_filter)
                        if section_info:
                            section_id = section_info['section_id']
                            logger.info(f"📌 DB에서 섹션 ID 조회: {section_name_filter} -> {section_id}")

                    result = await self.onenote_handler.list_pages(user_id, section_id)

                    # DB에 페이지들 저장 및 필터링
                    if result.get("success") and result.get("pages"):
                        pages = result["pages"]

                        for page in pages:
                            page_id = page.get("id")
                            page_title = page.get("title")
                            # parentSection에서 section_id 추출 (모든 페이지 조회 시)
                            if not section_id:
                                parent_section = page.get("parentSection", {})
                                page_section_id = parent_section.get("id", "")
                            else:
                                page_section_id = section_id

                            if page_id and page_title and page_section_id:
                                self.db_service.save_page(
                                    user_id, page_section_id, page_id, page_title,
                                    update_accessed=True  # 조회 시 last_accessed 업데이트
                                )
                                logger.info(f"✅ 페이지 자동 저장: {page_title}")

                        # page_title 필터링
                        if page_title_filter:
                            pages = [p for p in pages if page_title_filter.lower() in (p.get("title") or "").lower()]
                            result["pages"] = pages
                            logger.info(f"🔍 페이지 제목 필터 적용: '{page_title_filter}' -> {len(pages)}개")

                        # 사용자 친화적인 출력 포맷 추가
                        output_lines = [f"📄 총 {len(pages)}개 페이지 조회됨\n"]
                        for page in pages:
                            page_title = page.get("title", "제목 없음")
                            page_id = page.get("id")
                            web_url = page.get("links", {}).get("oneNoteWebUrl", {}).get("href")
                            output_lines.append(f"• {page_title}")
                            output_lines.append(f"  ID: {page_id}")
                            if web_url:
                                output_lines.append(f"  🔗 {web_url}")
                            output_lines.append("")

                        formatted_output = "\n".join(output_lines) + "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                        return [TextContent(type="text", text=formatted_output)]

                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                else:
                    error_msg = f"알 수 없는 action: {action}"
                    logger.error(error_msg)
                    return [TextContent(type="text", text=json.dumps({"success": False, "message": error_msg}, indent=2))]

            elif name == "manage_page_content":
                action = arguments.get("action")
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)

                if action == "get":
                    page_id = arguments.get("page_id")

                    # 페이지 ID가 없으면 최근 사용 페이지 조회
                    if not page_id:
                        recent_page = self.db_service.get_recent_page(user_id)
                        if recent_page:
                            page_id = recent_page['page_id']
                            logger.info(f"📌 최근 사용 페이지 자동 선택: {recent_page['page_title']} ({page_id})")

                    result = await self.onenote_handler.get_page_content(user_id, page_id)

                    # 조회한 페이지를 최근 사용으로 마킹
                    if result.get("success") and page_id:
                        page_title = result.get("title", "")
                        # DB에서 섹션 ID 조회
                        page_info = self.db_service.get_page(user_id, page_title) if page_title else None
                        if page_info:
                            self.db_service.save_page(
                                user_id,
                                page_info['section_id'],
                                page_id,
                                page_title,
                                mark_as_recent=True,
                                update_accessed=True
                            )

                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif action == "create":
                    section_id = arguments.get("section_id")
                    title = arguments.get("title")
                    content = arguments.get("content")

                    # 섹션 ID가 없으면 최근 사용 섹션 조회
                    if not section_id:
                        recent_section = self.db_service.get_recent_section(user_id)
                        if recent_section:
                            section_id = recent_section['section_id']
                            logger.info(f"📌 최근 사용 섹션 자동 선택: {recent_section['section_name']} ({section_id})")

                    result = await self.onenote_handler.create_page(user_id, section_id, title, content)

                    # DB에 페이지 자동 저장
                    if result.get("success") and result.get("page_id"):
                        self.db_service.save_page(
                            user_id,
                            section_id,
                            result["page_id"],
                            title,
                            mark_as_recent=False,
                            update_accessed=True
                        )
                        logger.info(f"✅ 생성된 페이지 DB 저장: {title}")

                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                elif action == "delete":
                    page_id = arguments.get("page_id")

                    if not page_id:
                        error_msg = "페이지 ID가 필요합니다"
                        logger.error(error_msg)
                        return [TextContent(type="text", text=json.dumps({"success": False, "message": error_msg}, indent=2))]

                    result = await self.onenote_handler.delete_page(user_id, page_id)

                    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

                else:
                    error_msg = f"알 수 없는 action: {action}"
                    logger.error(error_msg)
                    return [TextContent(type="text", text=json.dumps({"success": False, "message": error_msg}, indent=2))]

            elif name == "edit_page":
                request = UpdatePageRequest(**arguments)

                # 페이지 ID가 없으면 최근 사용 페이지 조회
                page_id = request.page_id
                if not page_id:
                    recent_page = self.db_service.get_recent_page(request.user_id)
                    if recent_page:
                        page_id = recent_page['page_id']
                        logger.info(f"📌 최근 사용 페이지 자동 선택: {recent_page['page_title']} ({page_id})")

                result = await self.onenote_handler.update_page(
                    request.user_id,
                    page_id,
                    request.content
                )

                # 업데이트한 페이지를 최근 사용으로 마킹
                if result.get("success") and page_id:
                    page_info = self.db_service.get_page(request.user_id, "")  # 제목으로 조회 안함
                    if page_info:
                        self.db_service.save_page(
                            request.user_id,
                            page_info.get('section_id', ''),
                            page_id,
                            page_info.get('page_title', ''),
                            mark_as_recent=True
                        )

                response = UpdatePageResponse(**result)
                return [TextContent(type="text", text=response.model_dump_json(indent=2))]

            elif name == "db_onenote_update":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                section_id = arguments.get("section_id")
                section_name = arguments.get("section_name")
                notebook_id = arguments.get("notebook_id")
                notebook_name = arguments.get("notebook_name")
                page_id = arguments.get("page_id")
                page_title = arguments.get("page_title")

                results = []

                # 섹션 정보 저장
                if section_id and section_name:
                    section_id = self.onenote_handler._normalize_onenote_id(section_id)
                    if notebook_id:
                        notebook_id = self.onenote_handler._normalize_onenote_id(notebook_id)

                    success = self.db_service.save_section(
                        user_id, notebook_id or "", section_id, section_name,
                        notebook_name=notebook_name,
                        update_accessed=True
                    )
                    results.append({
                        "type": "section",
                        "success": success,
                        "message": f"섹션 정보 저장: {section_name}" if success else "섹션 저장 실패"
                    })

                # 페이지 정보 저장
                if page_id and page_title:
                    page_id = self.onenote_handler._normalize_onenote_id(page_id)
                    if section_id:
                        section_id = self.onenote_handler._normalize_onenote_id(section_id)

                    success = self.db_service.save_page(
                        user_id, section_id or "", page_id, page_title,
                        update_accessed=True
                    )
                    results.append({
                        "type": "page",
                        "success": success,
                        "message": f"페이지 정보 저장: {page_title}" if success else "페이지 저장 실패"
                    })

                result = {
                    "success": all(r["success"] for r in results) if results else False,
                    "updates": results
                }
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
            # Handle OneNote-specific tools
            if name == "manage_sections_and_pages":
                action = arguments.get("action")
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)

                if action == "create_section":
                    notebook_id = arguments.get("notebook_id")
                    section_name = arguments.get("section_name")
                    result = await self.onenote_handler.create_section(user_id, notebook_id, section_name)

                    # DB에 섹션 저장
                    if result.get("success") and result.get("section"):
                        section_id = result["section"].get("id")
                        if section_id:
                            self.db_service.save_section(user_id, notebook_id, section_id, section_name)

                    return result

                elif action == "list_sections":
                    filter_section_name = arguments.get("section_name")
                    result = await self.onenote_handler.list_sections(user_id)

                    # DB에 섹션들 저장 및 필터링
                    if result.get("success") and result.get("sections"):
                        sections = result["sections"]
                        for section in sections:
                            section_id = section.get("id")
                            section_name = section.get("displayName") or section.get("name")
                            parent_notebook = section.get("parentNotebook", {})
                            notebook_id = parent_notebook.get("id", "")
                            notebook_name = parent_notebook.get("displayName", "")

                            if section_id and section_name:
                                self.db_service.save_section(
                                    user_id, notebook_id, section_id, section_name,
                                    notebook_name=notebook_name,
                                    update_accessed=True
                                )

                        if filter_section_name:
                            sections = [s for s in sections if filter_section_name.lower() in (s.get("displayName") or s.get("name") or "").lower()]
                            result["sections"] = sections

                    return result

                elif action == "list_pages":
                    section_id = arguments.get("section_id")
                    section_name_filter = arguments.get("section_name")
                    page_title_filter = arguments.get("page_title")

                    # section_name으로 section_id 조회
                    if section_name_filter and not section_id:
                        section_info = self.db_service.get_section(user_id, section_name_filter)
                        if section_info:
                            section_id = section_info['section_id']

                    result = await self.onenote_handler.list_pages(user_id, section_id)

                    # DB에 페이지들 저장 및 필터링
                    if result.get("success") and result.get("pages"):
                        pages = result["pages"]
                        for page in pages:
                            page_id = page.get("id")
                            page_title = page.get("title")
                            if not section_id:
                                parent_section = page.get("parentSection", {})
                                page_section_id = parent_section.get("id", "")
                            else:
                                page_section_id = section_id

                            if page_id and page_title and page_section_id:
                                self.db_service.save_page(
                                    user_id, page_section_id, page_id, page_title,
                                    update_accessed=True
                                )

                        if page_title_filter:
                            pages = [p for p in pages if page_title_filter.lower() in (p.get("title") or "").lower()]
                            result["pages"] = pages

                    return result

                else:
                    raise ValueError(f"알 수 없는 action: {action}")

            elif name == "manage_page_content":
                action = arguments.get("action")
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)

                if action == "get":
                    page_id = arguments.get("page_id")
                    result = await self.onenote_handler.get_page_content(user_id, page_id)
                    return result

                elif action == "create":
                    section_id = arguments.get("section_id")
                    title = arguments.get("title")
                    content = arguments.get("content")
                    result = await self.onenote_handler.create_page(user_id, section_id, title, content)

                    # DB에 페이지 저장
                    if result.get("success") and result.get("page_id"):
                        self.db_service.save_page(user_id, section_id, result["page_id"], title)

                    return result

                elif action == "delete":
                    page_id = arguments.get("page_id")
                    result = await self.onenote_handler.delete_page(user_id, page_id)
                    return result

                else:
                    raise ValueError(f"알 수 없는 action: {action}")

            elif name == "edit_page":
                request = UpdatePageRequest(**arguments)
                result = await self.onenote_handler.update_page(
                    request.user_id,
                    request.page_id,
                    request.content
                )
                return result

            elif name == "db_onenote_update":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                section_id = arguments.get("section_id")
                section_name = arguments.get("section_name")
                notebook_id = arguments.get("notebook_id")
                notebook_name = arguments.get("notebook_name")
                page_id = arguments.get("page_id")
                page_title = arguments.get("page_title")

                results = []

                # 섹션 정보 저장
                if section_id and section_name:
                    section_id = self.onenote_handler._normalize_onenote_id(section_id)
                    if notebook_id:
                        notebook_id = self.onenote_handler._normalize_onenote_id(notebook_id)

                    success = self.db_service.save_section(
                        user_id, notebook_id or "", section_id, section_name,
                        notebook_name=notebook_name,
                        update_accessed=True
                    )
                    results.append({
                        "type": "section",
                        "success": success,
                        "message": f"섹션 정보 저장: {section_name}" if success else "섹션 저장 실패"
                    })

                # 페이지 정보 저장
                if page_id and page_title:
                    page_id = self.onenote_handler._normalize_onenote_id(page_id)
                    if section_id:
                        section_id = self.onenote_handler._normalize_onenote_id(section_id)

                    success = self.db_service.save_page(
                        user_id, section_id or "", page_id, page_title,
                        update_accessed=True
                    )
                    results.append({
                        "type": "page",
                        "success": success,
                        "message": f"페이지 정보 저장: {page_title}" if success else "페이지 저장 실패"
                    })

                return {
                    "success": all(r["success"] for r in results) if results else False,
                    "updates": results
                }

            else:
                raise ValueError(f"알 수 없는 도구: {name}")

        except Exception as e:
            logger.error(f"❌ Tool 실행 오류: {name}, {str(e)}", exc_info=True)
            raise
