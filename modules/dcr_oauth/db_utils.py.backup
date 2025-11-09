"""
Database helper utilities for DCR OAuth module.

These helpers centralize simple SQLite operations so the service can
delegate without duplicating boilerplate.
"""

from typing import Any, Iterable, Optional, Tuple
import sqlite3


def execute_query(db_path: str, query: str, params: Tuple[Any, ...] = ()) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def fetch_one(db_path: str, query: str, params: Tuple[Any, ...] = ()) -> Optional[Tuple[Any, ...]]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()
    finally:
        conn.close()


def fetch_all(db_path: str, query: str, params: Tuple[Any, ...] = ()) -> Iterable[Tuple[Any, ...]]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()

