"""
Auth session store for managing OAuth state tokens
"""
import json
import time
from typing import Optional, Dict, Any
from infra.core.database import DatabaseManager
import hashlib
import secrets
import logging

logger = logging.getLogger(__name__)

class AuthSessionStore:
    """Store and manage OAuth authentication sessions"""

    def __init__(self, db_service: DatabaseManager):
        self.db = db_service
        self._ensure_table()

    def _ensure_table(self):
        """Create auth_sessions table if it doesn't exist"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            state TEXT PRIMARY KEY,
            user_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            metadata TEXT
        )
        """
        self.db.execute_query(create_table_sql)

        # Clean up expired sessions
        cleanup_sql = """
        DELETE FROM auth_sessions
        WHERE expires_at < datetime('now')
        """
        self.db.execute_query(cleanup_sql)
        logger.info("✅ Auth sessions table ensured and cleaned up")

    def create_session(self, user_id: Optional[str] = None, ttl_seconds: int = 600) -> str:
        """
        Create a new auth session and return the state token

        Args:
            user_id: Optional user ID to associate with the session
            ttl_seconds: Time to live in seconds (default 10 minutes)

        Returns:
            state: The generated state token
        """
        # Generate secure random state
        state = secrets.token_urlsafe(32)

        # Calculate expiration
        expires_at = time.time() + ttl_seconds

        # Store in database
        insert_sql = """
        INSERT INTO auth_sessions (state, user_id, expires_at, metadata)
        VALUES (?, ?, datetime('now', '+' || ? || ' seconds'), ?)
        """

        metadata = json.dumps({
            "created_at": time.time(),
            "ttl_seconds": ttl_seconds
        })

        self.db.execute_query(insert_sql, (state, user_id, ttl_seconds, metadata))

        logger.info(f"✅ Created auth session with state: {state[:10]}... for user: {user_id}")
        return state

    def validate_session(self, state: str) -> Optional[Dict[str, Any]]:
        """
        Validate a state token and return session info

        Args:
            state: The state token to validate

        Returns:
            Session info dict or None if invalid/expired
        """
        select_sql = """
        SELECT user_id, created_at, expires_at, metadata
        FROM auth_sessions
        WHERE state = ? AND expires_at > datetime('now')
        """

        result = self.db.fetch_one(select_sql, (state,))

        if result:
            user_id, created_at, expires_at, metadata_str = result
            metadata = json.loads(metadata_str) if metadata_str else {}

            logger.info(f"✅ Valid session found for state: {state[:10]}... user: {user_id}")

            return {
                "user_id": user_id,
                "created_at": created_at,
                "expires_at": expires_at,
                "metadata": metadata
            }
        else:
            logger.warning(f"❌ No valid session found for state: {state[:10]}...")
            return None

    def delete_session(self, state: str):
        """Delete a session after use"""
        delete_sql = "DELETE FROM auth_sessions WHERE state = ?"
        self.db.execute_query(delete_sql, (state,))
        logger.info(f"🗑️ Deleted session for state: {state[:10]}...")

    def cleanup_expired(self):
        """Clean up expired sessions"""
        cleanup_sql = """
        DELETE FROM auth_sessions
        WHERE expires_at < datetime('now')
        """
        result = self.db.execute_query(cleanup_sql)
        logger.info(f"🧹 Cleaned up expired sessions")