"""Build OpenAI API compatible responses"""

import time
from typing import List, Optional
import secrets

from .schemas import (
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatCompletionUsage,
    ChatMessage,
    ToolCall,
    FunctionCall,
)


class OpenAIResponseBuilder:
    """Build OpenAI-compatible API responses"""

    @staticmethod
    def build_tool_call_response(
        model: str,
        tool_calls: List[dict],
        request_id: Optional[str] = None,
    ) -> ChatCompletionResponse:
        """Build response for tool calls (function calling)

        Args:
            model: Model name
            tool_calls: List of tool calls to include in response
            request_id: Optional request ID

        Returns:
            ChatCompletionResponse with tool calls
        """
        if request_id is None:
            request_id = f"chatcmpl-{secrets.token_urlsafe(16)}"

        # Convert tool calls to OpenAI format
        openai_tool_calls = []
        for tc in tool_calls:
            openai_tool_calls.append(
                ToolCall(
                    id=tc.get("id", f"call_{secrets.token_urlsafe(16)}"),
                    type="function",
                    function=FunctionCall(
                        name=tc["name"],
                        arguments=tc["arguments"],  # JSON string
                    ),
                )
            )

        message = ChatMessage(
            role="assistant",
            content=None,
            tool_calls=openai_tool_calls,
        )

        choice = ChatCompletionChoice(
            index=0,
            message=message,
            finish_reason="tool_calls",
        )

        return ChatCompletionResponse(
            id=request_id,
            object="chat.completion",
            created=int(time.time()),
            model=model,
            choices=[choice],
            usage=ChatCompletionUsage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            ),
        )

    @staticmethod
    def build_text_response(
        model: str,
        content: str,
        finish_reason: str = "stop",
        request_id: Optional[str] = None,
    ) -> ChatCompletionResponse:
        """Build response with text content

        Args:
            model: Model name
            content: Response text content
            finish_reason: Reason for completion
            request_id: Optional request ID

        Returns:
            ChatCompletionResponse with text
        """
        if request_id is None:
            request_id = f"chatcmpl-{secrets.token_urlsafe(16)}"

        message = ChatMessage(
            role="assistant",
            content=content,
        )

        choice = ChatCompletionChoice(
            index=0,
            message=message,
            finish_reason=finish_reason,
        )

        return ChatCompletionResponse(
            id=request_id,
            object="chat.completion",
            created=int(time.time()),
            model=model,
            choices=[choice],
            usage=ChatCompletionUsage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            ),
        )

    @staticmethod
    def build_error_response(
        model: str,
        error_message: str,
        request_id: Optional[str] = None,
    ) -> ChatCompletionResponse:
        """Build error response

        Args:
            model: Model name
            error_message: Error message
            request_id: Optional request ID

        Returns:
            ChatCompletionResponse with error
        """
        return OpenAIResponseBuilder.build_text_response(
            model=model,
            content=f"Error: {error_message}",
            finish_reason="error",
            request_id=request_id,
        )
