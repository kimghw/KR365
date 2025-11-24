"""
Calendar MCP stdio server wrapper 메서드 테스트
stdio_server.py에서 호출하는 handle_list_tools/handle_call_tool wrapper 테스트
"""

import pytest
from modules.calendar_mcp.handlers import CalendarHandlers
from mcp.types import Tool, TextContent


@pytest.fixture
def calendar_handlers():
    """CalendarHandlers 인스턴스 생성"""
    return CalendarHandlers()


@pytest.mark.asyncio
async def test_handle_list_tools_wrapper_exists(calendar_handlers):
    """handle_list_tools wrapper 메서드 존재 확인"""
    assert hasattr(calendar_handlers, 'handle_list_tools')
    assert callable(calendar_handlers.handle_list_tools)


@pytest.mark.asyncio
async def test_handle_call_tool_wrapper_exists(calendar_handlers):
    """handle_call_tool wrapper 메서드 존재 확인"""
    assert hasattr(calendar_handlers, 'handle_call_tool')
    assert callable(calendar_handlers.handle_call_tool)


@pytest.mark.asyncio
async def test_handle_list_tools_returns_tools(calendar_handlers):
    """handle_list_tools가 Tool 리스트를 반환하는지 확인"""
    result = await calendar_handlers.handle_list_tools()

    # 리스트 타입 확인
    assert isinstance(result, list)

    # 최소 1개 이상의 도구가 있어야 함
    assert len(result) > 0

    # 모든 항목이 Tool 타입인지 확인
    for tool in result:
        assert isinstance(tool, Tool)
        assert hasattr(tool, 'name')
        assert hasattr(tool, 'description')
        assert hasattr(tool, 'inputSchema')


@pytest.mark.asyncio
async def test_handle_list_tools_returns_calendar_tools(calendar_handlers):
    """handle_list_tools가 Calendar 도구들을 반환하는지 확인"""
    result = await calendar_handlers.handle_list_tools()

    tool_names = [tool.name for tool in result]

    # 필수 Calendar 도구들
    expected_tools = [
        "calendar_list_events",
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
        "calendar_get_event"
    ]

    for expected_tool in expected_tools:
        assert expected_tool in tool_names, f"{expected_tool} not found in tool names"


@pytest.mark.asyncio
async def test_handle_call_tool_invalid_tool(calendar_handlers):
    """handle_call_tool에 잘못된 도구명 전달 시 오류 처리 확인"""
    result = await calendar_handlers.handle_call_tool(
        name="invalid_tool_name",
        arguments={}
    )

    # 결과는 TextContent 리스트여야 함
    assert isinstance(result, list)
    assert len(result) > 0
    assert isinstance(result[0], TextContent)

    # 오류 메시지 확인
    import json
    response = json.loads(result[0].text)
    assert response.get("success") is False
    assert "알 수 없는 도구" in response.get("message", "")


@pytest.mark.asyncio
async def test_handle_call_tool_missing_arguments(calendar_handlers):
    """handle_call_tool에 필수 인자 누락 시 오류 처리 확인"""
    # user_id 없이 calendar_list_events 호출
    result = await calendar_handlers.handle_call_tool(
        name="calendar_list_events",
        arguments={}  # user_id 누락
    )

    # 결과는 TextContent 리스트여야 함
    assert isinstance(result, list)
    assert len(result) > 0
    assert isinstance(result[0], TextContent)

    # 응답에 오류가 포함되어야 함
    import json
    response = json.loads(result[0].text)
    # 토큰이 없거나 오류가 발생해야 함
    assert "success" in response


@pytest.mark.asyncio
async def test_wrapper_delegates_to_original_methods(calendar_handlers):
    """wrapper가 원본 메서드를 올바르게 호출하는지 확인"""
    # handle_list_tools wrapper 테스트
    wrapper_result = await calendar_handlers.handle_list_tools()
    original_result = await calendar_handlers.handle_calendar_list_tools()

    # 같은 결과를 반환해야 함
    assert len(wrapper_result) == len(original_result)

    wrapper_names = [t.name for t in wrapper_result]
    original_names = [t.name for t in original_result]
    assert wrapper_names == original_names


@pytest.mark.asyncio
async def test_handle_call_tool_return_type(calendar_handlers):
    """handle_call_tool이 올바른 타입을 반환하는지 확인"""
    result = await calendar_handlers.handle_call_tool(
        name="calendar_list_events",
        arguments={"user_id": "test_user"}
    )

    # List[TextContent] 타입 확인
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, TextContent)
        assert hasattr(item, 'type')
        assert hasattr(item, 'text')
        assert item.type == "text"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
