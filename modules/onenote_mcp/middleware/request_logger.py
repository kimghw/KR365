"""
FastAPI Request/Response Logging Middleware
Logs all API requests and responses to DCR OAuth database
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from infra.core.logger import get_logger, log_api_request, log_api_response

logger = get_logger(__name__)


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """Middleware to log all API requests and responses"""

    def __init__(self, app: ASGIApp, db_path: str = None):
        super().__init__(app)
        if db_path:
            self.db_path = db_path
        else:
            # config.json에서 DCR OAuth 설정 읽기
            import os
            config_path = Path(__file__).parent.parent / "config.json"
            if config_path.exists():
                with open(config_path) as f:
                    config = json.load(f)
                    module_name = config.get("dcr_oauth", {}).get("module_name", "onenote")
                    db_name = f"auth_{module_name}.db"

                    # 환경 변수에서 DCR_DATABASE_PATH 확인
                    dcr_db_path = os.getenv("DCR_DATABASE_PATH")
                    if dcr_db_path:
                        self.db_path = dcr_db_path
                    else:
                        # 프로젝트 루트 기준 data 디렉토리
                        project_root = Path(__file__).parent.parent.parent.parent
                        self.db_path = str(project_root / "data" / db_name)
            else:
                # config.json이 없는 경우 기본값
                self.db_path = str(Path(__file__).parent.parent.parent.parent / "data/auth_onenote.db")

    def get_db_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)

    def log_request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        query_params: Dict[str, Any],
        body: Optional[str],
        response_status: int,
        response_body: Optional[str],
        duration_ms: int,
        client_ip: str,
        user_agent: str,
        dcr_client_id: Optional[str] = None,
        azure_object_id: Optional[str] = None,
        user_id: Optional[str] = None,
        error_message: Optional[str] = None,
        trace_id: Optional[str] = None
    ):
        """Log request to database"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO api_request_logs (
                    method, path, headers, query_params, request_body,
                    response_status, response_body, duration_ms,
                    client_ip, user_agent, dcr_client_id, azure_object_id,
                    user_id, error_message, trace_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                method, path,
                json.dumps(headers) if headers else None,
                json.dumps(query_params) if query_params else None,
                body,
                response_status,
                response_body,
                duration_ms,
                client_ip,
                user_agent,
                dcr_client_id,
                azure_object_id,
                user_id,
                error_message,
                trace_id
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log request: {str(e)}")

    def log_mcp_request(
        self,
        jsonrpc_id: Optional[str],
        method: str,
        params: Optional[Dict[str, Any]],
        result: Optional[Dict[str, Any]],
        error: Optional[Dict[str, Any]],
        session_id: Optional[str],
        dcr_client_id: Optional[str],
        user_id: Optional[str],
        duration_ms: int
    ):
        """Log MCP protocol request"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO mcp_request_logs (
                    jsonrpc_id, method, params, result, error,
                    session_id, dcr_client_id, user_id, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                jsonrpc_id,
                method,
                json.dumps(params) if params else None,
                json.dumps(result) if result else None,
                json.dumps(error) if error else None,
                session_id,
                dcr_client_id,
                user_id,
                duration_ms
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log MCP request: {str(e)}")

    def log_oauth_flow(
        self,
        flow_type: str,
        dcr_client_id: Optional[str],
        azure_object_id: Optional[str],
        state: Optional[str],
        redirect_uri: Optional[str],
        scope: Optional[str],
        grant_type: Optional[str],
        status: str,
        error_code: Optional[str],
        error_description: Optional[str],
        duration_ms: int
    ):
        """Log OAuth flow event"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO oauth_flow_logs (
                    flow_type, dcr_client_id, azure_object_id, state,
                    redirect_uri, scope, grant_type, status,
                    error_code, error_description, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                flow_type, dcr_client_id, azure_object_id, state,
                redirect_uri, scope, grant_type, status,
                error_code, error_description, duration_ms
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log OAuth flow: {str(e)}")

    async def dispatch(self, request: Request, call_next):
        """Process request and log it"""
        # Generate trace ID for this request
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id

        # Start timer
        start_time = time.time()

        # Get request details
        method = request.method
        path = request.url.path
        query_params = dict(request.query_params)
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "")

        # Get authentication info early for logging
        dcr_client_id = getattr(request.state, "dcr_client_id", None)
        azure_object_id = getattr(request.state, "azure_object_id", None)
        user_id = getattr(request.state, "user_id", None)

        # ✨ 표준화된 요청 로깅 (시작 시점)
        log_api_request(
            logger=logger,
            method=method,
            path=path,
            client_ip=client_ip,
            user_id=user_id,
            request_id=trace_id
        )

        # Get headers (filter sensitive data)
        headers = {}
        for key, value in request.headers.items():
            if key.lower() not in ["authorization", "cookie", "x-api-key"]:
                headers[key] = value
            else:
                headers[key] = "***REDACTED***"

        # Get request body (for non-GET requests)
        body = None
        if method != "GET":
            try:
                body_bytes = await request.body()
                if body_bytes:
                    body = body_bytes.decode('utf-8')
                    # Parse JSON to check for MCP protocol
                    try:
                        body_json = json.loads(body)
                        # Check if this is an MCP request
                        if "jsonrpc" in body_json and "method" in body_json:
                            # This is an MCP request
                            request.state.is_mcp = True
                            request.state.mcp_method = body_json.get("method")
                            request.state.mcp_id = body_json.get("id")
                            request.state.mcp_params = body_json.get("params")
                    except:
                        pass
            except:
                pass

        # Get authentication info from request.state (set by auth middleware)
        dcr_client_id = getattr(request.state, "dcr_client_id", None)
        azure_object_id = getattr(request.state, "azure_object_id", None)
        user_id = getattr(request.state, "user_id", None)

        # Process request
        response = None
        error_message = None
        response_body = None

        try:
            response = await call_next(request)

            # Capture response body
            if response.status_code < 400:
                # Try to get response body for successful requests
                if hasattr(response, "body"):
                    response_body = response.body.decode('utf-8') if response.body else None
            else:
                error_message = f"HTTP {response.status_code}"

        except Exception as e:
            error_message = str(e)
            logger.error(f"Request failed: {error_message}")
            response = Response(content=str(e), status_code=500)

        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)

        # ✨ 표준화된 응답 로깅
        log_api_response(
            logger=logger,
            method=method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=trace_id
        )

        # Log based on request type
        if path.startswith("/oauth/"):
            # OAuth flow logging
            flow_type = path.split("/")[-1]  # 'register', 'authorize', 'token', etc.
            status = "success" if response.status_code < 400 else "failed"

            self.log_oauth_flow(
                flow_type=flow_type,
                dcr_client_id=dcr_client_id,
                azure_object_id=azure_object_id,
                state=query_params.get("state"),
                redirect_uri=query_params.get("redirect_uri"),
                scope=query_params.get("scope"),
                grant_type=query_params.get("grant_type"),
                status=status,
                error_code=str(response.status_code) if response.status_code >= 400 else None,
                error_description=error_message,
                duration_ms=duration_ms
            )

        if getattr(request.state, "is_mcp", False):
            # MCP protocol logging
            self.log_mcp_request(
                jsonrpc_id=request.state.mcp_id,
                method=request.state.mcp_method,
                params=request.state.mcp_params,
                result=json.loads(response_body) if response_body and response.status_code == 200 else None,
                error={"message": error_message} if error_message else None,
                session_id=request.headers.get("mcp-session-id"),
                dcr_client_id=dcr_client_id,
                user_id=user_id,
                duration_ms=duration_ms
            )

        # Always log general API request
        self.log_request(
            method=method,
            path=path,
            headers=headers,
            query_params=query_params,
            body=body[:1000] if body else None,  # Limit body size
            response_status=response.status_code,
            response_body=response_body[:1000] if response_body else None,  # Limit response size
            duration_ms=duration_ms,
            client_ip=client_ip,
            user_agent=user_agent,
            dcr_client_id=dcr_client_id,
            azure_object_id=azure_object_id,
            user_id=user_id,
            error_message=error_message,
            trace_id=trace_id
        )

        # Add trace ID to response headers
        response.headers["X-Trace-Id"] = trace_id

        return response
