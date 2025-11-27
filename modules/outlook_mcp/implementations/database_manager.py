"""Mail Query MCP 모듈 전용 DatabaseManager"""

import sqlite3
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional, Any, Dict, List
from infra.core.logger import get_logger
from infra.core.config import get_config
from infra.core.database import DatabaseManager as BaseDatabaseManager

logger = get_logger(__name__)


class MailQueryDatabaseManager(BaseDatabaseManager):
    """Mail Query 모듈 전용 DatabaseManager"""

    def __init__(self):
        """Mail Query 데이터베이스 매니저 초기화"""
        super().__init__()
        # config의 mail_query_database_path를 사용하도록 오버라이드

    def _get_connection(self) -> sqlite3.Connection:
        """데이터베이스 연결을 반환 (mail_query 전용 경로 사용)"""
        # DB 파일이 삭제된 경우를 감지하여 재초기화
        if self._connection is not None:
            db_path = Path(self.config.mail_query_database_path)
            if not db_path.exists():
                logger.warning(f"데이터베이스 파일이 삭제되었습니다. 재초기화합니다: {db_path}")
                self._connection.close()
                self._connection = None
                self._initialized = False

        if self._connection is None:
            with self._lock:
                if self._connection is None:
                    self._connect()
                    if not self._initialized:
                        # 부모 클래스의 _initialize_schema 메서드 호출
                        self._initialize_schema()
                        self._initialized = True
        return self._connection

    def _connect(self) -> None:
        """Mail Query 데이터베이스에 연결"""
        try:
            # mail_query_database_path 사용
            db_path = self.config.mail_query_database_path
            logger.info(f"Mail Query 데이터베이스 연결 시도: {db_path}")

            # 데이터베이스 파일 경로 확인
            db_file = Path(db_path)
            if not db_file.parent.exists():
                db_file.parent.mkdir(parents=True, exist_ok=True)
                logger.info(f"데이터베이스 디렉터리 생성: {db_file.parent}")

            self._connection = sqlite3.connect(
                db_path,
                check_same_thread=False,
                isolation_level=None  # 자동 커밋 모드
            )
            self._connection.row_factory = sqlite3.Row

            # WAL 모드 설정
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")

            logger.info(f"Mail Query 데이터베이스 연결 성공: {db_path}")

        except sqlite3.Error as e:
            logger.error(f"Mail Query 데이터베이스 연결 실패: {e}")
            raise


@lru_cache(maxsize=1)
def get_mail_query_database() -> MailQueryDatabaseManager:
    """
    Mail Query 데이터베이스 매니저 인스턴스를 반환하는 레이지 싱글톤 함수

    Returns:
        MailQueryDatabaseManager: Mail Query 데이터베이스 매니저 인스턴스
    """
    return MailQueryDatabaseManager()