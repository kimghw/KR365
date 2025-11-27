-- FastAPI Request/Response Logging Tables for auth_mail_query.db
-- Based on logs.db structure

-- 1. API 요청/응답 로그 테이블
CREATE TABLE IF NOT EXISTS api_request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT (datetime('now')),
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    headers TEXT,  -- JSON string
    query_params TEXT,  -- JSON string
    request_body TEXT,  -- JSON string
    response_status INTEGER,
    response_body TEXT,  -- JSON string
    duration_ms INTEGER,
    client_ip TEXT,
    user_agent TEXT,
    dcr_client_id TEXT,  -- DCR client ID if authenticated
    azure_object_id TEXT,  -- Azure object ID if authenticated
    user_id TEXT,  -- Extracted user ID
    error_message TEXT,
    trace_id TEXT  -- For request tracing
);

-- 2. OAuth 플로우 로그 테이블
CREATE TABLE IF NOT EXISTS oauth_flow_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT (datetime('now')),
    flow_type TEXT NOT NULL,  -- 'register', 'authorize', 'token', 'refresh'
    dcr_client_id TEXT,
    azure_object_id TEXT,
    state TEXT,  -- OAuth state parameter
    redirect_uri TEXT,
    scope TEXT,
    grant_type TEXT,
    status TEXT,  -- 'success', 'failed', 'pending'
    error_code TEXT,
    error_description TEXT,
    duration_ms INTEGER
);

-- 3. MCP 프로토콜 로그 테이블
CREATE TABLE IF NOT EXISTS mcp_request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT (datetime('now')),
    jsonrpc_id TEXT,
    method TEXT NOT NULL,  -- 'initialize', 'tools/list', 'tools/call', etc.
    params TEXT,  -- JSON string
    result TEXT,  -- JSON string
    error TEXT,  -- JSON string
    session_id TEXT,  -- MCP session ID
    dcr_client_id TEXT,
    user_id TEXT,
    duration_ms INTEGER
);

-- 4. 인증 시도 로그 테이블
CREATE TABLE IF NOT EXISTS auth_attempt_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT (datetime('now')),
    auth_type TEXT NOT NULL,  -- 'bearer', 'client_credentials', 'azure_ad'
    client_id TEXT,
    user_email TEXT,
    success BOOLEAN,
    failure_reason TEXT,
    client_ip TEXT,
    user_agent TEXT
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_api_logs_timestamp ON api_request_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_api_logs_client ON api_request_logs(dcr_client_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_api_logs_user ON api_request_logs(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_api_logs_path ON api_request_logs(path, method, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_oauth_logs_client ON oauth_flow_logs(dcr_client_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_oauth_logs_type ON oauth_flow_logs(flow_type, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_mcp_logs_session ON mcp_request_logs(session_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_logs_method ON mcp_request_logs(method, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_auth_logs_timestamp ON auth_attempt_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_auth_logs_email ON auth_attempt_logs(user_email, timestamp DESC);