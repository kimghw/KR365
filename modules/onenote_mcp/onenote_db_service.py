"""
OneNote MCP Database Service
섹션과 페이지를 하나의 통합 테이블로 관리
"""

from ..base_db_service import BaseDBService
from typing import Any, Dict, List, Optional
from infra.core.logger import get_logger
import sqlite3

logger = get_logger(__name__)


class OneNoteDBService(BaseDBService):
    """OneNote 데이터베이스 서비스 (통합 테이블)"""

    def __init__(self):
        """Initialize OneNote DB Service"""
        # Use 'onenote' as server name
        # BaseDBService will automatically use DATABASE_ONENOTE_PATH env var
        # or default to data/onenote.db
        super().__init__(server_name='onenote')

        # Self reference for backward compatibility
        self.db = self

        # Ensure OneNote-specific tables exist
        self._ensure_onenote_tables()

    def _ensure_onenote_tables(self):
        """Create OneNote-specific tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create onenote_items table (sections and pages)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS onenote_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    item_type TEXT NOT NULL CHECK(item_type IN ('section', 'page')),
                    item_id TEXT NOT NULL UNIQUE,
                    item_name TEXT NOT NULL,
                    parent_id TEXT,
                    parent_name TEXT,
                    last_accessed DATETIME,
                    created_at DATETIME DEFAULT (datetime('now')),
                    updated_at DATETIME DEFAULT (datetime('now')),
                    UNIQUE(user_id, item_type, item_name)
                )
            """)

            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_user_type
                ON onenote_items(user_id, item_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_parent
                ON onenote_items(parent_id, item_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_last_accessed
                ON onenote_items(user_id, item_type, last_accessed DESC)
            """)

            conn.commit()
            logger.info("✅ OneNote-specific tables verified/created")

    def save_item(
        self,
        user_id: str,
        item_type: str,
        item_id: str,
        item_name: str,
        parent_id: str = None,
        parent_name: str = None,
        update_accessed: bool = False
    ) -> bool:
        """
        아이템 저장 (섹션 또는 페이지)

        Args:
            user_id: 사용자 ID
            item_type: 'section' 또는 'page'
            item_id: 아이템 ID (section_id 또는 page_id)
            item_name: 아이템 이름 (section_name 또는 page_title)
            parent_id: 부모 ID (섹션: notebook_id, 페이지: section_id)
            parent_name: 부모 이름 (섹션: notebook_name, 페이지: None)
            update_accessed: True면 last_accessed 업데이트

        Returns:
            성공 여부
        """
        try:
            if item_type not in ('section', 'page'):
                raise ValueError(f"Invalid item_type: {item_type}")

            # last_accessed 값 결정
            last_accessed_initial = "datetime('now')" if update_accessed else "NULL"
            last_accessed_update = "datetime('now')" if update_accessed else "last_accessed"

            self.execute_query(f"""
                INSERT INTO onenote_items (user_id, item_type, item_id, item_name, parent_id, parent_name, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?, {last_accessed_initial})
                ON CONFLICT(item_id) DO UPDATE SET
                    item_name = excluded.item_name,
                    parent_id = COALESCE(excluded.parent_id, parent_id),
                    parent_name = COALESCE(excluded.parent_name, parent_name),
                    last_accessed = {last_accessed_update},
                    updated_at = datetime('now')
            """, (user_id, item_type, item_id, item_name, parent_id, parent_name))

            logger.info(f"✅ Saved {item_type}: {item_name} (ID: {item_id})")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to save item: {str(e)}")
            return False

    def get_items(
        self,
        user_id: str,
        item_type: str,
        parent_id: str = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        아이템 목록 조회

        Args:
            user_id: 사용자 ID
            item_type: 'section' 또는 'page'
            parent_id: 부모 ID (선택사항)
            limit: 최대 개수

        Returns:
            아이템 목록
        """
        try:
            if parent_id:
                query = """
                    SELECT item_id, item_name, parent_id, parent_name, last_accessed
                    FROM onenote_items
                    WHERE user_id = ? AND item_type = ? AND parent_id = ?
                    ORDER BY last_accessed DESC NULLS LAST, item_name
                    LIMIT ?
                """
                params = (user_id, item_type, parent_id, limit)
            else:
                query = """
                    SELECT item_id, item_name, parent_id, parent_name, last_accessed
                    FROM onenote_items
                    WHERE user_id = ? AND item_type = ?
                    ORDER BY last_accessed DESC NULLS LAST, item_name
                    LIMIT ?
                """
                params = (user_id, item_type, limit)

            results = self.fetch_all(query, params)
            return results if results else []

        except Exception as e:
            logger.error(f"❌ Failed to get items: {str(e)}")
            return []

    def search_items(
        self,
        user_id: str,
        search_term: str,
        item_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        아이템 검색

        Args:
            user_id: 사용자 ID
            search_term: 검색어
            item_type: 'section' 또는 'page' (선택사항)
            limit: 최대 개수

        Returns:
            검색 결과
        """
        try:
            if item_type:
                query = """
                    SELECT item_type, item_id, item_name, parent_id, parent_name, last_accessed
                    FROM onenote_items
                    WHERE user_id = ? AND item_type = ? AND item_name LIKE ?
                    ORDER BY last_accessed DESC NULLS LAST, item_name
                    LIMIT ?
                """
                params = (user_id, item_type, f'%{search_term}%', limit)
            else:
                query = """
                    SELECT item_type, item_id, item_name, parent_id, parent_name, last_accessed
                    FROM onenote_items
                    WHERE user_id = ? AND item_name LIKE ?
                    ORDER BY last_accessed DESC NULLS LAST, item_name
                    LIMIT ?
                """
                params = (user_id, f'%{search_term}%', limit)

            results = self.fetch_all(query, params)
            return results if results else []

        except Exception as e:
            logger.error(f"❌ Failed to search items: {str(e)}")
            return []

    def update_last_accessed(self, item_id: str) -> bool:
        """
        마지막 접근 시간 업데이트

        Args:
            item_id: 아이템 ID

        Returns:
            성공 여부
        """
        try:
            self.execute_query(
                """UPDATE onenote_items
                SET last_accessed = datetime('now'), updated_at = datetime('now')
                WHERE item_id = ?""",
                (item_id,)
            )
            logger.info(f"✅ Updated last_accessed for: {item_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to update last_accessed: {str(e)}")
            return False

    # Backward compatibility methods
    def initialize_tables(self):
        """Legacy method for compatibility"""
        self._ensure_onenote_tables()
        return True