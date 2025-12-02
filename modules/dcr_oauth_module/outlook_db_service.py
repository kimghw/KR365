"""Outlook MCP DB Service for account management and synchronization"""

from ..base_db_service import BaseDBService


class OutlookDBService(BaseDBService):
    """Outlook DB Service for managing user accounts and synchronization with DCR"""

    def __init__(self):
        """Initialize Outlook DB Service"""
        # Use 'outlook' as server name (not 'mail_query')
        super().__init__(server_name='outlook')


# Alias for compatibility
MailQueryDBService = OutlookDBService