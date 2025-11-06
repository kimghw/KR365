"""
OneNote MCP Database Service
섹션 ID, 페이지 ID 관리를 위한 SQLite 테이블 초기화 및 관리
"""

from infra.core.database import get_database_manager
from infra.core.logger import get_logger

logger = get_logger(__name__)


class OneNoteDBService:
    """OneNote 데이터베이스 서비스"""

    def __init__(self):
        self.db = get_database_manager()
        logger.info("✅ OneNoteDBService initialized")

    def initialize_tables(self):
        """
        OneNote 관련 테이블 초기화
        - onenote_sections: 섹션 ID 관리
        - onenote_pages: 페이지 ID 관리
        """
        try:
            # 섹션 테이블 생성
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS onenote_sections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    notebook_id TEXT NOT NULL,
                    notebook_name TEXT,
                    section_id TEXT NOT NULL UNIQUE,
                    section_name TEXT NOT NULL,
                    recent_used INTEGER DEFAULT 0,
                    last_accessed DATETIME,
                    created_at DATETIME DEFAULT (datetime('now')),
                    updated_at DATETIME DEFAULT (datetime('now')),
                    UNIQUE(user_id, notebook_id, section_name)
                )
            """)
            logger.info("✅ onenote_sections 테이블 확인/생성 완료")

            # 페이지 테이블 생성
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS onenote_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    page_id TEXT NOT NULL UNIQUE,
                    page_title TEXT,
                    recent_used INTEGER DEFAULT 0,
                    last_accessed DATETIME,
                    created_at DATETIME DEFAULT (datetime('now')),
                    updated_at DATETIME DEFAULT (datetime('now')),
                    UNIQUE(user_id, section_id, page_title)
                )
            """)
            logger.info("✅ onenote_pages 테이블 확인/생성 완료")

            # 기존 테이블에 컬럼 추가 (없는 경우에만)
            try:
                self.db.execute_query("""
                    ALTER TABLE onenote_sections ADD COLUMN recent_used INTEGER DEFAULT 0
                """)
            except:
                pass  # 컬럼이 이미 존재하면 무시

            try:
                self.db.execute_query("""
                    ALTER TABLE onenote_pages ADD COLUMN recent_used INTEGER DEFAULT 0
                """)
            except:
                pass  # 컬럼이 이미 존재하면 무시

            try:
                self.db.execute_query("""
                    ALTER TABLE onenote_sections ADD COLUMN notebook_name TEXT
                """)
            except:
                pass  # 컬럼이 이미 존재하면 무시

            try:
                self.db.execute_query("""
                    ALTER TABLE onenote_sections ADD COLUMN last_accessed DATETIME
                """)
            except:
                pass  # 컬럼이 이미 존재하면 무시

            try:
                self.db.execute_query("""
                    ALTER TABLE onenote_pages ADD COLUMN last_accessed DATETIME
                """)
            except:
                pass  # 컬럼이 이미 존재하면 무시

            # 인덱스 생성
            self.db.execute_query("""
                CREATE INDEX IF NOT EXISTS idx_sections_user_id
                ON onenote_sections(user_id)
            """)
            self.db.execute_query("""
                CREATE INDEX IF NOT EXISTS idx_pages_section_id
                ON onenote_pages(section_id)
            """)
            self.db.execute_query("""
                CREATE INDEX IF NOT EXISTS idx_sections_last_accessed
                ON onenote_sections(user_id, last_accessed DESC)
            """)
            self.db.execute_query("""
                CREATE INDEX IF NOT EXISTS idx_pages_last_accessed
                ON onenote_pages(user_id, last_accessed DESC)
            """)
            logger.info("✅ 인덱스 생성 완료")

            return True

        except Exception as e:
            logger.error(f"❌ 테이블 초기화 실패: {str(e)}")
            return False

    # ========================================================================
    # 섹션 관리
    # ========================================================================

    def save_section(self, user_id: str, notebook_id: str, section_id: str, section_name: str, notebook_name: str = None, mark_as_recent: bool = False, update_accessed: bool = False) -> bool:
        """
        섹션 ID 저장 (중복 시 업데이트)

        Args:
            user_id: 사용자 ID
            notebook_id: 노트북 ID
            section_id: 섹션 ID
            section_name: 섹션 이름
            notebook_name: 노트북 이름 (선택)
            mark_as_recent: True면 recent_used 마킹 (deprecated, use update_accessed)
            update_accessed: True면 last_accessed 업데이트

        Returns:
            성공 여부
        """
        try:
            # 다른 섹션의 recent_used를 0으로 초기화 (mark_as_recent=True인 경우)
            if mark_as_recent:
                self.db.execute_query("""
                    UPDATE onenote_sections SET recent_used = 0 WHERE user_id = ?
                """, (user_id,))

            # last_accessed 업데이트 여부 결정
            last_accessed_value = "datetime('now')" if (update_accessed or mark_as_recent) else "last_accessed"

            self.db.execute_query(f"""
                INSERT INTO onenote_sections (user_id, notebook_id, notebook_name, section_id, section_name, recent_used, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(section_id) DO UPDATE SET
                    section_name = excluded.section_name,
                    notebook_name = COALESCE(excluded.notebook_name, notebook_name),
                    recent_used = excluded.recent_used,
                    last_accessed = {last_accessed_value},
                    updated_at = datetime('now')
            """, (user_id, notebook_id, notebook_name, section_id, section_name, 1 if mark_as_recent else 0))

            logger.info(f"✅ 섹션 저장 완료: {section_name} ({section_id}){' [최근 조회]' if update_accessed else ''}{' [최근 사용]' if mark_as_recent else ''}")
            return True

        except Exception as e:
            logger.error(f"❌ 섹션 저장 실패: {str(e)}")
            return False

    def get_section(self, user_id: str, section_name: str) -> dict:
        """
        섹션 ID 조회 (사용자 ID + 섹션 이름으로)

        Args:
            user_id: 사용자 ID
            section_name: 섹션 이름

        Returns:
            섹션 정보 dict 또는 None
        """
        try:
            result = self.db.fetch_one("""
                SELECT * FROM onenote_sections
                WHERE user_id = ? AND section_name = ?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (user_id, section_name))

            if result:
                return dict(result)
            return None

        except Exception as e:
            logger.error(f"❌ 섹션 조회 실패: {str(e)}")
            return None

    def list_sections(self, user_id: str) -> list:
        """
        사용자의 모든 섹션 목록 조회

        Args:
            user_id: 사용자 ID

        Returns:
            섹션 목록 (list of dict)
        """
        try:
            results = self.db.fetch_all("""
                SELECT * FROM onenote_sections
                WHERE user_id = ?
                ORDER BY updated_at DESC
            """, (user_id,))

            return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"❌ 섹션 목록 조회 실패: {str(e)}")
            return []

    # ========================================================================
    # 페이지 관리
    # ========================================================================

    def save_page(self, user_id: str, section_id: str, page_id: str, page_title: str, mark_as_recent: bool = False, update_accessed: bool = False) -> bool:
        """
        페이지 ID 저장 (중복 시 업데이트)

        Args:
            user_id: 사용자 ID
            section_id: 섹션 ID
            page_id: 페이지 ID
            page_title: 페이지 제목
            mark_as_recent: True면 recent_used 마킹 (deprecated, use update_accessed)
            update_accessed: True면 last_accessed 업데이트

        Returns:
            성공 여부
        """
        try:
            # 다른 페이지의 recent_used를 0으로 초기화 (mark_as_recent=True인 경우)
            if mark_as_recent:
                self.db.execute_query("""
                    UPDATE onenote_pages SET recent_used = 0 WHERE user_id = ?
                """, (user_id,))

            # last_accessed 업데이트 여부 결정
            last_accessed_value = "datetime('now')" if (update_accessed or mark_as_recent) else "last_accessed"

            self.db.execute_query(f"""
                INSERT INTO onenote_pages (user_id, section_id, page_id, page_title, recent_used, last_accessed)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(page_id) DO UPDATE SET
                    page_title = excluded.page_title,
                    recent_used = excluded.recent_used,
                    last_accessed = {last_accessed_value},
                    updated_at = datetime('now')
            """, (user_id, section_id, page_id, page_title, 1 if mark_as_recent else 0))

            logger.info(f"✅ 페이지 저장 완료: {page_title} ({page_id}){' [최근 조회]' if update_accessed else ''}{' [최근 사용]' if mark_as_recent else ''}")
            return True

        except Exception as e:
            logger.error(f"❌ 페이지 저장 실패: {str(e)}")
            return False

    def get_page(self, user_id: str, page_title: str) -> dict:
        """
        페이지 ID 조회 (사용자 ID + 페이지 제목으로)

        Args:
            user_id: 사용자 ID
            page_title: 페이지 제목

        Returns:
            페이지 정보 dict 또는 None
        """
        try:
            result = self.db.fetch_one("""
                SELECT * FROM onenote_pages
                WHERE user_id = ? AND page_title = ?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (user_id, page_title))

            if result:
                return dict(result)
            return None

        except Exception as e:
            logger.error(f"❌ 페이지 조회 실패: {str(e)}")
            return None

    def list_pages(self, user_id: str, section_id: str = None) -> list:
        """
        페이지 목록 조회

        Args:
            user_id: 사용자 ID
            section_id: 섹션 ID (선택)

        Returns:
            페이지 목록 (list of dict)
        """
        try:
            if section_id:
                results = self.db.fetch_all("""
                    SELECT * FROM onenote_pages
                    WHERE user_id = ? AND section_id = ?
                    ORDER BY updated_at DESC
                """, (user_id, section_id))
            else:
                results = self.db.fetch_all("""
                    SELECT * FROM onenote_pages
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                """, (user_id,))

            return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"❌ 페이지 목록 조회 실패: {str(e)}")
            return []

    # ========================================================================
    # 최근 사용 항목 조회
    # ========================================================================

    def get_recent_section(self, user_id: str, limit: int = 1) -> dict:
        """
        최근 조회한 섹션 조회 (last_accessed 기준)

        Args:
            user_id: 사용자 ID
            limit: 조회할 개수 (기본 1)

        Returns:
            섹션 정보 dict 또는 None (limit=1인 경우)
            섹션 정보 list (limit>1인 경우)
        """
        try:
            if limit == 1:
                result = self.db.fetch_one("""
                    SELECT * FROM onenote_sections
                    WHERE user_id = ? AND last_accessed IS NOT NULL
                    ORDER BY last_accessed DESC
                    LIMIT 1
                """, (user_id,))
                return dict(result) if result else None
            else:
                results = self.db.fetch_all("""
                    SELECT * FROM onenote_sections
                    WHERE user_id = ? AND last_accessed IS NOT NULL
                    ORDER BY last_accessed DESC
                    LIMIT ?
                """, (user_id, limit))
                return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"❌ 최근 섹션 조회 실패: {str(e)}")
            return None if limit == 1 else []

    def get_recent_page(self, user_id: str, limit: int = 1) -> dict:
        """
        최근 조회한 페이지 조회 (last_accessed 기준)

        Args:
            user_id: 사용자 ID
            limit: 조회할 개수 (기본 1)

        Returns:
            페이지 정보 dict 또는 None (limit=1인 경우)
            페이지 정보 list (limit>1인 경우)
        """
        try:
            if limit == 1:
                result = self.db.fetch_one("""
                    SELECT * FROM onenote_pages
                    WHERE user_id = ? AND last_accessed IS NOT NULL
                    ORDER BY last_accessed DESC
                    LIMIT 1
                """, (user_id,))
                return dict(result) if result else None
            else:
                results = self.db.fetch_all("""
                    SELECT * FROM onenote_pages
                    WHERE user_id = ? AND last_accessed IS NOT NULL
                    ORDER BY last_accessed DESC
                    LIMIT ?
                """, (user_id, limit))
                return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"❌ 최근 페이지 조회 실패: {str(e)}")
            return None if limit == 1 else []

    # ========================================================================
    # 삭제 관리
    # ========================================================================

    def delete_section(self, user_id: str, section_id: str) -> bool:
        """
        섹션 삭제

        Args:
            user_id: 사용자 ID
            section_id: 섹션 ID

        Returns:
            성공 여부
        """
        try:
            self.db.execute_query("""
                DELETE FROM onenote_sections
                WHERE user_id = ? AND section_id = ?
            """, (user_id, section_id))

            logger.info(f"✅ 섹션 삭제 완료: {section_id}")
            return True

        except Exception as e:
            logger.error(f"❌ 섹션 삭제 실패: {str(e)}")
            return False

    def delete_page(self, user_id: str, page_id: str) -> bool:
        """
        페이지 삭제

        Args:
            user_id: 사용자 ID
            page_id: 페이지 ID

        Returns:
            성공 여부
        """
        try:
            self.db.execute_query("""
                DELETE FROM onenote_pages
                WHERE user_id = ? AND page_id = ?
            """, (user_id, page_id))

            logger.info(f"✅ 페이지 삭제 완료: {page_id}")
            return True

        except Exception as e:
            logger.error(f"❌ 페이지 삭제 실패: {str(e)}")
            return False
