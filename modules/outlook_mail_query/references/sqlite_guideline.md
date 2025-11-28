# IACSGraph 데이터베이스 가이드

이 문서는 IACSGraph 프로젝트의 SQLite 데이터베이스 스키마와 사용법에 대한 가이드라인을 제공합니다. 신규 기능을 개발하거나 기존 기능을 수정할 때 반드시 이 문서를 참조하십시오.

## 1. 데이터베이스 접속 및 사용법

모든 데이터베이스 상호작용은 `infra.core.database`의 `DatabaseManager`를 통해 이루어져야 합니다. 이는 일관된 연결 관리와 트랜잭션 처리를 보장합니다.

### 1.1 기본 사용 패턴

```python
from infra.core import get_database_manager, get_logger
from infra.core.exceptions import DatabaseError

logger = get_logger(__name__)
db_manager = get_database_manager()

def get_active_users():
    try:
        with db_manager.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, user_name FROM accounts WHERE is_active = ?", (True,))
            return cursor.fetchall()
    except DatabaseError as e:
        logger.error(f"활성 사용자 조회 중 오류 발생: {e}", exc_info=True)
        return []
```

### 1.2 트랜잭션 사용법

데이터의 원자성이 중요한 작업(예: 생성, 수정, 삭제)은 반드시 트랜잭션 내에서 처리해야 합니다.

```python
def update_user_status(user_id: str, is_active: bool):
    try:
        with db_manager.transaction() as conn:
            # 이 블록 내의 모든 작업은 하나의 트랜잭션으로 처리됩니다.
            conn.execute("UPDATE accounts SET is_active = ? WHERE user_id = ?", (is_active, user_id))
            # 관련된 다른 테이블 업데이트 등...
            logger.info(f"{user_id}의 상태를 {is_active}로 변경했습니다.")
        return True
    except DatabaseError as e:
        logger.error(f"{user_id} 상태 업데이트 실패: {e}", exc_info=True)
        return False
```

## 2. 데이터베이스 스키마 정보

데이터베이스는 `iacsgraph.db` 파일에 저장되며, 다음 테이블들로 구성됩니다.

### 2.1 `accounts` 테이블

계정 정보를 저장하는 핵심 테이블입니다.

| 필드명 | 타입 | 설명 |
| --- | --- | --- |
| `id` | `INTEGER` | **PK**, Auto-increment |
| `user_id` | `TEXT` | 사용자 고유 ID (UNIQUE) |
| `user_name` | `TEXT` | 사용자 이름 |
| `access_token` | `TEXT` | **암호화된** 액세스 토큰 |
| `refresh_token` | `TEXT` | **암호화된** 리프레시 토큰 |
| `token_expiry` | `TIMESTAMP` | 토큰 만료 시간 |
| `is_active` | `BOOLEAN` | 계정 활성화 여부 (기본값: `TRUE`) |
| `last_sync_time` | `TIMESTAMP` | 마지막 동기화 시간 |
| `created_at` | `TIMESTAMP` | 생성 시간 (기본값: `CURRENT_TIMESTAMP`) |
| `updated_at` | `TIMESTAMP` | 마지막 수정 시간 (기본값: `CURRENT_TIMESTAMP`) |

### 2.2 `mail_history` 테이블

처리된 메일의 이력을 저장합니다.

| 필드명 | 타입 | 설명 |
| --- | --- | --- |
| `id` | `INTEGER` | **PK**, Auto-increment |
| `account_id` | `INTEGER` | `accounts.id` 외래 키 |
| `message_id` | `TEXT` | 메일의 고유 ID (UNIQUE) |
| `received_time` | `TIMESTAMP` | 메일 수신 시간 |
| `subject` | `TEXT` | 메일 제목 |
| `sender` | `TEXT` | 발신자 |
| `keywords` | `TEXT` | 추출된 키워드 (JSON 형태의 텍스트) |
| `processed_at` | `TIMESTAMP` | 처리 완료 시간 (기본값: `CURRENT_TIMESTAMP`) |

### 2.3 `processing_logs` 테이블

배치 작업 또는 특정 프로세스의 실행 로그를 기록합니다.

| 필드명 | 타입 | 설명 |
| --- | --- | --- |
| `id` | `INTEGER` | **PK**, Auto-increment |
| `run_id` | `TEXT` | 실행의 고유 ID (e.g., `uuid`) |
| `account_id` | `INTEGER` | `accounts.id` 외래 키 (선택 사항) |
| `log_level` | `TEXT` | 로그 레벨 (INFO, ERROR 등) |
| `message` | `TEXT` | 로그 메시지 |
| `timestamp` | `TIMESTAMP` | 로그 기록 시간 (기본값: `CURRENT_TIMESTAMP`) |

## 3. 관련 모듈

현재 다음 모듈들이 데이터베이스를 직접 사용하고 있습니다.

- **`modules.account`**: `accounts` 테이블의 CRUD를 담당합니다.
- **`modules.mail_history`**: `mail_history` 테이블의 CRUD를 담당합니다.
- **`modules.mail_processor`**: `processing_logs` 테이블에 로그를 기록합니다.

## 4. 개발 가이드라인

- **스키마 변경**: 스키마 변경이 필요한 경우, `infra/migrations/initial_schema.sql`을 직접 수정하지 마십시오. 대신, 별도의 마이그레이션 스크립트(`upgrade_YYYYMMDD.sql`)를 작성하고, `database.py`에 해당 스크립트를 실행하는 로직을 추가하는 것을 원칙으로 합니다. (현재는 초기 개발 단계이므로 `initial_schema.sql`을 수정할 수 있으나, 향후에는 마이그레이션 절차를 따라야 합니다.)
- **직접 쿼리 지양**: 가능한 경우, 각 모듈의 `repository.py`에 정의된 메서드를 사용하여 데이터베이스와 상호작용하십시오. 이는 코드의 재사용성을 높이고 SQL 인젝션과 같은 보안 위험을 줄입니다.
- **인덱스 추가**: 특정 필드를 자주 조회하는 쿼리가 추가될 경우, 성능 향상을 위해 해당 필드에 인덱스(`CREATE INDEX`)를 추가하는 것을 고려하십시오.
