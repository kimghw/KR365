#!/usr/bin/env python3
"""
OAuth 2.0 Refresh Token Grant 테스트

RFC 6749 Section 6: Refreshing an Access Token
https://datatracker.ietf.org/doc/html/rfc6749#section-6
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

# Add project root to path
sys.path.insert(0, '/home/kimghw/MailQueryWithMCP')

from modules.dcr_oauth import DCRService
from infra.core.logger import get_logger

logger = get_logger(__name__)


async def test_refresh_token_flow():
    """Refresh Token 그랜트 플로우 테스트"""

    print("=" * 80)
    print("OAuth 2.0 Refresh Token Grant Flow Test")
    print("=" * 80)

    dcr_service = DCRService()

    # 1. 테스트용 클라이언트 생성
    print("\n[1] 테스트 클라이언트 등록...")
    client_data = await dcr_service.register_client({
        "client_name": "Test Client (Refresh Token)",
        "redirect_uris": ["https://test.example.com/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "scope": "Mail.Read Mail.Send User.Read"
    })

    client_id = client_data["client_id"]
    client_secret = client_data["client_secret"]

    print(f"✅ Client ID: {client_id}")
    print(f"✅ Client Secret: {client_secret[:20]}...")

    # 2. 모의 Azure Object ID 생성 (실제로는 Azure 로그인 후 받음)
    mock_azure_object_id = "test-azure-object-id-12345"
    mock_user_email = "test@example.com"

    print(f"\n[2] 테스트 사용자 연결...")
    dcr_service.update_client_user(
        dcr_client_id=client_id,
        azure_object_id=mock_azure_object_id,
        user_email=mock_user_email,
        redirect_uri="https://test.example.com/callback"
    )
    print(f"✅ User: {mock_user_email} (Object ID: {mock_azure_object_id})")

    # 3. 모의 토큰 저장 (실제로는 authorization_code 교환 후 받음)
    print("\n[3] 초기 토큰 발급...")

    import secrets
    initial_access_token = secrets.token_urlsafe(32)
    initial_refresh_token = secrets.token_urlsafe(32)

    # Mock Azure tokens (실제로는 Azure AD에서 받음)
    mock_azure_access_token = "azure-access-token-mock"
    mock_azure_refresh_token = "azure-refresh-token-mock"
    mock_azure_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    dcr_service.store_tokens(
        dcr_client_id=client_id,
        dcr_access_token=initial_access_token,
        dcr_refresh_token=initial_refresh_token,
        expires_in=3600,
        scope="Mail.Read Mail.Send User.Read",
        azure_object_id=mock_azure_object_id,
        azure_access_token=mock_azure_access_token,
        azure_refresh_token=mock_azure_refresh_token,
        azure_expires_at=mock_azure_expiry,
        user_email=mock_user_email,
        user_name="Test User",
    )

    print(f"✅ Access Token: {initial_access_token[:20]}...")
    print(f"✅ Refresh Token: {initial_refresh_token[:20]}...")
    print(f"✅ Expires: 3600s (1 hour)")

    # 4. Refresh Token 검증 테스트
    print("\n[4] Refresh Token 검증 테스트...")

    refresh_data = dcr_service.verify_refresh_token(
        refresh_token=initial_refresh_token,
        dcr_client_id=client_id
    )

    if refresh_data:
        print(f"✅ Refresh Token 검증 성공!")
        print(f"   - Azure Object ID: {refresh_data['azure_object_id']}")
        print(f"   - Scope: {refresh_data['scope']}")
        print(f"   - User Name: {refresh_data.get('user_name', 'N/A')}")
    else:
        print(f"❌ Refresh Token 검증 실패!")
        return False

    # 5. 잘못된 Refresh Token 테스트
    print("\n[5] 잘못된 Refresh Token 테스트...")

    invalid_refresh_data = dcr_service.verify_refresh_token(
        refresh_token="invalid-refresh-token-xyz",
        dcr_client_id=client_id
    )

    if invalid_refresh_data is None:
        print(f"✅ 잘못된 토큰 거부 성공!")
    else:
        print(f"❌ 보안 문제: 잘못된 토큰이 통과됨!")
        return False

    # 6. 다른 클라이언트로 Refresh Token 사용 시도
    print("\n[6] 다른 클라이언트의 Refresh Token 사용 시도...")

    other_client_data = await dcr_service.register_client({
        "client_name": "Other Client",
        "redirect_uris": ["https://other.example.com/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
    })

    cross_client_data = dcr_service.verify_refresh_token(
        refresh_token=initial_refresh_token,
        dcr_client_id=other_client_data["client_id"]
    )

    if cross_client_data is None:
        print(f"✅ Cross-client 토큰 거부 성공!")
    else:
        print(f"❌ 보안 문제: Cross-client 토큰이 통과됨!")
        return False

    # 7. Bearer Token 검증 테스트
    print("\n[7] Bearer Token 검증 테스트...")

    bearer_data = dcr_service.verify_bearer_token(initial_access_token)

    if bearer_data:
        print(f"✅ Bearer Token 검증 성공!")
        print(f"   - Client ID: {bearer_data['dcr_client_id']}")
        print(f"   - Azure Object ID: {bearer_data['azure_object_id']}")
    else:
        print(f"❌ Bearer Token 검증 실패!")
        return False

    print("\n" + "=" * 80)
    print("✅ 모든 테스트 통과!")
    print("=" * 80)

    return True


if __name__ == "__main__":
    try:
        result = asyncio.run(test_refresh_token_flow())
        sys.exit(0 if result else 1)
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        sys.exit(1)
