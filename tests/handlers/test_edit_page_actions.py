#!/usr/bin/env python3
"""
edit_page 핸들러의 다양한 action 테스트

사용법:
    python tests/handlers/test_edit_page_actions.py
"""

import sys
import asyncio
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from modules.onenote_mcp.handlers import OneNoteHandlers


def print_test_result(test_name: str, passed: bool, details: str = ""):
    """테스트 결과 출력"""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} - {test_name}")
    if details:
        print(f"  {details}")


async def test_edit_page_append():
    """edit_page (append) 핸들러 테스트"""
    print("\n📝 [1/6] edit_page (append) 핸들러 테스트...")

    try:
        handler = OneNoteHandlers()
        result = await handler.handle_call_tool(
            "edit_page",
            {
                "user_id": "kimghw",
                "page_id": "1-test-page",
                "action": "append",
                "content": "<p>끝에 추가할 내용</p>"
            }
        )
        result_text = result[0].text if result else ""

        # 결과 검증
        success = "success" in result_text.lower() or "액세스 토큰이 없습니다" in result_text
        print_test_result("edit_page (append)", success, result_text[:200])

        return success

    except Exception as e:
        print_test_result("edit_page (append)", False, f"Exception: {e}")
        return False


async def test_edit_page_prepend():
    """edit_page (prepend) 핸들러 테스트"""
    print("\n📝 [2/6] edit_page (prepend) 핸들러 테스트...")

    try:
        handler = OneNoteHandlers()
        result = await handler.handle_call_tool(
            "edit_page",
            {
                "user_id": "kimghw",
                "page_id": "1-test-page",
                "action": "prepend",
                "content": "<p>시작에 추가할 내용</p>"
            }
        )
        result_text = result[0].text if result else ""

        # 결과 검증
        success = "success" in result_text.lower() or "액세스 토큰이 없습니다" in result_text
        print_test_result("edit_page (prepend)", success, result_text[:200])

        return success

    except Exception as e:
        print_test_result("edit_page (prepend)", False, f"Exception: {e}")
        return False


async def test_edit_page_insert():
    """edit_page (insert) 핸들러 테스트"""
    print("\n📝 [3/6] edit_page (insert) 핸들러 테스트...")

    try:
        handler = OneNoteHandlers()
        result = await handler.handle_call_tool(
            "edit_page",
            {
                "user_id": "kimghw",
                "page_id": "1-test-page",
                "action": "insert",
                "target": "#p:test-guid",
                "position": "after",
                "content": "<p>특정 위치에 삽입할 내용</p>"
            }
        )
        result_text = result[0].text if result else ""

        # 결과 검증
        success = "success" in result_text.lower() or "액세스 토큰이 없습니다" in result_text
        print_test_result("edit_page (insert)", success, result_text[:200])

        return success

    except Exception as e:
        print_test_result("edit_page (insert)", False, f"Exception: {e}")
        return False


async def test_edit_page_replace():
    """edit_page (replace) 핸들러 테스트"""
    print("\n📝 [4/6] edit_page (replace) 핸들러 테스트...")

    try:
        handler = OneNoteHandlers()
        result = await handler.handle_call_tool(
            "edit_page",
            {
                "user_id": "kimghw",
                "page_id": "1-test-page",
                "action": "replace",
                "target": "#p:test-guid",
                "content": "<p>교체할 내용</p>"
            }
        )
        result_text = result[0].text if result else ""

        # 결과 검증
        success = "success" in result_text.lower() or "액세스 토큰이 없습니다" in result_text
        print_test_result("edit_page (replace)", success, result_text[:200])

        return success

    except Exception as e:
        print_test_result("edit_page (replace)", False, f"Exception: {e}")
        return False


async def test_edit_page_clean():
    """edit_page (clean) 핸들러 테스트"""
    print("\n🧹 [5/6] edit_page (clean) 핸들러 테스트...")

    try:
        handler = OneNoteHandlers()
        result = await handler.handle_call_tool(
            "edit_page",
            {
                "user_id": "kimghw",
                "page_id": "1-test-page",
                "action": "clean",
                "keep_title": True
            }
        )
        result_text = result[0].text if result else ""

        # 결과 검증
        success = "success" in result_text.lower() or "액세스 토큰이 없습니다" in result_text
        print_test_result("edit_page (clean with title)", success, result_text[:200])

        return success

    except Exception as e:
        print_test_result("edit_page (clean with title)", False, f"Exception: {e}")
        return False


async def test_edit_page_clean_all():
    """edit_page (clean all) 핸들러 테스트"""
    print("\n🧹 [6/6] edit_page (clean all) 핸들러 테스트...")

    try:
        handler = OneNoteHandlers()
        result = await handler.handle_call_tool(
            "edit_page",
            {
                "user_id": "kimghw",
                "page_id": "1-test-page",
                "action": "clean",
                "keep_title": False
            }
        )
        result_text = result[0].text if result else ""

        # 결과 검증
        success = "success" in result_text.lower() or "액세스 토큰이 없습니다" in result_text
        print_test_result("edit_page (clean all)", success, result_text[:200])

        return success

    except Exception as e:
        print_test_result("edit_page (clean all)", False, f"Exception: {e}")
        return False


async def run_tests():
    """비동기 테스트 실행"""
    results = []

    # 테스트 실행
    results.append(await test_edit_page_append())
    results.append(await test_edit_page_prepend())
    results.append(await test_edit_page_insert())
    results.append(await test_edit_page_replace())
    results.append(await test_edit_page_clean())
    results.append(await test_edit_page_clean_all())

    return results


def main():
    """메인 테스트 실행"""
    print("=" * 80)
    print("🧪 edit_page 핸들러 다양한 action 테스트")
    print("=" * 80)

    # 비동기 테스트 실행
    results = asyncio.run(run_tests())

    # 결과 요약
    print("\n" + "=" * 80)
    print("📊 테스트 결과 요약")
    print("=" * 80)

    total = len(results)
    passed = sum(results)
    failed = total - passed

    print(f"총 테스트: {total}개")
    print(f"✅ 성공: {passed}개")
    print(f"❌ 실패: {failed}개")

    if failed == 0:
        print("\n✅ 모든 테스트 통과!")
        return 0
    else:
        print(f"\n❌ {failed}개의 테스트 실패")
        return 1


if __name__ == "__main__":
    sys.exit(main())
