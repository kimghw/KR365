"""Pure FastAPI-based MCP Server for OneDrive

Simple and clean implementation using only FastAPI.
"""

import secrets
from typing import Any, Dict, Optional, List
from datetime import datetime

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from infra.core.logger import get_logger
from infra.utils.datetime_utils import utc_now_iso
from modules.onedrive_mcp.handlers import OneDriveHandlers

logger = get_logger(__name__)


# ============================================================================
# Pydantic Models for MCP Protocol
# ============================================================================

class MCPRequest(BaseModel):
    """MCP JSON-RPC 2.0 Request"""
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class MCPResponse(BaseModel):
    """MCP JSON-RPC 2.0 Response"""
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class ToolCallParams(BaseModel):
    """Tool call parameters"""
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# FastAPI MCP Server
# ============================================================================

class FastAPIOneDriveServer:
    """Pure FastAPI-based MCP Server for OneDrive"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8004):
        self.host = host
        self.port = port

        # MCP Handlers
        self.handlers = OneDriveHandlers()

        # Active sessions (in-memory storage)
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # Create FastAPI app
        self.app = self._create_app()

        logger.info(f"🚀 FastAPI OneDrive MCP Server initialized on port {port}")

    def _create_app(self) -> FastAPI:
        """Create FastAPI application"""

        app = FastAPI(
            title="📁 OneDrive MCP Server",
            description="""
## OneDrive MCP Server (Pure FastAPI)

MCP (Model Context Protocol) server for OneDrive file management.

### Features
- 📁 File and folder listing
- 📄 File reading (text and binary)
- ✍️ File writing and creation
- 🗑️ File and folder deletion
- 📂 Folder creation
- 🔍 File search

### Permissions Required
- **Files.Read** - Read files
- **Files.ReadWrite** - Read and write files
- **Files.ReadWrite.All** - Full access to all files

### MCP Protocol
This server implements the MCP protocol using JSON-RPC 2.0.
All MCP requests should be sent as POST to the root endpoint `/`.

### Available Tools
1. **list_files** - List files and folders
2. **read_file** - Read file content
3. **write_file** - Write or create file
4. **delete_file** - Delete file or folder
5. **create_folder** - Create new folder
            """,
            version="1.0.0",
            docs_url="/docs",
            redoc_url="/redoc",
        )

        # CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Mcp-Session-Id"],
        )

        # ====================================================================
        # MCP Protocol Endpoint
        # ====================================================================

        @app.post("/", response_model=MCPResponse)
        async def mcp_endpoint(request: Request):
            """
            MCP Protocol JSON-RPC 2.0 Endpoint

            Handles all MCP methods:
            - initialize
            - tools/list
            - tools/call
            - prompts/list
            - resources/list
            """
            # Parse request
            try:
                body = await request.body()
                if not body:
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "error": {"code": -32700, "message": "Empty request body"},
                        },
                        status_code=400,
                    )

                rpc_request = MCPRequest.parse_raw(body)
            except Exception as e:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
                    },
                    status_code=400,
                )

            # Extract request details
            method = rpc_request.method
            params = rpc_request.params or {}
            request_id = rpc_request.id

            logger.info(f"📨 MCP Request: {method} (id={request_id})")

            # Handle notification (no id) - return 202 Accepted
            if request_id is None:
                logger.info(f"📤 Notification: {method}")
                return JSONResponse({}, status_code=202)

            # Route to method handlers
            try:
                if method == "initialize":
                    result = await self._handle_initialize(params, request)
                elif method == "tools/list":
                    result = await self._handle_tools_list()
                elif method == "tools/call":
                    result = await self._handle_tools_call(request, params)
                elif method == "prompts/list":
                    result = {"prompts": []}
                elif method == "resources/list":
                    result = {"resources": []}
                else:
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32601, "message": f"Method not found: {method}"},
                        },
                        status_code=404,
                    )

                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": result,
                    }
                )

            except Exception as e:
                logger.error(f"❌ Error handling {method}: {e}", exc_info=True)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
                    },
                    status_code=500,
                )

        # ====================================================================
        # Health & Info Endpoints
        # ====================================================================

        @app.get("/health")
        async def health_check():
            """Health check endpoint"""
            return {
                "status": "healthy",
                "server": "onedrive-mcp-server",
                "version": "1.0.0",
                "timestamp": utc_now_iso(),
            }

        @app.post("/ping")
        async def ping(request: Request):
            """MCP ping endpoint for keep-alive as per MCP specification"""
            # Get request ID from headers or body
            request_id = None
            if request.headers.get("content-type") == "application/json":
                try:
                    body = await request.json()
                    request_id = body.get("id", "ping")
                except:
                    request_id = "ping"
            else:
                request_id = request.headers.get("x-request-id", "ping")

            return JSONResponse({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {}
            })

        @app.get("/info")
        async def server_info():
            """Server information endpoint"""
            return {
                "name": "onedrive-mcp-server",
                "version": "1.0.0",
                "protocol": "mcp",
                "transport": "http",
                "implementation": "pure-fastapi",
                "tools_count": 5,
                "endpoints": {
                    "mcp": "/",
                    "health": "/health",
                    "info": "/info",
                    "docs": "/docs",
                    "discovery": "/.well-known/mcp.json",
                },
            }

        @app.get("/.well-known/mcp.json")
        async def mcp_discovery(request: Request):
            """MCP Server Discovery

            Note: OAuth is handled at the unified server level (root /.well-known/mcp.json)
            Individual MCP servers no longer expose OAuth endpoints to prevent
            Claude.ai from requesting separate authentication for each service.
            """
            return {
                "mcp_version": "1.0",
                "name": "OneDrive MCP Server",
                "description": "OneDrive file management service with read/write capabilities",
                "version": "1.0.0",
                "capabilities": {
                    "tools": True,
                    "resources": False,
                    "prompts": False
                }
            }

        return app

    # ========================================================================
    # MCP Method Handlers
    # ========================================================================

    async def _handle_initialize(self, params: Dict[str, Any], request: Request) -> Dict[str, Any]:
        """Handle initialize method"""
        # Create new session
        session_id = secrets.token_urlsafe(24)
        protocol_version = params.get("protocolVersion", "2025-06-18")

        # Store session
        self.sessions[session_id] = {
            "initialized": True,
            "protocol_version": protocol_version,
            "created_at": utc_now_iso(),
        }

        logger.info(f"✅ Session created: {session_id}")

        # Build capabilities
        capabilities = {
            "logging": {},
            "resources": {"listChanged": False},
            "tools": {"listChanged": True},
            "prompts": {"listChanged": False},
        }

        return {
            "protocolVersion": protocol_version,
            "capabilities": capabilities,
            "serverInfo": {
                "name": "onedrive-server",
                "title": "📁 OneDrive MCP Server",
                "version": "1.0.0",
                "description": "MCP server for OneDrive file management",
            },
            "instructions": "OneDrive 파일 읽기/쓰기/관리를 위한 MCP 서버입니다.",
        }

    async def _handle_tools_list(self) -> Dict[str, Any]:
        """Handle tools/list method"""
        tools = await self.handlers.handle_list_tools()

        # Convert Tool objects to dict
        tools_data = []
        for tool in tools:
            tool_dict = tool.model_dump()
            # Remove None values
            cleaned_tool = {k: v for k, v in tool_dict.items() if v is not None}
            tools_data.append(cleaned_tool)

        logger.info(f"📋 Returning {len(tools_data)} tools")

        return {"tools": tools_data}

    async def _handle_tools_call(self, request, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call method"""
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        logger.info(f"🔧 Calling tool: {tool_name}")
        logger.info(f"   Arguments: {tool_args}")

        # Extract authenticated user_id from request.state (set by auth middleware)
        authenticated_user_id = getattr(request.state, "user_id", None)
        if authenticated_user_id:
            logger.info(f"  • Authenticated user_id: {authenticated_user_id}")

        # Call handler
        results = await self.handlers.handle_call_tool(tool_name, tool_args, authenticated_user_id)

        # Convert TextContent to dict
        content_data = [content.model_dump() for content in results]

        return {"content": content_data}

    # ========================================================================
    # Server Run
    # ========================================================================

    def run(self):
        """Run the FastAPI server"""
        logger.info("=" * 80)
        logger.info(f"🚀 Starting FastAPI OneDrive MCP Server")
        logger.info("=" * 80)
        logger.info(f"📝 MCP endpoint: http://{self.host}:{self.port}/")
        logger.info(f"📚 OpenAPI docs: http://{self.host}:{self.port}/docs")
        logger.info(f"💚 Health check: http://{self.host}:{self.port}/health")
        logger.info(f"🔍 Discovery: http://{self.host}:{self.port}/.well-known/mcp.json")
        logger.info("=" * 80)

        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")


# Alias for backward compatibility
HTTPStreamingOneDriveServer = FastAPIOneDriveServer


def main():
    """Main entry point"""
    server = FastAPIOneDriveServer()
    server.run()


if __name__ == "__main__":
    main()
