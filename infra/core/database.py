"""
IACSGraph 프로젝트의 SQLite 데이터베이스 관리 시스템

SQLite 데이터베이스 연결을 관리하고 스키마 초기화를 담당합니다.
레이지 싱글톤 패턴으로 구현되어 전역에서 동일한 연결 풀을 사용합니다.
"""

import sqlite3
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .config import get_config
from .exceptions import ConnectionError, DatabaseError
from .logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """SQLite 데이터베이스 연결과 쿼리를 관리하는 클래스"""

    def __init__(self):
        """데이터베이스 매니저 초기화"""
        self.config = get_config()
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        """데이터베이스 연결을 반환 (레이지 초기화)"""
        # DB 파일이 삭제된 경우를 감지하여 재초기화
        if self._connection is not None:
            # 기존 연결이 있더라도 DB 파일이 없으면 재생성
            db_path = Path(self.config.database_path)
            if not db_path.exists():
                logger.warning(f"데이터베이스 파일이 삭제됨. 재생성 시작: {db_path}")
                # 기존 연결 종료
                try:
                    self._connection.close()
                except:
                    pass
                self._connection = None
                self._initialized = False  # 스키마 재초기화 필요

        if self._connection is None:
            with self._lock:
                if self._connection is None:
                    try:
                        # DB 디렉토리 생성 (없는 경우)
                        db_path = Path(self.config.database_path)
                        db_path.parent.mkdir(parents=True, exist_ok=True)

                        # SQLite 연결 생성
                        self._connection = sqlite3.connect(
                            self.config.database_path,
                            check_same_thread=False,  # 멀티스레드 환경 지원
                            timeout=30.0,  # 30초 타임아웃
                            isolation_level=None,  # 오토커밋 모드
                        )

                        # Row factory 설정 (딕셔너리 형태로 결과 반환)
                        self._connection.row_factory = sqlite3.Row

                        # 외래키 제약조건 활성화
                        self._connection.execute("PRAGMA foreign_keys = ON")

                        # WAL 모드 활성화 (동시성 향상)
                        self._connection.execute("PRAGMA journal_mode = WAL")

                        logger.info(
                            f"데이터베이스 연결 성공: {self.config.database_path}"
                        )

                        # 스키마 초기화
                        self._initialize_schema()

                        # WAL 체크포인트 실행 (메인 DB 파일 생성 보장)
                        self.checkpoint()

                    except sqlite3.Error as e:
                        raise ConnectionError(
                            f"데이터베이스 연결 실패: {str(e)}",
                            details={"database_path": self.config.database_path},
                        ) from e

        return self._connection

    def _initialize_schema(self) -> None:
        """데이터베이스 스키마를 초기화"""
        # DB 파일이 새로 생성된 경우 무조건 스키마 초기화
        # (self._initialized가 False이거나 accounts 테이블이 없는 경우)
        try:
            # 테이블 존재 여부 확인
            cursor = self._connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'"
            )

            if not cursor.fetchone():
                logger.info("데이터베이스 스키마 초기화 시작")
                self._execute_schema_script()
                self._initialized = True
                logger.info("데이터베이스 스키마 초기화 완료")
            else:
                self._initialized = True
                logger.debug("기존 데이터베이스 스키마 확인됨")

            # 추가 마이그레이션 실행 (teams_chats 테이블 등)
            self._run_migrations()

        except sqlite3.Error as e:
            raise DatabaseError(
                f"스키마 초기화 실패: {str(e)}", operation="initialize_schema"
            ) from e

    def _execute_schema_script(self) -> None:
        """초기 스키마 SQL 스크립트를 실행"""
        schema_path = Path(__file__).parent.parent / "migrations" / "initial_schema.sql"

        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_sql = f.read()

            # 스크립트를 세미콜론으로 분리하여 각각 실행
            statements = [
                stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()
            ]

            for statement in statements:
                self._connection.execute(statement)

            self._connection.commit()
            logger.info(f"스키마 스크립트 실행 완료: {len(statements)}개 구문")

        except FileNotFoundError:
            raise DatabaseError(
                f"스키마 파일을 찾을 수 없습니다: {schema_path}",
                operation="load_schema_file",
            )
        except sqlite3.Error as e:
            raise DatabaseError(
                f"스키마 실행 실패: {str(e)}", operation="execute_schema"
            ) from e

    def _run_migrations(self) -> None:
        """추가 마이그레이션 스크립트를 실행 (멱등성 보장)"""
        migrations_dir = Path(__file__).parent.parent / "migrations"

        # 실행할 마이그레이션 파일 목록 (initial_schema.sql 제외)
        migration_files = [
            "mail_query_schema.sql",
            "teams_schema.sql",
            "teams_add_topic_kr.sql",
            # 향후 추가 마이그레이션 파일을 여기에 추가
        ]

        for migration_file in migration_files:
            migration_path = migrations_dir / migration_file

            # 파일이 없으면 건너뛰기
            if not migration_path.exists():
                logger.debug(f"마이그레이션 파일 없음 (건너뛰기): {migration_file}")
                continue

            try:
                with open(migration_path, "r", encoding="utf-8") as f:
                    migration_sql = f.read()

                # 스크립트를 세미콜론으로 분리하여 각각 실행
                statements = [
                    stmt.strip() for stmt in migration_sql.split(";") if stmt.strip()
                ]

                for statement in statements:
                    stmt = statement.strip()
                    # ALTER TABLE로 컬럼 추가 시 이미 존재하면 건너뛰기 (SQLite는 IF NOT EXISTS 미지원)
                    if stmt.upper().startswith("ALTER TABLE TEAMS_CHATS ADD COLUMN TOPIC_KR"):
                        # 컬럼 존재 여부 확인
                        cols = [c["name"].lower() for c in self.get_table_info("teams_chats")]
                        if "topic_kr" in cols:
                            logger.info("마이그레이션 건너뜀: teams_chats.topic_kr 이미 존재")
                            continue
                    # CREATE TABLE/INDEX IF NOT EXISTS는 멱등성
                    self._connection.execute(stmt)

                self._connection.commit()
                logger.info(f"✅ 마이그레이션 완료: {migration_file} ({len(statements)}개 구문)")

            except sqlite3.Error as e:
                logger.error(f"❌ 마이그레이션 실패: {migration_file} - {str(e)}")
                # 마이그레이션 실패는 로그만 남기고 계속 진행 (IF NOT EXISTS로 멱등성 보장)

    @contextmanager
    def get_cursor(self):
        """커서를 안전하게 사용하기 위한 컨텍스트 매니저"""
        connection = self._get_connection()
        cursor = connection.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def execute_query(
        self,
        query: str,
        params: Union[tuple, dict, None] = None,
        fetch_result: bool = False,
    ) -> Optional[List[sqlite3.Row]]:
        """
        SQL 쿼리를 실행합니다.

        Args:
            query: 실행할 SQL 쿼리
            params: 쿼리 매개변수
            fetch_result: 결과를 반환할지 여부

        Returns:
            SELECT 쿼리의 경우 결과 행들, 그 외는 None
        """
        try:
            with self.get_cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                if fetch_result:
                    return cursor.fetchall()

                # INSERT, UPDATE, DELETE의 경우 변경된 행 수 로깅
                if cursor.rowcount > 0:
                    logger.debug(f"쿼리 실행 완료: {cursor.rowcount}행 영향받음")

                return None

        except sqlite3.Error as e:
            logger.error(f"쿼리 실행 실패: {query[:100]}...")
            raise DatabaseError(
                f"쿼리 실행 실패: {str(e)}",
                operation="execute_query",
                details={"query": query[:200], "params": str(params)[:200]},
            ) from e

    def execute_many(self, query: str, params_list: List[Union[tuple, dict]]) -> int:
        """
        동일한 쿼리를 여러 매개변수로 실행합니다.

        Args:
            query: 실행할 SQL 쿼리
            params_list: 매개변수 리스트

        Returns:
            전체 영향받은 행 수
        """
        try:
            with self.get_cursor() as cursor:
                cursor.executemany(query, params_list)
                total_rows = cursor.rowcount
                logger.debug(
                    f"배치 쿼리 실행 완료: {len(params_list)}개 배치, {total_rows}행 영향받음"
                )
                return total_rows

        except sqlite3.Error as e:
            logger.error(f"배치 쿼리 실행 실패: {query[:100]}...")
            raise DatabaseError(
                f"배치 쿼리 실행 실패: {str(e)}",
                operation="execute_many",
                details={"query": query[:200], "batch_size": len(params_list)},
            ) from e

    def fetch_one(
        self, query: str, params: Union[tuple, dict, None] = None
    ) -> Optional[sqlite3.Row]:
        """
        단일 행을 조회합니다.

        Args:
            query: SELECT 쿼리
            params: 쿼리 매개변수

        Returns:
            조회된 행 또는 None
        """
        try:
            with self.get_cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                return cursor.fetchone()

        except sqlite3.Error as e:
            raise DatabaseError(
                f"단일 행 조회 실패: {str(e)}",
                operation="fetch_one",
                details={"query": query[:200]},
            ) from e

    def fetch_all(
        self, query: str, params: Union[tuple, dict, None] = None
    ) -> List[sqlite3.Row]:
        """
        모든 행을 조회합니다.

        Args:
            query: SELECT 쿼리
            params: 쿼리 매개변수

        Returns:
            조회된 행들의 리스트
        """
        try:
            with self.get_cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                return cursor.fetchall()

        except sqlite3.Error as e:
            raise DatabaseError(
                f"전체 행 조회 실패: {str(e)}",
                operation="fetch_all",
                details={"query": query[:200]},
            ) from e

    def insert(self, table: str, data: Dict[str, Any]) -> int:
        """
        테이블에 데이터를 삽입합니다.

        Args:
            table: 테이블명
            data: 삽입할 데이터 딕셔너리

        Returns:
            삽입된 행의 ID
        """
        columns = list(data.keys())
        placeholders = ", ".join(["?" for _ in columns])
        values = list(data.values())

        query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"

        try:
            with self.get_cursor() as cursor:
                cursor.execute(query, values)
                return cursor.lastrowid

        except sqlite3.Error as e:
            raise DatabaseError(
                f"데이터 삽입 실패: {str(e)}",
                operation="insert",
                table=table,
                details={"data": str(data)[:200]},
            ) from e

    def update(
        self,
        table: str,
        data: Dict[str, Any],
        where_clause: str,
        where_params: Union[tuple, dict, None] = None,
    ) -> int:
        """
        테이블의 데이터를 업데이트합니다.

        Args:
            table: 테이블명
            data: 업데이트할 데이터 딕셔너리
            where_clause: WHERE 조건절
            where_params: WHERE 절 매개변수

        Returns:
            업데이트된 행 수
        """
        set_clause = ", ".join([f"{col} = ?" for col in data.keys()])
        values = list(data.values())

        query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"

        if where_params:
            if isinstance(where_params, dict):
                # Named parameters
                params = data.copy()
                params.update(where_params)
                query = f"UPDATE {table} SET {', '.join([f'{col} = :{col}' for col in data.keys()])} WHERE {where_clause}"
            else:
                # Positional parameters
                values.extend(where_params)
                params = values
        else:
            params = values

        try:
            with self.get_cursor() as cursor:
                cursor.execute(query, params)
                return cursor.rowcount

        except sqlite3.Error as e:
            raise DatabaseError(
                f"데이터 업데이트 실패: {str(e)}",
                operation="update",
                table=table,
                details={"where_clause": where_clause},
            ) from e

    def delete(
        self,
        table: str,
        where_clause: str,
        where_params: Union[tuple, dict, None] = None,
    ) -> int:
        """
        테이블에서 데이터를 삭제합니다.

        Args:
            table: 테이블명
            where_clause: WHERE 조건절
            where_params: WHERE 절 매개변수

        Returns:
            삭제된 행 수
        """
        query = f"DELETE FROM {table} WHERE {where_clause}"

        try:
            with self.get_cursor() as cursor:
                if where_params:
                    cursor.execute(query, where_params)
                else:
                    cursor.execute(query)
                return cursor.rowcount

        except sqlite3.Error as e:
            raise DatabaseError(
                f"데이터 삭제 실패: {str(e)}",
                operation="delete",
                table=table,
                details={"where_clause": where_clause},
            ) from e

    def checkpoint(self) -> None:
        """WAL 모드에서 체크포인트를 실행하여 변경사항을 메인 DB 파일에 반영"""
        try:
            connection = self._get_connection()
            # TRUNCATE 모드로 체크포인트 실행 (WAL 파일 초기화)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.debug("WAL 체크포인트 실행 완료")
        except sqlite3.Error as e:
            logger.warning(f"WAL 체크포인트 실행 중 오류 (무시됨): {str(e)}")

    def close(self) -> None:
        """데이터베이스 연결을 종료합니다."""
        if self._connection:
            with self._lock:
                if self._connection:
                    # 종료 전 체크포인트 실행
                    try:
                        self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    except:
                        pass  # 체크포인트 실패 무시
                    self._connection.close()
                    self._connection = None
                    logger.info("데이터베이스 연결 종료됨")

    def get_table_info(self, table_name: str) -> List[Dict[str, Any]]:
        """테이블 스키마 정보를 조회합니다."""
        query = f"PRAGMA table_info({table_name})"
        rows = self.fetch_all(query)
        return [dict(row) for row in rows]

    def table_exists(self, table_name: str) -> bool:
        """테이블 존재 여부를 확인합니다."""
        query = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
        result = self.fetch_one(query, (table_name,))
        return result is not None

    @contextmanager
    def transaction(self):
        """트랜잭션을 안전하게 처리하기 위한 컨텍스트 매니저"""
        connection = self._get_connection()

        # 수동 트랜잭션 시작
        connection.execute("BEGIN")

        try:
            yield connection
            connection.commit()
            logger.debug("트랜잭션 커밋됨")
        except Exception as e:
            connection.rollback()
            logger.error(f"트랜잭션 롤백됨: {str(e)}")
            raise

    def clear_table_data(self, table_name: str) -> dict:
        """
        테이블 데이터만 삭제 (스키마 유지)

        Args:
            table_name: 정리할 테이블명

        Returns:
            dict: 정리 결과 정보
        """
        try:
            # 테이블 존재 확인
            if not self.table_exists(table_name):
                return {
                    "success": False,
                    "error": f"테이블 {table_name}이 존재하지 않음",
                    "existing_count": 0,
                    "deleted_count": 0,
                }

            # 기존 데이터 개수 확인
            count_result = self.fetch_one(f"SELECT COUNT(*) as count FROM {table_name}")
            existing_count = count_result["count"] if count_result else 0

            if existing_count == 0:
                logger.info(f"테이블 {table_name}이 이미 비어있습니다.")
                return {
                    "success": True,
                    "existing_count": 0,
                    "deleted_count": 0,
                    "message": f"{table_name} 테이블이 이미 비어있음",
                }

            # 데이터 삭제 (스키마는 유지)
            deleted_count = self.delete(table_name, "1=1")  # 모든 데이터 삭제

            logger.info(
                f"테이블 {table_name} 데이터 삭제 완료: {existing_count}개 → 0개"
            )

            return {
                "success": True,
                "existing_count": existing_count,
                "deleted_count": deleted_count,
                "message": f"{table_name} 테이블에서 {deleted_count}개 레코드 삭제됨",
            }

        except Exception as e:
            logger.error(f"테이블 {table_name} 데이터 삭제 실패: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "existing_count": 0,
                "deleted_count": 0,
                "message": f"{table_name} 데이터 삭제 중 오류 발생",
            }

    def clear_multiple_tables_data(self, table_names: List[str]) -> dict:
        """
        여러 테이블의 데이터를 일괄 삭제 (스키마 유지)

        Args:
            table_names: 정리할 테이블명 리스트

        Returns:
            dict: 전체 정리 결과 정보
        """
        try:
            logger.info(f"다중 테이블 데이터 삭제 시작: {', '.join(table_names)}")

            results = []
            total_deleted = 0

            for table_name in table_names:
                result = self.clear_table_data(table_name)
                results.append({"table": table_name, **result})

                if result["success"]:
                    total_deleted += result["deleted_count"]

            success_count = sum(1 for r in results if r["success"])

            logger.info(
                f"다중 테이블 정리 완료: {success_count}/{len(table_names)}개 성공, 총 {total_deleted}개 레코드 삭제"
            )

            return {
                "success": success_count == len(table_names),
                "total_tables": len(table_names),
                "success_count": success_count,
                "total_deleted": total_deleted,
                "results": results,
                "message": f"{success_count}/{len(table_names)}개 테이블 정리 완료",
            }

        except Exception as e:
            logger.error(f"다중 테이블 정리 실패: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message": "다중 테이블 정리 중 오류 발생",
            }


@lru_cache(maxsize=1)
def get_database_manager() -> DatabaseManager:
    """
    데이터베이스 매니저 인스턴스를 반환하는 레이지 싱글톤 함수

    Returns:
        DatabaseManager: 데이터베이스 매니저 인스턴스
    """
    return DatabaseManager()


# 편의를 위한 전역 데이터베이스 매니저 인스턴스
db = get_database_manager()
