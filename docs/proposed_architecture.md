# 제안하는 모듈 아키텍처

## 1. 모듈별 독립 구조 (추천)

각 모듈이 완전히 독립적으로 동작하도록 구성:

```
modules/
├── base_mcp/                     # 공통 기능
│   ├── __init__.py
│   ├── base_auth_handler.py     # 상속 가능한 기본 OAuth 클래스
│   ├── base_db_service.py       # 상속 가능한 기본 DB 클래스
│   └── base_token_manager.py    # 상속 가능한 토큰 관리 클래스
│
├── outlook_mcp/
│   ├── __init__.py
│   ├── auth/
│   │   ├── __init__.py
│   │   └── outlook_auth.py      # OutlookAuthHandler(BaseAuthHandler)
│   ├── db/
│   │   ├── __init__.py
│   │   └── outlook_db.py        # OutlookDB(BaseDB)
│   ├── handlers.py
│   └── data/
│       └── outlook.db           # 인증 + 서비스 데이터 통합
│
├── teams_mcp/
│   ├── auth/
│   │   └── teams_auth.py        # TeamsAuthHandler(BaseAuthHandler)
│   ├── db/
│   │   └── teams_db.py          # TeamsDB(BaseDB)
│   └── data/
│       └── teams.db
│
└── onenote_mcp/
    ├── auth/
    │   └── onenote_auth.py      # OneNoteAuthHandler(BaseAuthHandler)
    ├── db/
    │   └── onenote_db.py        # OneNoteDB(BaseDB)
    └── data/
        └── onenote.db
```

## 2. 데이터베이스 스키마 관리

### 각 모듈의 DB는 통합 스키마:
```sql
-- outlook.db / teams.db / onenote.db 공통
CREATE TABLE accounts (
    -- 인증 정보
    user_id TEXT PRIMARY KEY,
    access_token TEXT,
    refresh_token TEXT,
    token_expiry TIMESTAMP,

    -- 서비스별 추가 필드
    ...
);

CREATE TABLE service_data (
    -- 각 서비스별 고유 데이터
    ...
);
```

## 3. 인증 처리 방식

### BaseAuthHandler (공통 클래스)
```python
class BaseAuthHandler:
    def __init__(self, db_service):
        self.db = db_service

    def authenticate(self, user_id):
        """공통 인증 로직"""
        pass

    def refresh_token(self, user_id):
        """공통 토큰 갱신"""
        pass
```

### OutlookAuthHandler (상속)
```python
class OutlookAuthHandler(BaseAuthHandler):
    def authenticate(self, user_id):
        # Outlook 특화 처리
        result = super().authenticate(user_id)
        # 추가 Outlook 로직
        return result
```

## 4. 장점

1. **독립성**: 각 모듈이 완전히 독립적
2. **확장성**: 새 모듈 추가 시 기존 모듈 영향 없음
3. **유지보수**: 모듈별로 별도 관리 가능
4. **테스트**: 모듈 단위 테스트 용이
5. **배포**: 선택적 배포 가능 (필요한 모듈만)

## 5. 마이그레이션 전략

### Phase 1: 공통 base 클래스 생성
- BaseAuthHandler, BaseDBService 생성
- 기존 코드와 호환성 유지

### Phase 2: 모듈별 마이그레이션
- 한 번에 하나씩 모듈 마이그레이션
- 기존 DCR 모듈과 병행 운영

### Phase 3: 통합 테스트
- 모든 모듈 독립 동작 확인
- DCR 모듈 제거

## 6. 환경 변수 관리

각 모듈별 독립적인 환경변수:
```bash
# Outlook
OUTLOOK_DB_PATH=./data/outlook.db
OUTLOOK_CLIENT_ID=xxx
OUTLOOK_CLIENT_SECRET=xxx

# Teams
TEAMS_DB_PATH=./data/teams.db
TEAMS_CLIENT_ID=xxx
TEAMS_CLIENT_SECRET=xxx

# OneNote
ONENOTE_DB_PATH=./data/onenote.db
ONENOTE_CLIENT_ID=xxx
ONENOTE_CLIENT_SECRET=xxx
```