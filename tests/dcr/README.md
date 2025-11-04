# DCR OAuth 테스트 스크립트

이 디렉토리에는 DCR(Dynamic Client Registration) OAuth 인증 및 GraphAPI 테스트를 위한 스크립트들이 있습니다.

## 테스트 파일 설명

### 1. test_dcr_auth.py
- DCR OAuth 인증 URL 생성
- PKCE 코드 챌린지 생성
- Authorization code 획득을 위한 브라우저 인증 플로우

### 2. test_dcr_accounts_sync.py
- DCR 인증과 graphapi.db의 accounts 테이블 연동 테스트
- 환경변수 설정 확인
- 토큰 동기화 상태 확인

### 3. test_dcr_and_graphapi.py
- DCR 토큰 상태 확인
- Accounts 테이블 상태 확인
- DCR과 accounts 테이블 동기화 확인
- GraphAPI 호출 테스트 (사용자 정보, 메일 조회)

### 4. test_mail_query.py
- Microsoft Graph API를 통한 상세 메일 조회
- 메일함 통계 조회
- 최근 메일 상세 정보 조회
- 폴더 목록 조회

## 사용 방법

```bash
# 1. DCR 인증 URL 생성 및 브라우저 인증
python tests/dcr/test_dcr_auth.py

# 2. DCR과 accounts 테이블 동기화 테스트
python tests/dcr/test_dcr_accounts_sync.py

# 3. 통합 테스트 (DCR + GraphAPI)
python tests/dcr/test_dcr_and_graphapi.py

# 4. 메일 조회 상세 테스트
python tests/dcr/test_mail_query.py
```

## 환경변수 설정

`.env` 파일에 다음 환경변수들이 설정되어 있어야 합니다:

```env
# DCR Azure AD 설정
DCR_AZURE_CLIENT_ID=your-client-id
DCR_AZURE_CLIENT_SECRET=your-client-secret
DCR_AZURE_TENANT_ID=your-tenant-id
DCR_OAUTH_REDIRECT_URI=http://localhost:8000/oauth/azure_callback
DCR_ALLOWED_DOMAINS=example.com,company.com

# 자동 계정 등록 설정
AUTO_REGISTER_USER_ID=userid
AUTO_REGISTER_EMAIL=user@example.com
AUTO_REGISTER_USER_NAME="User Name"
```

## 주의사항

- Azure Portal에서 redirect URI를 정확히 등록해야 합니다
- 토큰은 암호화되어 데이터베이스에 저장됩니다
- DCR 인증 완료 시 자동으로 accounts 테이블과 연동됩니다