# MCP 프로토콜 적합성 검토

## 주요 이슈 요약
- `modules/calendar_mcp/entrypoints/stdio_server.py`가 `CalendarHandlers`에 없는 `handle_list_tools`/`handle_call_tool`을 호출해 stdio 모드에서 tools/list·tools/call가 동작하지 않음.
- 여러 HTTP MCP 서버가 `initialize` 응답의 `protocolVersion` 기본값을 `"2025-06-18"`로 고정(`modules/outlook_mcp/mcp_server/http_server.py`, `modules/onedrive_mcp/mcp_server/http_server.py`, `modules/onenote_mcp/mcp_server/http_server.py`, `modules/teams_mcp/mcp_server/http_server.py`, `modules/mail_iacs/mcp_server/http_server.py`). 공식 MCP 버전과 달라 호환성 문제가 발생할 수 있음.
- OneDrive HTTP MCP 서버(`modules/onedrive_mcp/mcp_server/http_server.py`)는 `initialize` 응답에 `Mcp-Session-Id` 헤더를 보내지 않아 세션 재사용이 불가능함(다른 서버들과 불일치).
- Mail Query/ IACS HTTP MCP 서버가 `notifications/initialized` 후 list_changed 알림을 실제로 전송하지 않고 로그만 남김(`modules/outlook_mcp/mcp_server/http_server.py`, `modules/mail_iacs/mcp_server/http_server.py`). capabilities에는 listChanged가 true로 표시되어 있어 클라이언트 기대와 불일치.
- Mail Query MCP에서 `handle_get_prompt`는 구현되어 있지만 `handle_list_prompts`가 빈 목록을 반환(`modules/outlook_mcp/mcp_server/handlers.py`), prompts 기능이 발견되지 않음.
- 여러 서버가 `resources` capability를 true로 광고하지만 `resources/read`가 미구현되어 “method not found”가 발생(리소스 미지원이면 capability를 빼야 함).

## 개선 제안
[] 1. Calendar stdio: `handlers.handle_calendar_list_tools`/`handle_calendar_call_tool`을 호출하도록 수정하거나 `CalendarHandlers`에 wrapper 메서드를 추가해 tools/list·tools/call가 정상 동작하도록 보완.
[] 2. 초기화 버전: `protocolVersion`을 클라이언트 요청값 그대로 사용하고, 기본값은 MCP SDK가 제공하는 공식 버전(예: 상수)으로 통일. `"2025-06-18"` 하드코딩 제거.
[] 3. 세션 헤더: OneDrive HTTP 서버의 `initialize` 응답에도 `Mcp-Session-Id`와 `MCP-Protocol-Version` 헤더를 포함시켜 다른 서버와 일관성을 맞추고 클라이언트 세션 재사용을 보장.
[] 4. list_changed 알림: capabilities를 true로 유지할 경우 `notifications/tools.list_changed`/`prompts.list_changed`/`resources.list_changed`를 실제로 송신하거나, 알림을 보내지 않을 계획이면 listChanged 플래그를 false/미노출로 조정.
[] 5. Prompts: Mail Query MCP의 `handle_list_prompts`에서 실제 제공 가능한 프롬프트를 반환하도록 수정해 prompts 기능이 노출되게 개선.
[] 6. Resources capability: 리소스를 지원하지 않는 서버는 capabilities에서 `resources`를 제거하거나 false로 설정. 지원이 필요하다면 최소한 `resources/read`를 추가해 명시적 에러(unsupported 등)를 반환하도록 구현.
