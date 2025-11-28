# Mail Query $search 기능 사용 가이드

## 개요

Microsoft Graph API의 `$search` 기능을 사용하여 발신자명과 키워드로 메일을 검색할 수 있습니다.

## ✨ 자동 구분 로직

`mail_query_user_emails()` 메서드는 **자동으로 검색 방식을 선택**합니다:

- `filters.search_query`가 **있으면** → `$search` 방식 사용 (전문 검색)
- `filters.search_query`가 **없으면** → `$filter` 방식 사용 (구조화된 필터링)

**하나의 메서드만 사용하면 됩니다!**

## 주요 기능

### 1. 기본 키워드 검색
모든 필드(제목, 본문, 발신자 등)에서 키워드를 검색합니다.

```python
from modules.mail_query import (
    MailQueryOrchestrator,
    MailQueryRequest,
    MailQuerySeverFilters,
)

async with MailQueryOrchestrator() as orchestrator:
    # search_query가 있으면 자동으로 $search 방식 사용
    request = MailQueryRequest(
        user_id="kimghw",
        filters=MailQuerySeverFilters(search_query="계약서"),
        select_fields=["id", "subject", "from", "receivedDateTime"],
    )

    # mail_query_user_emails()만 호출하면 됨!
    response = await orchestrator.mail_query_user_emails(request)

    print(f"검색 결과: {response.total_fetched}개")
    print(f"검색 방식: {response.query_info['query_type']}")  # "$search"
    for mail in response.messages:
        print(f"- {mail.subject}")
```

### 2. 발신자명 검색
특정 발신자로부터 받은 메일을 검색합니다.

```python
filters = MailQuerySeverFilters(search_query="from:홍길동")
```

또는 이메일 주소로 검색:
```python
filters = MailQuerySeverFilters(search_query="from:hong@company.com")
```

### 3. AND 조건 검색
여러 키워드가 모두 포함된 메일을 검색합니다.

```python
filters = MailQuerySeverFilters(search_query="프로젝트 AND 승인")
```

결과: "프로젝트"와 "승인" 모두 포함된 메일

### 4. OR 조건 검색
여러 키워드 중 하나 이상 포함된 메일을 검색합니다.

```python
filters = MailQuerySeverFilters(search_query="보고서 OR 리포트")
```

결과: "보고서" 또는 "리포트"가 포함된 메일

### 5. 복합 조건 검색
여러 조건을 조합할 수 있습니다.

```python
# 홍길동이 보낸 메일 중 "계약서"가 포함된 메일
filters = MailQuerySeverFilters(search_query="from:홍길동 계약서")

# "프로젝트"와 ("승인" 또는 "검토")가 포함된 메일
filters = MailQuerySeverFilters(search_query="프로젝트 AND (승인 OR 검토)")
```

## 지원되는 검색 키워드

| 키워드 | 설명 | 예시 |
|--------|------|------|
| `from:` | 발신자명 또는 이메일 | `from:홍길동`, `from:hong@company.com` |
| `to:` | 수신자 | `to:kim@company.com` |
| `subject:` | 제목 | `subject:계약서` |
| `body:` | 본문 | `body:승인요청` |
| `hasattachments:yes` | 첨부파일 있음 | `hasattachments:yes` |
| `importance:high` | 중요도 높음 | `importance:high` |
| `AND` | 모든 조건 만족 | `keyword1 AND keyword2` |
| `OR` | 조건 중 하나 만족 | `keyword1 OR keyword2` |
| `NOT` | 제외 | `project NOT draft` |

## 제한사항

1. **최대 결과 수**: `$search`는 최대 250개 결과만 반환
2. **페이징 제한**: `skip` 파라미터 사용 불가
3. **필수 헤더**: `ConsistencyLevel: eventual` 헤더 필요 (자동 추가됨)
4. **성능**: 첫 검색 시 느릴 수 있음 (인덱싱)

## 완전한 예제

### 예제 1: $search 방식 (전문 검색)

```python
import asyncio
from modules.mail_query import (
    MailQueryOrchestrator,
    MailQueryRequest,
    MailQuerySeverFilters,
    PaginationOptions,
)

async def search_emails():
    async with MailQueryOrchestrator() as orchestrator:
        # search_query가 있으면 자동으로 $search 방식
        request = MailQueryRequest(
            user_id="kimghw",
            filters=MailQuerySeverFilters(
                search_query="from:홍길동 프로젝트"  # 👈 이것만 있으면 $search
            ),
            select_fields=[
                "id",
                "subject",
                "from",
                "receivedDateTime",
                "bodyPreview",
                "hasAttachments"
            ],
            pagination=PaginationOptions(top=100)
        )

        response = await orchestrator.mail_query_user_emails(request)

        print(f"검색 방식: {response.query_info['query_type']}")  # "$search"
        print(f"검색 결과: {response.total_fetched}개")
        print(f"실행 시간: {response.execution_time_ms}ms")

        for mail in response.messages:
            print(f"\n제목: {mail.subject}")
            print(f"발신자: {mail.from_address.get('emailAddress', {}).get('address')}")

asyncio.run(search_emails())
```

### 예제 2: $filter 방식 (구조화된 필터링)

```python
from datetime import datetime, timedelta

async def filter_emails():
    async with MailQueryOrchestrator() as orchestrator:
        # search_query가 없으면 자동으로 $filter 방식
        request = MailQueryRequest(
            user_id="kimghw",
            filters=MailQuerySeverFilters(
                date_from=datetime.now() - timedelta(days=7),
                sender_address="hong@company.com",  # 👈 정확한 이메일 주소
                has_attachments=True
            ),
        )

        response = await orchestrator.mail_query_user_emails(request)

        print(f"검색 방식: $filter")
        print(f"필터 조건: {response.query_info.get('odata_filter')}")
        print(f"검색 결과: {response.total_fetched}개")

asyncio.run(filter_emails())
```

### 예제 3: 명시적으로 search_user_emails() 호출

```python
# 명시적으로 $search 방식만 사용하고 싶은 경우
async def explicit_search():
    async with MailQueryOrchestrator() as orchestrator:
        request = MailQueryRequest(
            user_id="kimghw",
            filters=MailQuerySeverFilters(search_query="계약서"),
        )

        # 직접 호출 (자동 전환 없이)
        response = await orchestrator.search_user_emails(request)

asyncio.run(explicit_search())
```

## $filter vs $search 비교

| 기능 | $filter (mail_query_user_emails) | $search (search_user_emails) |
|------|----------------------------------|------------------------------|
| 검색 대상 | 특정 필드만 | 모든 필드 전체 검색 |
| 정확도 | 정확한 매칭 | 자연어 검색 (유사 매칭) |
| 성능 | 빠름 | 상대적으로 느림 |
| 최대 결과 | 무제한 (페이징) | 250개 제한 |
| 발신자 검색 | 이메일 주소만 | 이름도 가능 |
| 사용 예 | 구조화된 필터링 | 텍스트 검색 |

## 로그 확인

검색 실행 정보는 `query_logs` 테이블에 기록됩니다:

```sql
SELECT
    user_id,
    search_query,
    result_count,
    execution_time_ms,
    created_at
FROM query_logs
WHERE query_type = '$search'
ORDER BY created_at DESC
LIMIT 10;
```

## 문제 해결

### 검색 결과가 없는 경우
1. 검색어 철자 확인
2. 다른 키워드로 시도
3. OR 조건 사용하여 범위 확대

### 검색이 느린 경우
1. 검색 범위를 좁히기 (예: `from:` 추가)
2. 구체적인 키워드 사용
3. `$filter` 방식 사용 고려

### 인증 오류
```python
# TokenExpiredError 발생 시
# infra.token_service가 자동으로 토큰 갱신 시도
# 실패 시 재인증 필요
```
