"""
인증 관련 헬퍼 함수들

모든 MCP 핸들러에서 공통으로 사용하는 인증 관련 유틸리티
"""

from typing import Dict, Any, Optional
from infra.core.logger import get_logger

logger = get_logger(__name__)


def get_authenticated_user_id(arguments: Dict[str, Any], authenticated_user_id: Optional[str]) -> Optional[str]:
    """
    인증된 user_id를 반환합니다.

    보안 정책:
    1. authenticated_user_id가 있으면 → 무조건 그것만 사용 (파라미터 무시)
    2. authenticated_user_id가 없으면 → fallback (로컬 개발/테스트용)
       - 파라미터 user_id 사용
       - 없으면 DB에서 첫 번째 활성 user_id

    Args:
        arguments: 툴 호출 인자
        authenticated_user_id: 인증 미들웨어에서 추출한 user_id (DCR Bearer token 기반)

    Returns:
        user_id (존재하지 않으면 None)
    """
    # 보안: 인증된 user_id가 있으면 무조건 그것만 사용
    if authenticated_user_id:
        param_user_id = arguments.get("user_id")
        if param_user_id and param_user_id != authenticated_user_id:
            logger.warning(
                f"⚠️ 보안: 인증된 user_id({authenticated_user_id})와 "
                f"파라미터 user_id({param_user_id})가 다름. 인증된 user_id 강제 사용."
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
