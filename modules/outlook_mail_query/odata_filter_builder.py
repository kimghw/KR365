"""
OData 필터 문자열 생성기
Microsoft Graph API용 OData 쿼리 필터 구성
"""

from datetime import datetime
from typing import Optional

from .mail_query_helpers import escape_odata_string  # 언더스코어 제거됨
from .mail_query_schema import MailQuerySeverFilters


class ODataFilterBuilder:
    """OData 필터 문자열 생성기"""

    def build_filter(self, filters: MailQuerySeverFilters) -> Optional[str]:
        """필터 조건을 OData 필터 문자열로 변환"""
        conditions = []

        # 날짜 필터 처리
        if filters.date_from:
            date_str = self._format_datetime(filters.date_from)
            conditions.append(f"receivedDateTime ge {date_str}")

        if filters.date_to:
            date_str = self._format_datetime(filters.date_to)
            conditions.append(f"receivedDateTime le {date_str}")

        # 발신자 필터 처리
        if filters.sender_address:
            escaped_sender = escape_odata_string(filters.sender_address)
            conditions.append(f"from/emailAddress/address eq '{escaped_sender}'")

        # 제목 포함 필터 처리
        if filters.subject_contains:
            escaped_subject = escape_odata_string(filters.subject_contains)
            conditions.append(f"contains(subject, '{escaped_subject}')")

        # 읽음 상태 필터 처리
        if filters.is_read is not None:
            conditions.append(f"isRead eq {str(filters.is_read).lower()}")

        # 첨부파일 여부 필터 처리
        if filters.has_attachments is not None:
            conditions.append(
                f"hasAttachments eq {str(filters.has_attachments).lower()}"
            )

        # 중요도 필터 처리
        if filters.importance:
            conditions.append(f"importance eq '{filters.importance}'")

        return " and ".join(conditions) if conditions else None

    def build_search_query(self, search_query: str) -> str:
        """
        $search 쿼리 문자열 생성

        Args:
            search_query: 검색어 (예: "from:홍길동", "keyword1 AND keyword2")

        Returns:
            OData $search 쿼리 문자열

        Examples:
            - "홍길동" -> 모든 필드에서 "홍길동" 검색
            - "from:김철수" -> 발신자명에 "김철수" 포함
            - "계약서 AND 승인" -> "계약서"와 "승인" 모두 포함
            - "보고서 OR 리포트" -> "보고서" 또는 "리포트" 포함
        """
        # $search는 특별한 이스케이프 없이 그대로 전달
        # Graph API가 자동으로 처리
        return search_query.strip()

    def _format_datetime(self, dt: datetime) -> str:
        """datetime을 OData 형식으로 변환"""
        # ISO 8601 형식으로 변환 (Z suffix 추가)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def validate_filter_complexity(self, filters: MailQuerySeverFilters) -> bool:
        """필터 복잡성 검증 (InefficientFilter 오류 방지)"""
        condition_count = 0

        # 조건 개수 계산
        if filters.date_from or filters.date_to:
            condition_count += 1
        if filters.sender_address:
            condition_count += 1
        if filters.subject_contains:
            condition_count += 1
        if filters.is_read is not None:
            condition_count += 1
        if filters.has_attachments is not None:
            condition_count += 1
        if filters.importance:
            condition_count += 1

        # 복잡한 필터는 성능 문제를 일으킬 수 있음
        return condition_count <= 5

    def build_select_clause(
        self, select_fields: Optional[list] = None
    ) -> Optional[str]:
        """선택 필드 절 생성"""
        if not select_fields:
            return None

        # Graph API에서 지원하는 기본 필드들
        allowed_fields = {
            "id",
            "subject",
            "sender",
            "from",
            "toRecipients",
            "ccRecipients",
            "receivedDateTime",
            "sentDateTime",
            "bodyPreview",
            "body",
            "isRead",
            "hasAttachments",
            "attachments",  # 첨부파일 정보 추가
            "importance",
            "webLink",
            "parentFolderId",
            "conversationId",
            "internetMessageHeaders",
        }

        # 유효한 필드만 필터링
        valid_fields = [field for field in select_fields if field in allowed_fields]

        return ",".join(valid_fields) if valid_fields else None

    def estimate_query_performance(
        self, filters: MailQuerySeverFilters, pagination_top: int
    ) -> str:
        """쿼리 성능 예상 등급 반환"""
        score = 0

        # 날짜 필터는 인덱스가 있어 빠름
        if filters.date_from or filters.date_to:
            score += 1

        # 발신자 필터도 상대적으로 빠름
        if filters.sender_address:
            score += 1

        # 텍스트 검색은 느림
        if filters.subject_contains:
            score -= 2

        # 페이지 크기가 클수록 느림
        if pagination_top > 100:
            score -= 1
        if pagination_top > 500:
            score -= 2

        # 복합 조건은 느려질 수 있음
        condition_count = sum(
            [
                bool(filters.date_from or filters.date_to),
                bool(filters.sender_address),
                bool(filters.subject_contains),
                bool(filters.is_read is not None),
                bool(filters.has_attachments is not None),
                bool(filters.importance),
            ]
        )

        if condition_count > 3:
            score -= 1

        if score >= 2:
            return "FAST"
        elif score >= 0:
            return "MODERATE"
        else:
            return "SLOW"
