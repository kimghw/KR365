# DCR Database Logging

DCR 서비스의 데이터베이스 작업을 로깅하는 기능입니다.

## 활성화 방법

환경변수 `DCR_DB_LOGGING`을 설정하여 활성화/비활성화할 수 있습니다.

### 활성화
```bash
# .env 파일에 추가
DCR_DB_LOGGING=true

# 또는 직접 실행 시
export DCR_DB_LOGGING=true
python main.py
```

### 비활성화 (기본값)
```bash
# .env 파일에서 제거하거나 false로 설정
DCR_DB_LOGGING=false

# 또는 아예 설정하지 않음 (기본값 false)
```

## 지원하는 값

- `true`, `1`, `yes`, `on` : 로깅 활성화
- `false`, `0`, `no`, `off` : 로깅 비활성화 (기본값)

## 로그 형식

데이터베이스 작업이 실행될 때마다 다음 정보가 로깅됩니다:

```
[작업 아이콘] DB [작업 타입] on [테이블명] ([영향받은 행 수] rows affected) | Params: [파라미터] | Query: [쿼리]
```

### 작업 아이콘 및 타입
- ➕ INSERT : 데이터 삽입
- 📝 UPDATE : 데이터 수정
- 🗑️ DELETE : 데이터 삭제
- 🔍 SELECT : 데이터 조회
- ⚙️ OTHER : 기타 작업

### 로그 예시

```
➕ DB INSERT on DCR_CLIENTS (1 rows affected) | Params: ['dcr_xyz123', '***MASKED***', 'MCP Connector', ...] | Query: INSERT INTO dcr_clients (dcr_client_id, dcr_client_secret, dcr_client_name...

📝 DB UPDATE on DCR_CLIENTS (1 rows affected) | Params: ['user@example.com', 'object123'] | Query: UPDATE dcr_clients SET azure_object_id = ?, user_email = ? ...

🗑️ DB DELETE on DCR_CLIENTS (1 rows affected) | Params: ['dcr_old123'] | Query: DELETE FROM dcr_clients WHERE dcr_client_id = ?

🔍 DB SELECT on DCR_CLIENTS (3 rows found) | Params: ['dcr_xyz123'] | Query: SELECT dcr_client_name, azure_object_id FROM dcr_clients WHERE...
```

## 보안 기능

### 민감한 정보 마스킹
- 토큰, 시크릿, 패스워드, 키 등의 민감한 정보는 자동으로 `***MASKED***`로 표시됩니다
- 50자 이상의 긴 문자열은 처음 20자와 마지막 10자만 표시됩니다

### 파라미터 제한
- 최대 5개의 파라미터만 표시됩니다
- 5개를 초과하는 경우 "... and N more"로 표시됩니다

### 쿼리 미리보기
- 100자를 초과하는 쿼리는 처음 100자만 표시됩니다

## 로그 레벨

DB 로깅은 `DEBUG` 레벨로 기록됩니다. 로그를 보려면:

1. Python 로깅 레벨을 DEBUG로 설정
2. 또는 infra/core/logger.py에서 로그 레벨 조정

```python
# 예시: 로깅 레벨 설정
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 사용 사례

### 개발 중 디버깅
```bash
# 개발 환경에서 DB 작업 추적
DCR_DB_LOGGING=true
python main.py
```

### 프로덕션 문제 해결
```bash
# 특정 문제 발생 시 일시적으로 활성화
export DCR_DB_LOGGING=true
# 문제 재현
# 로그 분석 후 비활성화
export DCR_DB_LOGGING=false
```

### 성능 분석
로그를 통해 다음을 확인할 수 있습니다:
- 중복 쿼리 발생 여부
- 영향받은 행 수 확인
- 예상치 못한 DELETE/UPDATE 작업 감지

## 주의사항

1. **성능 영향**: 로깅은 약간의 성능 오버헤드를 발생시킵니다. 프로덕션에서는 필요한 경우에만 활성화하세요.

2. **로그 크기**: 활성화 시 많은 로그가 생성될 수 있습니다. 디스크 공간을 모니터링하세요.

3. **민감한 정보**: 자동 마스킹에도 불구하고, 로그 파일 접근 권한을 적절히 관리하세요.

## 변경 이력

- 2024-11-10: 초기 구현
  - 기본 DB 작업 로깅
  - 민감한 정보 마스킹
  - 환경변수 제어