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
