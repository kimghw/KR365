"""OpenAI-compatible API wrapper for MCP servers"""

from .schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    FunctionCall,
    ToolCall,
    ModelListResponse,
)
from .tool_converter import MCPToOpenAIConverter
from .response_builder import OpenAIResponseBuilder
from .mcp_wrapper import MCPOpenAIWrapper
from .unified_handler import UnifiedOpenAIHandler

__all__ = [
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatMessage",
    "FunctionCall",
    "ToolCall",
    "ModelListResponse",
    "MCPToOpenAIConverter",
    "OpenAIResponseBuilder",
    "MCPOpenAIWrapper",
    "UnifiedOpenAIHandler",
]
