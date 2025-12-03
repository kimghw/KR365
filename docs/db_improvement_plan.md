# DB 구조 개선 계획

## 현재 문제점
1. **DB 분리로 인한 복잡도**
   - `auth_outlook.db` + `outlook.db` = 2개 DB 관리
   - 동기화 로직 필요
   - 트랜잭션 처리 어려움

2. **DCR 사용 여부에 따른 분기**
   - DCR 사용/미사용 케이스 모두 지원 필요
   - 코드 복잡도 증가

## 개선 방안: 통합 DB 구조

### 1단계: DB 통합
각 모듈별 단일 DB로 통합

```
기존:
data/
├── auth_outlook.db  (인증 정보)
├── outlook.db       (서비스 데이터)
├── auth_teams.db
├── teams.db
├── auth_onenote.db
└── onenote.db

개선:
data/
├── outlook.db      (인증 + 서비스 통합)
├── teams.db        (인증 + 서비스 통합)
└── onenote.db      (인증 + 서비스 통합)
```

### 2단계: 스키마 통합

```sql
-- outlook.db / teams.db / onenote.db 공통 스키마

-- 1. 계정 테이블 (기존 accounts)
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE,
    user_name TEXT,
    email TEXT UNIQUE,

    -- DCR OAuth 정보 (NULL 가능)
    dcr_client_id TEXT,
    dcr_client_secret TEXT,
    dcr_tenant_id TEXT,
    dcr_redirect_uri TEXT,

    -- 일반 OAuth 정보 (NULL 가능)
    oauth_client_id TEXT,
    oauth_client_secret TEXT,

    -- 인증 타입
    auth_type TEXT DEFAULT 'none',  -- 'dcr', 'oauth', 'none'

    -- 토큰 정보
    access_token TEXT,
    refresh_token TEXT,
    token_expiry TIMESTAMP,

    -- 권한
    delegated_permissions TEXT,

    -- 상태
    status TEXT DEFAULT 'active',
    is_active BOOLEAN DEFAULT TRUE,

    -- 메타데이터
    last_sync_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. OAuth 플로우 로그 (기존 oauth_flow_logs)
CREATE TABLE oauth_flow_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_type TEXT,
    user_id TEXT,
    status TEXT,
    error_code TEXT,
    error_description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. 서비스별 데이터 테이블
-- Outlook: emails, attachments
-- Teams: chats, messages, meetings
-- OneNote: notebooks, sections, pages
```

### 3단계: 코드 구조 개선

```python
# modules/base_db_service.py
class BaseDBService:
    def __init__(self, server_name: str):
        # 단일 DB 경로만 관리
        self.db_path = self._get_db_path(server_name)
        self._ensure_tables()

    def _ensure_tables(self):
        """공통 테이블 생성 (accounts, oauth_flow_logs)"""
        pass

    def add_account(self, user_id, auth_type='none', **kwargs):
        """DCR/OAuth/None 모든 케이스 지원"""
        if auth_type == 'dcr':
            # DCR 필드 저장
            pass
        elif auth_type == 'oauth':
            # 일반 OAuth 필드 저장
            pass
        else:
            # 인증 없음
            pass

# modules/outlook_mcp/outlook_db_service.py
class OutlookDBService(BaseDBService):
    def __init__(self):
        super().__init__('outlook')
        self._ensure_outlook_tables()

    def _ensure_outlook_tables(self):
        """Outlook 전용 테이블 생성 (emails, attachments)"""
        pass
```

### 4단계: 마이그레이션 전략

#### 4.1 마이그레이션 스크립트
```python
# scripts/migrate_db.py
def migrate_to_unified_db(server_name):
    """auth_*.db + *.db → 통합 *.db"""

    # 1. 백업 생성
    backup_databases(server_name)

    # 2. 새 통합 DB 생성
    unified_db = f"data/{server_name}_new.db"

    # 3. 데이터 마이그레이션
    # - auth_*.db의 accounts → 통합 DB accounts
    # - auth_*.db의 oauth_flow_logs → 통합 DB
    # - *.db의 서비스 데이터 → 통합 DB

    # 4. 검증
    verify_migration(unified_db)

    # 5. 교체
    replace_with_unified(server_name)
```

#### 4.2 단계별 적용
1. **개발 환경에서 테스트**
2. **한 모듈씩 마이그레이션** (예: outlook → teams → onenote)
3. **롤백 계획 준비**

### 5단계: 환경 변수 단순화

```bash
# 기존
DATABASE_OUTLOOK_PATH=./data/outlook.db
AUTH_DATABASE_OUTLOOK_PATH=./data/auth_outlook.db

# 개선
OUTLOOK_DB_PATH=./data/outlook.db  # 하나로 통합
```

### 6단계: API 호환성 유지

```python
# 기존 코드와 호환성 유지
class BaseDBService:
    @property
    def auth_db_path(self):
        """Deprecated: 호환성을 위해 유지"""
        return self.db_path  # 같은 DB 반환
```

## 장점

1. **단순화**
   - DB 파일 수 50% 감소 (6개 → 3개)
   - 동기화 로직 제거
   - 트랜잭션 처리 단순화

2. **유연성**
   - DCR/OAuth/None 모두 지원
   - auth_type 필드로 구분
   - NULL 허용으로 선택적 사용

3. **성능**
   - 단일 DB 연결
   - JOIN 쿼리 가능
   - 트랜잭션 보장

4. **유지보수**
   - 백업/복구 단순화
   - 스키마 관리 용이
   - 디버깅 편리

## 실행 계획

### Phase 1 (1주차)
- [ ] 마이그레이션 스크립트 작성
- [ ] 개발 환경 테스트

### Phase 2 (2주차)
- [ ] Outlook 모듈 마이그레이션
- [ ] 통합 테스트

### Phase 3 (3주차)
- [ ] Teams, OneNote 마이그레이션
- [ ] 전체 통합 테스트

### Phase 4 (4주차)
- [ ] 문서화
- [ ] 기존 DB 정리

## 주의사항

1. **백업 필수**: 마이그레이션 전 모든 DB 백업
2. **단계별 적용**: 한 번에 모두 변경하지 않고 단계적 적용
3. **롤백 계획**: 문제 발생 시 즉시 이전 버전으로 복구
4. **호환성 유지**: 기존 API 변경 최소화