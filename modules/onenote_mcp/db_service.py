"""
OneNote MCP Database Service
섹션과 페이지를 하나의 통합 테이블로 관리
"""

from infra.core.database import get_database_manager
from infra.core.logger import get_logger

logger = get_logger(__name__)


class OneNoteDBService:
    """OneNote 데이터베이스 서비스 (통합 테이블)"""

    def __init__(self):
        self.db = get_database_manager()
        logger.info("✅ OneNoteDBService initialized")

    def initialize_tables(self):
        """
        OneNote 통합 테이블 초기화
        - onenote_items: 섹션과 페이지를 하나의 테이블로 통합 관리
        """
        try:
            # 통합 테이블 생성
            self.db.execute_query("""
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
            logger.info("✅ onenote_items 통합 테이블 확인/생성 완료")

            # 인덱스 생성
            self.db.execute_query("""
                CREATE INDEX IF NOT EXISTS idx_items_user_type
                ON onenote_items(user_id, item_type)
            """)
            self.db.execute_query("""
                CREATE INDEX IF NOT EXISTS idx_items_parent
                ON onenote_items(parent_id, item_type)
            """)
            self.db.execute_query("""
                CREATE INDEX IF NOT EXISTS idx_items_last_accessed
                ON onenote_items(user_id, item_type, last_accessed DESC)
            """)
            logger.info("✅ 인덱스 생성 완료")

            # 레거시 테이블 마이그레이션
            self._migrate_legacy_tables()

            return True

        except Exception as e:
            logger.error(f"❌ 테이블 초기화 실패: {str(e)}")
            return False

    def _migrate_legacy_tables(self):
        """
        기존 onenote_sections, onenote_pages 테이블 데이터를 통합 테이블로 마이그레이션
        """
        try:
            # 기존 섹션 테이블이 존재하는지 확인
            sections_exist = self.db.fetch_one("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='onenote_sections'
            """)

            if sections_exist:
                logger.info("🔄 기존 섹션 테이블 마이그레이션 시작...")

                # 섹션 데이터 마이그레이션
                sections = self.db.fetch_all("""
                    SELECT user_id, section_id, section_name, notebook_id, notebook_name, last_accessed
                    FROM onenote_sections
                """)

                for section in sections:
                    try:
                        self.db.execute_query("""
                            INSERT OR IGNORE INTO onenote_items
                            (user_id, item_type, item_id, item_name, parent_id, parent_name, last_accessed)
                            VALUES (?, 'section', ?, ?, ?, ?, ?)
                        """, (
                            section['user_id'],
                            section['section_id'],
                            section['section_name'],
                            section['notebook_id'],
                            section.get('notebook_name'),
                            section.get('last_accessed')
                        ))
                    except Exception as e:
                        logger.warning(f"섹션 마이그레이션 건너뛰기: {section.get('section_name')} - {str(e)}")

                logger.info(f"✅ 섹션 {len(sections)}개 마이그레이션 완료")

                # 기존 테이블 백업 후 삭제
                self.db.execute_query("DROP TABLE IF EXISTS onenote_sections_backup")
                self.db.execute_query("ALTER TABLE onenote_sections RENAME TO onenote_sections_backup")
                logger.info("✅ 기존 섹션 테이블 백업 완료 (onenote_sections_backup)")

            # 기존 페이지 테이블이 존재하는지 확인
            pages_exist = self.db.fetch_one("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='onenote_pages'
            """)

            if pages_exist:
                logger.info("🔄 기존 페이지 테이블 마이그레이션 시작...")

                # 페이지 데이터 마이그레이션
                pages = self.db.fetch_all("""
                    SELECT user_id, page_id, page_title, section_id, last_accessed
                    FROM onenote_pages
                """)

                for page in pages:
                    try:
                        self.db.execute_query("""
                            INSERT OR IGNORE INTO onenote_items
                            (user_id, item_type, item_id, item_name, parent_id, last_accessed)
                            VALUES (?, 'page', ?, ?, ?, ?)
                        """, (
                            page['user_id'],
                            page['page_id'],
                            page['page_title'],
                            page['section_id'],
                            page.get('last_accessed')
                        ))
                    except Exception as e:
                        logger.warning(f"페이지 마이그레이션 건너뛰기: {page.get('page_title')} - {str(e)}")

                logger.info(f"✅ 페이지 {len(pages)}개 마이그레이션 완료")

                # 기존 테이블 백업 후 삭제
                self.db.execute_query("DROP TABLE IF EXISTS onenote_pages_backup")
                self.db.execute_query("ALTER TABLE onenote_pages RENAME TO onenote_pages_backup")
                logger.info("✅ 기존 페이지 테이블 백업 완료 (onenote_pages_backup)")

        except Exception as e:
            logger.warning(f"⚠️ 레거시 테이블 마이그레이션 중 오류 (무시됨): {str(e)}")

    # ========================================================================
    # 통합 아이템 관리
    # ========================================================================

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

            self.db.execute_query(f"""
                INSERT INTO onenote_items (user_id, item_type, item_id, item_name, parent_id, parent_name, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?, {last_accessed_initial})
                ON CONFLICT(item_id) DO UPDATE SET
                    item_name = excluded.item_name,
                    parent_id = COALESCE(excluded.parent_id, parent_id),
                    parent_name = COALESCE(excluded.parent_name, parent_name),
                    last_accessed = {last_accessed_update},
                    updated_at = datetime('now')
            """, (user_id, item_type, item_id, item_name, parent_id, parent_name))

            logger.info(f"✅ {item_type} 저장 완료: {item_name} ({item_id}){' [최근 조회]' if update_accessed else ''}")
            return True

        except Exception as e:
            logger.error(f"❌ {item_type} 저장 실패: {str(e)}")
            return False

    def get_item(self, user_id: str, item_type: str, item_name: str) -> dict:
        """
        아이템 조회 (사용자 ID + 타입 + 이름으로)

        Args:
            user_id: 사용자 ID
            item_type: 'section' 또는 'page'
            item_name: 아이템 이름

        Returns:
            아이템 정보 dict 또는 None
        """
        try:
            result = self.db.fetch_one("""
                SELECT * FROM onenote_items
                WHERE user_id = ? AND item_type = ? AND item_name = ?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (user_id, item_type, item_name))

            if result:
                return dict(result)
            return None

        except Exception as e:
            logger.error(f"❌ {item_type} 조회 실패: {str(e)}")
            return None

    def list_items(
        self,
        user_id: str,
        item_type: str = None,
        parent_id: str = None
    ) -> list:
        """
        아이템 목록 조회

        Args:
            user_id: 사용자 ID
            item_type: 'section' 또는 'page' (None이면 전체)
            parent_id: 부모 ID 필터 (섹션의 경우 notebook_id, 페이지의 경우 section_id)

        Returns:
            아이템 목록 (list of dict)
        """
        try:
            # 쿼리 조건 생성
            conditions = ["user_id = ?"]
            params = [user_id]

            if item_type:
                conditions.append("item_type = ?")
                params.append(item_type)

            if parent_id:
                conditions.append("parent_id = ?")
                params.append(parent_id)

            where_clause = " AND ".join(conditions)

            results = self.db.fetch_all(f"""
                SELECT * FROM onenote_items
                WHERE {where_clause}
                ORDER BY updated_at DESC
            """, tuple(params))

            return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"❌ 아이템 목록 조회 실패: {str(e)}")
            return []

    def get_recent_items(
        self,
        user_id: str,
        item_type: str,
        limit: int = 1
    ) -> list:
        """
        최근 조회한 아이템 목록

        Args:
            user_id: 사용자 ID
            item_type: 'section' 또는 'page'
            limit: 조회할 개수

        Returns:
            아이템 목록 (list of dict)
        """
        try:
            results = self.db.fetch_all("""
                SELECT * FROM onenote_items
                WHERE user_id = ? AND item_type = ? AND last_accessed IS NOT NULL
                ORDER BY last_accessed DESC
                LIMIT ?
            """, (user_id, item_type, limit))

            return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"❌ 최근 {item_type} 조회 실패: {str(e)}")
            return []

    def delete_item(self, user_id: str, item_id: str) -> bool:
        """
        아이템 삭제

        Args:
            user_id: 사용자 ID
            item_id: 아이템 ID

        Returns:
            성공 여부
        """
        try:
            self.db.execute_query("""
                DELETE FROM onenote_items
                WHERE user_id = ? AND item_id = ?
            """, (user_id, item_id))

            logger.info(f"✅ 아이템 삭제 완료: {item_id}")
            return True

        except Exception as e:
            logger.error(f"❌ 아이템 삭제 실패: {str(e)}")
            return False

    # ========================================================================
    # 하위 호환성 메서드 (기존 API 유지)
    # ========================================================================

    def save_section(
        self,
        user_id: str,
        notebook_id: str,
        section_id: str,
        section_name: str,
        notebook_name: str = None,
        mark_as_recent: bool = False,
        update_accessed: bool = False
    ) -> bool:
        """하위 호환: 섹션 저장"""
        return self.save_item(
            user_id=user_id,
            item_type='section',
            item_id=section_id,
            item_name=section_name,
            parent_id=notebook_id,
            parent_name=notebook_name,
            update_accessed=update_accessed or mark_as_recent
        )

    def get_section(self, user_id: str, section_name: str) -> dict:
        """하위 호환: 섹션 조회"""
        item = self.get_item(user_id, 'section', section_name)
        if item:
            # 기존 키 매핑
            return {
                'section_id': item['item_id'],
                'section_name': item['item_name'],
                'notebook_id': item.get('parent_id'),
                'notebook_name': item.get('parent_name'),
                'user_id': item['user_id'],
                'last_accessed': item.get('last_accessed'),
                'created_at': item.get('created_at'),
                'updated_at': item.get('updated_at')
            }
        return None

    def list_sections(self, user_id: str) -> list:
        """하위 호환: 섹션 목록 조회"""
        items = self.list_items(user_id, item_type='section')
        # 기존 키 매핑
        return [{
            'section_id': item['item_id'],
            'section_name': item['item_name'],
            'notebook_id': item.get('parent_id'),
            'notebook_name': item.get('parent_name'),
            'user_id': item['user_id'],
            'last_accessed': item.get('last_accessed'),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at')
        } for item in items]

    def save_page(
        self,
        user_id: str,
        section_id: str,
        page_id: str,
        page_title: str,
        mark_as_recent: bool = False,
        update_accessed: bool = False
    ) -> bool:
        """하위 호환: 페이지 저장"""
        return self.save_item(
            user_id=user_id,
            item_type='page',
            item_id=page_id,
            item_name=page_title,
            parent_id=section_id,
            update_accessed=update_accessed or mark_as_recent
        )

    def get_page(self, user_id: str, page_title: str) -> dict:
        """하위 호환: 페이지 조회"""
        item = self.get_item(user_id, 'page', page_title)
        if item:
            # 기존 키 매핑
            return {
                'page_id': item['item_id'],
                'page_title': item['item_name'],
                'section_id': item.get('parent_id'),
                'user_id': item['user_id'],
                'last_accessed': item.get('last_accessed'),
                'created_at': item.get('created_at'),
                'updated_at': item.get('updated_at')
            }
        return None

    def list_pages(self, user_id: str, section_id: str = None) -> list:
        """하위 호환: 페이지 목록 조회"""
        items = self.list_items(user_id, item_type='page', parent_id=section_id)
        # 기존 키 매핑
        return [{
            'page_id': item['item_id'],
            'page_title': item['item_name'],
            'section_id': item.get('parent_id'),
            'user_id': item['user_id'],
            'last_accessed': item.get('last_accessed'),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at')
        } for item in items]

    def get_recent_section(self, user_id: str, limit: int = 1) -> dict:
        """하위 호환: 최근 섹션 조회"""
        items = self.get_recent_items(user_id, 'section', limit)
        if not items:
            return None if limit == 1 else []

        # 기존 키 매핑
        mapped = [{
            'section_id': item['item_id'],
            'section_name': item['item_name'],
            'notebook_id': item.get('parent_id'),
            'notebook_name': item.get('parent_name'),
            'user_id': item['user_id'],
            'last_accessed': item.get('last_accessed'),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at')
        } for item in items]

        return mapped[0] if limit == 1 else mapped

    def get_recent_page(self, user_id: str, limit: int = 1) -> dict:
        """하위 호환: 최근 페이지 조회"""
        items = self.get_recent_items(user_id, 'page', limit)
        if not items:
            return None if limit == 1 else []

        # 기존 키 매핑
        mapped = [{
            'page_id': item['item_id'],
            'page_title': item['item_name'],
            'section_id': item.get('parent_id'),
            'user_id': item['user_id'],
            'last_accessed': item.get('last_accessed'),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at')
        } for item in items]

        return mapped[0] if limit == 1 else mapped

    def delete_section(self, user_id: str, section_id: str) -> bool:
        """하위 호환: 섹션 삭제"""
        return self.delete_item(user_id, section_id)

    def delete_page(self, user_id: str, page_id: str) -> bool:
        """하위 호환: 페이지 삭제"""
        return self.delete_item(user_id, page_id)
