#!/usr/bin/env python3
"""OAuth2 인증 플로우 테스트 - 완전 자동"""

import os
import sys
import json
import httpx
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env", override=True)

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")

print("=" * 80)
print("OAuth2 인증 플로우 테스트")
print("=" * 80)
print(f"서버: {BASE_URL}\n")

# 콜백 받을 전역 변수
callback_code = None
callback_received = threading.Event()


class CallbackHandler(BaseHTTPRequestHandler):
    """OAuth 콜백을 받는 HTTP 핸들러"""

    def do_GET(self):
        global callback_code

        # URL 파싱
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)

        if parsed.path == "/oauth/callback":
            callback_code = query_params.get("code", [None])[0]

            # 응답
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <body>
                    <h1>Authentication Complete!</h1>
                    <p>You can close this window.</p>
                </body>
                </html>
            """)

            # 이벤트 시그널
            callback_received.set()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # 로그 출력 비활성화
        pass


def start_callback_server():
    """콜백 서버 시작"""
    server = HTTPServer(("127.0.0.1", 6337), CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    return server


# 1. 클라이언트 등록
print("1️⃣  클라이언트 등록")
print("-" * 80)

response = httpx.post(
    f"{BASE_URL}/oauth/register",
    json={
        "client_name": "Test Client",
        "redirect_uris": ["http://localhost:6337/oauth/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "scope": "offline_access User.Read Mail.ReadWrite"
    },
    timeout=30.0
)

print(f"← {response.status_code}")
data = response.json()
print(json.dumps(data, indent=2, ensure_ascii=False))

client_id = data["client_id"]
client_secret = data["client_secret"]
redirect_uri = data["redirect_uris"][0]


# 2. 인증 URL 생성
print("\n2️⃣  인증 URL 생성")
print("-" * 80)

response = httpx.get(
    f"{BASE_URL}/oauth/authorize",
    params={
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "offline_access User.Read Mail.ReadWrite",
        "state": "test123"
    },
    follow_redirects=False,
    timeout=30.0
)

print(f"← {response.status_code}")
azure_auth_url = response.headers.get("location")
print(f"리다이렉트: {azure_auth_url[:150]}...")


# 3. Azure 로그인 (콜백 대기)
print("\n3️⃣  Azure 인증 플로우")
print("-" * 80)

# 로컬 콜백 서버 시작
callback_server = start_callback_server()
print("✅ 콜백 서버 시작: http://localhost:6337")

# 브라우저에서 열기
import webbrowser
print(f"\n브라우저에서 Azure 로그인 페이지를 엽니다...")
print(f"URL: {azure_auth_url[:100]}...")
webbrowser.open(azure_auth_url)

# 콜백 대기 (최대 60초)
print("\n⏳ Azure 로그인 완료 및 콜백 대기 중...")
if callback_received.wait(timeout=60):
    print(f"✅ Authorization code 수신: {callback_code[:20] if callback_code else 'None'}...")
    auth_code = callback_code
else:
    print("❌ 타임아웃: 콜백을 받지 못했습니다")
    sys.exit(1)

callback_server.shutdown()


# 4. 토큰 교환
print("\n4️⃣  토큰 교환")
print("-" * 80)

response = httpx.post(
    f"{BASE_URL}/oauth/token",
    data={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": auth_code,
        "redirect_uri": redirect_uri
    },
    timeout=30.0
)

print(f"← {response.status_code}")
data = response.json()
print(json.dumps(data, indent=2, ensure_ascii=False))

access_token = data["access_token"]
refresh_token = data.get("refresh_token")


# 5. 토큰 갱신
if refresh_token:
    print("\n5️⃣  토큰 갱신")
    print("-" * 80)

    response = httpx.post(
        f"{BASE_URL}/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token
        },
        timeout=30.0
    )

    print(f"← {response.status_code}")
    data = response.json()
    print(json.dumps(data, indent=2, ensure_ascii=False))

    access_token = data["access_token"]


# 6. API 호출 테스트
print("\n6️⃣  API 호출 (Bearer 토큰)")
print("-" * 80)

response = httpx.get(
    f"{BASE_URL}/health",
    headers={"Authorization": f"Bearer {access_token}"},
    timeout=30.0
)

print(f"← {response.status_code}")
print(json.dumps(response.json(), indent=2, ensure_ascii=False))

print("\n" + "=" * 80)
print("✅ OAuth2 플로우 테스트 완료!")
print("=" * 80)
