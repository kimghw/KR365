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
                description="OneNote 페이지 내용을 편집합니다. 다양한 작업 지원: append(끝에 추가), prepend(시작에 추가), insert(특정 위치에 삽입), replace(내용 교체), clean(페이지 정리)",
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
                        "action": {
                            "type": "string",
                            "enum": ["append", "prepend", "insert", "replace", "clean"],
                            "description": "작업 유형: append(끝에 추가, 기본값), prepend(시작에 추가), insert(특정 위치에 삽입), replace(내용 교체), clean(페이지 정리)",
                            "default": "append"
                        },
                        "content": {
                            "type": "string",
                            "description": "추가/변경할 내용 (HTML) - clean action에서는 선택 사항"
                        },
                        "target": {
                            "type": "string",
                            "description": "특정 data-id 타겟 (예: #p:{guid}) - 지정하지 않으면 자동으로 찾음"
                        },
                        "position": {
                            "type": "string",
                            "enum": ["before", "after"],
                            "description": "insert 작업 시 삽입 위치 (before 또는 after, 기본값: after)",
                            "default": "after"
                        },
                        "keep_title": {
                            "type": "boolean",
                            "description": "clean 작업 시 제목 유지 여부 (기본값: true)",
                            "default": True
                        }
                    },
                    "required": ["page_id"]
                }
            ),
            Tool(
                name="sync_onenote_db",
                description="OneNote API에서 최신 섹션/페이지 정보를 가져와 로컬 DB와 동기화합니다. 삭제되거나 변경된 항목을 자동으로 감지하여 DB를 업데이트합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "sync_sections": {
                            "type": "boolean",
                            "description": "섹션 정보 동기화 여부 (기본값: true)",
                            "default": True
                        },
                        "sync_pages": {
                            "type": "boolean",
                            "description": "페이지 정보 동기화 여부 (기본값: true)",
                            "default": True
                        }
                    },
                    "required": []
                }
            ),
            Tool(
                name="get_recent_onenote_items",
                description="최근 사용한 OneNote 섹션과 페이지 목록을 조회합니다. 기본적으로 각각 3개씩 테이블 형식으로 표시합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "section_limit": {
                            "type": "integer",
                            "description": "조회할 섹션 개수 (기본값: 3)",
                            "default": 3
                        },
                        "page_limit": {
                            "type": "integer",
                            "description": "조회할 페이지 개수 (기본값: 3)",
                            "default": 3
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

                    # 먼저 DB에서 섹션 목록 조회
                    db_sections = self.db_service.list_sections(user_id)

                    # DB에 섹션이 없으면 API에서 조회 및 저장
                    if not db_sections:
                        logger.info("📌 DB에 섹션 정보 없음 - API에서 조회 시작")
                        result = await self.onenote_handler.list_sections(user_id)

                        # DB에 섹션들 저장
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
                    else:
                        logger.info(f"📌 DB에서 섹션 {len(db_sections)}개 조회")
                        result = await self.onenote_handler.list_sections(user_id)
                        sections = result.get("sections", [])

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

                    # 먼저 DB에서 페이지 목록 조회
                    db_pages = self.db_service.list_pages(user_id, section_id)

                    # DB에 페이지가 없으면 API에서 조회 및 저장
                    if not db_pages:
                        logger.info("📌 DB에 페이지 정보 없음 - API에서 조회 시작")
                        result = await self.onenote_handler.list_pages(user_id, section_id)

                        # DB에 페이지들 저장
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
                    else:
                        logger.info(f"📌 DB에서 페이지 {len(db_pages)}개 조회")
                        result = await self.onenote_handler.list_pages(user_id, section_id)
                        pages = result.get("pages", [])

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
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                page_id = arguments.get("page_id")
                action = arguments.get("action", "append")
                content = arguments.get("content", "")
                target = arguments.get("target")
                position = arguments.get("position", "after")
                keep_title = arguments.get("keep_title", True)

                # 페이지 ID가 없으면 최근 사용 페이지 조회
                if not page_id:
                    recent_page = self.db_service.get_recent_page(user_id)
                    if recent_page:
                        page_id = recent_page['page_id']
                        logger.info(f"📌 최근 사용 페이지 자동 선택: {recent_page['page_title']} ({page_id})")

                # clean 작업인 경우
                if action == "clean":
                    result = await self.onenote_handler.clean_page(
                        user_id,
                        page_id,
                        keep_title=keep_title
                    )
                else:
                    # content가 필요한 작업에서 content가 없으면 에러
                    if not content:
                        error_msg = f"{action} 작업에는 content가 필요합니다"
                        logger.error(error_msg)
                        return [TextContent(type="text", text=json.dumps({"success": False, "message": error_msg}, indent=2))]

                    # 일반 업데이트 작업
                    result = await self.onenote_handler.update_page(
                        user_id,
                        page_id,
                        content,
                        action=action,
                        target=target,
                        position=position
                    )

                # 업데이트한 페이지를 최근 사용으로 마킹
                if result.get("success") and page_id:
                    page_info = self.db_service.get_page(user_id, "")  # 제목으로 조회 안함
                    if page_info:
                        self.db_service.save_page(
                            user_id,
                            page_info.get('section_id', ''),
                            page_id,
                            page_info.get('page_title', ''),
                            mark_as_recent=True
                        )

                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "sync_onenote_db":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                sync_sections = arguments.get("sync_sections", True)
                sync_pages = arguments.get("sync_pages", True)

                results = []
                stats = {
                    "sections_added": 0,
                    "sections_updated": 0,
                    "sections_deleted": 0,
                    "pages_added": 0,
                    "pages_updated": 0,
                    "pages_deleted": 0
                }

                # 섹션 동기화
                if sync_sections:
                    logger.info("🔄 섹션 동기화 시작...")
                    sections_result = await self.onenote_handler.list_sections(user_id)

                    if sections_result.get("success") and sections_result.get("sections"):
                        api_sections = sections_result["sections"]
                        api_section_ids = set()

                        # API에서 가져온 섹션 저장/업데이트
                        for section in api_sections:
                            section_id = section.get("id")
                            section_name = section.get("displayName") or section.get("name")
                            parent_notebook = section.get("parentNotebook", {})
                            notebook_id = parent_notebook.get("id", "")
                            notebook_name = parent_notebook.get("displayName", "")

                            if section_id and section_name:
                                api_section_ids.add(section_id)

                                # 기존 DB에 있는지 확인
                                existing = self.db_service.get_section(user_id, section_name)

                                self.db_service.save_section(
                                    user_id, notebook_id, section_id, section_name,
                                    notebook_name=notebook_name,
                                    update_accessed=False  # 동기화는 accessed 시간 변경 안함
                                )

                                if existing:
                                    stats["sections_updated"] += 1
                                    logger.info(f"✅ 섹션 업데이트: {section_name}")
                                else:
                                    stats["sections_added"] += 1
                                    logger.info(f"✅ 섹션 추가: {section_name}")

                        # DB에는 있지만 API에 없는 섹션 삭제 처리
                        db_sections = self.db_service.list_sections(user_id)
                        for db_section in db_sections:
                            db_section_id = db_section.get("section_id")
                            if db_section_id not in api_section_ids:
                                section_name = db_section.get("section_name", "")
                                self.db_service.delete_section(user_id, db_section_id)
                                stats["sections_deleted"] += 1
                                logger.info(f"🗑️ 섹션 삭제 (API에 없음): {section_name}")

                        results.append({
                            "type": "sections",
                            "success": True,
                            "message": f"섹션 동기화 완료 (추가: {stats['sections_added']}, 업데이트: {stats['sections_updated']}, 삭제: {stats['sections_deleted']})"
                        })
                    else:
                        results.append({
                            "type": "sections",
                            "success": False,
                            "message": "섹션 정보 조회 실패"
                        })

                # 페이지 동기화
                if sync_pages:
                    logger.info("🔄 페이지 동기화 시작...")
                    pages_result = await self.onenote_handler.list_pages(user_id)

                    if pages_result.get("success") and pages_result.get("pages"):
                        api_pages = pages_result["pages"]
                        api_page_ids = set()

                        # API에서 가져온 페이지 저장/업데이트
                        for page in api_pages:
                            page_id = page.get("id")
                            page_title = page.get("title")
                            parent_section = page.get("parentSection", {})
                            page_section_id = parent_section.get("id", "")

                            if page_id and page_title and page_section_id:
                                api_page_ids.add(page_id)

                                # 기존 DB에 있는지 확인
                                existing = self.db_service.get_page(user_id, page_title)

                                self.db_service.save_page(
                                    user_id, page_section_id, page_id, page_title,
                                    update_accessed=False  # 동기화는 accessed 시간 변경 안함
                                )

                                if existing:
                                    stats["pages_updated"] += 1
                                    logger.info(f"✅ 페이지 업데이트: {page_title}")
                                else:
                                    stats["pages_added"] += 1
                                    logger.info(f"✅ 페이지 추가: {page_title}")

                        # DB에는 있지만 API에 없는 페이지 삭제 처리
                        db_pages = self.db_service.list_pages(user_id)
                        for db_page in db_pages:
                            db_page_id = db_page.get("page_id")
                            if db_page_id not in api_page_ids:
                                page_title = db_page.get("page_title", "")
                                self.db_service.delete_page(user_id, db_page_id)
                                stats["pages_deleted"] += 1
                                logger.info(f"🗑️ 페이지 삭제 (API에 없음): {page_title}")

                        results.append({
                            "type": "pages",
                            "success": True,
                            "message": f"페이지 동기화 완료 (추가: {stats['pages_added']}, 업데이트: {stats['pages_updated']}, 삭제: {stats['pages_deleted']})"
                        })
                    else:
                        results.append({
                            "type": "pages",
                            "success": False,
                            "message": "페이지 정보 조회 실패"
                        })

                result = {
                    "success": all(r["success"] for r in results) if results else False,
                    "stats": stats,
                    "updates": results
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "get_recent_onenote_items":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                section_limit = arguments.get("section_limit", 3)
                page_limit = arguments.get("page_limit", 3)

                # 최근 사용한 섹션 조회
                recent_sections = self.db_service.get_recent_section(user_id, section_limit)
                if not isinstance(recent_sections, list):
                    recent_sections = [recent_sections] if recent_sections else []

                # DB에 섹션 정보가 없으면 API에서 조회 및 저장
                if not recent_sections:
                    logger.info("📌 DB에 섹션 정보 없음 - API에서 조회 시작")
                    sections_result = await self.onenote_handler.list_sections(user_id)
                    if sections_result.get("success") and sections_result.get("sections"):
                        for section in sections_result["sections"]:
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
                        # 다시 DB에서 최근 섹션 조회
                        recent_sections = self.db_service.get_recent_section(user_id, section_limit)
                        if not isinstance(recent_sections, list):
                            recent_sections = [recent_sections] if recent_sections else []

                # 최근 사용한 페이지 조회
                recent_pages = self.db_service.get_recent_page(user_id, page_limit)
                if not isinstance(recent_pages, list):
                    recent_pages = [recent_pages] if recent_pages else []

                # DB에 페이지 정보가 없으면 API에서 조회 및 저장
                if not recent_pages:
                    logger.info("📌 DB에 페이지 정보 없음 - API에서 조회 시작")
                    pages_result = await self.onenote_handler.list_pages(user_id)
                    if pages_result.get("success") and pages_result.get("pages"):
                        for page in pages_result["pages"]:
                            page_id = page.get("id")
                            page_title = page.get("title")
                            parent_section = page.get("parentSection", {})
                            page_section_id = parent_section.get("id", "")

                            if page_id and page_title and page_section_id:
                                self.db_service.save_page(
                                    user_id, page_section_id, page_id, page_title,
                                    update_accessed=True
                                )
                        # 다시 DB에서 최근 페이지 조회
                        recent_pages = self.db_service.get_recent_page(user_id, page_limit)
                        if not isinstance(recent_pages, list):
                            recent_pages = [recent_pages] if recent_pages else []

                # 테이블 형식으로 출력 준비
                output_lines = []

                # 섹션 테이블
                output_lines.append("📂 최근 사용한 섹션")
                output_lines.append("=" * 120)

                if recent_sections:
                    # 헤더
                    output_lines.append(f"{'섹션명':<30} {'노트북':<15} {'최근 사용':<20}")
                    output_lines.append(f"{'섹션 ID':<120}")
                    output_lines.append("-" * 120)

                    for section in recent_sections:
                        section_name = section.get('section_name', '')[:30]
                        section_id = section.get('section_id', '')
                        notebook_name = section.get('notebook_name', '알 수 없음')[:15]
                        last_accessed = section.get('last_accessed', '')
                        if last_accessed:
                            last_accessed = last_accessed.split('.')[0][:20]  # 밀리초 제거

                        output_lines.append(f"{section_name:<30} {notebook_name:<15} {last_accessed:<20}")
                        output_lines.append(f"  ID: {section_id}")
                        output_lines.append("")  # 빈 줄로 구분
                else:
                    output_lines.append("최근 사용한 섹션이 없습니다.")

                output_lines.append("")  # 빈 줄

                # 페이지 테이블
                output_lines.append("📄 최근 사용한 페이지")
                output_lines.append("=" * 120)

                if recent_pages:
                    # 헤더
                    output_lines.append(f"{'페이지 제목':<35} {'최근 사용':<20}")
                    output_lines.append(f"{'페이지 ID':<120}")
                    output_lines.append("-" * 120)

                    for page in recent_pages:
                        page_title = page.get('page_title', '')[:35]
                        page_id = page.get('page_id', '')
                        last_accessed = page.get('last_accessed', '')
                        if last_accessed:
                            last_accessed = last_accessed.split('.')[0][:20]  # 밀리초 제거

                        output_lines.append(f"{page_title:<35} {last_accessed:<20}")
                        output_lines.append(f"  ID: {page_id}")
                        output_lines.append("")  # 빈 줄로 구분
                else:
                    output_lines.append("최근 사용한 페이지가 없습니다.")

                result_text = "\n".join(output_lines)

                return [TextContent(type="text", text=result_text)]

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

                    # 먼저 DB에서 섹션 목록 조회
                    db_sections = self.db_service.list_sections(user_id)

                    # DB에 섹션이 없으면 API에서 조회 및 저장
                    if not db_sections:
                        logger.info("📌 DB에 섹션 정보 없음 - API에서 조회 시작")
                        result = await self.onenote_handler.list_sections(user_id)

                        # DB에 섹션들 저장
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
                    else:
                        logger.info(f"📌 DB에서 섹션 {len(db_sections)}개 조회")
                        result = await self.onenote_handler.list_sections(user_id)
                        sections = result.get("sections", [])

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

                    # 먼저 DB에서 페이지 목록 조회
                    db_pages = self.db_service.list_pages(user_id, section_id)

                    # DB에 페이지가 없으면 API에서 조회 및 저장
                    if not db_pages:
                        logger.info("📌 DB에 페이지 정보 없음 - API에서 조회 시작")
                        result = await self.onenote_handler.list_pages(user_id, section_id)

                        # DB에 페이지들 저장
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
                    else:
                        logger.info(f"📌 DB에서 페이지 {len(db_pages)}개 조회")
                        result = await self.onenote_handler.list_pages(user_id, section_id)
                        pages = result.get("pages", [])

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
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                page_id = arguments.get("page_id")
                action = arguments.get("action", "append")
                content = arguments.get("content", "")
                target = arguments.get("target")
                position = arguments.get("position", "after")
                keep_title = arguments.get("keep_title", True)

                # clean 작업인 경우
                if action == "clean":
                    result = await self.onenote_handler.clean_page(
                        user_id,
                        page_id,
                        keep_title=keep_title
                    )
                else:
                    # 일반 업데이트 작업
                    result = await self.onenote_handler.update_page(
                        user_id,
                        page_id,
                        content,
                        action=action,
                        target=target,
                        position=position
                    )
                return result

            elif name == "sync_onenote_db":
                user_id = self._get_authenticated_user_id(arguments, authenticated_user_id)
                sync_sections = arguments.get("sync_sections", True)
                sync_pages = arguments.get("sync_pages", True)

                results = []
                stats = {
                    "sections_added": 0,
                    "sections_updated": 0,
                    "sections_deleted": 0,
                    "pages_added": 0,
                    "pages_updated": 0,
                    "pages_deleted": 0
                }

                # 섹션 동기화
                if sync_sections:
                    sections_result = await self.onenote_handler.list_sections(user_id)

                    if sections_result.get("success") and sections_result.get("sections"):
                        api_sections = sections_result["sections"]
                        api_section_ids = set()

                        for section in api_sections:
                            section_id = section.get("id")
                            section_name = section.get("displayName") or section.get("name")
                            parent_notebook = section.get("parentNotebook", {})
                            notebook_id = parent_notebook.get("id", "")
                            notebook_name = parent_notebook.get("displayName", "")

                            if section_id and section_name:
                                api_section_ids.add(section_id)
                                existing = self.db_service.get_section(user_id, section_name)

                                self.db_service.save_section(
                                    user_id, notebook_id, section_id, section_name,
                                    notebook_name=notebook_name,
                                    update_accessed=False
                                )

                                if existing:
                                    stats["sections_updated"] += 1
                                else:
                                    stats["sections_added"] += 1

                        db_sections = self.db_service.list_sections(user_id)
                        for db_section in db_sections:
                            db_section_id = db_section.get("section_id")
                            if db_section_id not in api_section_ids:
                                self.db_service.delete_section(user_id, db_section_id)
                                stats["sections_deleted"] += 1

                        results.append({
                            "type": "sections",
                            "success": True,
                            "message": f"섹션 동기화 완료 (추가: {stats['sections_added']}, 업데이트: {stats['sections_updated']}, 삭제: {stats['sections_deleted']})"
                        })
                    else:
                        results.append({
                            "type": "sections",
                            "success": False,
                            "message": "섹션 정보 조회 실패"
                        })

                # 페이지 동기화
                if sync_pages:
                    pages_result = await self.onenote_handler.list_pages(user_id)

                    if pages_result.get("success") and pages_result.get("pages"):
                        api_pages = pages_result["pages"]
                        api_page_ids = set()

                        for page in api_pages:
                            page_id = page.get("id")
                            page_title = page.get("title")
                            parent_section = page.get("parentSection", {})
                            page_section_id = parent_section.get("id", "")

                            if page_id and page_title and page_section_id:
                                api_page_ids.add(page_id)
                                existing = self.db_service.get_page(user_id, page_title)

                                self.db_service.save_page(
                                    user_id, page_section_id, page_id, page_title,
                                    update_accessed=False
                                )

                                if existing:
                                    stats["pages_updated"] += 1
                                else:
                                    stats["pages_added"] += 1

                        db_pages = self.db_service.list_pages(user_id)
                        for db_page in db_pages:
                            db_page_id = db_page.get("page_id")
                            if db_page_id not in api_page_ids:
                                self.db_service.delete_page(user_id, db_page_id)
                                stats["pages_deleted"] += 1

                        results.append({
                            "type": "pages",
                            "success": True,
                            "message": f"페이지 동기화 완료 (추가: {stats['pages_added']}, 업데이트: {stats['pages_updated']}, 삭제: {stats['pages_deleted']})"
                        })
                    else:
                        results.append({
                            "type": "pages",
                            "success": False,
                            "message": "페이지 정보 조회 실패"
                        })

                return {
                    "success": all(r["success"] for r in results) if results else False,
                    "stats": stats,
                    "updates": results
                }

            else:
                raise ValueError(f"알 수 없는 도구: {name}")

        except Exception as e:
            logger.error(f"❌ Tool 실행 오류: {name}, {str(e)}", exc_info=True)
            raise
