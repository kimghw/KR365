"""Unified OpenAI Handler - Aggregates all MCP servers"""

import json
from typing import Any, Dict, List
import time

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


class UnifiedOpenAIHandler:
    """Unified handler that aggregates all MCP servers and exposes them via OpenAI API

    This handler combines tools from all MCP servers and exposes them at the root level.
    """

    def __init__(self, mcp_servers: Dict[str, Any]):
        """Initialize Unified OpenAI Handler

        Args:
            mcp_servers: Dictionary of MCP server instances
                         e.g., {"teams": teams_server, "mail-query": mail_query_server}
        """
        self.mcp_servers = mcp_servers
        self.converter = MCPToOpenAIConverter()
        self.response_builder = OpenAIResponseBuilder()

    async def handle_chat_completions(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Handle /v1/chat/completions request

        Aggregates tools from all MCP servers

        Args:
            request: ChatCompletionRequest

        Returns:
            ChatCompletionResponse
        """
        try:
            logger.info(f"[Unified] Chat completion request for model: {request.model}")

            # Collect all tools from all MCP servers
            all_tools = []
            for server_name, server in self.mcp_servers.items():
                try:
                    mcp_tools = await server.handlers.handle_list_tools()
                    all_tools.extend(mcp_tools)
                    logger.info(f"[Unified] Loaded {len(mcp_tools)} tools from {server_name}")
                except Exception as e:
                    logger.warning(f"[Unified] Failed to load tools from {server_name}: {e}")

            logger.info(f"[Unified] Total tools available: {len(all_tools)}")

            # Extract last user message
            last_message = None
            for msg in reversed(request.messages):
                if msg.role == "user":
                    last_message = msg.content
                    break

            if not last_message:
                return self.response_builder.build_text_response(
                    model=request.model,
                    content="No user message found in request.",
                    finish_reason="stop",
                )

            # Convert MCP tools to OpenAI format
            openai_tools = self.converter.convert_tools(all_tools)

            # Build response with available tools
            tool_list = {}
            for tool in all_tools:
                # Group tools by server (inferred from tool name prefix or description)
                tool_list[tool.name] = tool.description or ""

            suggestion = (
                f"Available tools from all MCP servers ({len(all_tools)} total):\n\n"
                + "\n".join([f"- **{name}**: {desc}" for name, desc in tool_list.items()])
                + "\n\nPlease specify which tool you'd like to use and with what parameters."
            )

            return self.response_builder.build_text_response(
                model=request.model,
                content=suggestion,
                finish_reason="stop",
            )

        except Exception as e:
            logger.error(f"[Unified] Chat completion error: {str(e)}", exc_info=True)
            return self.response_builder.build_error_response(
                model=request.model,
                error_message=str(e),
            )

    async def handle_list_models(self) -> ModelListResponse:
        """Handle /v1/models request

        Returns all MCP servers as separate models

        Returns:
            ModelListResponse with all MCP servers as models
        """
        try:
            models = []
            for server_name in self.mcp_servers.keys():
                model_info = ModelInfo(
                    id=f"mcp-{server_name}",
                    object="model",
                    created=int(time.time()),
                    owned_by=f"mcp-unified-{server_name}",
                )
                models.append(model_info)

            # Add a unified model that combines all servers
            unified_model = ModelInfo(
                id="mcp-unified",
                object="model",
                created=int(time.time()),
                owned_by="mcp-unified-all",
            )
            models.insert(0, unified_model)

            logger.info(f"[Unified] Returning {len(models)} models")
            return ModelListResponse(object="list", data=models)

        except Exception as e:
            logger.error(f"[Unified] List models error: {str(e)}", exc_info=True)
            return ModelListResponse(object="list", data=[])
