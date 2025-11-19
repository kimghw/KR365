"""
Teams MCP Handlers
MCP 프로토콜 핸들러 레이어 - HTTP/stdio 공통 로직
"""

import json
from typing import Any, Dict, List, Optional
from mcp.types import Tool, TextContent

from infra.core.logger import get_logger
from .teams_handler import TeamsHandler
from .schemas import (
    ListTeamsRequest,
    ListTeamsResponse,
    ListChannelsRequest,
    ListChannelsResponse,
    SendMessageRequest,
    SendMessageResponse,
    GetMessagesRequest,
    GetMessagesResponse,
    GetRepliesRequest,
    GetRepliesResponse,
)

logger = get_logger(__name__)


class TeamsHandlers:
    """Teams MCP Protocol Handlers"""

    def __init__(self):
        """Initialize handlers with Teams handler instance"""
        self.teams_handler = TeamsHandler()
        logger.info("✅ TeamsHandlers initialized")

    # ========================================================================
    # Helper: Get help text
    # ========================================================================

    def _get_help_text(self) -> str:
        """Teams MCP 도구 사용법 안내"""
        return """
# Teams MCP 도구 사용 가이드

## 📋 사용 가능한 도구

### 1. teams_list_chats
**설명**: 사용자의 1:1 및 그룹 채팅 목록을 조회합니다.

**파라미터**:
- `user_id` (필수): 사용자 ID

**예제**:
```json
{
  "user_id": "user123"
}
```

**응답 예시**:
```json
{
  "success": true,
  "chats": [
    {
      "id": "19:abc123...",
      "chatType": "oneOnOne",
      "topic": "John Doe",
      "lastMessagePreview": "안녕하세요",
      "lastUpdateDateTime": "2025-01-15T10:30:00Z"
    }
  ],
  "count": 1
}
```

---

### 2. teams_get_chat_messages
**설명**: 채팅의 메시지 목록을 조회합니다.

**파라미터**:
- `user_id` (필수): 사용자 ID
- `chat_id` (선택): 채팅 ID (기본값: "48:notes" - 나의 Notes 채팅)
- `limit` (선택): 조회할 메시지 수 (기본값: 50)

**예제 1 - 특정 채팅 조회**:
```json
{
  "user_id": "user123",
  "chat_id": "19:abc123...",
  "limit": 30
}
```

**예제 2 - 나의 Notes 조회** (chat_id 생략):
```json
{
  "user_id": "user123",
  "limit": 20
}
```

**응답 예시**:
```json
{
  "success": true,
  "messages": [
    {
      "id": "1234567890",
      "from": {
        "user": {
          "displayName": "Jane Smith"
        }
      },
      "body": {
        "content": "회의 시간 확인 부탁드립니다."
      },
      "createdDateTime": "2025-01-15T10:30:00Z"
    }
  ],
  "count": 1
}
```

---

### 3. teams_send_chat_message
**설명**: 채팅에 메시지를 전송합니다.

**파라미터**:
- `user_id` (필수): 사용자 ID
- `content` (필수): 메시지 내용
- `chat_id` (선택): 채팅 ID (기본값: "48:notes" - 나의 Notes 채팅)
- `prefix` (선택): 메시지 프리픽스 (기본값: "[claude]")

**예제 1 - 특정 채팅에 전송**:
```json
{
  "user_id": "user123",
  "chat_id": "19:abc123...",
  "content": "회의는 오후 2시입니다.",
  "prefix": "[Bot]"
}
```

**예제 2 - 나의 Notes에 메모** (chat_id 생략):
```json
{
  "user_id": "user123",
  "content": "오늘 할 일: 보고서 작성",
  "prefix": ""
}
```

**응답 예시**:
```json
{
  "success": true,
  "message_id": "1234567890",
  "data": {
    "id": "1234567890",
    "createdDateTime": "2025-01-15T10:35:00Z"
  }
}
```

---

## 🎯 주요 사용 시나리오

### 시나리오 1: 특정 사용자와의 최근 대화 확인
1. `teams_list_chats`로 채팅 목록 조회
2. 목록에서 원하는 사용자의 `chat_id` 확인
3. `teams_get_chat_messages`로 해당 채팅의 메시지 조회

### 시나리오 2: 메시지 전송
1. `teams_list_chats`로 채팅 목록 조회
2. 목록에서 메시지를 보낼 채팅의 `chat_id` 확인
3. `teams_send_chat_message`로 메시지 전송

### 시나리오 3: 개인 메모 (Notes) 사용
- `chat_id`를 생략하면 자동으로 나의 Notes(48:notes) 사용
- 별도 채팅 조회 없이 바로 메모 작성 가능

---

## ⚠️ 주의사항

1. **user_id 필수**: 모든 도구는 `user_id`가 필요합니다.
2. **chat_id 형식**: Teams 채팅 ID는 보통 `19:` 또는 `48:`로 시작합니다.
3. **Notes 채팅**: `48:notes`는 본인만 볼 수 있는 특수 채팅입니다.
4. **메시지 제한**: `limit`은 최대 50개까지 권장됩니다.
5. **권한 필요**: Chat.ReadWrite 권한이 필요합니다.

---

## 🔍 오류 처리

**오류 응답 예시**:
```json
{
  "success": false,
  "message": "액세스 토큰이 없습니다",
  "status_code": 401
}
```

**일반적인 오류**:
- `401 Unauthorized`: 토큰 만료 또는 권한 부족
- `404 Not Found`: 잘못된 chat_id
- `400 Bad Request`: 잘못된 파라미터

---

📌 **Tip**: 처음 사용 시 `teams_list_chats`로 사용 가능한 채팅 목록을 먼저 확인하세요!
"""

    # ========================================================================
    # MCP Protocol: list_tools
    # ========================================================================

    async def handle_list_tools(self) -> List[Tool]:
        """List available MCP tools (Teams Chat only)"""
        logger.info("🔧 [MCP Handler] list_tools() called")

        # Define Teams Chat-specific tools (1:1 and group chats)
        teams_tools = [
            Tool(
                name="teams_help",
                description="Teams MCP 도구 사용법 및 예제를 안내합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            Tool(
                name="teams_list_chats",
                description="사용자의 1:1 및 그룹 채팅 목록을 조회합니다. 정렬, 필터링, 개수 제한 가능. **중요**: 출력에서 한글 이름(topic_kr)이 없는 채팅이 표시되면, 반드시 영문 이름을 참고하여 한글 이름으로 해석한 후 teams_save_korean_name 도구를 사용해 등록해야 합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "sort_by": {
                            "type": "string",
                            "description": "정렬 방식: 'recent' (최근순), 'name' (이름순), 'type' (타입순)",
                            "enum": ["recent", "name", "type"],
                            "default": "recent"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "최대 조회 개수 (전체 조회: null 또는 생략)"
                        },
                        "filter_by_name": {
                            "type": "string",
                            "description": "이름으로 필터링 (부분 일치)"
                        }
                    },
                    "required": []
                }
            ),
            Tool(
                name="teams_get_chat_messages",
                description="채팅의 메시지 목록을 조회합니다. chat_id, recipient_name 둘 다 없으면 최근 대화 또는 Notes(48:notes)를 조회합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "채팅 ID (선택사항)"
                        },
                        "recipient_name": {
                            "type": "string",
                            "description": "상대방 이름 (chat_id가 없을 때 사용)"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "조회할 메시지 수 (기본 50)",
                            "default": 50
                        }
                    },
                    "required": []
                }
            ),
            Tool(
                name="teams_send_chat_message",
                description="채팅에 메시지를 전송합니다. user_id, chat_id, recipient_name을 모두 생략하면 자동으로 48:notes(나에게 보내기)로 전송됩니다. '나에게', '내게' 등 자신에게 보내는 요청이거나, 상대방이 명시되지 않은 경우 모든 파라미터를 생략하세요.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (선택사항). 지정하지 않으면 기본 사용자 사용."
                        },
                        "content": {
                            "type": "string",
                            "description": "메시지 내용"
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "채팅 ID (선택사항). 명시하지 않으면 48:notes(나에게 보내기)를 사용합니다."
                        },
                        "recipient_name": {
                            "type": "string",
                            "description": "상대방 이름 (선택사항). 특정 상대방에게 보낼 때만 지정. 명시하지 않으면 48:notes(나에게 보내기)를 사용합니다."
                        },
                        "prefix": {
                            "type": "string",
                            "description": "메시지 앞에 붙을 프리픽스 (기본값: '[claude]')",
                            "default": "[claude]"
                        }
                    },
                    "required": ["content"]
                }
            ),
            Tool(
                name="teams_search_messages",
                description="메시지를 키워드로 검색합니다. 특정 채팅방 또는 전체 채팅방 검색 가능.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "keyword": {
                            "type": "string",
                            "description": "검색 키워드"
                        },
                        "search_scope": {
                            "type": "string",
                            "description": "검색 범위: 'current_chat' (특정 채팅) 또는 'all_chats' (전체)",
                            "enum": ["current_chat", "all_chats"],
                            "default": "all_chats"
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "채팅 ID (search_scope='current_chat'일 때 필수)"
                        },
                        "page_size": {
                            "type": "integer",
                            "description": "페이지 크기 (기본 50)",
                            "default": 50
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "최대 결과 수 (기본 500)",
                            "default": 500
                        }
                    },
                    "required": ["keyword"]
                }
            ),
            Tool(
                name="teams_save_korean_name",
                description="채팅방의 한글 이름을 DB에 저장합니다. 단일 저장 또는 배치 저장 가능. 배치 저장 시 names 파라미터에 리스트를 전달하면 한 번에 여러 개를 저장할 수 있습니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "names": {
                            "type": "array",
                            "description": "배치 저장용 - [{'topic_en': '영문', 'topic_kr': '한글'}, ...] 형식의 리스트",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "topic_en": {"type": "string"},
                                    "topic_kr": {"type": "string"}
                                },
                                "required": ["topic_en", "topic_kr"]
                            }
                        },
                        "topic_kr": {
                            "type": "string",
                            "description": "단일 저장용 - 한글 이름"
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "단일 저장용 - 채팅 ID"
                        },
                        "topic_en": {
                            "type": "string",
                            "description": "단일 저장용 - 영문 이름"
                        }
                    },
                    "required": []
                }
            ),
            Tool(
                name="teams_get_chats_by_date",
                description="날짜 범위 내에서 활동이 있었던 채팅방을 조회합니다. lastModifiedDateTime 기준으로 필터링하며, 사용자별로 정리된 결과를 제공합니다.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "사용자 ID (OPTIONAL - 세션에서 자동 매핑됨)"
                        },
                        "days": {
                            "type": "integer",
                            "description": "조회할 일수 (기본 7일). start_date/end_date가 없을 때 사용됩니다.",
                            "default": 7
                        },
                        "start_date": {
                            "type": "string",
                            "description": "시작 날짜 (ISO 8601 형식, 예: '2025-01-01T00:00:00Z'). days 대신 명시적 날짜 범위 지정 시 사용."
                        },
                        "end_date": {
                            "type": "string",
                            "description": "종료 날짜 (ISO 8601 형식, 예: '2025-01-15T23:59:59Z'). start_date와 함께 사용."
                        },
                        "user_name_filter": {
                            "type": "string",
                            "description": "특정 사용자 이름으로 필터링 (선택). 이름이 포함된 채팅만 조회합니다."
                        }
                    },
                    "required": []
                }
            ),
        ]

        # Return Teams tools only
        return teams_tools

    # ========================================================================
    # MCP Protocol: call_tool
    # ========================================================================

    async def handle_call_tool(
        self, name: str, arguments: Dict[str, Any], authenticated_user_id: Optional[str] = None
    ) -> List[TextContent]:
        """Handle MCP tool calls (Teams Chat only)"""
        logger.info(f"🔨 [MCP Handler] call_tool({name}) with args: {arguments}")

        try:
            # Handle Teams Help
            if name == "teams_help":
                help_text = self._get_help_text()
                return [TextContent(type="text", text=help_text)]

            # Handle Teams Chat-specific tools
            elif name == "teams_list_chats":
                # 인증된 user_id 사용 (보안)
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)

                sort_by = arguments.get("sort_by", "recent")
                limit = arguments.get("limit")
                filter_by_name = arguments.get("filter_by_name")
                result = await self.teams_handler.list_chats(user_id, sort_by, limit, filter_by_name)

                # 사용자 친화적인 출력 포맷
                if result.get("success") and result.get("chats"):
                    chats = result["chats"]
                    output_lines = [f"💬 총 {len(chats)}개 채팅 조회됨\n"]

                    # 한글 이름이 없는 채팅 수집
                    chats_without_korean = []

                    # 한글 포함 여부 체크 함수
                    def has_korean_chars(text):
                        if not text:
                            return False
                        return any('\uac00' <= char <= '\ud7a3' for char in text)

                    for chat in chats:
                        chat_type = chat.get("chatType", "unknown")
                        chat_id = chat.get("id")
                        topic_raw = chat.get("topic")
                        peer_name = chat.get("peer_user_name")
                        # 표시용 원본 이름: topic이 없으면 1:1의 상대 이름 사용
                        source_name = topic_raw or peer_name
                        topic_display = source_name if source_name else "(제목 없음)"
                        topic_kr = chat.get("topic_kr")  # DB에서 가져온 한글 이름

                        # 한글 이름이 있고 원본 이름과 다른 경우에만 표시
                        has_korean_name = topic_kr and topic_kr != (source_name or "")

                        if has_korean_name:
                            display_name = f"{topic_display} → {topic_kr}"
                        else:
                            display_name = topic_display
                            # 한글 이름이 없는 경우 수집
                            # 조건: 표시 이름이 있고, 한글이 포함되지 않은 경우(영문/기호)
                            if source_name and not has_korean_chars(source_name):
                                chats_without_korean.append({
                                    "name": topic_display,
                                    "chat_id": chat_id,
                                    "chat_type": chat_type
                                })

                        # chatType에 따라 표시
                        if chat_type == "oneOnOne":
                            output_lines.append(f"• [1:1] {display_name}")
                        elif chat_type == "group":
                            output_lines.append(f"• [그룹] {display_name}")
                        else:
                            output_lines.append(f"• [{chat_type}] {display_name}")

                        output_lines.append(f"  ID: {chat_id}")
                        output_lines.append("")

                    # 한글 이름이 없는 채팅 목록 추가
                    if chats_without_korean:
                        output_lines.append("\n" + "="*50)
                        output_lines.append(f"📝 한글 이름이 없는 채팅 ({len(chats_without_korean)}개)")
                        output_lines.append("="*50)
                        output_lines.append("")

                        # 영문 이름만 간단히 나열
                        output_lines.append("🔤 영문 이름 목록:")
                        for idx, item in enumerate(chats_without_korean, 1):
                            output_lines.append(f"  {idx}. {item['name']}")
                        output_lines.append("")

                        # 상세 정보
                        output_lines.append("📋 상세 정보:")
                        for idx, item in enumerate(chats_without_korean, 1):
                            output_lines.append(f"{idx}. 영문: {item['name']}")
                            output_lines.append(f"   chat_id: {item['chat_id']}")
                            output_lines.append("")

                        # 강조 메시지 추가
                        output_lines.append("="*50)
                        output_lines.append("⚠️  중요! 위 영문 이름들을 한글로 해석해서 등록해줘! ⚠️")
                        output_lines.append("💡 등록되지 않은 한글 이름을 등록하겠습니다")
                        output_lines.append("")
                        output_lines.append("📝 배치 저장 예시 (한 번에 여러 개):")
                        output_lines.append("teams_save_korean_name(")
                        output_lines.append("  user_id=\"...\",")
                        output_lines.append("  names=[")
                        # 처음 3개만 예시로 표시
                        for idx, item in enumerate(chats_without_korean[:3], 1):
                            comma = "," if idx < min(3, len(chats_without_korean)) else ""
                            output_lines.append(f"    {{\"topic_en\": \"{item['name']}\", \"topic_kr\": \"한글이름{idx}\"}}{comma}")
                        if len(chats_without_korean) > 3:
                            output_lines.append("    # ... 나머지도 추가")
                        output_lines.append("  ]")
                        output_lines.append(")")
                        output_lines.append("="*50)
                        output_lines.append("")

                    formatted_output = "\n".join(output_lines) + "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                    return [TextContent(type="text", text=formatted_output)]

                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "teams_get_chat_messages":
                # 인증된 user_id 사용 (보안)
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)

                chat_id = arguments.get("chat_id")
                recipient_name = arguments.get("recipient_name")
                limit = arguments.get("limit", 50)

                result = await self.teams_handler.get_chat_messages(user_id, chat_id, recipient_name, limit)

                # 사용자 친화적인 출력 포맷
                if result.get("success") and result.get("messages"):
                    messages = result["messages"]
                    output_lines = [f"💬 총 {len(messages)}개 메시지 조회됨\n"]
                    for msg in messages:
                        msg_id = msg.get("id")
                        from_user = msg.get("from", {}).get("user", {}).get("displayName", "알 수 없음")
                        created = msg.get("createdDateTime", "")
                        body = msg.get("body", {}).get("content", "")
                        # HTML 태그 제거 (간단하게)
                        import re
                        body_text = re.sub('<[^<]+?>', '', body)[:200]  # 처음 200자만

                        output_lines.append(f"• [{created}] {from_user}")
                        output_lines.append(f"  ID: {msg_id}")
                        output_lines.append(f"  내용: {body_text}...")
                        output_lines.append("")

                    formatted_output = "\n".join(output_lines) + "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                    return [TextContent(type="text", text=formatted_output)]

                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "teams_send_chat_message":
                # 1순위: 인증된 user_id (보안)
                # 2순위: 파라미터로 전달된 user_id
                # 3순위: DB에서 첫 번째 user_id 조회
                user_id = authenticated_user_id or arguments.get("user_id")

                if not user_id:
                    # user_id가 없으면 teams_chats에서 첫 번째 user_id 조회
                    from infra.core.database import get_database_manager
                    db = get_database_manager()
                    result_query = db.execute_query(
                        "SELECT DISTINCT user_id FROM teams_chats LIMIT 1",
                        fetch_result=True
                    )
                    if result_query and len(result_query) > 0:
                        user_id = result_query[0][0]
                    else:
                        # DB에 없으면 환경변수 사용
                        import os
                        user_id = os.getenv("AUTO_REGISTER_USER_ID", "kimghw")

                # 보안 검증: 파라미터 user_id가 인증된 user_id와 다르면 경고
                param_user_id = arguments.get("user_id")
                if authenticated_user_id and param_user_id and param_user_id != authenticated_user_id:
                    logger.warning(f"⚠️ 보안: 인증된 user_id({authenticated_user_id})와 파라미터 user_id({param_user_id})가 다름. 인증된 user_id 사용.")

                content = arguments.get("content")
                chat_id = arguments.get("chat_id")
                recipient_name = arguments.get("recipient_name")
                prefix = arguments.get("prefix", "[claude]")

                result = await self.teams_handler.send_chat_message(user_id, content, chat_id, recipient_name, prefix)
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "teams_search_messages":
                # 인증된 user_id 사용 (보안)
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)

                keyword = arguments.get("keyword")
                search_scope = arguments.get("search_scope", "all_chats")
                chat_id = arguments.get("chat_id")
                page_size = arguments.get("page_size", 50)
                max_results = arguments.get("max_results", 500)

                result = await self.teams_handler.search_messages(
                    user_id, keyword, search_scope, chat_id, page_size, max_results
                )

                # 사용자 친화적인 출력 포맷
                if result.get("success") and result.get("results"):
                    results = result["results"]
                    output_lines = [f"🔍 키워드 '{keyword}' 검색 결과: {len(results)}개\n"]
                    for idx, item in enumerate(results[:20], 1):  # 처음 20개만 상세 출력
                        output_lines.append(f"{idx}. [{item.get('created', '')}] {item.get('from', '')}")
                        if search_scope == "all_chats":
                            output_lines.append(f"   채팅: {item.get('chat_topic', '')}")
                        output_lines.append(f"   내용: {item.get('content', '')}...")
                        output_lines.append("")

                    if len(results) > 20:
                        output_lines.append(f"... 외 {len(results) - 20}개 결과 더 있음\n")

                    formatted_output = "\n".join(output_lines) + "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                    return [TextContent(type="text", text=formatted_output)]

                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "teams_save_korean_name":
                # 인증된 user_id 사용 (보안)
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)

                names = arguments.get("names")  # 배치 저장용

                # 배치 저장
                if names:
                    result = await self.teams_handler.save_korean_names_batch(user_id, names)
                    # 사용자 친화적인 출력
                    if result.get("success"):
                        output_lines = [f"✅ 배치 저장 완료: {result.get('saved')}개 성공, {result.get('failed')}개 실패\n"]
                        for item in result.get("results", []):
                            status = "✅" if item.get("success") else "❌"
                            output_lines.append(f"{status} {item.get('topic_en')} → {item.get('topic_kr')}")
                        formatted_output = "\n".join(output_lines) + "\n\n" + json.dumps(result, indent=2, ensure_ascii=False)
                        return [TextContent(type="text", text=formatted_output)]
                else:
                    # 단일 저장
                    topic_kr = arguments.get("topic_kr")
                    chat_id = arguments.get("chat_id")
                    topic_en = arguments.get("topic_en")
                    result = await self.teams_handler.save_korean_name(user_id, topic_kr, chat_id, topic_en)

                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            elif name == "teams_get_chats_by_date":
                # 인증된 user_id 사용 (보안)
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)

                days = arguments.get("days")
                start_date = arguments.get("start_date")
                end_date = arguments.get("end_date")
                user_name_filter = arguments.get("user_name_filter")

                result = await self.teams_handler.get_chats_by_date(
                    user_id, days, start_date, end_date, user_name_filter
                )

                # 사용자 친화적인 출력 포맷
                if result.get("success"):
                    users = result.get("users", [])
                    chats = result.get("chats", [])
                    days_info = result.get("days", "지정 범위")

                    output_lines = [f"📅 날짜 범위 채팅 조회 ({days_info}일)\n"]
                    output_lines.append(f"📊 총 {len(users)}명과 대화, {len(chats)}개 채팅방\n")

                    if result.get("filtered_by_user"):
                        output_lines.append(f"🔍 필터: {result['filtered_by_user']}\n")

                    output_lines.append("=" * 50)
                    output_lines.append("👥 사용자별 정리\n")

                    for idx, user in enumerate(users[:50], 1):  # 최대 50명까지 표시
                        user_name = user.get("user_name", "알 수 없음")
                        chat_type = user.get("chat_type", "unknown")
                        last_activity = user.get("last_activity", "")

                        type_icon = "💬" if chat_type == "oneOnOne" else "👥"
                        output_lines.append(f"{idx}. {type_icon} {user_name}")
                        output_lines.append(f"   마지막 활동: {last_activity}")
                        output_lines.append(f"   Chat ID: {user.get('chat_id', '')}")
                        output_lines.append("")

                    if len(users) > 50:
                        output_lines.append(f"... 외 {len(users) - 50}명 더 있음\n")

                    formatted_output = "\n".join(output_lines) + "\n" + json.dumps(result, indent=2, ensure_ascii=False)
                    return [TextContent(type="text", text=formatted_output)]

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
            if name == "teams_help":
                return {
                    "success": True,
                    "help_text": self._get_help_text()
                }

            elif name == "teams_list_chats":
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)
                sort_by = arguments.get("sort_by", "recent")
                limit = arguments.get("limit")
                filter_by_name = arguments.get("filter_by_name")
                return await self.teams_handler.list_chats(user_id, sort_by, limit, filter_by_name)

            elif name == "teams_get_chat_messages":
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)
                chat_id = arguments.get("chat_id")
                recipient_name = arguments.get("recipient_name")
                limit = arguments.get("limit", 50)
                return await self.teams_handler.get_chat_messages(user_id, chat_id, recipient_name, limit)

            elif name == "teams_send_chat_message":
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)

                content = arguments.get("content")
                chat_id = arguments.get("chat_id")
                recipient_name = arguments.get("recipient_name")
                prefix = arguments.get("prefix", "[claude]")
                return await self.teams_handler.send_chat_message(user_id, content, chat_id, recipient_name, prefix)

            elif name == "teams_search_messages":
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)
                keyword = arguments.get("keyword")
                search_scope = arguments.get("search_scope", "all_chats")
                chat_id = arguments.get("chat_id")
                page_size = arguments.get("page_size", 50)
                max_results = arguments.get("max_results", 500)
                return await self.teams_handler.search_messages(
                    user_id, keyword, search_scope, chat_id, page_size, max_results
                )

            elif name == "teams_save_korean_name":
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)
                names = arguments.get("names")

                if names:
                    # 배치 저장
                    return await self.teams_handler.save_korean_names_batch(user_id, names)
                else:
                    # 단일 저장
                    topic_kr = arguments.get("topic_kr")
                    chat_id = arguments.get("chat_id")
                    topic_en = arguments.get("topic_en")
                    return await self.teams_handler.save_korean_name(user_id, topic_kr, chat_id, topic_en)

            elif name == "teams_get_chats_by_date":
                from infra.core.auth_helpers import get_authenticated_user_id
                user_id = get_authenticated_user_id(arguments, authenticated_user_id)
                days = arguments.get("days")
                start_date = arguments.get("start_date")
                end_date = arguments.get("end_date")
                user_name_filter = arguments.get("user_name_filter")

                return await self.teams_handler.get_chats_by_date(
                    user_id, days, start_date, end_date, user_name_filter
                )

            else:
                raise ValueError(f"알 수 없는 도구: {name}")

        except Exception as e:
            logger.error(f"❌ Tool 실행 오류: {name}, {str(e)}", exc_info=True)
            raise
