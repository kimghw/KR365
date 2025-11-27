"""
Database helper utilities for DCR OAuth module - Redirects to new db_service module

This module now redirects to the new db_service module which provides:
- Better connection management (connection pooling)
- Thread-safe operations
- WAL mode support
- Improved error handling
"""

# Import everything from new db_service for backward compatibility
from .db_service import execute_query, fetch_one, fetch_all

__all__ = ['execute_query', 'fetch_one', 'fetch_all']