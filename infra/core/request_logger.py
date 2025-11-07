"""
Unified Server Request/Response Logger
요청/응답을 별도 logs.db에 저장하는 로깅 시스템
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from infra.core.logs_db import get_logs_db_service
from infra.core.logger import get_logger

logger = get_logger(__name__)


class RequestLogger:
    """Unified Server 요청/응답 로거 (logs.db 사용)"""

    def __init__(self):
        """로거 초기화"""
        self.logs_db = get_logs_db_service()
        self.enabled = os.getenv("ENABLE_UNIFIED_REQUEST_LOGGING", "false").lower() == "true"

        if self.enabled:
            logger.info(f"✅ RequestLogger 활성화 (logs.db 사용)")
        else:
            logger.info("⏸️ RequestLogger 비활성화")

    # Note: 테이블 초기화는 logs_db에서 자동으로 처리됨

    def log_request(
        self,
        method: str,
        path: str,
        user_id: Optional[str] = None,
        request_body: Optional[Dict[str, Any]] = None,
        response_status: Optional[int] = None,
        response_body: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> bool:
        """
        요청/응답 로그 저장 (logs.db에 저장)

        Args:
            method: HTTP 메소드 (GET, POST, etc.)
            path: 요청 경로
            user_id: 사용자 ID (선택)
            request_body: 요청 본문 (선택)
            response_status: 응답 상태 코드 (선택)
            response_body: 응답 본문 (선택)
            duration_ms: 처리 시간 (밀리초)
            error_message: 에러 메시지 (선택)

        Returns:
            성공 여부
        """
        if not self.enabled:
            return False

        try:
            # logs.db의 log_unified_request 메서드 호출
            return self.logs_db.log_unified_request(
                method=method,
                path=path,
                user_id=user_id,
                request_body=request_body,
                response_status=response_status,
                response_body=response_body,
                duration_ms=duration_ms,
                error_message=error_message
            )

        except Exception as e:
            logger.error(f"❌ 요청 로그 저장 실패: {str(e)}")
            return False

    def get_recent_logs(self, limit: int = 100, user_id: Optional[str] = None) -> list:
        """
        최근 요청 로그 조회 (logs.db에서 조회)

        Args:
            limit: 조회할 개수
            user_id: 특정 사용자의 로그만 조회 (선택)

        Returns:
            로그 목록
        """
        if not self.enabled:
            return []

        try:
            return self.logs_db.get_unified_logs(limit=limit, user_id=user_id)

        except Exception as e:
            logger.error(f"❌ 요청 로그 조회 실패: {str(e)}")
            return []

    def clear_logs(self, user_id: Optional[str] = None) -> bool:
        """
        로그 삭제 (logs.db에서 삭제)

        Args:
            user_id: 특정 사용자의 로그만 삭제 (선택)

        Returns:
            성공 여부
        """
        if not self.enabled:
            return False

        try:
            return self.logs_db.clear_unified_logs(user_id=user_id)

        except Exception as e:
            logger.error(f"❌ 요청 로그 삭제 실패: {str(e)}")
            return False


# 전역 RequestLogger 인스턴스
_request_logger: Optional[RequestLogger] = None


def get_request_logger() -> RequestLogger:
    """RequestLogger 싱글톤 인스턴스 반환"""
    global _request_logger
    if _request_logger is None:
        _request_logger = RequestLogger()
    return _request_logger
