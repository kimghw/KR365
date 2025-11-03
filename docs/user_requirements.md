# 사용자 요구사항

## 현재 요구사항

1. **로그인 계정마다 dcr_client_id 발급 및 토큰 개별 관리**
   - 각 사용자별로 독립적인 client_id 발급
   - 토큰을 사용자별로 격리하여 관리

2. **클라이언트가 다를 경우 dcr_azure_auth 계정 별도 관리**
   - 클라이언트별 Azure 인증 정보 분리
   - 다중 클라이언트 환경 지원

---

## 추가 요구사항 (멀티 테넌시 지원)

### 3. **사용자별 데이터 격리 (Data Isolation)**

#### 3.1 Azure Object ID 기반 사용자 식별
- Azure 로그인 시 받은 `object_id`를 사용자 고유 식별자로 사용
- DCR Bearer token과 Azure `object_id` 매핑
- API 요청 시 Bearer token으로 사용자 식별

#### 3.2 Graph API 호출 시 사용자 컨텍스트 적용
```
요청: GET /teams/v1/chat/completions (Bearer token 포함)
처리:
  1. Bearer token 검증 → Azure object_id 획득
  2. 해당 사용자의 Azure access_token 조회
  3. Graph API 호출 시 해당 사용자의 token 사용
결과: 요청한 사용자의 메일만 조회됨
```

#### 3.3 토큰-사용자 매핑 테이블 구조
```sql
dcr_tokens 테이블:
- dcr_token_value (Bearer token)
- dcr_client_id
- azure_object_id  ← 사용자 식별자
- token_type
- token_expiry

azure_tokens 테이블:
- azure_object_id  ← 사용자 식별자
- access_token (암호화)
- refresh_token (암호화)
- expires_at
```

### 4. **권한 검증 (Authorization)**

#### 4.1 API 요청 시 권한 확인
- Bearer token → client_id + azure_object_id 추출
- Graph API 호출 전 해당 사용자의 유효한 토큰 확인
- 만료 시 자동 refresh

#### 4.2 교차 사용자 접근 방지
```
사용자 A의 Bearer token → 사용자 A의 메일만 접근 가능
사용자 B의 Bearer token → 사용자 B의 메일만 접근 가능
```

### 5. **세션 관리**

#### 5.1 토큰 만료 처리
- Azure access_token 만료 시 자동 refresh
- Refresh token도 만료된 경우 재인증 요구
- DCR Bearer token 만료 시 새로 발급

#### 5.2 동시 세션 관리
- 동일 사용자가 여러 클라이언트(Claude.ai, ChatGPT)에서 동시 접속 가능
- 각 클라이언트별로 독립적인 Bearer token 발급
- 하나의 Azure 계정 → 여러 DCR Bearer token 매핑 가능

### 6. **감사 로그 (Audit Log)**

#### 6.1 사용자 활동 추적
- 누가 (azure_object_id)
- 언제 (timestamp)
- 무엇을 (API endpoint, method)
- 어떤 결과 (성공/실패, 응답 코드)

#### 6.2 로그 저장
```sql
audit_logs 테이블:
- timestamp
- azure_object_id
- dcr_client_id
- endpoint
- method (tools/call, v1/chat/completions 등)
- status_code
- error_message (있을 경우)
```

### 7. **계정 관리**

#### 7.1 사용자별 리소스 제한
- API 호출 횟수 제한 (Rate Limiting)
- 저장 공간 제한 (첨부파일 다운로드 시)
- 동시 접속 세션 수 제한

#### 7.2 계정 비활성화/삭제
- 사용자 계정 비활성화 시 모든 토큰 무효화
- 계정 삭제 시 관련 데이터 삭제 (GDPR 준수)

---

## 구현 체크리스트

### ✅ 이미 구현됨
- [x] DCR 클라이언트별 독립 관리
- [x] Azure object_id 기반 사용자 식별
- [x] Bearer token과 Azure token 매핑
- [x] 토큰 검증 시 사용자 컨텍스트 확인

### 🔄 추가 구현 필요
- [ ] API 요청 시 사용자별 권한 검증 강화
- [ ] 교차 사용자 접근 방지 테스트
- [ ] 감사 로그 시스템 구축
- [ ] Rate Limiting 구현
- [ ] 계정 관리 기능 (비활성화/삭제)

---

## 보안 고려사항

### 1. 토큰 보안
- DCR Bearer token: 평문 저장 (빠른 검증용, 자체 발급)
- Azure access/refresh token: 암호화 저장 (민감 정보)

### 2. 사용자 격리
- Graph API 호출 시 반드시 요청 사용자의 access_token 사용
- 다른 사용자의 토큰 사용 절대 금지

### 3. 토큰 유출 대응
- Bearer token 유출 시 해당 토큰만 무효화
- Refresh token 주기적 갱신
- 의심스러운 활동 감지 시 자동 세션 종료

---

## 시나리오 예시

### 사용자 A와 사용자 B가 동일 서버 사용

```
사용자 A (alice@company.com):
1. 로그인 → Azure object_id: aaa-111
2. DCR Bearer token: token_A
3. API 요청 → token_A 사용
4. Graph API 호출 → alice의 access_token 사용
5. 결과: alice의 메일만 조회

사용자 B (bob@company.com):
1. 로그인 → Azure object_id: bbb-222
2. DCR Bearer token: token_B
3. API 요청 → token_B 사용
4. Graph API 호출 → bob의 access_token 사용
5. 결과: bob의 메일만 조회

격리 보장:
- token_A로는 alice 데이터만
- token_B로는 bob 데이터만
- 교차 접근 불가능
```
