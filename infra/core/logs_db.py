"""
로그 전용 데이터베이스 서비스
Unified Request Logs와 DCR Middleware Logs를 별도 DB에 저장
"""

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from infra.core.logger import get_logger

logger = get_logger(__name__)


class LogsDBService:
    """로그 전용 DB 서비스 (자동 테이블 생성)"""

    def __init__(self, db_path: Optional[str] = None):
        """
        로그 DB 서비스 초기화

        Args:
            db_path: DB 파일 경로 (기본값: data/logs.db)
        """
        if db_path is None:
            # data 폴더의 logs.db 사용
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            data_dir = os.path.join(project_root, "data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "logs.db")

        self.db_path = db_path

        # 설정
        self.max_unified_logs = int(os.getenv("MAX_UNIFIED_REQUEST_LOGS", "10000"))
        self.max_dcr_logs = int(os.getenv("MAX_DCR_MIDDLEWARE_LOGS", "10000"))

        # DB 초기화 (연결은 매번 생성)
        self._initialize_db()

        logger.info(f"✅ LogsDBService 초기화 완료: {self.db_path}")

    def _get_connection(self):
        """DB 연결 생성 (매번 새로 생성)"""
        # data 디렉토리 확인 및 생성
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"📁 DB 디렉토리 생성: {db_dir}")

        # DB 파일이 존재하는지 확인
        db_exists = os.path.exists(self.db_path)

        # DB 연결 (파일이 없으면 자동 생성됨)
        # check_same_thread=False: 멀티스레드 환경(FastAPI 비동기)에서 안전하게 사용
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Dict처럼 사용 가능

        # WAL 모드 활성화 (동시성 향상 및 성능 개선)
        conn.execute("PRAGMA journal_mode = WAL")
        # 외래키 제약조건 활성화
        conn.execute("PRAGMA foreign_keys = ON")

        # DB 파일이 새로 생성되었거나 비어있으면 테이블 초기화
        if not db_exists or os.path.getsize(self.db_path) == 0:
            logger.info(f"📄 새 DB 파일 생성 또는 빈 파일 감지: {self.db_path}")
            self._initialize_tables(conn)

        return conn

    def _initialize_db(self):
        """초기 DB 설정 (서비스 시작 시 한 번만 실행)"""
        conn = self._get_connection()
        try:
            # 초기화는 _get_connection에서 자동으로 처리됨
            pass
        finally:
            conn.close()

    def _initialize_tables(self, conn):
        """테이블 생성 (conn 매개변수로 받음)"""
        try:
            cursor = conn.cursor()

            # 1. unified_request_logs 테이블
            cursor.execute("""
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

            # unified_request_logs 인덱스
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_unified_logs_timestamp
                ON unified_request_logs(timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_unified_logs_user_id
                ON unified_request_logs(user_id, timestamp DESC)
            """)

            # 2. dcr_middleware_logs 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dcr_middleware_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT (datetime('now')),
                    path TEXT NOT NULL,
                    method TEXT NOT NULL,
                    dcr_client_id TEXT,
                    azure_object_id TEXT,
                    user_id TEXT,
                    auth_result TEXT NOT NULL,
                    token_valid INTEGER,
                    error_message TEXT
                )
            """)

            # dcr_middleware_logs 인덱스
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_dcr_logs_timestamp
                ON dcr_middleware_logs(timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_dcr_logs_client_id
                ON dcr_middleware_logs(dcr_client_id, timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_dcr_logs_user_id
                ON dcr_middleware_logs(user_id, timestamp DESC)
            """)

            # 3. dcr_database_operations 테이블 (dcr.db 생성/삭제 추적용)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dcr_database_operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT (datetime('now')),
                    operation TEXT NOT NULL,  -- CREATE, DELETE, BACKUP, RESTORE 등
                    database_path TEXT NOT NULL,
                    file_size INTEGER,
                    performed_by TEXT,  -- 작업 수행자 (사용자 또는 시스템)
                    details TEXT,  -- 추가 상세 정보 (JSON 형식)
                    success INTEGER DEFAULT 1,
                    error_message TEXT
                )
            """)

            # dcr_database_operations 인덱스
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_dcr_db_ops_timestamp
                ON dcr_database_operations(timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_dcr_db_ops_operation
                ON dcr_database_operations(operation, timestamp DESC)
            """)

            conn.commit()
            logger.info("✅ 로그 테이블 초기화 완료 (unified_request_logs, dcr_middleware_logs, dcr_database_operations)")

        except Exception as e:
            logger.error(f"❌ 로그 테이블 초기화 실패: {str(e)}")
            raise

    def get_tables(self) -> List[str]:
        """DB의 모든 테이블 목록 조회"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            return tables
        except Exception as e:
            logger.error(f"❌ 테이블 목록 조회 실패: {str(e)}")
            return []
        finally:
            conn.close()

    # ========================================================================
    # Unified Request Logs
    # ========================================================================

    def log_unified_request(
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
        Unified 요청 로그 저장

        Args:
            method: HTTP 메소드
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
        conn = self._get_connection()
        try:
            # JSON 직렬화
            request_json = json.dumps(request_body, ensure_ascii=False) if request_body else None
            response_json = json.dumps(response_body, ensure_ascii=False) if response_body else None

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO unified_request_logs
                (method, path, user_id, request_body, response_status, response_body, duration_ms, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (method, path, user_id, request_json, response_status, response_json, duration_ms, error_message))

            conn.commit()

            # 레코드 수 제한 적용
            self._enforce_unified_log_limit()

            return True

        except Exception as e:
            logger.error(f"❌ Unified 요청 로그 저장 실패: {str(e)}")
            return False
        finally:
            conn.close()

    def _enforce_unified_log_limit(self):
        """Unified 로그 레코드 수 제한 적용"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM unified_request_logs")
            count = cursor.fetchone()[0]

            if count > self.max_unified_logs:
                delete_count = count - self.max_unified_logs
                cursor.execute(f"""
                    DELETE FROM unified_request_logs
                    WHERE id IN (
                        SELECT id FROM unified_request_logs
                        ORDER BY timestamp ASC
                        LIMIT {delete_count}
                    )
                """)
                conn.commit()
                logger.info(f"🗑️ 오래된 Unified 로그 {delete_count}개 삭제 (제한: {self.max_unified_logs})")

        except Exception as e:
            logger.error(f"❌ Unified 로그 제한 적용 실패: {str(e)}")
        finally:
            conn.close()

    def get_unified_logs(self, limit: int = 100, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Unified 로그 조회

        Args:
            limit: 조회할 개수
            user_id: 특정 사용자의 로그만 조회 (선택)

        Returns:
            로그 목록
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if user_id:
                cursor.execute("""
                    SELECT * FROM unified_request_logs
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (user_id, limit))
            else:
                cursor.execute("""
                    SELECT * FROM unified_request_logs
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"❌ Unified 로그 조회 실패: {str(e)}")
            return []
        finally:
            conn.close()

    def clear_unified_logs(self, user_id: Optional[str] = None) -> bool:
        """
        Unified 로그 삭제

        Args:
            user_id: 특정 사용자의 로그만 삭제 (선택)

        Returns:
            성공 여부
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if user_id:
                cursor.execute("DELETE FROM unified_request_logs WHERE user_id = ?", (user_id,))
                logger.info(f"✅ 사용자 {user_id}의 Unified 로그 삭제 완료")
            else:
                cursor.execute("DELETE FROM unified_request_logs")
                logger.info("✅ 모든 Unified 로그 삭제 완료")

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"❌ Unified 로그 삭제 실패: {str(e)}")
            return False
        finally:
            conn.close()

    # ========================================================================
    # DCR Middleware Logs
    # ========================================================================

    def log_dcr_middleware(
        self,
        path: str,
        method: str,
        dcr_client_id: Optional[str],
        azure_object_id: Optional[str],
        user_id: Optional[str],
        auth_result: str,
        token_valid: bool,
        error_message: Optional[str] = None
    ) -> bool:
        """
        DCR 미들웨어 인증 로그 저장

        Args:
            path: 요청 경로
            method: HTTP 메소드
            dcr_client_id: DCR 클라이언트 ID (선택)
            azure_object_id: Azure Object ID (선택)
            user_id: 사용자 ID (선택)
            auth_result: 인증 결과 (success/failed/skipped)
            token_valid: 토큰 유효성
            error_message: 에러 메시지 (선택)

        Returns:
            성공 여부
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO dcr_middleware_logs
                (path, method, dcr_client_id, azure_object_id, user_id, auth_result, token_valid, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (path, method, dcr_client_id, azure_object_id, user_id, auth_result, int(token_valid), error_message))

            conn.commit()

            # 레코드 수 제한 적용
            self._enforce_dcr_log_limit()

            return True

        except Exception as e:
            logger.error(f"❌ DCR 미들웨어 로그 저장 실패: {str(e)}")
            return False
        finally:
            conn.close()

    def _enforce_dcr_log_limit(self):
        """DCR 로그 레코드 수 제한 적용"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM dcr_middleware_logs")
            count = cursor.fetchone()[0]

            if count > self.max_dcr_logs:
                delete_count = count - self.max_dcr_logs
                cursor.execute(f"""
                    DELETE FROM dcr_middleware_logs
                    WHERE id IN (
                        SELECT id FROM dcr_middleware_logs
                        ORDER BY timestamp ASC
                        LIMIT {delete_count}
                    )
                """)
                conn.commit()
                logger.info(f"🗑️ 오래된 DCR 로그 {delete_count}개 삭제 (제한: {self.max_dcr_logs})")

        except Exception as e:
            logger.error(f"❌ DCR 로그 제한 적용 실패: {str(e)}")
        finally:
            conn.close()

    def get_dcr_middleware_logs(
        self,
        limit: int = 100,
        dcr_client_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        DCR 미들웨어 로그 조회

        Args:
            limit: 조회할 개수
            dcr_client_id: 특정 클라이언트의 로그만 조회 (선택)
            user_id: 특정 사용자의 로그만 조회 (선택)

        Returns:
            로그 목록
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if dcr_client_id:
                cursor.execute("""
                    SELECT * FROM dcr_middleware_logs
                    WHERE dcr_client_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (dcr_client_id, limit))
            elif user_id:
                cursor.execute("""
                    SELECT * FROM dcr_middleware_logs
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (user_id, limit))
            else:
                cursor.execute("""
                    SELECT * FROM dcr_middleware_logs
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"❌ DCR 미들웨어 로그 조회 실패: {str(e)}")
            return []
        finally:
            conn.close()

    def clear_dcr_middleware_logs(
        self,
        dcr_client_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> bool:
        """
        DCR 미들웨어 로그 삭제

        Args:
            dcr_client_id: 특정 클라이언트의 로그만 삭제 (선택)
            user_id: 특정 사용자의 로그만 삭제 (선택)

        Returns:
            성공 여부
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if dcr_client_id:
                cursor.execute("DELETE FROM dcr_middleware_logs WHERE dcr_client_id = ?", (dcr_client_id,))
                logger.info(f"✅ 클라이언트 {dcr_client_id}의 DCR 로그 삭제 완료")
            elif user_id:
                cursor.execute("DELETE FROM dcr_middleware_logs WHERE user_id = ?", (user_id,))
                logger.info(f"✅ 사용자 {user_id}의 DCR 로그 삭제 완료")
            else:
                cursor.execute("DELETE FROM dcr_middleware_logs")
                logger.info("✅ 모든 DCR 로그 삭제 완료")

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"❌ DCR 로그 삭제 실패: {str(e)}")
            return False
        finally:
            conn.close()

    # ========================================================================
    # DCR Database Operations Logs
    # ========================================================================

    def log_dcr_database_operation(
        self,
        operation: str,
        database_path: str,
        file_size: Optional[int] = None,
        performed_by: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> bool:
        """
        DCR 데이터베이스 작업 로그 저장 (생성/삭제/백업/복원 등)

        Args:
            operation: 작업 유형 (CREATE, DELETE, BACKUP, RESTORE 등)
            database_path: 데이터베이스 파일 경로
            file_size: 파일 크기 (바이트, 선택)
            performed_by: 작업 수행자 (사용자 또는 시스템)
            details: 추가 상세 정보 (선택)
            success: 성공 여부
            error_message: 에러 메시지 (실패 시)

        Returns:
            성공 여부
        """
        conn = self._get_connection()
        try:
            # JSON 직렬화
            details_json = json.dumps(details, ensure_ascii=False) if details else None

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO dcr_database_operations
                (operation, database_path, file_size, performed_by, details, success, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (operation, database_path, file_size, performed_by, details_json, int(success), error_message))

            conn.commit()

            # 콘솔 로깅
            if success:
                logger.info(f"📁 DCR DB {operation}: {database_path} (수행자: {performed_by or 'SYSTEM'})")
            else:
                logger.error(f"❌ DCR DB {operation} 실패: {database_path} - {error_message}")

            return True

        except Exception as e:
            logger.error(f"❌ DCR 데이터베이스 작업 로그 저장 실패: {str(e)}")
            return False
        finally:
            conn.close()

    def get_dcr_database_operations(
        self,
        limit: int = 100,
        operation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        DCR 데이터베이스 작업 로그 조회

        Args:
            limit: 조회할 개수
            operation: 특정 작업만 조회 (CREATE, DELETE 등)

        Returns:
            로그 목록
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if operation:
                cursor.execute("""
                    SELECT * FROM dcr_database_operations
                    WHERE operation = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (operation, limit))
            else:
                cursor.execute("""
                    SELECT * FROM dcr_database_operations
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            logs = []
            for row in cursor.fetchall():
                log_dict = dict(row)
                # JSON 문자열을 딕셔너리로 파싱
                if log_dict.get('details'):
                    try:
                        log_dict['details'] = json.loads(log_dict['details'])
                    except:
                        pass
                logs.append(log_dict)

            return logs

        except Exception as e:
            logger.error(f"❌ DCR 데이터베이스 작업 로그 조회 실패: {str(e)}")
            return []
        finally:
            conn.close()

    def get_dcr_database_stats(self) -> Dict[str, Any]:
        """
        DCR 데이터베이스 작업 통계 조회

        Returns:
            작업별 통계 정보
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # 전체 작업 수
            cursor.execute("SELECT COUNT(*) FROM dcr_database_operations")
            total_operations = cursor.fetchone()[0]

            # 작업 유형별 카운트
            cursor.execute("""
                SELECT operation, COUNT(*) as count
                FROM dcr_database_operations
                GROUP BY operation
            """)
            operations_by_type = {row[0]: row[1] for row in cursor.fetchall()}

            # 성공/실패 카운트
            cursor.execute("""
                SELECT success, COUNT(*) as count
                FROM dcr_database_operations
                GROUP BY success
            """)
            success_stats = {bool(row[0]): row[1] for row in cursor.fetchall()}

            # 최근 작업 (최근 5개)
            cursor.execute("""
                SELECT operation, database_path, timestamp, success
                FROM dcr_database_operations
                ORDER BY timestamp DESC
                LIMIT 5
            """)
            recent_operations = [
                {
                    "operation": row[0],
                    "database_path": row[1],
                    "timestamp": row[2],
                    "success": bool(row[3])
                }
                for row in cursor.fetchall()
            ]

            return {
                "total_operations": total_operations,
                "operations_by_type": operations_by_type,
                "success_count": success_stats.get(True, 0),
                "failure_count": success_stats.get(False, 0),
                "recent_operations": recent_operations
            }

        except Exception as e:
            logger.error(f"❌ DCR 데이터베이스 작업 통계 조회 실패: {str(e)}")
            return {
                "error": str(e),
                "total_operations": 0
            }
        finally:
            conn.close()

    def close(self):
        """DB 연결 종료 (매번 연결하므로 불필요)"""
        logger.info("✅ LogsDBService는 매 요청마다 연결을 생성/종료합니다")


# 전역 LogsDBService 인스턴스
_logs_db_service: Optional[LogsDBService] = None


def get_logs_db_service() -> LogsDBService:
    """LogsDBService 싱글톤 인스턴스 반환"""
    global _logs_db_service
    if _logs_db_service is None:
        _logs_db_service = LogsDBService()
    return _logs_db_service
