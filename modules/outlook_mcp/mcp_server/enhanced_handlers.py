"""Enhanced MCP Protocol handlers with notifications and sampling"""

import json
import logging
from typing import Any, Dict, List, Optional

from mcp.types import (
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
    Tool,
    LogLevel,
    CreateMessageRequest,
    CreateMessageResult,
    StopReason
)
from mcp.server import Server

from infra.core.logger import get_logger
from .handlers import MCPHandlers

logger = get_logger(__name__)


class EnhancedMCPHandlers(MCPHandlers):
    """MCP Handlers with notification and sampling capabilities"""

    def __init__(self, session=None):
        """Initialize with optional session for server-to-client communication"""
        super().__init__()
        self.session = session

    async def handle_call_tool_with_notifications(
        self,
        name: str,
        arguments: dict,
        session
    ):
        """
        Enhanced tool handler with notifications and LLM sampling

        Args:
            name: Tool name
            arguments: Tool arguments
            session: MCP session for server-to-client communication
        """
        try:
            # 1. Send initial log message
            if session:
                await session.send_log_message(
                    level=LogLevel.INFO,
                    data=f"🚀 Starting tool execution: {name}"
                )

            # 2. Execute the tool with progress notifications
            if name == "search_emails":
                # Send progress notification
                if session:
                    await session.send_progress_notification(
                        progress=10,
                        total=100,
                        message="Searching emails..."
                    )

                # Execute search
                result = await super().handle_call_tool(name, arguments)

                # 3. Use LLM to summarize results (if available)
                if session and hasattr(session, 'create_message'):
                    try:
                        # Send progress
                        await session.send_progress_notification(
                            progress=50,
                            total=100,
                            message="Analyzing results with AI..."
                        )

                        # Request LLM summary
                        email_data = json.dumps(result, ensure_ascii=False)

                        llm_response = await session.create_message(
                            CreateMessageRequest(
                                messages=[{
                                    "role": "user",
                                    "content": f"""다음 이메일 검색 결과를 간단히 요약해줘:

{email_data[:1000]}  # Limit for context

핵심 내용만 3줄로 요약:"""
                                }],
                                max_tokens=200,
                                temperature=0.7
                            )
                        )

                        # Add summary to result
                        if llm_response and llm_response.content:
                            result["ai_summary"] = llm_response.content[0].text

                            # Log the summary
                            await session.send_log_message(
                                level=LogLevel.INFO,
                                data=f"📝 AI Summary: {llm_response.content[0].text[:100]}..."
                            )
                    except Exception as e:
                        logger.warning(f"LLM summarization failed: {e}")
                        # Continue without summary

                # 4. Send completion notification
                if session:
                    await session.send_progress_notification(
                        progress=100,
                        total=100,
                        message="Search completed!"
                    )

                    await session.send_log_message(
                        level=LogLevel.INFO,
                        data=f"✅ Tool execution completed: {name}"
                    )

                return result

            else:
                # For other tools, use standard handler
                return await super().handle_call_tool(name, arguments)

        except Exception as e:
            # Send error notification
            if session:
                await session.send_log_message(
                    level=LogLevel.ERROR,
                    data=f"❌ Tool execution failed: {str(e)}"
                )
            raise


# Example usage in STDIO server
async def create_enhanced_stdio_server():
    """Create STDIO server with enhanced capabilities"""
    from mcp.server import Server
    from mcp.server.models import InitializationOptions
    from mcp.server.stdio import stdio_server

    server = Server("enhanced-email-mcp-server")

    @server.list_tools()
    async def list_tools():
        handlers = EnhancedMCPHandlers()
        return await handlers.handle_list_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict, ctx):
        """Tool handler with session context"""
        handlers = EnhancedMCPHandlers()

        # Get session from context if available
        session = ctx.session if hasattr(ctx, 'session') else None

        if session:
            return await handlers.handle_call_tool_with_notifications(
                name, arguments, session
            )
        else:
            return await handlers.handle_call_tool(name, arguments)

    return server