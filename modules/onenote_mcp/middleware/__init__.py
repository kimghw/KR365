"""OneNote MCP Middleware

FastAPI middleware for authentication and request logging.
"""

from .auth_dependencies import optional_auth, required_auth
from .request_logger import RequestLoggerMiddleware

__all__ = ["optional_auth", "required_auth", "RequestLoggerMiddleware"]
