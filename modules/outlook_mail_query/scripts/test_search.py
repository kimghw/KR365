"""
$search 기능 테스트 스크립트
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from modules.outlook_mail_query import (
    MailQueryOrchestrator,
    MailQueryRequest,
    MailQuerySeverFilters,
    PaginationOptions,
)


async def test_search_basic():
    """기본 검색 테스트"""
    print("=" * 60)
    print("1. 기본 키워드 검색 테스트")
    print("=" * 60)

    async with MailQueryOrchestrator() as orchestrator:
        request = MailQueryRequest(
            user_id="kimghw",
            filters=MailQuerySeverFilters(search_query="계약서"),
            select_fields=["id", "subject", "from", "receivedDateTime"],
        )

        response = await orchestrator.search_user_emails(request)

        print(f"\n검색어: '계약서'")
        print(f"결과 수: {response.total_fetched}개")
        print(f"실행 시간: {response.execution_time_ms}ms")
        print(f"\n상위 5개 결과:")

        for i, mail in enumerate(response.messages[:5], 1):
            print(f"\n{i}. {mail.subject}")
            print(f"   발신자: {mail.from_address.get('emailAddress', {}).get('address')}")
            print(f"   수신: {mail.received_date_time}")


async def test_search_from():
    """발신자 검색 테스트"""
    print("\n" + "=" * 60)
    print("2. 발신자 검색 테스트")
    print("=" * 60)

    async with MailQueryOrchestrator() as orchestrator:
        request = MailQueryRequest(
            user_id="kimghw",
            filters=MailQuerySeverFilters(search_query="from:홍길동"),
            select_fields=["id", "subject", "from", "receivedDateTime"],
        )

        response = await orchestrator.search_user_emails(request)

        print(f"\n검색어: 'from:홍길동'")
        print(f"결과 수: {response.total_fetched}개")
        print(f"실행 시간: {response.execution_time_ms}ms")


async def test_search_and():
    """AND 조건 검색 테스트"""
    print("\n" + "=" * 60)
    print("3. AND 조건 검색 테스트")
    print("=" * 60)

    async with MailQueryOrchestrator() as orchestrator:
        request = MailQueryRequest(
            user_id="kimghw",
            filters=MailQuerySeverFilters(search_query="프로젝트 AND 승인"),
            select_fields=["id", "subject", "from", "receivedDateTime"],
        )

        response = await orchestrator.search_user_emails(request)

        print(f"\n검색어: '프로젝트 AND 승인'")
        print(f"결과 수: {response.total_fetched}개")
        print(f"실행 시간: {response.execution_time_ms}ms")


async def test_search_or():
    """OR 조건 검색 테스트"""
    print("\n" + "=" * 60)
    print("4. OR 조건 검색 테스트")
    print("=" * 60)

    async with MailQueryOrchestrator() as orchestrator:
        request = MailQueryRequest(
            user_id="kimghw",
            filters=MailQuerySeverFilters(search_query="보고서 OR 리포트"),
            select_fields=["id", "subject", "from", "receivedDateTime"],
        )

        response = await orchestrator.search_user_emails(request)

        print(f"\n검색어: '보고서 OR 리포트'")
        print(f"결과 수: {response.total_fetched}개")
        print(f"실행 시간: {response.execution_time_ms}ms")


async def main():
    """메인 함수"""
    try:
        await test_search_basic()
        await test_search_from()
        await test_search_and()
        await test_search_or()

        print("\n" + "=" * 60)
        print("✅ 모든 테스트 완료")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 테스트 실패: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
