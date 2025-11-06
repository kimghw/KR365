"""
Unified Server Request/Response Logger
요청/응답을 DB에 저장하는 로깅 시스템
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from infra.core.database import get_database_manager
from infra.core.logger import get_logger

logger = get_logger(__name__)


class RequestLogger:
    """Unified Server 요청/응답 로거"""

    def __init__(self):
        """로거 초기화"""
        self.db = get_database_manager()
        self.enabled = os.getenv("ENABLE_UNIFIED_REQUEST_LOGGING", "false").lower() == "true"
        self.max_records = int(os.getenv("UNIFIED_REQUEST_LOG_MAX_RECORDS", "1000"))

        if self.enabled:
            self._initialize_table()
            logger.info(f"✅ RequestLogger 활성화 (최대 {self.max_records}개 레코드)")
        else:
            logger.info("⏸️ RequestLogger 비활성화")

    def _initialize_table(self):
        """요청 로그 테이블 초기화"""
        try:
            # 테이블 생성
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS unified_request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT (datetime('now')),
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    user_id TEXT,
                    request_body TEXT,
                    response_status INTEGER,
                    response_body TEXT,
                    duration_ms INTEGER,
                    error_message TEXT
                )
            """)

            # 인덱스 생성
            self.db.execute_query("""
                CREATE INDEX IF NOT EXISTS idx_request_logs_timestamp
                ON unified_request_logs(timestamp DESC)
            """)

            self.db.execute_query("""
                CREATE INDEX IF NOT EXISTS idx_request_logs_user_id
                ON unified_request_logs(user_id, timestamp DESC)
            """)

            logger.info("✅ unified_request_logs 테이블 초기화 완료")

            # 테이블이 사라진 경우를 대비해 매번 확인
            self._ensure_table_exists()

        except Exception as e:
            logger.error(f"❌ 요청 로그 테이블 초기화 실패: {str(e)}")

    def _ensure_table_exists(self):
        """테이블이 존재하는지 확인하고 없으면 재생성"""
        try:
            result = self.db.fetch_one("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='unified_request_logs'
            """)

            if not result:
                logger.warning("⚠️ unified_request_logs 테이블이 없습니다. 재생성합니다.")
                self._initialize_table()
        except Exception as e:
            logger.error(f"❌ 테이블 존재 확인 실패: {str(e)}")

    def _enforce_record_limit(self):
        """최대 레코드 수 제한 적용"""
        try:
            # 현재 레코드 수 확인
            count_result = self.db.fetch_one("SELECT COUNT(*) as count FROM unified_request_logs")
            current_count = count_result['count'] if count_result else 0

            # 제한 초과 시 오래된 레코드 삭제
            if current_count >= self.max_records:
                delete_count = current_count - self.max_records + 1
                self.db.execute_query(f"""
                    DELETE FROM unified_request_logs
                    WHERE id IN (
                        SELECT id FROM unified_request_logs
                        ORDER BY timestamp ASC
                        LIMIT {delete_count}
                    )
                """)
                logger.info(f"🗑️ 오래된 요청 로그 {delete_count}개 삭제 (제한: {self.max_records})")

        except Exception as e:
            logger.error(f"❌ 레코드 제한 적용 실패: {str(e)}")

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
        요청/응답 로그 저장

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
            # 테이블 존재 확인
            self._ensure_table_exists()

            # 레코드 제한 적용
            self._enforce_record_limit()

            # JSON 직렬화
            request_json = json.dumps(request_body, ensure_ascii=False) if request_body else None
            response_json = json.dumps(response_body, ensure_ascii=False) if response_body else None

            # DB에 저장
            self.db.execute_query("""
                INSERT INTO unified_request_logs
                (method, path, user_id, request_body, response_status, response_body, duration_ms, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (method, path, user_id, request_json, response_status, response_json, duration_ms, error_message))

            return True

        except Exception as e:
            logger.error(f"❌ 요청 로그 저장 실패: {str(e)}")
            return False

    def get_recent_logs(self, limit: int = 100, user_id: Optional[str] = None) -> list:
        """
        최근 요청 로그 조회

        Args:
            limit: 조회할 개수
            user_id: 특정 사용자의 로그만 조회 (선택)

        Returns:
            로그 목록
        """
        if not self.enabled:
            return []

        try:
            if user_id:
                results = self.db.fetch_all("""
                    SELECT * FROM unified_request_logs
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (user_id, limit))
            else:
                results = self.db.fetch_all("""
                    SELECT * FROM unified_request_logs
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"❌ 요청 로그 조회 실패: {str(e)}")
            return []

    def clear_logs(self, user_id: Optional[str] = None) -> bool:
        """
        로그 삭제

        Args:
            user_id: 특정 사용자의 로그만 삭제 (선택)

        Returns:
            성공 여부
        """
        if not self.enabled:
            return False

        try:
            if user_id:
                self.db.execute_query("DELETE FROM unified_request_logs WHERE user_id = ?", (user_id,))
                logger.info(f"✅ 사용자 {user_id}의 요청 로그 삭제 완료")
            else:
                self.db.execute_query("DELETE FROM unified_request_logs")
                logger.info("✅ 모든 요청 로그 삭제 완료")

            return True

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
