"""
환경변수로부터 계정 정보를 로드하는 유틸리티

환경변수 형식:
- AUTO_REGISTER_USER_ID: 사용자 ID (필수)
- AUTO_REGISTER_USER_NAME: 사용자 이름 (필수)
- AUTO_REGISTER_EMAIL: 이메일 주소 (필수)
- AUTO_REGISTER_OAUTH_CLIENT_ID: OAuth 클라이언트 ID (필수)
- AUTO_REGISTER_OAUTH_CLIENT_SECRET: OAuth 클라이언트 시크릿 (필수)
- AUTO_REGISTER_OAUTH_TENANT_ID: OAuth 테넌트 ID (필수)
- AUTO_REGISTER_OAUTH_REDIRECT_URI: OAuth 리다이렉트 URI (필수)
- AUTO_REGISTER_DELEGATED_PERMISSIONS: 위임된 권한 (선택, 쉼표 구분)
"""

import os
from typing import Dict, List, Optional

from infra.core.logger import get_logger

from .account_schema import AccountCreate, AccountStatus, AuthType

logger = get_logger(__name__)


def env_parse_delegated_permissions(permissions_str: Optional[str]) -> List[str]:
    """
    환경변수의 권한 문자열을 파싱하여 리스트로 변환

    Args:
        permissions_str: 쉼표로 구분된 권한 문자열

    Returns:
        권한 리스트
    """
    if not permissions_str:
        # 기본 권한
        return ["Mail.ReadWrite", "Mail.Send", "offline_access"]

    # 쉼표로 구분하여 파싱
    permissions = [p.strip() for p in permissions_str.split(",") if p.strip()]

    # offline_access가 없으면 추가
    if "offline_access" not in permissions:
        permissions.append("offline_access")

    # User.Read에 포함되지 않는 스코프 검증 (.All 제외)
    from ._scope_validator import validate_scopes_coverage
    validate_scopes_coverage(permissions, base_scope="User.Read")

    return permissions


def env_validate_account_data(data: Dict[str, Optional[str]]) -> tuple[bool, List[str]]:
    """
    환경변수에서 로드한 계정 데이터 검증

    Args:
        data: 검증할 데이터 딕셔너리

    Returns:
        (검증 성공 여부, 오류 메시지 리스트)
    """
    errors = []

    # 필수 필드 검증
    required_fields = [
        "user_id",
        "user_name",
        "email",
        "oauth_client_id",
        "oauth_client_secret",
        "oauth_tenant_id",
        "oauth_redirect_uri"
    ]

    for field in required_fields:
        if not data.get(field):
            errors.append(f"필수 필드 누락: AUTO_REGISTER_{field.upper()}")

    # 데이터 형식 검증
    if data.get("user_id"):
        import re
        if not re.match(r"^[a-zA-Z0-9._-]+$", data["user_id"]):
            errors.append("user_id는 영문, 숫자, '.', '_', '-'만 포함할 수 있습니다")

    if data.get("email"):
        if "@" not in data["email"]:
            errors.append("올바른 이메일 형식이 아닙니다")

    if data.get("oauth_client_id"):
        if len(data["oauth_client_id"]) != 36 or data["oauth_client_id"].count("-") != 4:
            errors.append("oauth_client_id는 GUID 형식이어야 합니다")

    if data.get("oauth_tenant_id"):
        if len(data["oauth_tenant_id"]) != 36 or data["oauth_tenant_id"].count("-") != 4:
            errors.append("oauth_tenant_id는 GUID 형식이어야 합니다")

    if data.get("oauth_redirect_uri"):
        if not data["oauth_redirect_uri"].startswith(("http://", "https://")):
            errors.append("oauth_redirect_uri는 http:// 또는 https://로 시작해야 합니다")

    return len(errors) == 0, errors


def env_load_account_from_env() -> Optional[AccountCreate]:
    """
    환경변수로부터 계정 정보를 로드

    Returns:
        AccountCreate 객체 또는 None (환경변수가 설정되지 않은 경우)
    """
    # 환경변수 읽기
    user_id = os.getenv("AUTO_REGISTER_USER_ID")

    # AUTO_REGISTER_USER_ID가 없으면 환경변수 기반 자동 등록 비활성화
    if not user_id:
        logger.debug("AUTO_REGISTER_USER_ID가 설정되지 않음 - 환경변수 기반 자동 등록 비활성화")
        return None

    # 모든 필드 읽기
    data = {
        "user_id": user_id,
        "user_name": os.getenv("AUTO_REGISTER_USER_NAME"),
        "email": os.getenv("AUTO_REGISTER_EMAIL"),
        "oauth_client_id": os.getenv("AUTO_REGISTER_OAUTH_CLIENT_ID"),
        "oauth_client_secret": os.getenv("AUTO_REGISTER_OAUTH_CLIENT_SECRET"),
        "oauth_tenant_id": os.getenv("AUTO_REGISTER_OAUTH_TENANT_ID"),
        "oauth_redirect_uri": os.getenv("AUTO_REGISTER_OAUTH_REDIRECT_URI"),
        "delegated_permissions_str": os.getenv("AUTO_REGISTER_DELEGATED_PERMISSIONS"),
    }

    # 검증
    is_valid, errors = env_validate_account_data(data)

    if not is_valid:
        logger.error("환경변수 기반 계정 정보 검증 실패:")
        for error in errors:
            logger.error(f"  - {error}")
        return None

    # 권한 파싱
    delegated_permissions = env_parse_delegated_permissions(
        data.get("delegated_permissions_str")
    )

    # AccountCreate 객체 생성
    try:
        account_create = AccountCreate(
            user_id=data["user_id"],
            user_name=data["user_name"],
            email=data["email"],
            enrollment_file_path="<ENV_AUTO_REGISTERED>",
            enrollment_file_hash="<ENV_AUTO_REGISTERED>",
            oauth_client_id=data["oauth_client_id"],
            oauth_client_secret=data["oauth_client_secret"],
            oauth_tenant_id=data["oauth_tenant_id"],
            oauth_redirect_uri=data["oauth_redirect_uri"],
            auth_type=AuthType.AUTHORIZATION_CODE_FLOW,
            delegated_permissions=delegated_permissions,
            status=AccountStatus.ACTIVE,
        )

        logger.info(f"✅ 환경변수 기반 계정 정보 로드 성공: user_id={data['user_id']}")
        logger.info(f"   - 이메일: {data['email']}")
        logger.info(f"   - OAuth Client ID: {data['oauth_client_id'][:8]}...")
        logger.info(f"   - OAuth Tenant ID: {data['oauth_tenant_id'][:8]}...")
        logger.info(f"   - Redirect URI: {data['oauth_redirect_uri']}")
        logger.info(f"   - 권한: {', '.join(delegated_permissions)}")

        return account_create

    except Exception as e:
        logger.error(f"환경변수 기반 계정 정보 생성 실패: {str(e)}")
        return None
