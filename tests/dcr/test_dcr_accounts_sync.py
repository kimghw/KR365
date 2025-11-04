#!/usr/bin/env python3
"""DCR 인증과 accounts 테이블 연동 테스트"""

import os
import sqlite3
from pathlib import Path
import sys

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infra.core.database import get_database_manager
from infra.utils.datetime_utils import utc_now_iso
from modules.enrollment.account import AccountCryptoHelpers

def check_databases():
    """데이터베이스 상태 확인"""
    print("\n=== 데이터베이스 상태 확인 ===\n")

    # 1. graphapi.db 확인
    print("1. graphapi.db (accounts 테이블)")
    db_manager = get_database_manager()

    accounts = db_manager.fetch_all("""
        SELECT user_id, email, access_token IS NOT NULL as has_token,
               token_expiry, status, updated_at
        FROM accounts
        WHERE user_id = ? OR email = ?
    """, (os.getenv("AUTO_REGISTER_USER_ID", ""), os.getenv("AUTO_REGISTER_EMAIL", "")))

    if accounts:
        for account in accounts:
            print(f"  - User ID: {account[0]}")
            print(f"    Email: {account[1]}")
            print(f"    Token: {'있음' if account[2] else '없음'}")
            print(f"    Expiry: {account[3]}")
            print(f"    Status: {account[4]}")
            print(f"    Updated At: {account[5]}")
    else:
        print("  계정 없음")

    # 2. claudedcr.db 확인
    print("\n2. claudedcr.db (dcr_azure_tokens 테이블)")
    dcr_db_path = "./data/claudedcr.db"

    if Path(dcr_db_path).exists():
        conn = sqlite3.connect(dcr_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_email, user_name, expires_at, created_at
            FROM dcr_azure_tokens
            WHERE user_email = ?
        """, (os.getenv("AUTO_REGISTER_EMAIL", ""),))

        tokens = cursor.fetchall()
        if tokens:
            for token in tokens:
                print(f"  - Email: {token[0]}")
                print(f"    Name: {token[1]}")
                print(f"    Expires: {token[2]}")
                print(f"    Created: {token[3]}")
        else:
            print("  토큰 없음")

        conn.close()
    else:
        print("  claudedcr.db 파일 없음")

def check_env_vars():
    """환경변수 설정 확인"""
    print("\n=== 환경변수 설정 확인 ===\n")

    required_vars = [
        "AUTO_REGISTER_USER_ID",
        "AUTO_REGISTER_EMAIL",
        "AUTO_REGISTER_USER_NAME",
        "AUTO_REGISTER_OAUTH_CLIENT_ID",
        "AUTO_REGISTER_OAUTH_CLIENT_SECRET",
        "AUTO_REGISTER_OAUTH_TENANT_ID",
        "DCR_AZURE_CLIENT_ID",
        "DCR_AZURE_CLIENT_SECRET",
        "DCR_AZURE_TENANT_ID",
        "DCR_ALLOWED_DOMAINS"
    ]

    for var in required_vars:
        value = os.getenv(var)
        if value:
            if "SECRET" in var:
                print(f"✅ {var}: ******* (설정됨)")
            else:
                print(f"✅ {var}: {value[:30]}..." if len(value) > 30 else f"✅ {var}: {value}")
        else:
            print(f"❌ {var}: 설정 안됨")

def test_sync_simulation():
    """연동 시뮬레이션 테스트"""
    print("\n=== 연동 시뮬레이션 테스트 ===\n")

    # DCR 서비스 import
    from modules.dcr_oauth.dcr_service import DCRService

    dcr_service = DCRService()

    # 테스트용 더미 데이터 (UTC 기준)
    test_email = os.getenv("AUTO_REGISTER_EMAIL", "testuser@example.com")
    test_user_name = os.getenv("AUTO_REGISTER_USER_NAME", "Kim Geohwa")
    test_access_token = "test_access_token_" + utc_now_iso()
    test_refresh_token = "test_refresh_token_" + utc_now_iso()
    test_expires_at = utc_now_iso()

    print(f"테스트 이메일: {test_email}")
    print(f"테스트 사용자: {test_user_name}")

    try:
        # _sync_with_accounts_table 직접 호출
        dcr_service._sync_with_accounts_table(
            azure_object_id="test_object_id",
            user_email=test_email,
            user_name=test_user_name,
            azure_access_token=test_access_token,
            azure_refresh_token=test_refresh_token,
            azure_expires_at=test_expires_at
        )
        print("\n✅ 연동 테스트 완료")

        # 결과 확인
        print("\n연동 후 accounts 테이블 상태:")
        db_manager = get_database_manager()
        result = db_manager.fetch_one("""
            SELECT user_id, email, access_token IS NOT NULL as has_token,
                   token_expiry, status, updated_at
            FROM accounts
            WHERE user_id = ? OR email = ?
        """, (os.getenv("AUTO_REGISTER_USER_ID", ""), test_email))

        if result:
            print(f"  - User ID: {result[0]}")
            print(f"    Email: {result[1]}")
            print(f"    Token 저장됨: {'예' if result[2] else '아니오'}")
            print(f"    Token Expiry: {result[3]}")
            print(f"    Status: {result[4]}")
            print(f"    Updated At: {result[5]}")
        else:
            print("  계정이 생성되지 않음")

    except Exception as e:
        print(f"\n❌ 연동 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("DCR 인증과 accounts 테이블 연동 테스트")
    print("=" * 60)

    # .env 파일 로드
    from dotenv import load_dotenv
    load_dotenv()

    check_env_vars()
    check_databases()

    print("\n연동 테스트를 실행하시겠습니까? (y/n): ", end="")
    if input().lower() == 'y':
        test_sync_simulation()

    print("\n테스트 완료")