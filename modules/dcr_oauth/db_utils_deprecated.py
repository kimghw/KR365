"""
DEPRECATED: Database helper utilities for DCR OAuth module.

⚠️ DEPRECATION WARNING ⚠️
This module is deprecated and will be removed in a future version.
Please use db_service.py instead, which provides:
- Better connection management (connection pooling)
- Thread-safe operations
- WAL mode support
- Improved error handling

Migration guide:
1. Replace: from modules.dcr_oauth.db_utils import ...
   With: from modules.dcr_oauth.db_service import ...
2. Or use DCRDatabaseService class directly for better control

These helpers centralize simple SQLite operations so the service can
delegate without duplicating boilerplate.
"""

from typing import Any, Iterable, Optional, Tuple
import sqlite3
import warnings


def execute_query(db_path: str, query: str, params: Tuple[Any, ...] = ()) -> int:
    warnings.warn(
        "db_utils.execute_query is deprecated. Use db_service.execute_query instead.",
        DeprecationWarning,
        stacklevel=2
    )
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def fetch_one(db_path: str, query: str, params: Tuple[Any, ...] = ()) -> Optional[Tuple[Any, ...]]:
    warnings.warn(
        "db_utils.fetch_one is deprecated. Use db_service.fetch_one instead.",
        DeprecationWarning,
        stacklevel=2
    )
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()
    finally:
        conn.close()


def fetch_all(db_path: str, query: str, params: Tuple[Any, ...] = ()) -> Iterable[Tuple[Any, ...]]:
    warnings.warn(
        "db_utils.fetch_all is deprecated. Use db_service.fetch_all instead.",
        DeprecationWarning,
        stacklevel=2
    )
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()