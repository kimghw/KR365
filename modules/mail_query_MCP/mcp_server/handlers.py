"""MCP Protocol handlers"""

import json
import logging
from typing import Any, Dict, List, Optional

from mcp.types import Prompt, PromptArgument, PromptMessage, TextContent, Tool

from infra.core.logger import get_logger
from infra.core.error_messages import ErrorCode, MCPError
from infra.core.database import get_database_manager
from infra.handlers.attachment_filter_handlers import AttachmentFilterHandlers
from modules.calendar_mcp import CalendarHandlers
from .prompts import get_prompt
from .tools import MailAttachmentTools  # This now imports from tools/__init__.py
from .utils import preprocess_arguments

logger = get_logger(__name__)


def get_default_user_id() -> Optional[str]:
    """
    Get default user_id from database based on token validity and last usage

    우선순위:
    1. 유효한 토큰이 있고 최근 사용한 계정 (last_used_at 기준)
    2. 유효한 토큰이 있는 계정 (만료 시간이 가장 먼 계정)
    3. 최근 사용한 계정 (last_used_at 기준)
    4. 계정이 1개만 있는 경우 해당 계정

    Returns:
        user_id if valid account found, None otherwise
    """
    try:
        from datetime import datetime, timezone

        db = get_database_manager()

        # 활성화된 계정 조회 (last_used_at 추가)
        query = """
            SELECT user_id, token_expiry, access_token, last_used_at
            FROM accounts
            WHERE is_active = 1
            ORDER BY last_used_at DESC NULLS LAST, token_expiry DESC NULLS LAST
        """
        rows = db.fetch_all(query)

        if len(rows) == 0:
            logger.warning("⚠️ 등록된 계정이 없습니다")
            return None

        # 유효한 토큰을 가진 계정 필터링
        now = datetime.now(timezone.utc)
        valid_accounts = []

        for row in rows:
            # Convert sqlite3.Row to dict for .get() method
            row_dict = dict(row)
            user_id = row_dict['user_id']
            token_expiry = row_dict['token_expiry']
            access_token = row_dict['access_token']
            last_used_at = row_dict.get('last_used_at')

            # access_token과 token_expiry가 모두 있고, 만료되지 않은 경우
            if access_token and token_expiry:
                try:
                    # Parse token_expiry (ISO format string to datetime)
                    if isinstance(token_expiry, str):
                        # Remove microseconds if present for cleaner parsing
                        if '.' in token_expiry:
                            token_expiry = token_expiry.split('.')[0]
                        expiry_dt = datetime.fromisoformat(token_expiry.replace('Z', '+00:00'))
                    else:
                        expiry_dt = token_expiry

                    # Make timezone-aware if naive
                    if expiry_dt.tzinfo is None:
                        expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)

                    if expiry_dt > now:
                        # Parse last_used_at
                        last_used_dt = None
                        if last_used_at:
                            try:
                                if isinstance(last_used_at, str):
                                    if '.' in last_used_at:
                                        last_used_at = last_used_at.split('.')[0]
                                    last_used_dt = datetime.fromisoformat(last_used_at.replace('Z', '+00:00'))
                                else:
                                    last_used_dt = last_used_at

                                if last_used_dt and last_used_dt.tzinfo is None:
                                    last_used_dt = last_used_dt.replace(tzinfo=timezone.utc)
                            except Exception as e:
                                logger.debug(f"last_used_at 파싱 실패: {e}")

                        valid_accounts.append({
                            'user_id': user_id,
                            'token_expiry': expiry_dt,
                            'last_used_at': last_used_dt
                        })
                        logger.info(f"✅ 유효한 토큰 발견: {user_id} (만료: {expiry_dt}, 마지막 사용: {last_used_dt or 'N/A'})")
                except Exception as e:
                    logger.warning(f"⚠️ {user_id}의 토큰 만료 시간 파싱 실패: {e}")
                    continue

        # 우선순위 1: 유효한 토큰이 있고 최근 사용한 계정
        if valid_accounts:
            # last_used_at이 있는 계정 우선, 없으면 token_expiry 기준
            valid_with_last_used = [acc for acc in valid_accounts if acc['last_used_at']]
            if valid_with_last_used:
                selected = max(valid_with_last_used, key=lambda x: x['last_used_at'])
                user_id = selected['user_id']
                logger.info(f"✅ 최근 사용 계정 자동 선택: {user_id} (마지막 사용: {selected['last_used_at']})")
                return user_id

            # last_used_at이 없으면 만료 시간이 가장 먼 계정 선택
            selected = max(valid_accounts, key=lambda x: x['token_expiry'])
            user_id = selected['user_id']
            logger.info(f"✅ 유효한 토큰 계정 자동 선택: {user_id}")
            return user_id

        # 우선순위 2: 최근 사용한 계정 (토큰 만료되어도)
        for row in rows:
            if row.get('last_used_at'):
                user_id = row['user_id']
                logger.info(f"✅ 최근 사용 계정 선택: {user_id} (토큰 만료됨, 재인증 필요)")
                return user_id

        # 우선순위 3: 계정이 1개만 있는 경우
        if len(rows) == 1:
            user_id = rows[0]['user_id']
            logger.info(f"✅ 단일 계정 발견, 자동 선택: {user_id} (토큰 만료됨)")
            return user_id

        # 다중 계정이지만 모두 토큰이 만료된 경우
        logger.warning(f"⚠️ 다중 계정 존재 ({len(rows)}개), 모두 토큰 만료됨 - user_id 명시 필요")
        return None

    except Exception as e:
        logger.error(f"❌ 기본 user_id 조회 실패: {e}")
        return None


class MCPHandlers(AttachmentFilterHandlers, CalendarHandlers):
    """MCP Protocol handlers for Mail Query (상속: AttachmentFilterHandlers, CalendarHandlers)"""

    def __init__(self):
        # 다중 상속: AttachmentFilterHandlers와 CalendarHandlers 초기화
        AttachmentFilterHandlers.__init__(self)
        CalendarHandlers.__init__(self)

        self.tools = MailAttachmentTools()
        logger.info("✅ MCPHandlers initialized with AttachmentFilterHandlers and CalendarHandlers")
    
    async def handle_list_tools(self) -> List[Tool]:
        """List available tools"""
        logger.info("🔧 [MCP Handler] list_tools() called")

        # Define mail query tools
        mail_query_tools = [
            Tool(
                name="search_messages",
                title="📧 Search Messages",
                description="Query emails and download/convert attachments to text. Date priority: start_date/end_date > days_back",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "User ID to query - email prefix without @domain (e.g., 'ejlee' for ejlee@company.com, 'yhjoe' for yhjoe@krs.co.kr). IMPORTANT: This field is OPTIONAL and will be automatically detected from the authenticated user if not provided. DO NOT use tools to search for the user_id unless the user explicitly requests a specific user_id. Only explicitly provide this field when you want to query a DIFFERENT user's mailbox than the currently authenticated user.",
                        },
                        "use_recent_account": {
                            "type": "boolean",
                            "description": "If true, automatically selects the most recently used account (based on last_used_at field). Set to true when you don't have a specific user_id and want to use the last active account. If false (default), user_id is required.",
                        },
                        "days_back": {
                            "type": "integer",
                            "description": "Number of days to look back",
                            "default": 30
                        },
                        "max_mails": {
                            "type": "integer",
                            "description": "Maximum number of mails to retrieve",
                            "default": 300
                        },
                        "include_body": {
                            "type": "string",
                            "description": "Include full email body content in the response. When 'yes', returns complete HTML/text content of each email. When 'no', only returns email preview (first ~255 chars). Useful for detailed content analysis",
                            "enum": ["yes", "no"],
                            "default": "yes"
                        },
                        "download_attachments": {
                            "type": "string",
                            "description": "Download email attachments and convert supported formats (PDF, DOCX, XLSX, etc.) to text. When 'yes', creates local copies and includes text content in response. When 'no', only shows attachment metadata (name, size)",
                            "enum": ["yes", "no"],
                            "default": "no"
                        },
                        "save_emails": {
                            "type": "string",
                            "description": "Save each email as individual text file to disk (mcp_attachments/{user_id}/). Files include headers, body, and attachment list. Useful for archiving or offline access. File names contain subject, date, and sender",
                            "enum": ["yes", "no"],
                            "default": "no"
                        },
                        "save_csv": {
                            "type": "string",
                            "description": "Export all retrieved emails' metadata to a single CSV file. Includes: subject, sender, date, read status, importance, attachment count/names, body preview (100 chars). Excel-compatible format with UTF-8 BOM encoding",
                            "enum": ["yes", "no"],
                            "default": "no"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format. When user says 'this week', calculate 7 days ago from today. When 'last month', calculate 30 days ago. When 'last 3 months', calculate 90 days ago.",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD format. When user mentions a time period without specific end date, use today's date. For 'this week' or 'last month', end_date should be today.",
                        },
                        "sender_address": {
                            "type": "string",
                            "description": "받은 메일 필터: 특정 발신자가 나에게 보낸 메일만 조회. 예: 'kim@company.com' → kim이 나에게 보낸 메일만. (내가 kim에게 보낸 메일은 포함 안 됨)",
                        },
                        "subject_contains": {
                            "type": "string",
                            "description": "Filter emails by subject text. Only emails containing this text in the subject will be retrieved. Case-insensitive partial matching (e.g., 'meeting' matches 'Weekly Meeting Report').",
                        },
                        "keyword": {
                            "type": "string",
                            "description": "전체 메일 검색 키워드 (클라이언트 측 필터링). 제목, 본문, 발신자, 수신자, 첨부파일명 등 모든 필드에서 검색. 날짜/발신자 필터와 함께 사용 가능. 단순 키워드 검색만 지원. 예: '계약서', '프로젝트'. 고급 검색은 keyword_filter를 사용하세요.",
                        },
                        "keyword_filter": {
                            "type": "object",
                            "description": "구조화된 키워드 검색 필터 (클라이언트 측 필터링). AND/OR/NOT 조건을 조합하여 복잡한 검색 가능. 예: {\"and_keywords\": [\"계약서\", \"2024\"], \"not_keywords\": [\"취소\"]} → 계약서와 2024가 모두 포함되고 취소는 제외",
                            "properties": {
                                "and_keywords": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "AND 조건: 모든 키워드가 포함되어야 함. 예: [\"계약서\", \"2024\"] → 둘 다 포함"
                                },
                                "or_keywords": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "OR 조건: 하나 이상의 키워드가 포함되어야 함. 예: [\"계약서\", \"제안서\"] → 둘 중 하나 이상"
                                },
                                "not_keywords": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "NOT 조건: 이 키워드들이 포함되지 않아야 함. 예: [\"취소\", \"반려\"] → 둘 다 제외"
                                }
                            }
                        },
                        "recipient_address": {
                            "type": "string",
                            "description": "보낸 메일 필터: 내가 특정 수신자에게 보낸 메일만 조회. 예: 'kim@company.com' → 내가 kim에게 보낸 메일만. (kim이 나에게 보낸 메일은 포함 안 됨)",
                        },
                        "conversation_with": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "대화 전체 조회: 특정 사람과 주고받은 모든 메일. 이메일 주소 배열로 입력. 예: ['kim@company.com', 'lee@company.com'] → ①이 사람들이 나에게 보낸 메일 + ②내가 이 사람들에게 보낸 메일 모두 포함. 완전한 대화 내역을 보려면 이것을 사용하세요.",
                        },
                        "output_format": {
                            "type": "string",
                            "description": "Output format for the response. 'json' for structured JSON data (optimized for programmatic access), 'text' for human-readable formatted text (default, easier to read)",
                            "enum": ["text", "json"],
                            "default": "text"
                        },
                        "query_context": {
                            "type": "object",
                            "description": "Query context information for handling multi-turn conversations",
                            "properties": {
                                "is_first_query": {
                                    "type": "boolean",
                                    "description": "Whether this is the first query in the conversation. When true, all required fields must be provided. When false, missing fields may use previous values"
                                },
                                "conversation_turn": {
                                    "type": "integer",
                                    "description": "The conversation turn number (1 for first query, 2 for second, etc.)"
                                },
                                "previous_user_id": {
                                    "type": "string",
                                    "description": "User ID from the previous query that can be reused if not specified in current query"
                                }
                            }
                        },
                    },
                    "required": [
                        "start_date",
                        "end_date",
                        "include_body",
                        "query_context"
                    ],
                },
            ),
            Tool(
                name="query_email_help",
                title="📘 Query Email Help",
                description="Get detailed usage guide for query_email tool with examples for all parameter combinations",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="help",
                title="❓ Help",
                description="Get detailed help and documentation for available tools. Use without parameters to see all tools, or specify tool_name for detailed information",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "Name of the tool to get help for (optional). If not specified, shows list of all available tools",
                            "enum": [
                                "query_email",
                                "query_email_help",
                                "help"
                            ]
                        }
                    }
                }
            ),
        ]

        # AttachmentFilterHandlers에서 attachmentManager 툴 추가
        attachment_tools = self.get_attachment_filter_tools()
        mail_query_tools.extend(attachment_tools)

        # CalendarHandlers에서 Calendar 툴 추가
        calendar_tools = await self.handle_calendar_list_tools()
        mail_query_tools.extend(calendar_tools)

        return mail_query_tools
    
    async def handle_call_tool(self, name: str, arguments: Dict[str, Any], authenticated_user_id: Optional[str] = None) -> List[TextContent]:
        """Handle tool calls"""
        logger.info(f"🛠️ [MCP Handler] call_tool() called with tool: {name}")
        logger.info(f"📝 [MCP Handler] Raw arguments: {json.dumps(arguments, indent=2, ensure_ascii=False)}")

        # Preprocess arguments
        arguments = preprocess_arguments(arguments)
        logger.info(f"🔄 [MCP Handler] Preprocessed arguments: {json.dumps(arguments, indent=2, ensure_ascii=False)}")

        # 인증된 user_id 적용 (보안) - 공통 헬퍼 사용
        from infra.core.auth_helpers import get_authenticated_user_id
        final_user_id = get_authenticated_user_id(arguments, authenticated_user_id)
        if final_user_id:
            arguments["user_id"] = final_user_id

        try:
            # AttachmentFilterHandlers 툴 체크
            if self.is_attachment_filter_tool(name):
                return await self.handle_attachment_filter_tool(name, arguments)

            # CalendarHandlers 툴 체크
            if name.startswith("calendar_"):
                return await self.handle_calendar_call_tool(name, arguments)

            # Mail Query 툴 처리
            if name == "search_messages":
                # Convert "yes"/"no" strings to boolean
                for key in ["include_body", "download_attachments", "save_emails", "save_csv"]:
                    if key in arguments:
                        arguments[key] = arguments[key] == "yes"
                result = await self.tools.query_email(arguments)
                return [TextContent(type="text", text=result)]

            elif name == "query_email_help":
                result = await self.tools.query_email_help(arguments)
                return [TextContent(type="text", text=result)]

            elif name == "help":
                result = await self.tools.help(arguments)
                return [TextContent(type="text", text=result)]

            else:
                raise MCPError(
                    ErrorCode.MCP_TOOL_NOT_FOUND,
                    tool_name=name
                )

        except MCPError as e:
            logger.error(f"❌ MCP Error in tool {name}: {e.get_user_message()}")
            return [TextContent(type="text", text=e.get_user_message())]
        except Exception as e:
            logger.error(f"❌ Unexpected error in tool {name}: {str(e)}", exc_info=True)
            error = MCPError(
                ErrorCode.MCP_TOOL_EXECUTION_FAILED,
                tool_name=name,
                original_exception=e
            )
            return [TextContent(type="text", text=error.get_user_message())]
    
    async def handle_list_prompts(self) -> List[Prompt]:
        """List available prompts"""
        logger.info("📋 [MCP Handler] list_prompts() called")
        
        # Return empty list as requested
        return []
    
    async def handle_get_prompt(self, name: str, arguments: Dict[str, Any]) -> PromptMessage:
        """Get specific prompt"""
        logger.info(f"📝 [MCP Handler] get_prompt() called with prompt: {name}")
        
        return await get_prompt(name, arguments)