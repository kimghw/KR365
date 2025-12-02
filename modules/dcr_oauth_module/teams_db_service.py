"""Teams MCP DB Service for account management"""

from ..base_db_service import BaseDBService
import json
from typing import Any, Dict, Optional
from infra.core.logger import get_logger

logger = get_logger(__name__)


class TeamsDBService(BaseDBService):
    """Teams DB Service for managing user accounts and Teams-specific data"""

    def __init__(self, db_name: str = "teams"):
        """
        Initialize Teams DB Service

        Args:
            db_name: Name of the database (default: "teams")
        """
        # Use db_name as server name (for backward compatibility)
        super().__init__(server_name=db_name)

        # Ensure Teams-specific tables exist
        self._ensure_teams_tables()

    def _ensure_teams_tables(self):
        """Create Teams-specific tables (chats, messages, etc.)"""
        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create chats table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id TEXT PRIMARY KEY,
                    chat_type TEXT NOT NULL,
                    topic TEXT,
                    created_date_time TEXT,
                    last_updated_date_time TEXT,
                    web_url TEXT,
                    members TEXT,
                    korean_name TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    from_user_id TEXT,
                    from_user_name TEXT,
                    content TEXT,
                    created_date_time TEXT,
                    last_modified_date_time TEXT,
                    message_type TEXT,
                    importance TEXT,
                    attachments TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (chat_id) REFERENCES chats (chat_id)
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_date_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats(last_updated_date_time)")

            conn.commit()
            logger.info("✅ Teams-specific tables verified/created")

    def save_chat(self, chat_data: Dict[str, Any]) -> bool:
        """
        Save chat information (Teams-specific)

        Args:
            chat_data: Chat data from Teams API

        Returns:
            True if successful
        """
        try:
            chat_id = chat_data.get("id")
            if not chat_id:
                logger.error("Chat ID is required")
                return False

            # Extract members
            members = chat_data.get("members", [])
            members_json = json.dumps(members) if members else None

            # Upsert chat
            existing = self.fetch_one("SELECT chat_id FROM chats WHERE chat_id = ?", (chat_id,))

            if existing:
                self.execute_query(
                    """UPDATE chats SET
                    chat_type = ?, topic = ?, last_updated_date_time = ?,
                    web_url = ?, members = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE chat_id = ?""",
                    (
                        chat_data.get("chatType", "unknown"),
                        chat_data.get("topic"),
                        chat_data.get("lastUpdatedDateTime"),
                        chat_data.get("webUrl"),
                        members_json,
                        chat_id
                    )
                )
            else:
                self.execute_query(
                    """INSERT INTO chats
                    (chat_id, chat_type, topic, created_date_time, last_updated_date_time,
                    web_url, members)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chat_id,
                        chat_data.get("chatType", "unknown"),
                        chat_data.get("topic"),
                        chat_data.get("createdDateTime"),
                        chat_data.get("lastUpdatedDateTime"),
                        chat_data.get("webUrl"),
                        members_json
                    )
                )

            return True

        except Exception as e:
            logger.error(f"Failed to save chat: {str(e)}")
            return False

    def save_message(self, message_data: Dict[str, Any], chat_id: str) -> bool:
        """
        Save message information (Teams-specific)

        Args:
            message_data: Message data from Teams API
            chat_id: Chat ID the message belongs to

        Returns:
            True if successful
        """
        try:
            message_id = message_data.get("id")
            if not message_id:
                logger.error("Message ID is required")
                return False

            # Extract attachments
            attachments = message_data.get("attachments", [])
            attachments_json = json.dumps(attachments) if attachments else None

            # Upsert message
            existing = self.fetch_one("SELECT message_id FROM messages WHERE message_id = ?", (message_id,))

            if existing:
                self.execute_query(
                    """UPDATE messages SET
                    content = ?, last_modified_date_time = ?,
                    attachments = ?
                    WHERE message_id = ?""",
                    (
                        message_data.get("body", {}).get("content"),
                        message_data.get("lastModifiedDateTime"),
                        attachments_json,
                        message_id
                    )
                )
            else:
                self.execute_query(
                    """INSERT INTO messages
                    (message_id, chat_id, from_user_id, from_user_name,
                    content, created_date_time, last_modified_date_time,
                    message_type, importance, attachments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        message_id,
                        chat_id,
                        message_data.get("from", {}).get("user", {}).get("id"),
                        message_data.get("from", {}).get("user", {}).get("displayName"),
                        message_data.get("body", {}).get("content"),
                        message_data.get("createdDateTime"),
                        message_data.get("lastModifiedDateTime"),
                        message_data.get("messageType"),
                        message_data.get("importance"),
                        attachments_json
                    )
                )

            return True

        except Exception as e:
            logger.error(f"Failed to save message: {str(e)}")
            return False