"""Convert MCP Tools to OpenAI Function Calling format"""

from typing import Any, Dict, List
from mcp.types import Tool

from .schemas import FunctionDefinition, ToolDefinition


class MCPToOpenAIConverter:
    """Convert MCP tools to OpenAI function calling format"""

    @staticmethod
    def convert_tool(mcp_tool: Tool) -> ToolDefinition:
        """Convert a single MCP tool to OpenAI tool definition

        Args:
            mcp_tool: MCP Tool object

        Returns:
            OpenAI ToolDefinition
        """
        # Convert MCP tool schema to OpenAI function parameters
        parameters = mcp_tool.inputSchema if mcp_tool.inputSchema else {
            "type": "object",
            "properties": {},
        }

        function_def = FunctionDefinition(
            name=mcp_tool.name,
            description=mcp_tool.description or "",
            parameters=parameters,
        )

        return ToolDefinition(type="function", function=function_def)

    @classmethod
    def convert_tools(cls, mcp_tools: List[Tool]) -> List[ToolDefinition]:
        """Convert multiple MCP tools to OpenAI tool definitions

        Args:
            mcp_tools: List of MCP Tool objects

        Returns:
            List of OpenAI ToolDefinitions
        """
        return [cls.convert_tool(tool) for tool in mcp_tools]

    @staticmethod
    def convert_tool_result_to_message(
        tool_call_id: str, tool_name: str, result_content: List[Any]
    ) -> Dict[str, Any]:
        """Convert MCP tool call result to OpenAI tool message format

        Args:
            tool_call_id: Unique tool call ID
            tool_name: Name of the tool that was called
            result_content: MCP tool result content (list of TextContent/ImageContent)

        Returns:
            OpenAI tool message dict
        """
        # Combine all text content from MCP result
        combined_text = ""
        for content in result_content:
            if hasattr(content, 'text'):
                combined_text += content.text + "\n"
            elif isinstance(content, dict) and 'text' in content:
                combined_text += content['text'] + "\n"

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": combined_text.strip(),
        }
