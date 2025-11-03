# AI 클라이언트 통합 MCP 서버 아키텍처

## 전체 구조 개요

이 시스템은 **Claude.ai**와 **ChatGPT** 모두에서 사용 가능한 통합 MCP 서버입니다.

- **Claude.ai**: OAuth DCR 프로토콜로 통합 (Root에서 인증 처리)
- **ChatGPT**: OpenAI 호환 API로 통합 (각 서브경로에서 `/v1/chat/completions` 제공)

**구조:**
- **Root (`/`)**: OAuth 인증만 담당 (DCR 서버)
- **서브경로 (`/teams`, `/mail-query` 등)**: 실제 비즈니스 로직 처리 (MCP 서버)

---

## 1. DCR 서버 로직 (Root 인증 담당)

### 역할
Root 서버는 **OAuth 인증 및 토큰 관리만** 수행합니다. 비즈니스 로직은 처리하지 않습니다.

### 주요 책임

#### 🔵 Claude.ai & ChatGPT 공통
1. **OAuth 메타데이터 제공**
   - `/.well-known/oauth-authorization-server`: OAuth 설정 정보
   - 인증 엔드포인트, 토큰 엔드포인트 위치 공개

2. **인증 플로우 처리**
   - 사용자를 Microsoft Azure로 리디렉트
   - Authorization code 수신
   - Azure 토큰과 교환
   - DCR Bearer 토큰 생성 및 저장

3. **토큰 관리**
   - Access token, Refresh token 저장 (평문)
   - 토큰 검증 (Bearer token)
   - 만료된 토큰 갱신

4. **리디렉트 정책**
   - 모든 서브경로의 인증 요청을 Root로 리디렉트
   - 예: `/enrollment/authorize` → `/authorize`
   - 인증 완료 후 원래 요청한 서브경로로 credential 전달

5. **클라이언트 동적 등록 (DCR)**
   - 새로운 클라이언트 자동 등록
   - `client_id`, `client_secret` 발급
   - 필수 scope 강제 추가 (Mail.Read, Mail.Send, Calendars.ReadWrite 등)
   - Claude.ai와 ChatGPT 모두 동일한 DCR 플로우 사용

---

## 2. MCP 서버 로직 (서브경로 비즈니스 담당)

### 역할
각 서브경로는 **독립적인 MCP 서버**로 동작하며, 특정 도메인의 비즈니스 로직을 처리합니다.

### 서브경로 구조
```
/teams           → Teams 메시지, 채널, 회의 관리
/mail-query      → 이메일 검색, 조회, 분석
/onenote         → OneNote 노트 관리
/enrollment      → 계정 등록 및 관리
```

### 각 MCP 서버의 책임

#### 🔵 Claude.ai & ChatGPT 공통

**2.1 인증 위임**
- Root에서 발급받은 Bearer token으로 요청 검증
- 토큰 유효성 확인 후 Azure access token 획득
- Microsoft Graph API 호출

**2.2 비즈니스 로직 실행**
- MCP 프로토콜에 따라 도구(tool) 노출
- 클라이언트 요청에 따라 Microsoft Graph API 호출
- 결과를 MCP 형식으로 생성

#### 🟢 Claude.ai 전용

**2.3 MCP 네이티브 프로토콜**
- MCP SSE(Server-Sent Events) 프로토콜 사용
- `/mcp` 엔드포인트에서 JSON-RPC 2.0 요청 처리
- `tools/list`, `tools/call` 등 MCP 표준 메서드 제공
- 결과를 MCP 네이티브 형식으로 직접 반환

#### 🟠 ChatGPT 전용

**2.4 OpenAI 호환 API**
- 각 서브경로가 독립적으로 OpenAI API 노출
- **`/v1/chat/completions`**: MCP 도구를 OpenAI function calling 형식으로 제공
- **`/v1/models`**: 해당 MCP 서버를 하나의 "모델"로 표현

**2.5 MCP ↔ OpenAI 변환**
`modules/openai_wrapper` 모듈을 사용하여:

1. **Tool 변환**
   - MCP Tool → OpenAI Function Definition
   - `inputSchema` → `parameters` 래핑

2. **Result 변환**
   - MCP `List[TextContent]` → OpenAI tool message
   - 여러 텍스트를 하나로 합쳐서 반환

---

## 3. 요청 흐름

### 3.1 초기 인증 (Claude.ai & ChatGPT 공통)

#### Step 1: Discovery (서버 정보 탐색)
```
1. Client → GET /.well-known/oauth-authorization-server
2. Root → OAuth 메타데이터 응답
   {
     "authorization_endpoint": "https://server.com/authorize",
     "token_endpoint": "https://server.com/token",
     "registration_endpoint": "https://server.com/register"
   }
```

#### Step 2: 클라이언트 동적 등록 (DCR)
```
3. Client → POST /register
   {
     "client_name": "My App",
     "redirect_uris": ["https://client.com/callback"],
     "scope": "Mail.Read User.Read"
   }

4. Root → client_id 확인
   - 미등록 시: 자동 등록
     • client_id, client_secret 생성
     • 필수 scope 강제 추가 (Mail.Read, Mail.Send, Calendars.ReadWrite 등)
     • DB에 저장
   - 이미 등록된 경우: 기존 정보 반환

5. Root → 응답
   {
     "client_id": "abc123",
     "client_secret": "secret456",
     "redirect_uris": ["https://client.com/callback"]
   }
```

#### Step 3: 인증 플로우 시작
```
6. Client → GET /teams/authorize?client_id=abc123&redirect_uri=...&scope=...

7. Root → /authorize (서브경로 요청을 Root로 리디렉트)

8. Root → Microsoft Azure 로그인 페이지로 리디렉트
   https://login.microsoftonline.com/...?
     client_id=<azure_client_id>
     &redirect_uri=https://server.com/callback
     &scope=Mail.Read Mail.Send Calendars.ReadWrite
```

#### Step 4: 사용자 인증 및 토큰 교환
```
9. 사용자 → Azure에서 로그인 및 권한 승인

10. Azure → Root /callback?code=<authorization_code>&state=...

11. Root → Azure Token Endpoint
    POST https://login.microsoftonline.com/.../token
    {
      "grant_type": "authorization_code",
      "code": "<authorization_code>",
      "redirect_uri": "https://server.com/callback"
    }

12. Azure → Root 응답
    {
      "access_token": "azure_token_xxx",
      "refresh_token": "azure_refresh_xxx",
      "expires_in": 3600,
      "id_token": "eyJhbGc..." ← JWT 토큰 (사용자 정보 포함)
    }

13. Root → 사용자 정보 추출 (중요!)
    - id_token(JWT) 디코딩하여 사용자 식별
    - 또는 Graph API 호출: GET https://graph.microsoft.com/v1.0/me

    사용자 정보:
    {
      "id": "aaa-bbb-ccc-ddd",        ← Azure Object ID (고유 식별자)
      "userPrincipalName": "alice@company.com",
      "displayName": "Alice",
      "mail": "alice@company.com"
    }
```

#### Step 5: DCR Bearer 토큰 발급 및 전달
```
14. Root → DCR Bearer 토큰 생성 및 DB 저장

    dcr_tokens 테이블:
    {
      "dcr_token_value": "dcr_bearer_xxx",  ← 새로 생성한 Bearer token
      "dcr_client_id": "abc123",
      "azure_object_id": "aaa-bbb-ccc-ddd", ← 사용자 식별자 (중요!)
      "token_type": "Bearer",
      "token_expiry": "2024-11-04T10:00:00Z"
    }

    azure_tokens 테이블:
    {
      "azure_object_id": "aaa-bbb-ccc-ddd",  ← 사용자 식별자 (중요!)
      "access_token": "암호화(azure_token_xxx)",
      "refresh_token": "암호화(azure_refresh_xxx)",
      "expires_at": "2024-11-03T11:00:00Z"
    }

15. Root → /teams/callback?code=<dcr_code> (원래 요청한 서브경로로 리디렉트)
    또는 redirect_uri로 credential 직접 전달:
    {
      "access_token": "<dcr_bearer_token>",
      "token_type": "Bearer",
      "expires_in": 3600
    }

16. Client → Bearer token 저장 완료
    이후 모든 API 요청에 Authorization: Bearer <dcr_bearer_token> 헤더 사용
```

### 3.2 API 호출 (클라이언트별) - 사용자 격리 적용

**Claude.ai (MCP 프로토콜)**
```
프로토콜: JSON-RPC 2.0 over SSE

1. Claude.ai → /teams/mcp
   Authorization: Bearer dcr_bearer_xxx

2. Teams MCP 서버 → 사용자 식별 및 검증
   a) DCR Bearer token 검증
      - dcr_tokens 테이블에서 dcr_bearer_xxx 조회
      - client_id: abc123
      - azure_object_id: aaa-bbb-ccc-ddd ← 사용자 A 식별!

   b) 사용자 A의 Azure access token 획득
      - azure_tokens 테이블에서 azure_object_id로 조회
      - access_token 복호화

   c) Graph API 호출 (사용자 A의 토큰 사용)
      GET https://graph.microsoft.com/v1.0/me/messages
      Authorization: Bearer azure_token_xxx ← 사용자 A의 토큰

   d) 결과: 사용자 A의 메일만 반환

3. MCP 네이티브 형식으로 응답
```

**ChatGPT (OpenAI API)**
```
프로토콜: REST API (HTTP POST)

1. ChatGPT → /teams/v1/chat/completions
   Authorization: Bearer dcr_bearer_yyy

2. Teams MCP 서버 → 사용자 식별 및 검증
   a) DCR Bearer token 검증
      - dcr_tokens 테이블에서 dcr_bearer_yyy 조회
      - client_id: xyz789
      - azure_object_id: bbb-ccc-ddd-eee ← 사용자 B 식별!

   b) 사용자 B의 Azure access token 획득
      - azure_tokens 테이블에서 azure_object_id로 조회
      - access_token 복호화

   c) Graph API 호출 (사용자 B의 토큰 사용)
      GET https://graph.microsoft.com/v1.0/me/messages
      Authorization: Bearer azure_token_yyy ← 사용자 B의 토큰

   d) 결과: 사용자 B의 메일만 반환

3. OpenAI 형식으로 변환하여 반환
   - stream: true 설정 시 SSE로 스트리밍 응답
```

**핵심: 사용자 격리 보장**
```
DCR Bearer token → azure_object_id → Azure access_token → Graph API
    (요청 식별)      (사용자 식별)     (사용자 토큰)      (개인 데이터)

사용자 A의 Bearer token → 사용자 A의 데이터만
사용자 B의 Bearer token → 사용자 B의 데이터만
```

---

## 4. 핵심 설계 원칙

### 멀티 클라이언트 지원
- **하나의 서버**로 Claude.ai와 ChatGPT 모두 지원
- 동일한 MCP 도구를 두 가지 프로토콜로 노출
- 클라이언트별 엔드포인트 분리로 호환성 극대화

### 관심사의 분리
- **Root**: 인증/인가만 처리 → 보안 집중
- **서브경로**: 비즈니스 로직만 처리 → 도메인 전문성
- **openai_wrapper**: 프로토콜 변환만 담당 → 재사용성

### 독립적 확장성
- 각 MCP 서버는 독립적으로 배포/확장 가능
- 새로운 서브경로 추가 시 Root 수정 불필요
- 새로운 AI 클라이언트 추가 시 래퍼만 추가

### 표준 준수
- OAuth 2.0 DCR (RFC 7591) - Claude.ai
- OpenAI API 스펙 - ChatGPT
- MCP 프로토콜 - 공통

### 토큰 보안
- DCR Bearer 토큰: 평문 저장 (빠른 검증)
- Azure tokens: 암호화 저장 (민감 정보 보호)

---

## 5. 클라이언트별 연동 방법

### Claude.ai 연동
```
Base URL: https://your-server.com/teams
프로토콜: MCP (OAuth DCR)
인증: Root에서 자동 처리
엔드포인트: /teams/mcp (SSE)
```

### ChatGPT 연동
```
Base URL: https://your-server.com/teams
프로토콜: OpenAI Compatible API
인증: Root에서 자동 처리
엔드포인트:
  - /teams/v1/chat/completions
  - /teams/v1/models
```