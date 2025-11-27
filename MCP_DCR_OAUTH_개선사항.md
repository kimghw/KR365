# MCP + DCR OAuth2 구조 개선 사항

## 검토 일시
2025-11-27

## 검토 범위
- `/home/kimghw/KR365/modules/dcr_oauth_module/`
- `/home/kimghw/KR365/modules/mail_query_MCP/`

---

## 🔴 긴급 (보안/기능 장애)

### 1. MCP 엔드포인트 인증 정책 수정
**파일**: `modules/mail_query_MCP/implementations/fastapi_server.py`
**위치**: Lines 538-566

**문제**:
- MCP 표준 엔드포인트(`/`, `/mcp`, `/stream`)에 `required_auth` 의존성 적용
- MCP 클라이언트가 `initialize` 호출 전에는 토큰을 가질 수 없어 인증 불가능
- 표준 MCP 초기화 플로우가 차단됨

**현재 코드**:
```python
@app.post("/", response_model=MCPResponse, ...)
async def mcp_endpoint(request: Request, user_data: dict = Depends(required_auth)):
    """MCP Protocol endpoint with required DCR authentication"""
```

**권장 수정**:
```python
@app.post("/", response_model=MCPResponse, ...)
async def mcp_endpoint(request: Request, user_data: dict = Depends(optional_auth)):
    """MCP Protocol endpoint with optional DCR authentication"""
    # initialize, tools/list는 인증 없이 허용
    # tools/call은 인증된 사용자만 허용 (핸들러 내부에서 검증)
```

**우선순위**: 🔴 긴급 (MCP 클라이언트 연결 불가)

---

### 2. Authorization Code 테이블명 오류 수정
**파일**: `modules/mail_query_MCP/implementations/dcr_endpoints.py`
**위치**: Lines 283-299

**문제**:
- `auth_code_result` 쿼리가 잘못된 테이블명 사용
- `dcr_oauth` 테이블은 존재하지 않음 (실제는 `dcr_tokens_{module_name}`)
- Authorization Code 검증 시 Azure 코드 조회 실패

**현재 코드**:
```python
auth_code_result = dcr_service.db.fetch_one(
    "SELECT metadata FROM dcr_oauth WHERE token_type = 'auth_code' AND token_value = ?",
    (code,)
)
```

**권장 수정**:
```python
auth_code_result = dcr_service.db_service.fetch_one(
    f"SELECT metadata FROM {dcr_service._get_table_name('dcr_tokens')} "
    f"WHERE dcr_token_type = 'authorization_code' AND dcr_token_value = ?",
    (code,)
)
```

**우선순위**: 🔴 긴급 (토큰 교환 실패)

---

### 3. 토큰 무효화 쿼리 f-string 누락
**파일**: `modules/dcr_oauth_module/dcr_service.py`
**위치**: Lines 1101-1109

**문제**:
- f-string 미적용으로 테이블명 치환되지 않음
- 기존 Bearer 토큰 무효화 실패
- 다중 활성 토큰 생성 가능성

**현재 코드**:
```python
invalidate_query = """
UPDATE {self._get_table_name('dcr_tokens')}
SET dcr_status = 'revoked'
WHERE dcr_client_id = ? AND azure_object_id = ? ...
"""
```

**권장 수정**:
```python
invalidate_query = f"""
UPDATE {self._get_table_name('dcr_tokens')}
SET dcr_status = 'revoked'
WHERE dcr_client_id = ? AND azure_object_id = ? ...
"""
```

**우선순위**: 🔴 긴급 (토큰 관리 오류)

---

## 🟠 중요 (안정성)

### 4. 인증 제외 경로 범위 과도하게 넓음
**파일**: `modules/mail_query_MCP/middleware/auth_dependencies.py`
**위치**: Lines 48-65

**문제**:
- `/oauth` 전체 경로가 인증 제외됨
- `/oauth/token` 같은 민감 엔드포인트도 인증 없이 접근 가능
- 보안 취약점

**현재 코드**:
```python
excluded_paths = [
    "/.well-known",
    "/oauth",  # 너무 넓음
    "/health",
    ...
]
```

**권장 수정**:
```python
excluded_paths = [
    "/.well-known",
    "/oauth/register",
    "/oauth/authorize",
    "/oauth/azure_callback",
    "/oauth/.well-known",
    "/health",
    ...
]
# /oauth/token은 제외하지 않음 (클라이언트 인증 필요)
```

**우선순위**: 🟠 중요 (보안 취약점)

---

### 5. Graph API 호출 실패 시 에러 처리 미흡
**파일**: `modules/mail_query_MCP/implementations/fastapi_server.py`
**위치**: Lines 836-875

**문제**:
- 사용자 정보 조회 실패 시 경고만 로깅하고 계속 진행
- `object_id`, `user_email` 없이 DCR 저장 시도 가능
- 불완전한 인증 상태

**현재 코드**:
```python
except Exception as user_fetch_error:
    logger.warning(f"⚠️ Could not fetch user info from Graph API: {str(user_fetch_error)}")
# 계속 진행됨
```

**권장 수정**:
```python
except Exception as user_fetch_error:
    logger.error(f"❌ Failed to fetch user info from Graph API: {str(user_fetch_error)}")
    html = f"""
    <html>
    <head><title>인증 오류</title></head>
    <body>
        <h1>❌ 사용자 정보 조회 실패</h1>
        <p>Microsoft Graph API에서 사용자 정보를 가져올 수 없습니다.</p>
        <p>오류: {str(user_fetch_error)}</p>
    </body>
    </html>
    """
    return HTMLResponse(html, status_code=500)
```

**우선순위**: 🟠 중요 (데이터 무결성)

---

### 6. PKCE 함수 import 이름 불일치
**파일**: `modules/dcr_oauth_module/dcr_service.py`
**위치**: Lines 25, 1405-1409

**문제**:
- `_verify_pkce_helper` import하지만 실제 함수는 `verify_code_verifier`
- PKCE 검증 실패 가능성

**현재 코드**:
```python
from .pkce import verify_pkce as _verify_pkce_helper  # 존재하지 않음

def _verify_pkce(self, code_verifier: str, code_challenge: str, method: str = "plain") -> bool:
    return _verify_pkce_helper(code_verifier, code_challenge, method)
```

**권장 수정**:
```python
from .pkce import verify_code_verifier as _verify_pkce_helper

def _verify_pkce(self, code_verifier: str, code_challenge: str, method: str = "plain") -> bool:
    return _verify_pkce_helper(code_verifier, code_challenge, method)
```

**우선순위**: 🟠 중요 (PKCE 기능 오류)

---

## 🟡 개선 (유지보수성)

### 7. 레거시 OAuth 엔드포인트 중복
**파일**: `modules/mail_query_MCP/implementations/fastapi_server.py`
**위치**: Lines 643-909

**문제**:
- `/auth/login`, `/auth/callback`이 DCR 표준(`/oauth/*`)과 별도 존재
- 인증 경로 혼란 및 유지보수 부담
- 보안 정책 불일치 가능성

**권장 조치**:
1. DCR 표준 경로로 통합하거나
2. 명확한 용도 분리 및 문서화
   - `/auth/*`: 직접 브라우저 로그인
   - `/oauth/*`: DCR 표준 플로우

**우선순위**: 🟡 개선 (코드 정리)

---

### 8. MCP 세션 재사용 로직 부재
**파일**: `modules/mail_query_MCP/implementations/fastapi_server.py`
**위치**: Lines 203-238

**문제**:
- 매 `initialize` 호출마다 새 세션 생성
- 클라이언트 재연결 시 기존 컨텍스트 손실

**권장 수정**:
```python
# 클라이언트가 Mcp-Session-Id 헤더를 보내면 재사용
existing_session_id = request.headers.get("Mcp-Session-Id")
if existing_session_id and existing_session_id in self.sessions:
    logger.info(f"♻️ Reusing existing session: {existing_session_id}")
    session_id = existing_session_id
else:
    session_id = secrets.token_urlsafe(24)
    self.sessions[session_id] = {...}
```

**우선순위**: 🟡 개선 (사용자 경험)

---

### 9. Authorization Code에 사용자 정보 연결 시점 문제
**파일**: `modules/mail_query_MCP/implementations/dcr_endpoints.py`
**위치**: Lines 148-157, 184-238

**문제**:
- Authorization Code 생성 시 `azure_object_id = NULL`
- Azure 콜백에서 사용자 정보 획득했지만 Authorization Code에 반영 안됨
- 토큰 교환 시 사용자 식별 불가능

**권장 수정**:
`/oauth/azure_callback`에서 Azure 코드 저장 시 사용자 정보도 업데이트:
```python
# Azure 사용자 정보 조회
async with httpx.AsyncClient() as client:
    headers = {"Authorization": f"Bearer {temp_access_token}"}
    response = await client.get("https://graph.microsoft.com/v1.0/me", headers=headers)
    user_info = response.json()
    azure_object_id = user_info.get("id")

# Authorization Code에 사용자 정보 연결
dcr_service.update_auth_code_with_object_id(state, azure_object_id)
```

**우선순위**: 🟡 개선 (인증 플로우 완성도)

---

### 10. 클라이언트 병합 시 트랜잭션 처리 부재
**파일**: `modules/dcr_oauth_module/dcr_service.py`
**위치**: Lines 593-617

**문제**:
- 토큰 마이그레이션 후 클라이언트 삭제
- 중간 실패 시 일관성 깨짐 (토큰은 이전되었지만 클라이언트는 남음)

**권장 수정**:
```python
# 트랜잭션 시작
try:
    # 1. 토큰 마이그레이션
    migrate_tokens_query = ...
    self._execute_query(migrate_tokens_query, ...)

    # 2. 클라이언트 삭제
    delete_old_client_query = ...
    self._execute_query(delete_old_client_query, ...)

    # 커밋 (DCRDatabaseService에 트랜잭션 지원 추가 필요)
except Exception as e:
    # 롤백
    logger.error(f"Client merge failed, rolling back: {e}")
    raise
```

**우선순위**: 🟡 개선 (데이터 일관성)

---

## 📊 요약

| 우선순위 | 항목 수 | 주요 내용 |
|---------|--------|----------|
| 🔴 긴급 | 3 | MCP 인증 정책, 테이블명 오류, f-string 누락 |
| 🟠 중요 | 3 | 인증 경로 보안, Graph API 에러 처리, PKCE import |
| 🟡 개선 | 4 | 레거시 코드 정리, 세션 재사용, 트랜잭션 처리 |

---

## 추가 권장 사항

### 11. 데이터베이스 로깅 최적화
- `DCR_DB_LOGGING=true` 시 모든 쿼리 로깅으로 성능 저하 가능
- 프로덕션 환경에서는 로깅 레벨 세분화 권장 (ERROR/WARN만)

### 12. 설정 관리 통합
- 환경 변수와 `config.json`의 일관성 확보
- DCR 관련 설정을 중앙화하여 관리

### 13. 단위 테스트 추가
- DCR 인증 플로우 엔드투엔드 테스트
- PKCE 검증 로직 테스트
- 토큰 무효화 및 갱신 테스트

---

## 검토 결과

전반적으로 MCP 프로토콜과 DCR OAuth2 표준을 잘 준수하려는 구조이나, 몇 가지 **긴급 수정이 필요한 버그**와 **보안 취약점**이 발견되었습니다.

**우선 조치**:
1. MCP 엔드포인트 인증 정책 수정 (클라이언트 연결 가능하도록)
2. 테이블명 오류 및 f-string 누락 수정 (기능 정상화)
3. 인증 제외 경로 보안 강화

위 3가지만 우선 수정하면 기본 기능이 안정적으로 동작할 것으로 예상됩니다.
