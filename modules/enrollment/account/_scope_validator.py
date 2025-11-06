"""
Scope Validator
delegated_permissions 형식 파싱 및 검증
"""

import json
from typing import List, Optional
from infra.core.logger import get_logger

logger = get_logger(__name__)


def parse_scopes_from_storage(scope_str: Optional[str]) -> List[str]:
    """
    다양한 형식의 scope 문자열을 List[str]로 파싱

    지원 형식:
    1. JSON 배열: '["scope1", "scope2"]'
    2. 공백 구분: "scope1 scope2"
    3. 쉼표 구분: "scope1,scope2"

    Args:
        scope_str: 저장된 scope 문자열

    Returns:
        파싱된 scope 리스트
    """
    if not scope_str:
        return []

    scope_str = scope_str.strip()
    if not scope_str:
        return []

    # 1. JSON 배열 형식 시도
    if scope_str.startswith('['):
        try:
            parsed = json.loads(scope_str)
            if isinstance(parsed, list):
                return [s.strip() for s in parsed if s.strip()]
        except json.JSONDecodeError:
            pass

    # 2. 공백 구분 (OAuth 2.0 표준)
    if ' ' in scope_str:
        return [s.strip() for s in scope_str.split() if s.strip()]

    # 3. 쉼표 구분
    if ',' in scope_str:
        return [s.strip() for s in scope_str.split(',') if s.strip()]

    # 4. 단일 scope
    return [scope_str]


def format_scopes_for_storage(scopes: List[str]) -> str:
    """
    scope 리스트를 저장 형식으로 변환 (공백 구분)

    Args:
        scopes: scope 리스트

    Returns:
        공백으로 구분된 scope 문자열
    """
    if not scopes:
        return ""

    return ' '.join(scopes)


def validate_scopes_coverage(user_scopes: List[str], base_scope: str = "User.Read") -> dict:
    """
    사용자 스코프가 기본 스코프에 포함되지 않는 것을 확인하고 로그 남김
    (.All로 끝나는 스코프는 제외)

    Args:
        user_scopes: 확인할 사용자 스코프 리스트
        base_scope: 기본 스코프 (기본값: "User.Read")

    Returns:
        {
            "base_scope": "User.Read",
            "not_included": ["Mail.Read", "Files.ReadWrite", ...],
            "excluded_all_scopes": ["Files.ReadWrite.All", ...]
        }
    """
    # .All로 끝나는 스코프 필터링
    all_scopes = [s for s in user_scopes if s.endswith('.All')]
    regular_scopes = [s for s in user_scopes if not s.endswith('.All')]

    # base_scope에 포함되지 않는 스코프 찾기
    # User.Read는 기본 사용자 프로필만 읽을 수 있으므로
    # 대부분의 다른 스코프는 포함되지 않음
    basic_scopes = {
        "User.Read",
        "openid",
        "profile",
        "email",
        "offline_access"
    }

    not_included = [s for s in regular_scopes if s not in basic_scopes]

    result = {
        "base_scope": base_scope,
        "not_included": not_included,
        "excluded_all_scopes": all_scopes
    }

    # 로그 출력
    if not_included:
        logger.info(f"📋 {base_scope}에 포함되지 않는 스코프 ({len(not_included)}개): {', '.join(not_included)}")

    if all_scopes:
        logger.info(f"🔒 .All 스코프 제외됨 ({len(all_scopes)}개): {', '.join(all_scopes)}")

    return result
