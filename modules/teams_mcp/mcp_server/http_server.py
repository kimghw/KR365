"""HTTP MCP Server for Teams Chat (Pure FastAPI)

This server uses FastAPI for both MCP protocol implementation and OpenAPI documentation.
"""

import json
import secrets
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from mcp.server import NotificationOptions, Server
from pydantic import BaseModel, Field

from infra.core.logger import get_logger
from modules.teams_mcp.handlers import TeamsHandlers

logger = get_logger(__name__)


class HTTPStreamingTeamsServer:
    """HTTP Streaming-based MCP Server for Teams Chat (Pure FastAPI)"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8004):
        self.host = host
        self.port = port

        # MCP Server
        self.mcp_server = Server("teams-server")

        # MCP Handlers
        self.handlers = TeamsHandlers()

        # Active sessions
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # Create FastAPI app
        self.app = self._create_app()

        logger.info(f"🚀 HTTP Streaming Teams Server initialized on port {port}")

    async def _handle_mcp_request(self, request: Request):
        """Handle MCP JSON-RPC request"""
        # Common headers
        base_headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS, DELETE",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, MCP-Session-Id, MCP-Protocol-Version",
            "Access-Control-Expose-Headers": "MCP-Session-Id",
        }

        # Bearer token authentication handled by unified_http_server middleware
        # request.state.azure_token is available if ENABLE_OAUTH_AUTH=true

        # Read and parse request
        try:
            body = await request.body()
            if not body:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32700, "message": "Empty request body"},
                    },
                    status_code=400,
                    headers=base_headers,
                )

            try:
                rpc_request = json.loads(body)
            except json.JSONDecodeError as e:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
                    },
                    status_code=400,
                    headers=base_headers,
                )
        except Exception as e:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
                },
                status_code=500,
                headers=base_headers,
            )

        # Extract request details
        method = rpc_request.get("method")
        params = rpc_request.get("params", {}) or {}
        request_id = rpc_request.get("id")

        logger.info(f"📨 Received RPC request: {method} with id: {request_id}")

        # Handle notification (no id) - return 202 with no body
        if request_id is None:
            logger.info(f"📤 Handling notification: {method}")
            return Response(status_code=202, headers=base_headers)

        # Process based on method
        logger.info(f"📤 Processing method: {method} with params: {params}")

        if method == "initialize":
            # Initialize session
            session_id = secrets.token_urlsafe(24)
            caps = self.mcp_server.get_capabilities(
                notification_options=NotificationOptions(), experimental_capabilities={}
            )

            # Fix null fields to empty objects/lists for spec compliance
            caps_dict = caps.model_dump()
            if caps_dict.get("logging") is None:
                caps_dict["logging"] = {}
            if caps_dict.get("resources") is None:
                caps_dict["resources"] = {"listChanged": False}
            if caps_dict.get("tools") is None:
                caps_dict["tools"] = {"listChanged": True}
            if caps_dict.get("prompts") is None:
                caps_dict["prompts"] = {"listChanged": False}
            if caps_dict.get("completions") is None:
                caps_dict.pop("completions", None)

            self.sessions[session_id] = {
                "initialized": True,
                "capabilities": caps_dict,
            }

            # Use the protocol version requested by the client
            requested_version = params.get("protocolVersion", "2025-06-18")

            # Add session header
            headers = base_headers.copy()
            headers["MCP-Session-Id"] = session_id
            headers["MCP-Protocol-Version"] = requested_version
            headers["Access-Control-Expose-Headers"] = "MCP-Session-Id, MCP-Protocol-Version"

            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": requested_version,
                    "capabilities": caps_dict,
                    "serverInfo": {
                        "name": "teams-server",
                        "title": "💬 Teams Chat MCP Server",
                        "version": "1.0.0",
                        "description": "MCP server for Microsoft Teams 1:1 and group chat management",
                    },
                    "instructions": "Microsoft Teams 1:1 채팅 및 그룹 채팅 메시지 관리를 위한 MCP 서버입니다.",
                },
            }
            logger.info(f"📤 Sending initialize response")
            return JSONResponse(response, headers=headers)

        elif method == "tools/list":
            # List tools
            tools = await self.handlers.handle_list_tools()

            # Clean up tool data - remove null fields
            tools_data = []
            for tool in tools:
                tool_dict = tool.model_dump()
                cleaned_tool = {}
                for key, value in tool_dict.items():
                    if value is not None:
                        cleaned_tool[key] = value
                tools_data.append(cleaned_tool)

            logger.info(f"📤 Returning {len(tools_data)} tools: {[t['name'] for t in tools_data]}")

            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": tools_data},
            }
            return JSONResponse(response, headers=base_headers)

        elif method == "tools/call":
            # Call tool
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            logger.info(f"🔧 [MCP Server] Received tools/call request")
            logger.info(f"  • Tool: {tool_name}")
            logger.info(f"  • Arguments: {json.dumps(tool_args, indent=2, ensure_ascii=False)}")

            # Extract authenticated user_id from request.state (set by auth middleware)
            authenticated_user_id = getattr(request.state, "user_id", None)
            if authenticated_user_id:
                logger.info(f"  • Authenticated user_id: {authenticated_user_id}")

            try:
                results = await self.handlers.handle_call_tool(tool_name, tool_args, authenticated_user_id)

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [content.model_dump() for content in results]},
                }
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32603, "message": str(e)},
                }

            return JSONResponse(response, headers=base_headers)

        elif method == "prompts/list":
            # No prompts supported
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"prompts": []},
            }
            return JSONResponse(response, headers=base_headers)

        elif method == "resources/list":
            # No resources supported
            response = {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
            return JSONResponse(response, headers=base_headers)

        else:
            # Unknown method
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
            return JSONResponse(response, status_code=404, headers=base_headers)

    def _create_app(self):
        """Create FastAPI application"""

        # Create FastAPI app
        app = FastAPI(
            title="💬 Teams Chat MCP Server",
            description="""
## Teams Chat MCP Server

MCP (Model Context Protocol) server for Microsoft Teams 1:1 and group chat management.

### Features
- 💬 Chat listing (1:1 and group chats)
- 📬 Message reading
- 📤 Message sending
- 🔐 Integrated authentication support

### MCP Protocol
This server implements the MCP protocol (JSON-RPC 2.0).
All MCP requests should be sent to the root endpoint `/` as POST requests.

### Tools Available
1. **teams_list_chats** - List user's chats (1:1 and group)
2. **teams_get_chat_messages** - Get messages from a chat
3. **teams_send_chat_message** - Send message to a chat
            """,
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
        )

        # Pydantic models for documentation
        class MCPRequest(BaseModel):
            jsonrpc: str = Field("2.0", description="JSON-RPC version")
            method: str = Field(..., description="MCP method name (e.g., 'tools/list', 'tools/call')")
            params: Optional[Dict[str, Any]] = Field(default={}, description="Method parameters")
            id: Optional[int] = Field(None, description="Request ID for correlation")

            class Config:
                json_schema_extra = {
                    "examples": [
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/list",
                            "params": {}
                        }
                    ]
                }

        class MCPResponse(BaseModel):
            jsonrpc: str = Field("2.0", description="JSON-RPC version")
            result: Optional[Dict[str, Any]] = Field(None, description="Result data")
            error: Optional[Dict[str, Any]] = Field(None, description="Error information")
            id: Optional[int] = Field(None, description="Request ID for correlation")

        # Root endpoint - MCP Protocol
        @app.post(
            "/",
            response_model=MCPResponse,
            summary="MCP Protocol Endpoint",
            description="""
Send MCP (Model Context Protocol) requests using JSON-RPC 2.0 format.

**Common Methods:**
- `initialize` - Initialize MCP session
- `tools/list` - List available tools
- `tools/call` - Call a specific tool
            """,
            tags=["MCP Protocol"],
        )
        async def mcp_endpoint(request: Request):
            """MCP Protocol endpoint"""
            return await self._handle_mcp_request(request)

        @app.get(
            "/",
            summary="Server Info",
            description="Get basic server information",
            tags=["Info"],
        )
        async def root():
            return {
                "name": "teams-server",
                "version": "1.0.0",
                "protocol": "mcp",
                "transport": "http",
                "endpoints": {"mcp": "/", "health": "/health", "info": "/info"},
            }

        @app.options("/")
        async def options_handler():
            return Response(
                "",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS, DELETE",
                    "Access-Control-Allow-Headers": "Content-Type, MCP-Session-Id, Authorization, MCP-Protocol-Version",
                    "Access-Control-Expose-Headers": "MCP-Session-Id",
                    "Access-Control-Max-Age": "3600",
                },
            )

        # Health check endpoint
        @app.get(
            "/health",
            tags=["Health"],
            summary="Health Check",
            description="Check if the server is running and healthy"
        )
        async def health_check():
            return {
                "status": "healthy",
                "server": "teams-server",
                "version": "1.0.0",
                "transport": "http-streaming",
            }

        # Server info endpoint
        @app.get(
            "/info",
            tags=["Info"],
            summary="Server Information",
            description="Get server information and capabilities"
        )
        async def server_info():
            return {
                "name": "teams-mcp-server",
                "version": "1.0.0",
                "protocol": "mcp",
                "transport": "http",
                "tools_count": 5,
                "documentation": f"http://{self.host}:{self.port}/docs"
            }

        # MCP Discovery endpoint
        @app.get(
            "/.well-known/mcp.json",
            tags=["MCP Discovery"],
            summary="MCP Server Discovery",
            description="RFC-style discovery endpoint for MCP servers"
        )
        async def mcp_discovery(request: Request):
            """MCP Server Discovery - /.well-known/mcp.json

            Note: OAuth is handled at the unified server level (root /.well-known/mcp.json)
            Individual MCP servers no longer expose OAuth endpoints to prevent
            Claude.ai from requesting separate authentication for each service.
            """
            return {
                "mcp_version": "1.0",
                "name": "Teams Chat MCP Server",
                "description": "Microsoft Teams 1:1 and group chat service",
                "version": "1.0.0",
                "capabilities": {
                    "tools": True,
                    "resources": False,
                    "prompts": False
                }
            }

        # Initialize OpenAI wrapper
        from modules.openai_wrapper import MCPOpenAIWrapper
        self.openai_wrapper = MCPOpenAIWrapper(
            mcp_server=self,
            server_name="teams",
            model_id="mcp-teams"
        )

        # OpenAI-compatible endpoints
        @app.post(
            "/v1/chat/completions",
            tags=["OpenAI Compatible"],
            summary="Chat Completions",
            description="OpenAI-compatible chat completions endpoint exposing MCP tools"
        )
        async def chat_completions(request: Request):
            """Handle OpenAI chat completions request"""
            from modules.openai_wrapper.schemas import ChatCompletionRequest
            body = await request.json()
            chat_request = ChatCompletionRequest(**body)
            response = await self.openai_wrapper.handle_chat_completions(chat_request)
            return response.model_dump(exclude_none=True)

        @app.get(
            "/v1/models",
            tags=["OpenAI Compatible"],
            summary="List Models",
            description="List available models (MCP server as a model)"
        )
        async def list_models():
            """Handle OpenAI list models request"""
            response = await self.openai_wrapper.handle_list_models()
            return response.model_dump()

        logger.info("📚 FastAPI app created - OpenAPI available at /docs")
        return app

    def run(self):
        """Run the HTTP MCP server"""
        logger.info(f"🚀 Starting HTTP Teams Server on http://{self.host}:{self.port}")
        logger.info(f"📝 MCP endpoint: http://{self.host}:{self.port}/")
        logger.info(f"📚 OpenAPI docs: http://{self.host}:{self.port}/docs")
        logger.info(f"💚 Health check: http://{self.host}:{self.port}/health")
        logger.info(f"ℹ️  Server info: http://{self.host}:{self.port}/info")

        # Run uvicorn with FastAPI app
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")


def main():
    """Main entry point"""
    server = HTTPStreamingTeamsServer()
    server.run()


if __name__ == "__main__":
    main()
