"""MCP OpenAI Wrapper - Wraps individual MCP server with OpenAI API"""

import json
import time
from typing import Any, Dict, List, Optional
import secrets

from infra.core.logger import get_logger
from .schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelInfo,
    ModelListResponse,
)
from .tool_converter import MCPToOpenAIConverter
from .response_builder import OpenAIResponseBuilder

logger = get_logger(__name__)


class MCPOpenAIWrapper:
    """Wrapper for individual MCP server to expose OpenAI-compatible API

    Each MCP server gets its own wrapper instance with:
    - /v1/chat/completions endpoint
    - /v1/models endpoint
    """

    def __init__(self, mcp_server: Any, server_name: str, model_id: str):
        """Initialize MCP OpenAI Wrapper

        Args:
            mcp_server: The MCP server instance (HTTPStreamingXXXServer)
            server_name: Name of the MCP server (e.g., "mail-query")
            model_id: Model ID to expose (e.g., "mcp-mail-query")
        """
        self.mcp_server = mcp_server
        self.server_name = server_name
        self.model_id = model_id
        self.converter = MCPToOpenAIConverter()
        self.response_builder = OpenAIResponseBuilder()

    async def handle_chat_completions(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Handle /v1/chat/completions request

        Args:
            request: ChatCompletionRequest

        Returns:
            ChatCompletionResponse
        """
        try:
            logger.info(f"[{self.server_name}] Chat completion request for model: {request.model}")

            # Get available tools from MCP server
            mcp_tools = await self.mcp_server.handlers.handle_list_tools()
            logger.info(f"[{self.server_name}] Available tools: {[t.name for t in mcp_tools]}")

            # Check if request includes tool definitions (auto mode)
            if request.tools:
                logger.info(f"[{self.server_name}] Request includes {len(request.tools)} tool definitions")

            # Extract last user message
            last_message = None
            for msg in reversed(request.messages):
                if msg.role == "user":
                    last_message = msg.content
                    break

            if not last_message:
                return self.response_builder.build_text_response(
                    model=self.model_id,
                    content="No user message found in request.",
                    finish_reason="stop",
                )

            # Simple heuristic: check if message seems to be requesting a tool
            # In real implementation, you'd use an LLM to decide which tool to call
            # For now, we'll return the available tools for the client to decide

            # Convert MCP tools to OpenAI format
            openai_tools = self.converter.convert_tools(mcp_tools)

            # Return a response suggesting available tools
            tool_names = [t.function.name for t in openai_tools]
            suggestion = (
                f"Available tools for {self.server_name}: {', '.join(tool_names)}. "
                f"Please specify which tool you'd like to use and with what parameters."
            )

            return self.response_builder.build_text_response(
                model=self.model_id,
                content=suggestion,
                finish_reason="stop",
            )

        except Exception as e:
            logger.error(f"[{self.server_name}] Chat completion error: {str(e)}", exc_info=True)
            return self.response_builder.build_error_response(
                model=self.model_id,
                error_message=str(e),
            )

    async def handle_list_models(self) -> ModelListResponse:
        """Handle /v1/models request

        Returns:
            ModelListResponse with single model representing this MCP server
        """
        try:
            model_info = ModelInfo(
                id=self.model_id,
                object="model",
                created=int(time.time()),
                owned_by=f"mcp-{self.server_name}",
            )

            return ModelListResponse(
                object="list",
                data=[model_info],
            )

        except Exception as e:
            logger.error(f"[{self.server_name}] List models error: {str(e)}", exc_info=True)
            return ModelListResponse(object="list", data=[])

    async def execute_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute MCP tool call and return result

        Args:
            tool_name: Name of tool to call
            arguments: Tool arguments

        Returns:
            JSON string with tool result
        """
        try:
            logger.info(f"[{self.server_name}] Executing tool: {tool_name}")
            logger.info(f"[{self.server_name}] Arguments: {json.dumps(arguments, indent=2)}")

            # Call MCP tool
            result_content = await self.mcp_server.handlers.handle_call_tool(
                tool_name, arguments
            )

            # Convert result to text
            result_text = ""
            for content in result_content:
                if hasattr(content, 'text'):
                    result_text += content.text + "\n"
                elif isinstance(content, dict) and 'text' in content:
                    result_text += content['text'] + "\n"

            logger.info(f"[{self.server_name}] Tool execution successful")
            return result_text.strip()

        except Exception as e:
            logger.error(f"[{self.server_name}] Tool execution error: {str(e)}", exc_info=True)
            return f"Error executing tool {tool_name}: {str(e)}"
