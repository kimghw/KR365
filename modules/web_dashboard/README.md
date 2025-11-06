# Web Dashboard for MailQueryWithMCP

독립 실행형 웹 기반 관리 대시보드입니다. Unified MCP 서버와는 별도로 실행되며, 시스템 전체를 관리할 수 있습니다.

## 🚀 시작하기

### 대시보드 서버 실행

```bash
# 대시보드 서버 시작
./start-dashboard.sh start

# 상태 확인
./start-dashboard.sh status

# 서버 중지
./start-dashboard.sh stop

# 서버 재시작
./start-dashboard.sh restart
```

기본적으로 **포트 9000**에서 실행됩니다.

### 접속

브라우저에서 다음 URL로 접속:
- **로컬**: http://localhost:9000/dashboard
- **터널**: https://[your-cloudflare-url]/dashboard (포트 포워딩 설정 시)

## ✨ 주요 기능

### 1. 📊 서버 모니터링
- **Unified Server** 실시간 상태 확인 (PID, 실행 상태)
- **Cloudflare Tunnel** 상태 및 공개 URL 확인
- 자동 새로고침 (5초 간격)

### 2. 🎮 서버 제어
- **▶️ Start Server**: Unified MCP 서버 시작
- **⏹️ Stop Server**: Unified MCP 서버 종료
- 원클릭으로 서버 관리 가능

### 3. 🔗 서비스 엔드포인트 정보
- Mail Query, Enrollment, OneNote, OneDrive, Teams 서비스 URL
- OAuth 엔드포인트 (Cloudflare Tunnel URL 기반)
- 클릭하면 클립보드에 자동 복사

### 4. 📋 로그 뷰어 (Logs 탭)
- 모든 로그 파일 목록 조회
- 실시간 로그 내용 확인 (최근 200줄)
- 수동 새로고침 기능

### 5. 💾 데이터베이스 뷰어 (Database 탭)
- **데이터베이스 탐색**:
  - Main Database (graphapi.db)
  - DCR Database (dcr.db)
- **테이블 목록** 조회
- **테이블 스키마** 확인 (컬럼명, 타입, NULL 여부, PK)
- **SQL 쿼리 실행**:
  - SELECT, INSERT, UPDATE, DELETE 등 모든 SQL 지원
  - 자동 LIMIT 추가 (SELECT 쿼리)
  - 쿼리 결과 테이블 형태로 표시
- **빠른 작업**: "View All Rows" 버튼으로 전체 데이터 조회

### 6. ⚙️ 환경변수 관리 (Environment 탭)
- `.env` 파일의 모든 환경변수 조회
- **REDIRECT_URI** 등 환경변수 추가/수정
- 실시간 업데이트 및 적용

## 🎨 사용자 인터페이스

### 탭 구조
대시보드는 3개의 탭으로 구성되어 있습니다:

1. **📋 Logs** - 로그 파일 조회 및 모니터링
2. **💾 Database** - 데이터베이스 탐색 및 SQL 실행
3. **⚙️ Environment** - 환경변수 관리

### 반응형 디자인
- 데스크톱과 모바일 모두 지원
- 직관적인 UI/UX
- 실시간 상태 업데이트

## 🔧 설정

### 포트 변경

환경변수로 포트를 변경할 수 있습니다:

```bash
DASHBOARD_PORT=8080 ./start-dashboard.sh start
```

또는 `.env` 파일에 추가:

```env
DASHBOARD_PORT=8080
```

### 호스트 설정

기본적으로 `0.0.0.0`으로 모든 인터페이스에서 접속 가능합니다.

```bash
DASHBOARD_HOST=127.0.0.1 ./start-dashboard.sh start  # 로컬만 접속 허용
```

## 📁 파일 구조

```
modules/web_dashboard/
├── __init__.py              # 모듈 초기화
├── dashboard.py             # 메인 대시보드 로직 (API + UI)
├── standalone_server.py     # 독립 서버 실행 스크립트
├── tests/
│   ├── __init__.py
│   └── test_dashboard.py   # 테스트 모듈
└── README.md               # 이 파일

start-dashboard.sh          # 대시보드 실행 스크립트
```

## 🔒 보안 고려사항

1. **SQL Injection 방지**:
   - SELECT 쿼리에 자동 LIMIT 추가
   - 파라미터 검증

2. **서버 제어**:
   - Stop 시 확인 대화상자
   - 안전한 프로세스 종료 (SIGTERM → SIGKILL)

3. **환경변수**:
   - 민감한 정보는 표시되지만 수정 시 주의 필요
   - 프로덕션 환경에서는 인증 추가 권장

## 🐛 문제 해결

### 대시보드가 시작되지 않을 때

```bash
# 로그 확인
cat logs/dashboard.log

# 포트 사용 확인
lsof -i :9000

# 강제 종료 후 재시작
pkill -f standalone_server.py
./start-dashboard.sh start
```

### Unified Server가 시작되지 않을 때

대시보드에서 "Start Server" 버튼 클릭 후:
1. 로그 탭에서 `unified_server.log` 확인
2. 환경변수 확인 (Azure 설정 등)
3. 데이터베이스 경로 확인

### OAuth endpoints가 localhost로 표시될 때

1. Cloudflare Tunnel이 실행 중인지 확인
2. Tunnel URL이 로그에 기록되었는지 확인
3. 대시보드를 새로고침하여 최신 Tunnel URL 가져오기

## 📝 API 엔드포인트

대시보드는 다음 REST API를 제공합니다:

- `GET /dashboard` - 대시보드 웹 페이지
- `GET /dashboard/api/status` - 서버 및 터널 상태
- `POST /dashboard/api/server/start` - 서버 시작
- `POST /dashboard/api/server/stop` - 서버 종료
- `GET /dashboard/api/endpoints` - 서비스 엔드포인트 정보
- `GET /dashboard/api/env` - 환경변수 조회
- `POST /dashboard/api/env` - 환경변수 업데이트
- `GET /dashboard/api/logs` - 로그 파일 목록
- `GET /dashboard/api/logs/{log_name}` - 로그 내용
- `GET /dashboard/api/databases` - 데이터베이스 목록
- `GET /dashboard/api/db/tables` - 테이블 목록
- `GET /dashboard/api/db/schema` - 테이블 스키마
- `POST /dashboard/api/db/query` - SQL 쿼리 실행

## 🧪 테스트

```bash
# 테스트 실행 (pytest 설치 필요)
python3 -m pytest modules/web_dashboard/tests/ -v
```

## 📄 라이선스

이 프로젝트의 라이선스를 따릅니다.
