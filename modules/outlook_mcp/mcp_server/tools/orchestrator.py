"""Tool orchestrator for MCP server"""

import logging
from typing import Any, Dict

from .email_query import EmailQueryTool
from .export import ExportTool
from .account import AccountManagementTool
from .help_content import get_tool_help, get_query_email_help

logger = logging.getLogger(__name__)


class ToolOrchestrator:
    """
    Orchestrator that manages all MCP tools
    Maintains backward compatibility with MailAttachmentTools
    """

    def __init__(self):
        """Initialize all tools"""
        # Load configuration
        from ..config import Config
        self.config = Config()

        # Initialize individual tools
        self.email_tool = EmailQueryTool(self.config)
        self.export_tool = ExportTool(self.config)
        self.account_tool = AccountManagementTool(self.config)

        logger.info("ToolOrchestrator initialized with all tools")

    # Core tool methods (simplified to 5 essential tools)
    async def register_account(self, arguments: Dict[str, Any]) -> str:
        """Register a new account with OAuth credentials"""
        return await self.account_tool.register_account(arguments)

    async def get_account_status(self, arguments: Dict[str, Any]) -> str:
        """Get account status and authentication information"""
        return await self.account_tool.get_account_status(arguments)

    async def start_authentication(self, arguments: Dict[str, Any]) -> str:
        """Start OAuth authentication flow"""
        return await self.account_tool.start_authentication(arguments)

    async def query_email(self, arguments: Dict[str, Any]) -> str:
        """Query emails and download/convert attachments"""
        return await self.email_tool.query_email(arguments)

    async def help(self, arguments: Dict[str, Any]) -> str:
        """Get help information for tools"""
        tool_name = arguments.get("tool_name")
        return get_tool_help(tool_name)

    async def query_email_help(self, arguments: Dict[str, Any]) -> str:
        """Get detailed help for query_email tool"""
        return get_query_email_help()

    # Internal utility methods (not exposed as tools)
    def save_emails_to_csv(self, emails: list[Dict[str, Any]], user_id: str):
        """Internal: Save email data to CSV file"""
        return self.export_tool.save_emails_to_csv(emails, user_id)

    def save_emails_to_json(self, emails: list[Dict[str, Any]], user_id: str):
        """Internal: Save email data to JSON file"""
        return self.export_tool.save_emails_to_json(emails, user_id)

    def export_email_summary(self, emails: list[Dict[str, Any]], user_id: str, format: str = "markdown"):
        """Internal: Export email summary in specified format"""
        return self.export_tool.export_email_summary(emails, user_id, format)

    # Additional utility methods
    def get_config(self):
        """Get configuration object"""
        return self.config

    def get_tool_status(self) -> Dict[str, bool]:
        """
        Get status of all tools

        Returns:
            Dictionary with tool availability status
        """
        return {
            "email_query": self.email_tool is not None,
            "export": self.export_tool is not None,
            "account_management": self.account_tool is not None,
            "config_loaded": self.config is not None
        }

    def get_supported_operations(self) -> list[str]:
        """
        Get list of supported tool operations

        Returns:
            List of tool names
        """
        return [
            "register_account",
            "get_account_status",
            "start_authentication",
            "query_email",
            "query_email_help",
            "help"
        ]