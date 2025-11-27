"""MCP Server Tools Package"""

from .email_query import EmailQueryTool
from .export import ExportTool
from .account import AccountManagementTool
from .orchestrator import ToolOrchestrator

# Export the main orchestrator for backward compatibility
MailAttachmentTools = ToolOrchestrator

__all__ = [
    'EmailQueryTool',
    'ExportTool',
    'AccountManagementTool',
    'ToolOrchestrator',
    'MailAttachmentTools'  # Backward compatibility
]