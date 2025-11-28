# Calendar MCP Module

Microsoft Outlook Calendar API를 사용한 일정 관리 MCP 모듈입니다.

## 개요

이 모듈은 Microsoft Graph API를 통해 Outlook Calendar와 연동하여 일정을 관리할 수 있는 MCP (Model Context Protocol) 핸들러를 제공합니다. outlook_mcp 모듈에서 상속하여 사용할 수 있도록 설계되었습니다.

## 기능

### Calendar Handler (`calendar_handler.py`)

Graph API를 사용한 실제 비즈니스 로직 구현:

- `list_events()` - 일정 목록 조회
  - 날짜 범위 필터링
  - 검색어 기반 조회
  - 기본값: 오늘부터 30일 후까지

- `create_event()` - 일정 생성
  - 일반 일정
  - 온라인 회의 (Teams 연동)
  - 종일 일정
  - 참석자 추가

- `update_event()` - 일정 수정
  - 제목, 시간, 위치 변경
  - 참석자 관리
  - 부분 업데이트 지원

- `delete_event()` - 일정 삭제

- `get_event()` - 특정 일정 상세 조회

### MCP Handlers (`handlers.py`)

MCP 프로토콜 인터페이스 구현:

- `handle_calendar_list_tools()` - Calendar 도구 목록 제공
- `handle_calendar_call_tool()` - Calendar 도구 실행
- `call_calendar_tool_as_dict()` - HTTP API용 헬퍼

### Schemas (`schemas.py`)

Pydantic 기반 데이터 모델:

- `CalendarEvent` - 일정 데이터 모델
- `ListEventsRequest/Response` - 일정 목록 조회
- `CreateEventRequest/Response` - 일정 생성
- `UpdateEventRequest/Response` - 일정 수정
- `DeleteEventRequest/Response` - 일정 삭제

## 사용 방법

### 1. 독립 모듈로 사용

```python
from modules.calendar_mcp import CalendarHandlers

# 핸들러 초기화
handlers = CalendarHandlers()

# MCP 도구 목록 조회
tools = await handlers.handle_calendar_list_tools()

# 도구 실행
result = await handlers.handle_calendar_call_tool(
    "calendar_list_events",
    {"user_id": "kimghw"}
)
```

### 2. 상속하여 사용 (outlook_mcp)

```python
from infra.handlers.attachment_filter_handlers import AttachmentFilterHandlers
from modules.calendar_mcp import CalendarHandlers

class MCPHandlers(AttachmentFilterHandlers, CalendarHandlers):
    def __init__(self):
        # 다중 상속 초기화
        AttachmentFilterHandlers.__init__(self)
        CalendarHandlers.__init__(self)

    async def handle_list_tools(self):
        # 부모 클래스의 도구 추가
        calendar_tools = await self.handle_calendar_list_tools()
        # ... 다른 도구와 병합
```

## MCP 도구 목록

### 1. calendar_list_events

일정 목록 조회

**파라미터:**
- `user_id` (필수) - 사용자 ID
- `start_date` - 시작 날짜 (YYYY-MM-DD)
- `end_date` - 종료 날짜 (YYYY-MM-DD)
- `limit` - 조회할 일정 수 (기본 50)
- `search_query` - 검색어 (제목 검색)

**예시:**
```json
{
  "user_id": "kimghw",
  "start_date": "2024-10-01",
  "end_date": "2024-10-31",
  "limit": 100
}
```

### 2. calendar_create_event

새 일정 생성

**파라미터:**
- `user_id` (필수) - 사용자 ID
- `subject` (필수) - 일정 제목
- `start` (필수) - 시작 시간 (ISO 8601)
- `end` (필수) - 종료 시간 (ISO 8601)
- `body` - 일정 내용
- `location` - 위치
- `attendees` - 참석자 이메일 목록
- `is_all_day` - 종일 일정 여부 (기본 false)
- `is_online_meeting` - 온라인 회의 여부 (기본 false)

**예시:**
```json
{
  "user_id": "kimghw",
  "subject": "팀 회의",
  "start": "2024-10-25T14:00:00",
  "end": "2024-10-25T15:00:00",
  "body": "월간 팀 미팅",
  "location": "회의실 A",
  "is_online_meeting": true,
  "attendees": ["colleague@company.com"]
}
```

### 3. calendar_update_event

기존 일정 수정

**파라미터:**
- `user_id` (필수) - 사용자 ID
- `event_id` (필수) - 일정 ID
- `subject` - 일정 제목
- `start` - 시작 시간 (ISO 8601)
- `end` - 종료 시간 (ISO 8601)
- `body` - 일정 내용
- `location` - 위치
- `attendees` - 참석자 이메일 목록
- `is_online_meeting` - 온라인 회의 여부

**예시:**
```json
{
  "user_id": "kimghw",
  "event_id": "AAMkADY...",
  "subject": "팀 회의 (수정됨)",
  "start": "2024-10-25T15:00:00",
  "end": "2024-10-25T16:00:00"
}
```

### 4. calendar_delete_event

일정 삭제

**파라미터:**
- `user_id` (필수) - 사용자 ID
- `event_id` (필수) - 일정 ID

**예시:**
```json
{
  "user_id": "kimghw",
  "event_id": "AAMkADY..."
}
```

### 5. calendar_get_event

특정 일정 상세 조회

**파라미터:**
- `user_id` (필수) - 사용자 ID
- `event_id` (필수) - 일정 ID

**예시:**
```json
{
  "user_id": "kimghw",
  "event_id": "AAMkADY..."
}
```

## API 권한 요구사항

Microsoft Graph API의 다음 권한이 필요합니다:

- `Calendars.ReadWrite` - 일정 읽기 및 쓰기
- `Calendars.Read` - 일정 읽기 (조회만 필요한 경우)
- `OnlineMeetings.ReadWrite` - 온라인 회의 생성 (is_online_meeting=true 사용 시)

## 테스트

### Unit 테스트

```bash
pytest tests/handlers/test_calendar_handlers.py -v
```

### JSON-RPC 테스트

```bash
./tests/handlers/run_jsonrpc_tests.sh calendar
```

테스트 케이스는 `tests/handlers/jsonrpc_cases/calendar.json`에 정의되어 있습니다.

## 의존성

- `httpx` - HTTP 클라이언트
- `pydantic` - 데이터 검증
- `mcp` - MCP 프로토콜
- `infra.core.logger` - 로깅
- `infra.core.token_service` - 토큰 관리
- `infra.core.database` - 데이터베이스 관리

## 파일 구조

```
modules/calendar_mcp/
├── __init__.py              # 모듈 초기화 및 export
├── calendar_handler.py      # Graph API 비즈니스 로직
├── handlers.py              # MCP 프로토콜 핸들러
├── schemas.py               # Pydantic 데이터 모델
├── README.md                # 이 파일
└── mcp_server/              # HTTP/stdio 서버 (선택적)
```

## 통합 현황

### outlook_mcp

`modules/outlook_mcp/mcp_server/handlers.py`:

```python
class MCPHandlers(AttachmentFilterHandlers, CalendarHandlers):
    """MCP Protocol handlers for Mail Query (상속: AttachmentFilterHandlers, CalendarHandlers)"""

    def __init__(self):
        # 다중 상속 초기화
        AttachmentFilterHandlers.__init__(self)
        CalendarHandlers.__init__(self)
        # ...
```

outlook_mcp는 다음 도구들을 모두 제공합니다:
- Mail Query 도구 (query_email, query_email_help, help)
- Attachment 도구 (attachmentManager)
- **Calendar 도구 (calendar_list_events, calendar_create_event, etc.)**

## 라이선스

이 프로젝트의 라이선스와 동일
