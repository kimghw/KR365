# Mail Query 모듈

Microsoft Graph API를 통해 메일 데이터를 조회하고 필터링하는 모듈입니다. OData 쿼리를 활용한 고급 필터링과 효율적인 페이징 처리를 지원합니다.

## 🔄 데이터 파이프라인 구조

```
MailQueryRequest (user_id, filters, pagination)
        ↓
MailQueryOrchestrator
        ↓
TokenService (토큰 검증/갱신)
        ↓
ODataFilterBuilder (필터 쿼리 생성)
        ↓
GraphAPIClient
        ↓
Microsoft Graph API (/me/messages)
        ↓
    ┌─────────────────┬──────────────────┐
    ↓                 ↓                  ↓
GraphMailItem 변환   페이징 처리      query_logs 테이블
    ↓                 ↓                  ↓
MailQueryResponse   다음 페이지      실행 로그 기록
```

### 동작 방식
1. **토큰 검증**: TokenService를 통해 유효한 액세스 토큰 확보
2. **필터 구성**: OData 쿼리 문자열 생성 (`$filter`, `$select`, `$orderby`)
3. **API 호출**: Microsoft Graph API에 페이징된 요청
4. **데이터 변환**: JSON 응답을 GraphMailItem 객체로 파싱
5. **로그 기록**: 쿼리 실행 정보를 query_logs 테이블에 저장

## 📋 모듈 설정 파일 관리

### 환경 변수 설정 (`.env`)
```env
# Graph API 설정
GRAPH_API_BASE_URL=https://graph.microsoft.com/v1.0
GRAPH_API_TIMEOUT=30
GRAPH_API_MAX_RETRIES=3

# 페이징 설정
MAIL_QUERY_DEFAULT_PAGE_SIZE=50
MAIL_QUERY_MAX_PAGE_SIZE=1000
MAIL_QUERY_DEFAULT_MAX_PAGES=10

# 성능 설정
MAIL_QUERY_ENABLE_CACHING=false
MAIL_QUERY_CACHE_TTL=300

# 로깅 설정
MAIL_QUERY_LOG_LEVEL=INFO
MAIL_QUERY_LOG_QUERIES=true
```

## 🚀 모듈별 사용 방법 및 예시

### 1. 기본 메일 조회
```python
from modules.mail_query import (
    MailQueryOrchestrator, 
    MailQueryRequest
)
import asyncio

async def basic_mail_query():
    # 컨텍스트 매니저로 자동 리소스 정리
    async with MailQueryOrchestrator() as orchestrator:
        request = MailQueryRequest(user_id="kimghw")
        response = await orchestrator.mail_query_user_emails(request)
        
        print(f"조회된 메일: {response.total_fetched}개")
        
        for mail in response.messages[:5]:  # 상위 5개만
            print(f"\n제목: {mail.subject}")
            print(f"발신자: {mail.from_address.get('emailAddress', {}).get('address')}")
            print(f"수신 시간: {mail.received_date_time}")
            print(f"첨부파일: {'있음' if mail.has_attachments else '없음'}")

asyncio.run(basic_mail_query())
```

### 2. 필터링된 조회
```python
from modules.mail_query import MailQuerySeverFilters, PaginationOptions
from datetime import datetime, timedelta

async def filtered_query():
    async with MailQueryOrchestrator() as orchestrator:
        # 필터 설정
        filters = MailQuerySeverFilters(
            date_from=datetime.now() - timedelta(days=7),  # 최근 7일
            is_read=False,                                 # 읽지 않은 메일
            has_attachments=True,                          # 첨부파일 있음
            importance="high",                             # 중요도 높음
            subject_contains="프로젝트"                    # 제목에 "프로젝트" 포함
        )
        
        # 페이징 설정
        pagination = PaginationOptions(
            top=100,        # 페이지당 100개
            skip=0,         # 처음부터
            max_pages=5     # 최대 5페이지 (500개)
        )
        
        request = MailQueryRequest(
            user_id="kimghw",
            filters=filters,
            pagination=pagination,
            select_fields=["id", "subject", "from", "receivedDateTime", "bodyPreview"]
        )
        
        response = await orchestrator.mail_query_user_emails(request)
        
        print(f"필터 조건: {response.query_info['odata_filter']}")
        print(f"조회 성능: {response.query_info['performance_estimate']}")
        print(f"실행 시간: {response.execution_time_ms}ms")
```

### 3. 메시지 검색 ($search)
```python
async def search_messages():
    async with MailQueryOrchestrator() as orchestrator:
        # 키워드 검색
        response = await orchestrator.mail_query_search_messages(
            user_id="kimghw",
            search_term="계약서",
            select_fields=["id", "subject", "from", "receivedDateTime"],
            top=50
        )
        
        print(f"'{search_term}' 검색 결과: {response.total_fetched}개")
        
        for mail in response.messages:
            print(f"- {mail.subject} ({mail.received_date_time.date()})")
```

### 4. 특정 메시지 조회
```python
async def get_specific_message():
    async with MailQueryOrchestrator() as orchestrator:
        # 메시지 ID로 조회
        message = await orchestrator.mail_query_get_message_by_id(
            user_id="kimghw",
            message_id="AAMkADU2MGM5YzRjLTE4NmItNDE4NC...",
            select_fields=["id", "subject", "body", "attachments"]
        )
        
        print(f"제목: {message.subject}")
        print(f"본문: {message.body.get('content', '')[:200]}...")
```

### 5. 메일 JSON 저장
```python
async def save_mails_as_json():
    async with MailQueryOrchestrator() as orchestrator:
        # 메일 조회
        request = MailQueryRequest(
            user_id="kimghw",
            filters=MailQuerySeverFilters(date_from=datetime(2025, 6, 1))
        )
        response = await orchestrator.mail_query_user_emails(request)
        
        # JSON 파일로 저장
        saved_files = await orchestrator.save_messages_to_json(
            messages=response.messages,
            save_dir="./data/mail_samples/2025-06"
        )
        
        print(f"{len(saved_files)}개 파일 저장 완료")
```

## 📊 OData 필터 옵션

### 지원하는 필터 조건
| 필터 | OData 쿼리 | 예시 |
|------|------------|------|
| `date_from` | `receivedDateTime ge {date}` | 2025-06-01 이후 |
| `date_to` | `receivedDateTime le {date}` | 2025-06-30 이전 |
| `sender_address` | `from/emailAddress/address eq '{email}'` | sender@company.com |
| `subject_contains` | `contains(subject, '{text}')` | "회의" 포함 |
| `is_read` | `isRead eq {bool}` | true/false |
| `has_attachments` | `hasAttachments eq {bool}` | true/false |
| `importance` | `importance eq '{level}'` | low/normal/high |

### 필터 조합 예시
```python
# 복잡한 필터 조합
filters = MailQuerySeverFilters(
    date_from=datetime(2025, 6, 1),
    date_to=datetime(2025, 6, 30),
    sender_address="manager@company.com",
    has_attachments=True,
    is_read=False
)

# 생성되는 OData 쿼리:
# receivedDateTime ge 2025-06-01T00:00:00.000Z and 
# receivedDateTime le 2025-06-30T23:59:59.000Z and 
# from/emailAddress/address eq 'manager@company.com' and 
# hasAttachments eq true and 
# isRead eq false
```

## 🚀 성능 최적화

### 1. 필드 선택 ($select)
```python
# 필요한 필드만 조회하여 성능 향상
request = MailQueryRequest(
    user_id="kimghw",
    select_fields=["id", "subject", "receivedDateTime"]  # 3개 필드만
)
```

### 2. 페이징 전략
```python
# 대량 데이터 조회 시
pagination = PaginationOptions(
    top=200,      # 큰 페이지 크기
    max_pages=50  # 많은 페이지
)

# 빠른 미리보기
pagination = PaginationOptions(
    top=20,       # 작은 페이지
    max_pages=1   # 첫 페이지만
)
```

### 3. 성능 예측
```python
# query_info의 performance_estimate 확인
response = await orchestrator.mail_query_user_emails(request)
performance = response.query_info['performance_estimate']

if performance == "SLOW":
    print("⚠️ 쿼리 성능이 느릴 수 있습니다. 필터를 조정해보세요.")
```

## 📈 쿼리 로그 분석

### query_logs 테이블 구조
```sql
CREATE TABLE query_logs (
    id INTEGER PRIMARY KEY,
    user_id TEXT,
    query_type TEXT,          -- 'mail_query' or 'mail_search'
    odata_filter TEXT,        -- 사용된 필터
    select_fields TEXT,       -- 선택된 필드
    result_count INTEGER,     -- 조회된 결과 수
    execution_time_ms INTEGER,-- 실행 시간
    has_error BOOLEAN,        -- 오류 발생 여부
    error_message TEXT,       -- 오류 메시지
    created_at TIMESTAMP
);
```

### 로그 조회 예시
```python
from infra.core import get_database_manager

db = get_database_manager()

# 최근 느린 쿼리 조회
slow_queries = db.fetch_all("""
    SELECT user_id, odata_filter, execution_time_ms 
    FROM query_logs 
    WHERE execution_time_ms > 1000 
    ORDER BY created_at DESC 
    LIMIT 10
""")
```

## ⚠️ 주의사항

### API 제한사항
1. **Rate Limiting**: 분당 요청 수 제한
2. **페이지 크기**: 최대 1000개
3. **$search 제한**: 최대 250개 결과

### 에러 처리
```python
from infra.core.exceptions import TokenExpiredError, APIConnectionError

try:
    response = await orchestrator.mail_query_user_emails(request)
except TokenExpiredError:
    print("토큰이 만료되었습니다. 재인증이 필요합니다.")
except APIConnectionError as e:
    print(f"API 연결 실패: {e}")
```

## 🔗 다른 모듈과의 연계

### Token Service
- 자동 토큰 검증 및 갱신
- 401 오류 시 자동 재시도

### Mail Processor
- Mail Query로 조회한 메일을 처리
- 중복 확인을 위한 message_id 활용

### Database
- query_logs 테이블에 실행 이력 저장
- 성능 분석 및 최적화에 활용

## 🎯 사용 사례

### 1. 일일 보고서용 메일 수집
```python
# 어제 받은 모든 보고서 메일 조회
filters = MailQuerySeverFilters(
    date_from=datetime.now().date() - timedelta(days=1),
    date_to=datetime.now().date(),
    subject_contains="일일보고"
)
```

### 2. 첨부파일 관리
```python
# 대용량 첨부파일이 있는 메일 찾기
filters = MailQuerySeverFilters(
    has_attachments=True,
    date_from=datetime.now() - timedelta(days=30)
)
```

### 3. 중요 메일 알림
```python
# 읽지 않은 중요 메일 확인
filters = MailQuerySeverFilters(
    is_read=False,
    importance="high"
)
```