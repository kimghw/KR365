"""
Mail Query 모듈 헬퍼 함수들
mail_query_user_emails에 필요한 유틸리티 함수만 포함
"""

import re
from datetime import datetime
from typing import Any, Dict, Optional

from infra.core.logger import get_logger

from .mail_query_schema import GraphMailItem

logger = get_logger(__name__)


def escape_odata_string(value: str) -> str:
    """OData 문자열 이스케이프"""
    if not value:
        return ""

    # OData에서 특수 문자 이스케이프
    # 작은따옴표는 두 번 연속으로 표시
    escaped = value.replace("'", "''")
    # 백슬래시 이스케이프
    escaped = escaped.replace("\\", "\\\\")

    return escaped


def parse_graph_mail_item(item: Dict[str, Any]) -> GraphMailItem:
    """Graph API 응답을 GraphMailItem으로 변환"""
    try:
        # 날짜 파싱 처리
        received_date = item.get("receivedDateTime")
        if isinstance(received_date, str):
            # ISO 8601 형식 파싱 (Z 또는 +00:00 처리)
            if received_date.endswith("Z"):
                received_date = received_date.replace("Z", "+00:00")
            received_date = datetime.fromisoformat(received_date)
        elif not isinstance(received_date, datetime):
            received_date = datetime.utcnow()

        # from 필드 처리 (Python 예약어이므로 from_address로 매핑)
        from_field = item.get("from")

        return GraphMailItem(
            id=item.get("id", ""),
            subject=item.get("subject"),
            sender=item.get("sender"),
            from_address=from_field,
            to_recipients=item.get("toRecipients", []),
            received_date_time=received_date,
            body_preview=item.get("bodyPreview"),
            body=item.get("body"),
            is_read=item.get("isRead", False),
            has_attachments=item.get("hasAttachments", False),
            attachments=item.get("attachments"),  # 첨부파일 데이터 추가
            importance=item.get("importance", "normal"),
            web_link=item.get("webLink"),
        )

    except Exception as e:
        # 파싱 실패 시 기본값으로 생성
        return GraphMailItem(
            id=item.get("id", "unknown"),
            received_date_time=datetime.utcnow(),
            subject=f"파싱 오류: {str(e)}",
        )


def format_query_summary(
    user_id: str, result_count: int, execution_time_ms: int, has_error: bool = False
) -> str:
    """쿼리 결과 요약 포맷"""
    status = "ERROR" if has_error else "SUCCESS"
    return f"[{status}] user_id={user_id}, count={result_count}, time={execution_time_ms}ms"


def validate_pagination_params(top: int, skip: int, max_pages: int) -> bool:
    """페이징 매개변수 유효성 검사"""
    if not (1 <= top <= 1000):
        return False
    if skip < 0:
        return False
    if not (1 <= max_pages <= 50):
        return False
    return True


def sanitize_filter_input(filter_value: str) -> str:
    """필터 입력값 정제 (보안 및 안정성)"""
    if not filter_value:
        return ""

    # 기본 정제: 제어 문자 제거
    sanitized = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", filter_value)

    # 길이 제한 (너무 긴 필터는 성능 문제 야기)
    if len(sanitized) > 500:
        sanitized = sanitized[:500]

    return sanitized.strip()


def parse_graph_error_response(error_response: Dict[str, Any]) -> Dict[str, Any]:
    """Graph API 오류 응답 파싱"""
    error_info = {"code": "unknown", "message": "Unknown error", "inner_error": None}

    if "error" in error_response:
        error_data = error_response["error"]
        error_info["code"] = error_data.get("code", "unknown")
        error_info["message"] = error_data.get("message", "Unknown error")
        error_info["inner_error"] = error_data.get("innerError")

    return error_info


def calculate_retry_delay(
    attempt: int, base_delay: float = 1.0, max_delay: float = 60.0
) -> float:
    """지수 백오프 재시도 지연 시간 계산"""
    delay = base_delay * (2**attempt)
    return min(delay, max_delay)


def is_transient_error(status_code: int, error_code: Optional[str] = None) -> bool:
    """일시적 오류인지 판단 (재시도 가능 여부)"""
    # HTTP 상태 코드 기반 판단
    transient_status_codes = {429, 500, 502, 503, 504}

    if status_code in transient_status_codes:
        return True

    # 특정 오류 코드 기반 판단
    if error_code:
        transient_error_codes = {
            "TooManyRequests",
            "ServiceUnavailable",
            "InternalServerError",
            "BadGateway",
            "GatewayTimeout",
        }
        return error_code in transient_error_codes

    return False
