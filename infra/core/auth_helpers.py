"""
인증 관련 헬퍼 함수들

모든 MCP 핸들러에서 공통으로 사용하는 인증 관련 유틸리티
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from infra.core.logger import get_logger

logger = get_logger(__name__)


def get_delegated_user_ids(user_id: str) -> List[str]:
    """
    사용자가 접근 가능한 다른 사용자 ID 목록을 반환합니다.

    Args:
        user_id: 인증된 사용자 ID

    Returns:
        접근 가능한 user_id 리스트 (본인 제외)
    """
    try:
        from infra.core.database import get_database_manager
        db = get_database_manager()

        # 관리자 확인
        admin_result = db.execute_query(
            "SELECT is_admin FROM accounts WHERE user_id = ?",
            (user_id,),
            fetch_result=True
        )

        if admin_result and len(admin_result) > 0 and admin_result[0][0] == 1:
            # 관리자는 모든 활성 계정 접근 가능
            all_users_result = db.execute_query(
                "SELECT user_id FROM accounts WHERE is_active = TRUE AND user_id != ?",
                (user_id,),
                fetch_result=True
            )
            delegated = [row[0] for row in all_users_result] if all_users_result else []
            logger.info(f"🔑 관리자 {user_id}는 {len(delegated)}개 계정 접근 가능")
            return delegated

        # 일반 사용자: 위임받은 계정만
        now = datetime.now(timezone.utc).isoformat()
        delegation_result = db.execute_query(
            """
            SELECT delegator_user_id
            FROM account_delegations
            WHERE delegate_user_id = ?
              AND is_active = 1
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            (user_id, now),
            fetch_result=True
        )

        delegated = [row[0] for row in delegation_result] if delegation_result else []
        if delegated:
            logger.info(f"🔑 {user_id}는 {len(delegated)}개 계정 접근 가능: {delegated}")

        return delegated

    except Exception as e:
        logger.error(f"❌ 위임 계정 조회 실패: {e}")
        return []


def is_user_accessible(authenticated_user_id: str, target_user_id: str) -> bool:
    """
    인증된 사용자가 대상 사용자의 데이터에 접근 가능한지 확인합니다.

    Args:
        authenticated_user_id: 인증된 사용자 ID
        target_user_id: 접근하려는 대상 사용자 ID

    Returns:
        접근 가능 여부
    """
    # 본인이면 항상 접근 가능
    if authenticated_user_id == target_user_id:
        return True

    # 위임 확인
    delegated_users = get_delegated_user_ids(authenticated_user_id)
    return target_user_id in delegated_users


def get_authenticated_user_id(arguments: Dict[str, Any], authenticated_user_id: Optional[str]) -> Optional[str]:
    """
    인증된 user_id를 반환합니다.

    보안 정책:
    1. authenticated_user_id가 있으면:
       - 파라미터 user_id가 없거나 본인이면 → 본인 반환
       - 파라미터 user_id가 다른 사용자면 → 권한 확인
         - 위임/관리자 권한 있음 → 요청한 user_id 반환
         - 권한 없음 → 본인 반환 (거부)
    2. authenticated_user_id가 없으면 → fallback (로컬 개발/테스트용)

    Args:
        arguments: 툴 호출 인자
        authenticated_user_id: 인증 미들웨어에서 추출한 user_id (DCR Bearer token 기반)

    Returns:
        user_id (존재하지 않으면 None)
    """
    # 보안: 인증된 user_id가 있으면 권한 확인
    if authenticated_user_id:
        param_user_id = arguments.get("user_id")

        # 파라미터가 없거나 본인이면 바로 반환
        if not param_user_id or param_user_id == authenticated_user_id:
            return authenticated_user_id

        # 다른 사용자 요청 → 권한 확인
        if is_user_accessible(authenticated_user_id, param_user_id):
            logger.info(
                f"✅ 위임 권한: {authenticated_user_id} → {param_user_id} 접근 허용"
            )
            return param_user_id
        else:
            logger.warning(
                f"⚠️ 권한 거부: {authenticated_user_id}는 {param_user_id}에 접근 권한 없음. "
                f"본인 계정으로 제한됨."
            )
            return authenticated_user_id

    # Fallback: 인증 없는 경우 (로컬 개발/테스트용)
    # 프로덕션에서는 ENABLE_OAUTH_AUTH=true로 설정하여 이 경로를 사용하지 않음
    user_id = arguments.get("user_id")

    # 파라미터도 없으면 DB 조회
    if not user_id:
        from infra.core.database import get_database_manager
        db = get_database_manager()
        result = db.execute_query(
            "SELECT DISTINCT user_id FROM accounts WHERE is_active = TRUE LIMIT 1",
            fetch_result=True
        )
        if result and len(result) > 0:
            user_id = result[0][0]
            logger.info(f"📝 Fallback: DB에서 기본 user_id 조회: {user_id}")

    return user_id
