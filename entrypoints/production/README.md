# Unified Production Server

KR365 프로젝트의 모든 서비스를 하나의 서버로 통합한 프로덕션 서버입니다.

## 서비스 구성

- `/onenote` - OneNote MCP 서비스
- `/outlook` - Outlook MCP 서비스
- `/teams` - Teams MCP 서비스
- `/dashboard` - 웹 대시보드

## 실행 방법

### 기본 실행
```bash
./start.sh
```

### Python으로 직접 실행
```bash
python unified_server.py
```

### 커스텀 포트로 실행
```bash
UNIFIED_PORT=9000 ./start.sh
```

## 환경 변수

- `UNIFIED_PORT` - 서버 포트 (기본: 8080)
- `UNIFIED_HOST` - 서버 호스트 (기본: 0.0.0.0)

## API 문서

서버 실행 후 다음 주소에서 API 문서를 확인할 수 있습니다:
- http://localhost:8080/docs

## 서비스 엔드포인트

- OneNote API: http://localhost:8080/onenote
- Outlook API: http://localhost:8080/outlook
- Teams API: http://localhost:8080/teams
- Dashboard: http://localhost:8080/dashboard