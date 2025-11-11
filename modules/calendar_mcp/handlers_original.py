"""
Calendar MCP Handlers
MCP 프로토콜 핸들러 레이어 - HTTP/stdio 공통 로직
"""

import json
from typing import Any, Dict, List
from mcp.types import Tool, TextContent

from infra.core.logger import get_logger
from .calendar_handler import CalendarHandler
from .schemas import (
    ListEventsRequest,
    ListEventsResponse,
    CreateEventRequest,
    CreateEventResponse,
    UpdateEventRequest,
    UpdateEventResponse,
    DeleteEventRequest,
    DeleteEventResponse,
)

logger = get_logger(__name__)


class CalendarHandlers:
    """Calendar MCP Protocol Handlers"""

    def __init__(self):
        """Initialize handlers with Calendar handler instance"""
        self.calendar_handler = CalendarHandler()
        logger.info("✅ CalendarHandlers initialized")

    # ========================================================================
    # MCP Protocol: list_tools
    # ========================================================================

    async def handle_calendar_list_tools(self) -> List[Tool]:
        """List available Calendar MCP tools"""
        logger.info("🔧 [Calendar MCP Handler] list_tools() called")

        calendar_tools = [
            Tool(
                name="calendar_list_events",
                description="사용자의 일정 목록을 조회합니다. 기간을 지정하지 않으면 오늘부터 30일 후까지의 일정을 조회합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "시작 날짜 (YYYY-MM-DD 형식)",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "종료 날짜 (YYYY-MM-DD 형식)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "조회할 일정 수 (기본 50)",
                            "default": 50
                        },
                        "search_query": {
                            "type": "string",
                            "description": "검색어 (일정 제목 검색)"
                        }
                    },
                    "required": ["user_id"]
                }
            ),
            Tool(
                name="calendar_create_event",
                description="새로운 일정을 생성합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID"
                        },
                        "subject": {
                            "type": "string",
                            "description": "일정 제목"
                        },
                        "start": {
                            "type": "string",
                            "description": "시작 시간 (ISO 8601 형식, 예: 2024-10-24T09:00:00)"
                        },
                        "end": {
                            "type": "string",
                            "description": "종료 시간 (ISO 8601 형식, 예: 2024-10-24T10:00:00)"
                        },
                        "body": {
                            "type": "string",
                            "description": "일정 내용"
                        },
                        "location": {
                            "type": "string",
                            "description": "위치"
                        },
                        "attendees": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "참석자 이메일 목록"
                        },
                        "is_all_day": {
                            "type": "boolean",
                            "description": "종일 일정 여부",
                            "default": False
                        },
                        "is_online_meeting": {
                            "type": "boolean",
                            "description": "온라인 회의 여부",
                            "default": False
                        }
                    },
                    "required": ["user_id", "subject", "start", "end"]
                }
            ),
            Tool(
                name="calendar_update_event",
                description="기존 일정을 수정합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID"
                        },
                        "event_id": {
                            "type": "string",
                            "description": "수정할 일정의 ID"
                        },
                        "subject": {
                            "type": "string",
                            "description": "일정 제목"
                        },
                        "start": {
                            "type": "string",
                            "description": "시작 시간 (ISO 8601 형식)"
                        },
                        "end": {
                            "type": "string",
                            "description": "종료 시간 (ISO 8601 형식)"
                        },
                        "body": {
                            "type": "string",
                            "description": "일정 내용"
                        },
                        "location": {
                            "type": "string",
                            "description": "위치"
                        },
                        "attendees": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "참석자 이메일 목록"
                        },
                        "is_online_meeting": {
                            "type": "boolean",
                            "description": "온라인 회의 여부"
                        }
                    },
                    "required": ["user_id", "event_id"]
                }
            ),
            Tool(
                name="calendar_delete_event",
                description="일정을 삭제합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID"
                        },
                        "event_id": {
                            "type": "string",
                            "description": "삭제할 일정의 ID"
                        }
                    },
                    "required": ["user_id", "event_id"]
                }
            ),
            Tool(
                name="calendar_get_event",
                description="특정 일정의 상세 정보를 조회합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID"
                        },
                        "event_id": {
                            "type": "string",
                            "description": "조회할 일정의 ID"
                        }
                    },
                    "required": ["user_id", "event_id"]
                }
            ),
        ]

        return calendar_tools

    # ========================================================================
    # MCP Protocol: call_tool
    # ========================================================================

    async def handle_calendar_call_tool(
        self, name: str, arguments: Dict[str, Any]
    ) -> List[TextContent]:
        """Handle Calendar MCP tool calls"""
        logger.info(f"🔨 [Calendar MCP Handler] call_tool({name}) with args: {arguments}")

        try:
            if name == "calendar_list_events":
                user_id = arguments.get("user_id")
                start_date = arguments.get("start_date")
                end_date = arguments.get("end_date")
                limit = arguments.get("limit", 50)
                search_query = arguments.get("search_query")

                result = await self.calendar_handler.list_events(
                    user_id, start_date, end_date, limit, search_query
                )

                # 사용자 친화적인 출력 포맷
                if result.get("success") and result.get("events"):
                    events = result["events"]
                    output_lines = [f"📅 총 {len(events)}개 일정 조회됨\n"]
                    for event in events:
                        subject = event.get("subject", "제목 없음")
                        event_id = event.get("id")
                        start_time = event.get("start", {}).get("dateTime", "")
                        end_time = event.get("end", {}).get("dateTime", "")
                        location = event.get("location", {}).get("displayName", "")
                        is_online = event.get("isOnlineMeeting", False)

                        output_lines.append(f"• {subject}")
                        output_lines.append(f"  ID: {event_id}")
                        output_lines.append(f"  시간: {start_time} ~ {end_time}")
                        if location:
                            output_lines.append(f"  위치: {location}")
                        if is_online:
                            online_url = event.get("onlineMeeting", {}).get("joinUrl", "")
                            output_lines.append(f"  온라인 회의: {online_url}")
                        output_lines.append("")

                    formatted_output = "\n".join(output_lines) + "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                    return [TextContent(type="text", text=formatted_output)]

                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "calendar_create_event":
                user_id = arguments.get("user_id")
                subject = arguments.get("subject")
                start = arguments.get("start")
                end = arguments.get("end")
                body = arguments.get("body")
                location = arguments.get("location")
                attendees = arguments.get("attendees")
                is_all_day = arguments.get("is_all_day", False)
                is_online_meeting = arguments.get("is_online_meeting", False)

                result = await self.calendar_handler.create_event(
                    user_id, subject, start, end, body, location,
                    attendees, is_all_day, is_online_meeting
                )

                # 성공 시 사용자 친화적인 출력
                if result.get("success"):
                    event = result.get("event", {})
                    event_id = result.get("event_id")
                    output = f"✅ 일정이 생성되었습니다!\n\n"
                    output += f"제목: {subject}\n"
                    output += f"ID: {event_id}\n"
                    output += f"시간: {start} ~ {end}\n"
                    if location:
                        output += f"위치: {location}\n"
                    if is_online_meeting and event.get("onlineMeeting"):
                        online_url = event.get("onlineMeeting", {}).get("joinUrl", "")
                        output += f"온라인 회의 링크: {online_url}\n"
                    output += "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                    return [TextContent(type="text", text=output)]

                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "calendar_update_event":
                user_id = arguments.get("user_id")
                event_id = arguments.get("event_id")
                subject = arguments.get("subject")
                start = arguments.get("start")
                end = arguments.get("end")
                body = arguments.get("body")
                location = arguments.get("location")
                attendees = arguments.get("attendees")
                is_online_meeting = arguments.get("is_online_meeting")

                result = await self.calendar_handler.update_event(
                    user_id, event_id, subject, start, end, body,
                    location, attendees, is_online_meeting
                )

                if result.get("success"):
                    output = f"✅ 일정이 수정되었습니다!\n\n"
                    output += f"ID: {event_id}\n"
                    output += "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                    return [TextContent(type="text", text=output)]

                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "calendar_delete_event":
                user_id = arguments.get("user_id")
                event_id = arguments.get("event_id")

                result = await self.calendar_handler.delete_event(user_id, event_id)

                if result.get("success"):
                    output = f"✅ 일정이 삭제되었습니다!\n\n"
                    output += f"ID: {event_id}\n"
                    return [TextContent(type="text", text=output)]

                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "calendar_get_event":
                user_id = arguments.get("user_id")
                event_id = arguments.get("event_id")

                result = await self.calendar_handler.get_event(user_id, event_id)

                if result.get("success") and result.get("event"):
                    event = result["event"]
                    subject = event.get("subject", "제목 없음")
                    start_time = event.get("start", {}).get("dateTime", "")
                    end_time = event.get("end", {}).get("dateTime", "")
                    location = event.get("location", {}).get("displayName", "")
                    body_content = event.get("body", {}).get("content", "")
                    is_online = event.get("isOnlineMeeting", False)

                    output = f"📅 일정 상세 정보\n\n"
                    output += f"제목: {subject}\n"
                    output += f"ID: {event_id}\n"
                    output += f"시간: {start_time} ~ {end_time}\n"
                    if location:
                        output += f"위치: {location}\n"
                    if body_content:
                        # HTML 태그 제거 (간단하게)
                        import re
                        body_text = re.sub('<[^<]+?>', '', body_content)[:500]
                        output += f"내용: {body_text}\n"
                    if is_online:
                        online_url = event.get("onlineMeeting", {}).get("joinUrl", "")
                        output += f"온라인 회의: {online_url}\n"
                    output += "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                    return [TextContent(type="text", text=output)]

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

    async def call_calendar_tool_as_dict(
        self, name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        HTTP API용 헬퍼: call_tool 결과를 dict로 반환
        """
        try:
            if name == "calendar_list_events":
                user_id = arguments.get("user_id")
                start_date = arguments.get("start_date")
                end_date = arguments.get("end_date")
                limit = arguments.get("limit", 50)
                search_query = arguments.get("search_query")
                return await self.calendar_handler.list_events(
                    user_id, start_date, end_date, limit, search_query
                )

            elif name == "calendar_create_event":
                user_id = arguments.get("user_id")
                subject = arguments.get("subject")
                start = arguments.get("start")
                end = arguments.get("end")
                body = arguments.get("body")
                location = arguments.get("location")
                attendees = arguments.get("attendees")
                is_all_day = arguments.get("is_all_day", False)
                is_online_meeting = arguments.get("is_online_meeting", False)
                return await self.calendar_handler.create_event(
                    user_id, subject, start, end, body, location,
                    attendees, is_all_day, is_online_meeting
                )

            elif name == "calendar_update_event":
                user_id = arguments.get("user_id")
                event_id = arguments.get("event_id")
                subject = arguments.get("subject")
                start = arguments.get("start")
                end = arguments.get("end")
                body = arguments.get("body")
                location = arguments.get("location")
                attendees = arguments.get("attendees")
                is_online_meeting = arguments.get("is_online_meeting")
                return await self.calendar_handler.update_event(
                    user_id, event_id, subject, start, end, body,
                    location, attendees, is_online_meeting
                )

            elif name == "calendar_delete_event":
                user_id = arguments.get("user_id")
                event_id = arguments.get("event_id")
                return await self.calendar_handler.delete_event(user_id, event_id)

            elif name == "calendar_get_event":
                user_id = arguments.get("user_id")
                event_id = arguments.get("event_id")
                return await self.calendar_handler.get_event(user_id, event_id)

            else:
                raise ValueError(f"알 수 없는 도구: {name}")

        except Exception as e:
            logger.error(f"❌ Tool 실행 오류: {name}, {str(e)}", exc_info=True)
            raise
