"""
DCR OAuth Database Service
DatabaseManager를 사용하는 개선된 DB 서비스
"""

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from contextlib import contextmanager

from infra.core.database import DatabaseManager
from infra.core.logger import get_logger
from infra.core.config import get_config
from infra.core.logs_db import get_logs_db_service
from .dcr_db_logger import get_dcr_db_logger

logger = get_logger(__name__)


class DCRDatabaseService:
    """
    DCR OAuth 전용 데이터베이스 서비스

    기존 db_utils.py를 대체하며 다음 개선사항 제공:
    - DatabaseManager 패턴 사용 (연결 재사용)
    - Thread-safe 연결 관리
    - WAL 모드 지원
    - 더 나은 에러 처리
    - 타입 힌트 개선
    """

    def __init__(self):
        """DCR Database Service 초기화"""
        self.config = get_config()
        self.db_path = self.config.dcr_database_path
        self._connection: Optional[sqlite3.Connection] = None
        self.db_logger = get_dcr_db_logger()  # DCR DB 로거 초기화
        self.logs_db = get_logs_db_service()  # logs.db 서비스 초기화
        self._ensure_database()

    def _ensure_database(self):
        """데이터베이스 파일과 디렉토리 확인/생성"""
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # 데이터베이스 초기 연결 및 설정
        if not db_path.exists():
            logger.info(f"DCR 데이터베이스 생성: {self.db_path}")

            # logs.db에 DCR DB 생성 로깅
            self.logs_db.log_dcr_database_operation(
                operation="CREATE",
                database_path=str(self.db_path),
                performed_by="SYSTEM",
                details={"reason": "Database file not exists, creating new one"}
            )

            self._get_connection()  # 초기 연결로 파일 생성

            # 생성 후 파일 크기 확인 및 로깅
            if db_path.exists():
                file_size = db_path.stat().st_size
                self.logs_db.log_dcr_database_operation(
                    operation="CREATE_COMPLETE",
                    database_path=str(self.db_path),
                    file_size=file_size,
                    performed_by="SYSTEM",
                    details={"initial_size": file_size}
                )

    def _get_connection(self) -> sqlite3.Connection:
        """데이터베이스 연결 반환 (레이지 초기화)"""
        if self._connection is None:
            try:
                # 연결 생성
                self._connection = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,  # 멀티스레드 환경 지원
                    timeout=30.0,
                    isolation_level=None,  # 오토커밋 모드
                )

                # Row factory 설정 (딕셔너리 형태로 결과 반환)
                self._connection.row_factory = sqlite3.Row

                # WAL 모드 활성화 (동시성 향상)
                self._connection.execute("PRAGMA journal_mode = WAL")

                # 외래키 제약조건 활성화
                self._connection.execute("PRAGMA foreign_keys = ON")

                logger.debug(f"DCR 데이터베이스 연결 성공: {self.db_path}")

            except sqlite3.Error as e:
                logger.error(f"DCR 데이터베이스 연결 실패: {str(e)}")
                raise

        return self._connection

    @contextmanager
    def get_cursor(self):
        """커서를 안전하게 사용하기 위한 컨텍스트 매니저"""
        connection = self._get_connection()
        cursor = connection.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def _extract_table_name(self, query: str, prefix: str) -> str:
        """SQL 쿼리에서 테이블명 추출"""
        try:
            # 쿼리를 소문자로 변환하여 처리
            query_lower = query.lower()
            prefix_lower = prefix.lower()

            # prefix 이후의 테이블명 찾기
            start_idx = query_lower.find(prefix_lower)
            if start_idx == -1:
                return "UNKNOWN"

            # prefix 이후 첫 단어가 테이블명
            remaining = query[start_idx + len(prefix):].strip()
            # 공백, 괄호, 세미콜론 등으로 테이블명 끝 찾기
            import re
            match = re.match(r'[\w_]+', remaining)
            if match:
                return match.group(0)

            return "UNKNOWN"
        except:
            return "UNKNOWN"

    def execute_query(
        self,
        query: str,
        params: Union[Tuple[Any, ...], Dict[str, Any], None] = None,
        user_email: Optional[str] = None,
        client_id: Optional[str] = None
    ) -> int:
        """
        SQL 쿼리 실행 (INSERT, UPDATE, DELETE)

        Args:
            query: 실행할 SQL 쿼리
            params: 쿼리 매개변수
            user_email: 작업 수행 사용자 (로깅용)
            client_id: 클라이언트 ID (로깅용)

        Returns:
            lastrowid (INSERT의 경우) 또는 영향받은 행 수

        Note:
            기존 db_utils.execute_query와 호환되도록 설계됨
        """
        # 작업 유형과 테이블 파싱
        query_upper = query.strip().upper()
        if query_upper.startswith('INSERT'):
            operation = 'INSERT'
            # INSERT INTO table_name 패턴에서 테이블명 추출
            table = self._extract_table_name(query, 'INSERT INTO')
        elif query_upper.startswith('UPDATE'):
            operation = 'UPDATE'
            table = self._extract_table_name(query, 'UPDATE')
        elif query_upper.startswith('DELETE'):
            operation = 'DELETE'
            table = self._extract_table_name(query, 'DELETE FROM')
        else:
            operation = 'OTHER'
            table = 'UNKNOWN'

        try:
            with self.get_cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                # INSERT의 경우 lastrowid, 그 외는 rowcount 반환
                if operation == 'INSERT':
                    result = cursor.lastrowid
                else:
                    result = cursor.rowcount

                # 파일 로깅 (기존)
                self.db_logger.log_operation(
                    operation=operation,
                    table=table,
                    query=query,
                    params=params,
                    result=result,
                    user_email=user_email,
                    client_id=client_id
                )

                # logs.db에도 로깅 (추가)
                details = {
                    "table": table,
                    "query": query[:500],  # 쿼리가 너무 길 수 있으므로 제한
                    "params": str(params)[:200] if params else None,
                    "rows_affected": result,
                    "user_email": user_email,
                    "client_id": client_id
                }

                self.logs_db.log_dcr_database_operation(
                    operation=f"DCR_{operation}",
                    database_path=str(self.db_path),
                    performed_by=user_email or "SYSTEM",
                    details=details,
                    success=True
                )

                return result

        except sqlite3.Error as e:
            error_msg = str(e)
            logger.error(f"DCR 쿼리 실행 실패: {query[:100]}... - {error_msg}")

            # 파일 로깅 (기존)
            self.db_logger.log_operation(
                operation=operation,
                table=table,
                query=query,
                params=params,
                error=error_msg,
                user_email=user_email,
                client_id=client_id
            )

            # logs.db에도 실패 로깅 (추가)
            details = {
                "table": table,
                "query": query[:500],
                "params": str(params)[:200] if params else None,
                "user_email": user_email,
                "client_id": client_id
            }

            self.logs_db.log_dcr_database_operation(
                operation=f"DCR_{operation}_FAILED",
                database_path=str(self.db_path),
                performed_by=user_email or "SYSTEM",
                details=details,
                success=False,
                error_message=error_msg[:500]  # 에러 메시지도 길이 제한
            )

            raise

    def fetch_one(
        self,
        query: str,
        params: Union[Tuple[Any, ...], Dict[str, Any], None] = None
    ) -> Optional[sqlite3.Row]:
        """
        단일 행 조회

        Args:
            query: SELECT 쿼리
            params: 쿼리 매개변수

        Returns:
            조회된 행 또는 None

        Note:
            기존 db_utils.fetch_one과 달리 Row 객체 반환 (튜플 대신)
            하위 호환성을 위해 튜플처럼 사용 가능
        """
        try:
            with self.get_cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                return cursor.fetchone()

        except sqlite3.Error as e:
            logger.error(f"DCR 단일 행 조회 실패: {query[:100]}... - {str(e)}")
            raise

    def fetch_all(
        self,
        query: str,
        params: Union[Tuple[Any, ...], Dict[str, Any], None] = None
    ) -> List[sqlite3.Row]:
        """
        모든 행 조회

        Args:
            query: SELECT 쿼리
            params: 쿼리 매개변수

        Returns:
            조회된 행들의 리스트

        Note:
            기존 db_utils.fetch_all과 달리 Row 객체 리스트 반환
        """
        try:
            with self.get_cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                return cursor.fetchall()

        except sqlite3.Error as e:
            logger.error(f"DCR 전체 행 조회 실패: {query[:100]}... - {str(e)}")
            raise

    @contextmanager
    def transaction(self):
        """
        트랜잭션을 안전하게 처리하기 위한 컨텍스트 매니저

        Usage:
            with db_service.transaction():
                db_service.execute_query(query1, params1)
                db_service.execute_query(query2, params2)
                # 자동 commit 또는 rollback
        """
        connection = self._get_connection()

        # 수동 트랜잭션 시작
        connection.execute("BEGIN")

        try:
            yield connection
            connection.commit()
            logger.debug("DCR 트랜잭션 커밋됨")
        except Exception as e:
            connection.rollback()
            logger.error(f"DCR 트랜잭션 롤백됨: {str(e)}")
            raise

    def close(self):
        """데이터베이스 연결 종료"""
        if self._connection:
            try:
                # WAL 체크포인트 실행
                self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except:
                pass  # 체크포인트 실패 무시

            self._connection.close()
            self._connection = None
            logger.debug("DCR 데이터베이스 연결 종료됨")

    def delete_database(self, performed_by: str = "SYSTEM", reason: Optional[str] = None) -> bool:
        """
        DCR 데이터베이스 파일 삭제

        Args:
            performed_by: 삭제 수행자
            reason: 삭제 이유

        Returns:
            삭제 성공 여부
        """
        db_path = Path(self.db_path)

        # 연결 종료
        self.close()

        if db_path.exists():
            try:
                # 파일 크기 기록
                file_size = db_path.stat().st_size

                # logs.db에 삭제 시작 로깅
                self.logs_db.log_dcr_database_operation(
                    operation="DELETE",
                    database_path=str(self.db_path),
                    file_size=file_size,
                    performed_by=performed_by,
                    details={"reason": reason or "Manual deletion"}
                )

                # WAL 및 SHM 파일도 함께 삭제
                for suffix in ['', '-wal', '-shm']:
                    file_path = Path(str(db_path) + suffix)
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"삭제됨: {file_path}")

                # logs.db에 삭제 완료 로깅
                self.logs_db.log_dcr_database_operation(
                    operation="DELETE_COMPLETE",
                    database_path=str(self.db_path),
                    file_size=file_size,
                    performed_by=performed_by,
                    details={"deleted_size": file_size}
                )

                logger.info(f"DCR 데이터베이스 삭제 완료: {self.db_path}")
                return True

            except Exception as e:
                error_msg = str(e)
                logger.error(f"DCR 데이터베이스 삭제 실패: {error_msg}")

                # logs.db에 삭제 실패 로깅
                self.logs_db.log_dcr_database_operation(
                    operation="DELETE_FAILED",
                    database_path=str(self.db_path),
                    performed_by=performed_by,
                    details={"reason": reason or "Manual deletion"},
                    success=False,
                    error_message=error_msg
                )
                return False
        else:
            logger.warning(f"삭제할 DCR 데이터베이스가 없음: {self.db_path}")
            return False


# 하위 호환성을 위한 래퍼 함수들
# 기존 db_utils.py의 함수 시그니처와 동일하게 제공

_service_instance: Optional[DCRDatabaseService] = None


def _get_service() -> DCRDatabaseService:
    """싱글톤 서비스 인스턴스 반환"""
    global _service_instance
    if _service_instance is None:
        _service_instance = DCRDatabaseService()
    return _service_instance


def execute_query(db_path: str, query: str, params: Tuple[Any, ...] = ()) -> int:
    """
    기존 db_utils.execute_query와 호환되는 래퍼

    Note: db_path는 무시됨 (설정에서 자동으로 가져옴)
    """
    service = _get_service()
    return service.execute_query(query, params)


def fetch_one(db_path: str, query: str, params: Tuple[Any, ...] = ()) -> Optional[Tuple[Any, ...]]:
    """
    기존 db_utils.fetch_one과 호환되는 래퍼

    Note: db_path는 무시됨 (설정에서 자동으로 가져옴)
    """
    service = _get_service()
    result = service.fetch_one(query, params)
    # Row 객체를 튜플로 변환 (하위 호환성)
    return tuple(result) if result else None


def fetch_all(db_path: str, query: str, params: Tuple[Any, ...] = ()) -> List[Tuple[Any, ...]]:
    """
    기존 db_utils.fetch_all과 호환되는 래퍼

    Note: db_path는 무시됨 (설정에서 자동으로 가져옴)
    """
    service = _get_service()
    results = service.fetch_all(query, params)
    # Row 객체들을 튜플로 변환 (하위 호환성)
    return [tuple(row) for row in results]