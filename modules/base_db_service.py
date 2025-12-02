"""Base DB Service for all MCP modules with DCR OAuth account synchronization"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from infra.core.logger import get_logger

logger = get_logger(__name__)


class BaseDBService:
    """Base DB Service for managing user accounts and synchronization with DCR"""

    def __init__(self, server_name: str):
        """
        Initialize Base DB Service

        Args:
            server_name: Server name (e.g., 'teams', 'onenote', 'outlook')
                        Used for both auth DB and service DB naming
        """
        self.server_name = server_name

        # Service DB path: data/{server_name}.db
        project_root = Path(__file__).parent.parent
        self.db_path = str(project_root / "data" / f"{server_name}.db")

        # Auth DB path: data/auth_{server_name}.db
        self.auth_db_path = os.getenv("DCR_DATABASE_PATH")
        if not self.auth_db_path:
            self.auth_db_path = str(project_root / "data" / f"auth_{server_name}.db")

        self._ensure_database_exists()
        logger.info(f"📚 {server_name.capitalize()} DB Service initialized: {self.db_path}")

    def _ensure_database_exists(self):
        """Ensure database and accounts table exist"""
        # Create directory if needed
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create accounts table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL UNIQUE,
                    user_name TEXT,
                    email TEXT UNIQUE,

                    -- OAuth settings
                    oauth_client_id TEXT,
                    oauth_client_secret TEXT,
                    oauth_tenant_id TEXT,
                    oauth_redirect_uri TEXT,

                    -- Account status
                    status TEXT DEFAULT 'active',
                    auth_type TEXT DEFAULT 'DCR OAuth',

                    -- Delegated permissions
                    delegated_permissions TEXT,

                    -- Token info
                    access_token TEXT,
                    refresh_token TEXT,
                    token_expiry TIMESTAMP,

                    -- Metadata
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    last_sync_time TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts (email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_is_active ON accounts (is_active)")

            conn.commit()
            logger.info(f"✅ Database tables verified/created for {self.server_name}.db")

    def execute_query(self, query: str, params: Optional[Tuple] = None) -> None:
        """Execute a query without returning results"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            conn.commit()

    def fetch_one(self, query: str, params: Optional[Tuple] = None) -> Optional[Tuple]:
        """Fetch a single row"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchone()

    def fetch_all(self, query: str, params: Optional[Tuple] = None) -> List[Tuple]:
        """Fetch all rows"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchall()

    def sync_accounts_from_dcr(self) -> int:
        """
        Sync accounts from auth_{server_name}.db to {server_name}.db

        Returns:
            Number of accounts synced
        """
        try:
            if not Path(self.auth_db_path).exists():
                logger.warning(f"⚠️ Auth DB not found: {self.auth_db_path}")
                return 0

            # Connect to auth DB
            auth_conn = sqlite3.connect(self.auth_db_path)
            auth_conn.row_factory = sqlite3.Row
            auth_cursor = auth_conn.cursor()

            # Get users from dcr_azure_users and dcr_azure_app
            auth_cursor.execute('''
                SELECT
                    dau.object_id,
                    dau.user_email,
                    dau.user_name,
                    dau.access_token,
                    dau.refresh_token,
                    dau.expires_at,
                    dau.scope,
                    dau.application_id,
                    daa.client_secret,
                    daa.tenant_id,
                    daa.redirect_uri
                FROM dcr_azure_users dau
                LEFT JOIN dcr_azure_app daa ON dau.application_id = daa.application_id
                WHERE dau.user_email IS NOT NULL
            ''')

            users = auth_cursor.fetchall()
            logger.info(f"📋 Found {len(users)} users in auth_{self.server_name}.db")

            synced_count = 0

            for user in users:
                try:
                    user_email = user['user_email']
                    # user_id is the part before @ in email
                    user_id = user_email.split('@')[0] if '@' in user_email else user_email

                    # Default permissions based on server type
                    delegated_permissions = user['scope'] or self._get_default_permissions()

                    # UPSERT: Update if exists, Insert if not
                    existing = self.fetch_one(
                        "SELECT id FROM accounts WHERE user_id = ? OR email = ?",
                        (user_id, user_email)
                    )

                    if existing:
                        # UPDATE
                        self.execute_query('''
                            UPDATE accounts SET
                                email = ?,
                                user_name = ?,
                                oauth_client_id = ?,
                                oauth_client_secret = ?,
                                oauth_tenant_id = ?,
                                oauth_redirect_uri = ?,
                                delegated_permissions = ?,
                                access_token = ?,
                                refresh_token = ?,
                                token_expiry = ?,
                                status = 'active',
                                is_active = 1,
                                last_sync_time = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE user_id = ? OR email = ?
                        ''', (
                            user_email,
                            user['user_name'] or user_email,
                            user['application_id'],
                            user['client_secret'],
                            user['tenant_id'],
                            user['redirect_uri'],
                            delegated_permissions,
                            user['access_token'],
                            user['refresh_token'],
                            user['expires_at'],
                            user_id,
                            user_email
                        ))
                        logger.info(f"✅ Updated account: {user_email}")
                    else:
                        # INSERT
                        self.execute_query('''
                            INSERT INTO accounts (
                                user_id, user_name, email,
                                oauth_client_id, oauth_client_secret, oauth_tenant_id, oauth_redirect_uri,
                                delegated_permissions,
                                access_token, refresh_token, token_expiry,
                                status, is_active, last_sync_time
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, CURRENT_TIMESTAMP)
                        ''', (
                            user_id,
                            user['user_name'] or user_email,
                            user_email,
                            user['application_id'],
                            user['client_secret'],
                            user['tenant_id'],
                            user['redirect_uri'],
                            delegated_permissions,
                            user['access_token'],
                            user['refresh_token'],
                            user['expires_at']
                        ))
                        logger.info(f"✅ Created account: {user_email}")

                    synced_count += 1

                except Exception as e:
                    logger.error(f"❌ Failed to sync user {user['user_email'] if 'user_email' in user else 'unknown'}: {str(e)}")
                    continue

            auth_conn.close()
            logger.info(f"✅ Synced {synced_count} accounts from auth_{self.server_name}.db to {self.server_name}.db")
            return synced_count

        except Exception as e:
            logger.error(f"❌ Failed to sync accounts from DCR: {str(e)}")
            return 0

    def _get_default_permissions(self) -> str:
        """Get default permissions based on server type"""
        default_permissions = {
            'teams': 'User.Read Chat.Read Chat.ReadWrite ChannelMessage.Read ChannelMessage.Send offline_access',
            'onenote': 'User.Read Notes.Read Notes.ReadWrite offline_access',
            'outlook': 'User.Read Mail.Read Mail.ReadWrite Mail.Send offline_access',
            'mail_query': 'User.Read Mail.Read Mail.ReadWrite Mail.Send offline_access',  # Legacy support
        }
        return default_permissions.get(self.server_name, 'User.Read offline_access')

    def upsert_account(
        self,
        user_id: str,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_expiry: Optional[datetime] = None,
        scopes: Optional[List[str]] = None,
        is_active: bool = True
    ) -> bool:
        """
        Upsert user account (for real-time updates from DCR endpoints)

        Args:
            user_id: User email or ID
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            token_expiry: Token expiry time
            scopes: List of OAuth scopes
            is_active: Whether account is active

        Returns:
            True if successful
        """
        try:
            # Check if account exists
            existing = self.fetch_one(
                "SELECT id FROM accounts WHERE user_id = ? OR email = ?",
                (user_id, user_id)
            )

            if existing:
                # Update existing account
                update_parts = ["updated_at = CURRENT_TIMESTAMP"]
                params = []

                if access_token is not None:
                    update_parts.append("access_token = ?")
                    params.append(access_token)

                if refresh_token is not None:
                    update_parts.append("refresh_token = ?")
                    params.append(refresh_token)

                if token_expiry is not None:
                    update_parts.append("token_expiry = ?")
                    params.append(token_expiry.isoformat() if isinstance(token_expiry, datetime) else token_expiry)

                if scopes is not None:
                    update_parts.append("delegated_permissions = ?")
                    params.append(' '.join(scopes) if isinstance(scopes, list) else scopes)

                update_parts.append("is_active = ?")
                params.append(1 if is_active else 0)

                update_parts.append("status = ?")
                params.append('active' if is_active else 'inactive')

                # Add WHERE clause parameters
                params.append(user_id)
                params.append(user_id)

                query = f"UPDATE accounts SET {', '.join(update_parts)} WHERE user_id = ? OR email = ?"
                self.execute_query(query, tuple(params))
                logger.info(f"✅ Updated account in {self.server_name}.db: {user_id}")
            else:
                # For new accounts from DCR endpoints, we need minimal info
                # The full sync will fill in the rest
                self.execute_query('''
                    INSERT INTO accounts (
                        user_id, email,
                        access_token, refresh_token, token_expiry,
                        delegated_permissions,
                        status, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', 1)
                ''', (
                    user_id.split('@')[0] if '@' in user_id else user_id,
                    user_id if '@' in user_id else None,
                    access_token,
                    refresh_token,
                    token_expiry.isoformat() if isinstance(token_expiry, datetime) else token_expiry,
                    ' '.join(scopes) if isinstance(scopes, list) else scopes,
                ))
                logger.info(f"✅ Created minimal account in {self.server_name}.db: {user_id}")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to upsert account {user_id} in {self.server_name}.db: {str(e)}")
            return False

    def get_active_account(self, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get active account

        Args:
            user_id: Specific user ID to get, or None for any active account

        Returns:
            Account dict or None
        """
        if user_id:
            result = self.fetch_one(
                """SELECT user_id, email, access_token, refresh_token, token_expiry, delegated_permissions
                FROM accounts WHERE (user_id = ? OR email = ?) AND is_active = 1""",
                (user_id, user_id)
            )
        else:
            result = self.fetch_one(
                """SELECT user_id, email, access_token, refresh_token, token_expiry, delegated_permissions
                FROM accounts WHERE is_active = 1
                ORDER BY updated_at DESC LIMIT 1"""
            )

        if result:
            return {
                "user_id": result[0],
                "email": result[1],
                "access_token": result[2],
                "refresh_token": result[3],
                "token_expiry": result[4],
                "scopes": result[5].split() if result[5] else []
            }
        return None

    def deactivate_account(self, user_id: str) -> bool:
        """
        Deactivate an account

        Args:
            user_id: User ID to deactivate

        Returns:
            True if successful
        """
        try:
            self.execute_query(
                "UPDATE accounts SET is_active = 0, status = 'inactive', updated_at = CURRENT_TIMESTAMP WHERE user_id = ? OR email = ?",
                (user_id, user_id)
            )
            logger.info(f"✅ Deactivated account in {self.server_name}.db: {user_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to deactivate account {user_id} in {self.server_name}.db: {str(e)}")
            return False

    def list_accounts(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """
        List all accounts

        Args:
            active_only: Only return active accounts

        Returns:
            List of account dicts
        """
        query = "SELECT user_id, email, is_active, token_expiry, updated_at FROM accounts"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY updated_at DESC"

        results = self.fetch_all(query)
        accounts = []
        for row in results:
            accounts.append({
                "user_id": row[0],
                "email": row[1],
                "is_active": bool(row[2]),
                "token_expiry": row[3],
                "updated_at": row[4]
            })

        return accounts