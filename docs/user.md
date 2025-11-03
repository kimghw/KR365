# 사용자 질문 및 답변

## 1. dcr_azure_app 테이블 데이터 저장 방식

### 질문
`dcr_azure_app` 테이블에 시간(`created_at`)을 제외하고 다른 정보가 들어오면 데이터가 추가 저장되는가?

### 답변
**아니요, 추가 저장이 아니라 UPDATE(덮어쓰기)됩니다.**

### 상세 설명

#### 테이블 구조
```sql
CREATE TABLE IF NOT EXISTS dcr_azure_app (
    application_id TEXT PRIMARY KEY,      -- Azure Application (client) ID
    client_secret TEXT NOT NULL,          -- Azure Client Secret (암호화)
    tenant_id TEXT NOT NULL,              -- Azure Tenant ID
    redirect_uri TEXT,                    -- Azure에 등록된 Redirect URI
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Primary Key: `application_id`**
- 하나의 `application_id`당 **1개의 레코드만** 존재
- 같은 `application_id`로 다시 저장하면 **덮어쓰기(UPDATE)**

#### 저장 로직 ([azure_config.py:57-97](modules/dcr_oauth/azure_config.py#L57-L97))

```python
def save_azure_config_to_db(service):
    # 1. 기존 레코드 확인
    existing = service._fetch_one(
        "SELECT application_id FROM dcr_azure_app WHERE application_id = ?",
        (service.azure_application_id,),
    )

    if existing:
        # 2-A. 존재하면 UPDATE (덮어쓰기)
        service._execute_query(
            """
            UPDATE dcr_azure_app
            SET client_secret = ?, tenant_id = ?, redirect_uri = ?
            WHERE application_id = ?
            """,
            (...)
        )
    else:
        # 2-B. 없으면 INSERT (새로 추가)
        service._execute_query(
            """
            INSERT INTO dcr_azure_app (application_id, client_secret, tenant_id, redirect_uri)
            VALUES (?, ?, ?, ?)
            """,
            (...)
        )
```

#### 환경변수 변경 시 동작 ([azure_config.py:128-173](modules/dcr_oauth/azure_config.py#L128-L173))

**환경변수에서 Azure 설정이 변경되면:**

1. **DB의 기존 값과 비교**
   ```python
   changes = []
   if env_app_id != current_app_id:
       changes.append("application_id")
   if env_secret != current_secret:
       changes.append("client_secret")
   # ... 기타 필드 비교
   ```

2. **변경 사항이 있으면 UPDATE 실행**
   ```python
   UPDATE dcr_azure_app
   SET application_id = ?, client_secret = ?, tenant_id = ?, redirect_uri = ?
   WHERE application_id = ?
   ```

3. **모든 활성 DCR Bearer 토큰 무효화**
   ```python
   UPDATE dcr_tokens
   SET dcr_status = 'revoked'
   WHERE dcr_status = 'active'
     AND dcr_token_type IN ('Bearer', 'refresh')
   ```
   - 보안상 이유: Azure 앱이 바뀌면 기존 토큰은 무효화해야 함

---

## 정리

### dcr_azure_app 테이블 특성

| 상황 | 동작 | 레코드 수 변화 |
|------|------|--------------|
| 최초 저장 | INSERT | 0 → 1 |
| 같은 application_id로 다시 저장 | UPDATE | 1 → 1 (덮어쓰기) |
| 다른 application_id로 저장 | UPDATE (기존 레코드 변경) | 1 → 1 |
| 환경변수 변경 감지 | UPDATE + 토큰 무효화 | 1 → 1 |

### 핵심

- **추가 저장(INSERT) 아님**
- **덮어쓰기(UPDATE)됨**
- **항상 1개의 Azure 앱 정보만 유지**
- **변경 시 기존 DCR 토큰 자동 무효화**

---

## 관련 파일

- 테이블 스키마: [modules/dcr_oauth/migrations/dcr_schema_v3.sql](modules/dcr_oauth/migrations/dcr_schema_v3.sql#L5-L11)
- 저장 로직: [modules/dcr_oauth/azure_config.py:save_azure_config_to_db](modules/dcr_oauth/azure_config.py#L57-L97)
- 환경변수 동기화: [modules/dcr_oauth/azure_config.py:load_azure_config](modules/dcr_oauth/azure_config.py#L99-L190)

---

## 2. dcr_azure_users 테이블 데이터 저장 방식

### 질문
`dcr_azure_users` 테이블은 내용이 다르면 추가로 생성되는가?

### 답변
**상황에 따라 다릅니다.**
- **같은 사용자(object_id)**: REPLACE (덮어쓰기)
- **다른 사용자(object_id)**: INSERT (새로 추가)

### 상세 설명

#### 테이블 구조
```sql
CREATE TABLE IF NOT EXISTS dcr_azure_users (
    object_id TEXT PRIMARY KEY,           -- Azure User Object ID
    application_id TEXT NOT NULL,         -- 어느 Azure 앱으로 받았는지
    access_token TEXT NOT NULL,           -- Azure Access Token (암호화)
    refresh_token TEXT,                   -- Azure Refresh Token (암호화)
    expires_at DATETIME NOT NULL,
    scope TEXT,
    user_email TEXT,
    user_name TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (application_id) REFERENCES dcr_azure_app(application_id)
);
```

**Primary Key: `object_id` (Azure 사용자 고유 ID)**
- 하나의 `object_id`당 **1개의 레코드만** 존재
- **사용자별로** 토큰 저장

#### 저장 로직
```sql
INSERT OR REPLACE INTO dcr_azure_users (
    object_id, application_id, access_token, refresh_token, expires_at,
    scope, user_email, user_name, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
```

**`INSERT OR REPLACE` 의미:**
- `object_id`가 없으면 → INSERT (새 레코드 추가)
- `object_id`가 있으면 → REPLACE (기존 레코드 덮어쓰기)

---

## 시나리오별 동작

### 시나리오 1: 사용자 A가 첫 로그인
```
DB 상태: 비어있음

사용자 A 로그인 (object_id: aaa-111)
→ INSERT (새 레코드 추가)

결과:
| object_id | user_email          | access_token |
|-----------|---------------------|--------------|
| aaa-111   | alice@company.com   | token_A      |
```

### 시나리오 2: 사용자 A가 토큰 갱신
```
DB 상태:
| object_id | user_email          | access_token |
|-----------|---------------------|--------------|
| aaa-111   | alice@company.com   | token_A      |

사용자 A 토큰 갱신 (object_id: aaa-111)
→ REPLACE (기존 레코드 덮어쓰기)

결과:
| object_id | user_email          | access_token  |
|-----------|---------------------|---------------|
| aaa-111   | alice@company.com   | token_A_new   |  ← 갱신됨
```

### 시나리오 3: 사용자 B가 로그인
```
DB 상태:
| object_id | user_email          | access_token  |
|-----------|---------------------|---------------|
| aaa-111   | alice@company.com   | token_A_new   |

사용자 B 로그인 (object_id: bbb-222)
→ INSERT (새 레코드 추가)

결과:
| object_id | user_email          | access_token  |
|-----------|---------------------|---------------|
| aaa-111   | alice@company.com   | token_A_new   |
| bbb-222   | bob@company.com     | token_B       |  ← 추가됨
```

### 시나리오 4: 사용자 A와 B 모두 활성
```
DB 상태:
| object_id | user_email          | access_token  |
|-----------|---------------------|---------------|
| aaa-111   | alice@company.com   | token_A_new   |
| bbb-222   | bob@company.com     | token_B       |

사용자 A가 다시 토큰 갱신
→ REPLACE (A의 레코드만 갱신, B는 그대로)

결과:
| object_id | user_email          | access_token    |
|-----------|---------------------|-----------------|
| aaa-111   | alice@company.com   | token_A_newest  |  ← A만 갱신
| bbb-222   | bob@company.com     | token_B         |  ← B는 그대로
```

---

## 정리 (2)

### dcr_azure_users 테이블 특성

| 상황 | 동작 | 설명 |
|------|------|------|
| 새 사용자 로그인 | INSERT | 새 object_id → 레코드 추가 |
| 기존 사용자 토큰 갱신 | REPLACE | 같은 object_id → 덮어쓰기 |
| 여러 사용자 로그인 | INSERT (각각) | 사용자별로 독립적인 레코드 |

### dcr_azure_app vs dcr_azure_users 비교

| 테이블 | Primary Key | 저장 대상 | 레코드 수 | 갱신 방식 |
|--------|-------------|-----------|----------|----------|
| **dcr_azure_app** | application_id | **Azure 앱 정보** | **1개** (앱 정보) | UPDATE |
| **dcr_azure_users** | object_id | **사용자 토큰** | **N개** (사용자 수) | INSERT OR REPLACE |

### 핵심 (2)

- **dcr_azure_app**: 1개의 Azure 앱 정보만 유지 (덮어쓰기)
- **dcr_azure_users**: 사용자별로 토큰 관리 (사용자당 1개, 여러 사용자 가능)
- **멀티 테넌시**: 여러 사용자가 각자의 토큰을 가질 수 있음

### 관련 파일 (2)

- 테이블 스키마: [modules/dcr_oauth/migrations/dcr_schema_v3.sql](modules/dcr_oauth/migrations/dcr_schema_v3.sql#L14-L30)
- 저장 로직: modules/dcr_oauth/dcr_service.py (INSERT OR REPLACE 사용)

---

## 3. dcr_clients 테이블 데이터 저장 방식 (사용자별 격리)

### 질문
`dcr_clients` 테이블은 사용자별로 독립적인 클라이언트를 생성하는가?

### 답변
**예, 플랫폼 + 사용자 조합별로 독립적인 클라이언트를 유지합니다.**

### 상세 설명

#### 테이블 구조
```sql
CREATE TABLE IF NOT EXISTS dcr_clients (
    dcr_client_id TEXT PRIMARY KEY,
    dcr_client_secret TEXT NOT NULL,
    dcr_client_name TEXT,
    dcr_redirect_uris TEXT,
    dcr_grant_types TEXT,
    dcr_requested_scope TEXT,
    azure_application_id TEXT NOT NULL,
    azure_object_id TEXT,  -- 어느 사용자가 등록했는지 (NULL = 로그인 전)
    user_email TEXT,        -- 사용자 이메일 (참고용)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (azure_application_id) REFERENCES dcr_azure_app(application_id),
    FOREIGN KEY (azure_object_id) REFERENCES dcr_azure_users(object_id) ON DELETE SET NULL
);

-- 플랫폼 + 사용자별 유니크 제약
CREATE UNIQUE INDEX IF NOT EXISTS idx_dcr_clients_platform_user
ON dcr_clients(azure_application_id, json_extract(dcr_redirect_uris, '$[0]'), azure_object_id)
WHERE azure_object_id IS NOT NULL;
```

**핵심 특징:**
- `azure_object_id`: 사용자 식별자 (로그인 전에는 NULL)
- Unique Index: 같은 플랫폼에 같은 사용자가 중복 등록 방지

#### 2단계 등록 로직

**1단계: 클라이언트 등록 (로그인 전)** - [dcr_service.py:register_client](modules/dcr_oauth/dcr_service.py#L96-L182)

```python
async def register_client(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
    """초기 등록 시 azure_object_id = NULL로 생성"""

    # 미할당 클라이언트 찾기 (같은 플랫폼 + redirect_uri, object_id = NULL)
    existing_query = """
    SELECT dcr_client_id, dcr_client_secret, created_at
    FROM dcr_clients
    WHERE azure_application_id = ?
      AND json_extract(dcr_redirect_uris, '$[0]') = ?
      AND azure_object_id IS NULL  -- 미할당만
    ORDER BY created_at DESC
    LIMIT 1
    """

    if existing_client:
        # 기존 미할당 클라이언트 재사용
        return existing_client_info
    else:
        # 새 클라이언트 생성 (azure_object_id = NULL)
        INSERT INTO dcr_clients (..., azure_object_id, user_email)
        VALUES (..., NULL, NULL)
```

**2단계: 사용자 연결 (로그인 완료 후)** - [dcr_service.py:update_client_user](modules/dcr_oauth/dcr_service.py#L184-L253)

```python
def update_client_user(
    self,
    dcr_client_id: str,
    azure_object_id: str,
    user_email: str,
    redirect_uri: str
) -> str:
    """로그인 완료 후 클라이언트에 사용자 정보를 연결

    Returns:
        사용할 client_id (기존 것이 있으면 그것, 없으면 현재 것)
    """

    # 1. 이미 이 사용자가 같은 플랫폼에 등록한 클라이언트 확인
    existing_user_client = SELECT dcr_client_id
        FROM dcr_clients
        WHERE azure_application_id = ?
          AND json_extract(dcr_redirect_uris, '$[0]') = ?
          AND azure_object_id = ?  -- 사용자가 이미 할당된 클라이언트

    if existing_user_client:
        # 기존 클라이언트 재사용 - 현재 클라이언트 삭제
        DELETE FROM dcr_tokens WHERE dcr_client_id = ?  # 현재 클라이언트 토큰 삭제
        DELETE FROM dcr_clients WHERE dcr_client_id = ?  # 현재 클라이언트 삭제
        return existing_client_id  # 기존 클라이언트 ID 반환
    else:
        # 현재 클라이언트에 사용자 정보 업데이트
        UPDATE dcr_clients
        SET azure_object_id = ?, user_email = ?, updated_at = CURRENT_TIMESTAMP
        WHERE dcr_client_id = ?
        return dcr_client_id  # 현재 클라이언트 ID 반환
```

**호출 위치:** [unified_http_server.py:oauth_azure_callback_handler](entrypoints/production/unified_http_server.py#L1351-L1368)

```python
# Azure 로그인 완료 후
final_client_id = dcr_service.update_client_user(
    dcr_client_id=client_id,
    azure_object_id=azure_object_id,
    user_email=user_email,
    redirect_uri=redirect_uri
)

# 만약 기존 클라이언트로 교체되었다면, auth_code의 client_id도 업데이트
if final_client_id != client_id:
    UPDATE dcr_tokens
    SET dcr_client_id = ?
    WHERE dcr_token_value = ? AND dcr_token_type = 'authorization_code'
```

---

## 시나리오별 동작 (3)

### 시나리오 1: 사용자 A가 Claude.ai에서 첫 로그인

```
1. Claude.ai → POST /oauth/register
   → dcr_clients 생성 (client_id: dcr_aaa, object_id: NULL)

2. Claude.ai → GET /oauth/authorize?client_id=dcr_aaa
   → Azure 로그인 페이지로 리디렉트

3. 사용자 A 로그인 (object_id: user-a-111)
   → Azure callback → update_client_user()
   → dcr_clients 업데이트 (client_id: dcr_aaa, object_id: user-a-111)

결과:
| dcr_client_id | azure_object_id | user_email          |
|---------------|-----------------|---------------------|
| dcr_aaa       | user-a-111      | alice@company.com   |
```

### 시나리오 2: 사용자 B가 Claude.ai에서 로그인

```
1. Claude.ai → POST /oauth/register
   → 기존 미할당 클라이언트 없음 (user-a-111이 이미 dcr_aaa 사용 중)
   → 새 클라이언트 생성 (client_id: dcr_bbb, object_id: NULL)

2. 사용자 B 로그인 (object_id: user-b-222)
   → dcr_clients 업데이트 (client_id: dcr_bbb, object_id: user-b-222)

결과:
| dcr_client_id | azure_object_id | user_email          |
|---------------|-----------------|---------------------|
| dcr_aaa       | user-a-111      | alice@company.com   |
| dcr_bbb       | user-b-222      | bob@company.com     |
```

### 시나리오 3: 사용자 A가 다시 Claude.ai에 연결 (재등록)

```
1. Claude.ai → POST /oauth/register
   → 새 클라이언트 생성 (client_id: dcr_ccc, object_id: NULL)

2. 사용자 A 로그인 (object_id: user-a-111)
   → update_client_user() 실행
   → 기존 클라이언트 확인: dcr_aaa (user-a-111이 이미 등록됨)
   → dcr_ccc 삭제, dcr_aaa 재사용

결과:
| dcr_client_id | azure_object_id | user_email          |
|---------------|-----------------|---------------------|
| dcr_aaa       | user-a-111      | alice@company.com   |  ← 계속 사용
| dcr_bbb       | user-b-222      | bob@company.com     |
```

### 시나리오 4: 사용자 A가 ChatGPT에서 로그인

```
1. ChatGPT → POST /oauth/register (redirect_uri: chatgpt.com)
   → 새 클라이언트 생성 (client_id: dcr_ddd, object_id: NULL)

2. 사용자 A 로그인 (object_id: user-a-111)
   → dcr_clients 업데이트 (client_id: dcr_ddd, object_id: user-a-111)

결과:
| dcr_client_id | azure_object_id | user_email          | redirect_uri      |
|---------------|-----------------|---------------------|-------------------|
| dcr_aaa       | user-a-111      | alice@company.com   | claude.ai         |
| dcr_bbb       | user-b-222      | bob@company.com     | claude.ai         |
| dcr_ddd       | user-a-111      | alice@company.com   | chatgpt.com       |

→ 사용자 A는 플랫폼별로 독립적인 클라이언트 유지!
```

---

## 정리 (3)

### dcr_clients 테이블 특성

| 상황 | 동작 | 레코드 수 변화 |
|------|------|----------------|
| 첫 등록 (로그인 전) | INSERT (object_id=NULL) | +1 미할당 클라이언트 |
| 로그인 완료 | UPDATE (object_id 업데이트) | 미할당 → 할당됨 |
| 재로그인 (같은 플랫폼) | 기존 클라이언트 재사용, 새 클라이언트 삭제 | 0 (변화 없음) |
| 다른 플랫폼 로그인 | 새 클라이언트 생성 | +1 (플랫폼별 독립) |

### 사용자별 격리 보장

```
사용자 A + Claude.ai → dcr_client_A_Claude → Bearer token A_Claude → Azure token A
사용자 B + Claude.ai → dcr_client_B_Claude → Bearer token B_Claude → Azure token B
사용자 A + ChatGPT   → dcr_client_A_ChatGPT → Bearer token A_ChatGPT → Azure token A
```

**핵심 보안:**
- Bearer token → dcr_client_id → azure_object_id → Azure access_token
- 사용자별로 독립적인 Bearer token 사용
- Cross-user 데이터 접근 불가능

### 관련 파일 (3)

- 테이블 스키마: [modules/dcr_oauth/migrations/dcr_schema_v3.sql](modules/dcr_oauth/migrations/dcr_schema_v3.sql#L32-L51)
- 등록 로직: [modules/dcr_oauth/dcr_service.py:register_client](modules/dcr_oauth/dcr_service.py#L96-L182)
- 사용자 연결: [modules/dcr_oauth/dcr_service.py:update_client_user](modules/dcr_oauth/dcr_service.py#L184-L253)
- 호출 위치: [entrypoints/production/unified_http_server.py:oauth_azure_callback_handler](entrypoints/production/unified_http_server.py#L1351-L1368)
