"""
Azure AD configuration loading/saving for DCR OAuth module.

These helpers operate with a DCRService-like instance that exposes:
- db_path, crypto, allowed_users, dcr_bearer_ttl_seconds
- _execute_query, _fetch_one methods (delegates are fine)
"""

import os
from infra.core.logger import get_logger

logger = get_logger(__name__)


def ensure_dcr_schema(service) -> None:
    """Initialize DCR V3 schema using module-specific table names."""
    import sqlite3
    try:
        conn = sqlite3.connect(service.db_path)  # Use db_path instead of config.dcr_database_path

        # 모듈별 테이블 이름 생성
        module_suffix = f"_{service.module_name}" if service.module_name != "default" else ""

        # 기본 테이블이 없으면 생성 (dcr_azure_app은 공통)
        schema_sql = f"""
        -- Azure AD App Configuration (shared across modules)
        CREATE TABLE IF NOT EXISTS dcr_azure_app (
            application_id TEXT PRIMARY KEY,
            client_secret TEXT NOT NULL,
            tenant_id TEXT DEFAULT 'common',
            redirect_uri TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Azure Users (shared across modules)
        CREATE TABLE IF NOT EXISTS dcr_azure_users (
            object_id TEXT PRIMARY KEY,
            application_id TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at TIMESTAMP NOT NULL,
            scope TEXT,
            user_email TEXT,
            user_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (application_id) REFERENCES dcr_azure_app(application_id) ON DELETE CASCADE
        );

        -- DCR Clients (module-specific)
        CREATE TABLE IF NOT EXISTS dcr_clients{module_suffix} (
            dcr_client_id TEXT PRIMARY KEY,
            dcr_client_secret TEXT NOT NULL,
            dcr_client_name TEXT,
            dcr_redirect_uris TEXT NOT NULL,
            dcr_grant_types TEXT NOT NULL,
            dcr_requested_scope TEXT,
            azure_application_id TEXT,
            azure_object_id TEXT,
            user_email TEXT,
            mcp_session_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (azure_object_id) REFERENCES dcr_azure_users(object_id) ON DELETE SET NULL
        );

        -- DCR Tokens (module-specific)
        CREATE TABLE IF NOT EXISTS dcr_tokens{module_suffix} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dcr_token_value TEXT NOT NULL,
            dcr_client_id TEXT NOT NULL,
            dcr_token_type TEXT NOT NULL,
            azure_object_id TEXT,
            expires_at TIMESTAMP,
            dcr_status TEXT DEFAULT 'active',
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dcr_client_id) REFERENCES dcr_clients{module_suffix}(dcr_client_id) ON DELETE CASCADE,
            FOREIGN KEY (azure_object_id) REFERENCES dcr_azure_users(object_id) ON DELETE SET NULL
        );

        -- Indexes for module-specific tables
        CREATE INDEX IF NOT EXISTS idx_dcr_clients{module_suffix}_azure_object_id
            ON dcr_clients{module_suffix}(azure_object_id);
        CREATE INDEX IF NOT EXISTS idx_dcr_clients{module_suffix}_mcp_session
            ON dcr_clients{module_suffix}(mcp_session_id);
        CREATE INDEX IF NOT EXISTS idx_dcr_tokens{module_suffix}_client_id
            ON dcr_tokens{module_suffix}(dcr_client_id);
        CREATE INDEX IF NOT EXISTS idx_dcr_tokens{module_suffix}_status
            ON dcr_tokens{module_suffix}(dcr_status);

        -- API Request Logs table for middleware logging
        CREATE TABLE IF NOT EXISTS api_request_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            method TEXT,
            path TEXT,
            headers TEXT,
            query_params TEXT,
            request_body TEXT,
            response_status INTEGER,
            response_body TEXT,
            duration_ms INTEGER,
            client_ip TEXT,
            user_agent TEXT,
            dcr_client_id TEXT,
            azure_object_id TEXT,
            user_id TEXT,
            error_message TEXT,
            trace_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_api_request_logs_created_at
            ON api_request_logs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_api_request_logs_trace_id
            ON api_request_logs(trace_id);
        """

        conn.executescript(schema_sql)
        conn.commit()
        conn.close()
        logger.info(f"✅ DCR V3 schema initialized with module suffix: {module_suffix}")
    except Exception as e:
        logger.error(f"❌ DCR V3 schema initialization failed: {e}")
        raise


def revoke_active_dcr_tokens_on_config_change(service) -> None:
    """Revoke active DCR Bearer/refresh tokens when Azure config changes."""
    try:
        # Get table name
        tokens_table = service._get_table_name("dcr_tokens")

        count_row = service._fetch_one(
            f"""
            SELECT COUNT(*) FROM {tokens_table}
            WHERE dcr_status = 'active'
              AND dcr_token_type IN ('Bearer', 'refresh')
            """
        )
        active_count = int(count_row[0]) if count_row and count_row[0] is not None else 0

        service._execute_query(
            f"""
            UPDATE {tokens_table}
            SET dcr_status = 'revoked'
            WHERE dcr_status = 'active'
              AND dcr_token_type IN ('Bearer', 'refresh')
            """
        )
        logger.info(f"🔒 Revoked {active_count} active DCR tokens due to Azure config change")
    except Exception as e:
        logger.error(f"❌ Failed to revoke DCR tokens on config change: {e}")


def save_azure_config_to_db(service) -> None:
    """Persist Azure config from service fields to DB if present."""
    if not all([service.azure_application_id, service.azure_client_secret]):
        return
    try:
        # ALWAYS use the redirect URI from service (which already prioritizes env)
        redirect_uri = service.azure_redirect_uri

        existing = service._fetch_one(
            "SELECT application_id FROM dcr_azure_app WHERE application_id = ?",
            (service.azure_application_id,),
        )
        if existing:
            service._execute_query(
                """
                UPDATE dcr_azure_app
                SET client_secret = ?, tenant_id = ?, redirect_uri = ?
                WHERE application_id = ?
                """,
                (
                    service.crypto.account_encrypt_sensitive_data(service.azure_client_secret),
                    service.azure_tenant_id,
                    redirect_uri,  # Use the redirect_uri from service
                    service.azure_application_id,
                ),
            )
            logger.info(f"✅ Updated Azure config in dcr_azure_app: {service.azure_application_id}, redirect_uri: {redirect_uri}")
        else:
            service._execute_query(
                """
                INSERT INTO dcr_azure_app (application_id, client_secret, tenant_id, redirect_uri)
                VALUES (?, ?, ?, ?)
                """,
                (
                    service.azure_application_id,
                    service.crypto.account_encrypt_sensitive_data(service.azure_client_secret),
                    service.azure_tenant_id,
                    redirect_uri,  # Use the redirect_uri from service
                ),
            )
            logger.info(f"✅ Saved Azure config to dcr_azure_app: {service.azure_application_id}, redirect_uri: {redirect_uri}")
    except Exception as e:
        logger.error(f"❌ Failed to save Azure config to DB: {e}")


def load_azure_config(service) -> None:
    """Load Azure config from DB or environment and keep DB in sync.

    Priority:
    1) dcr_azure_app table; if env overrides present (client_id and secret), update
       DB and revoke active tokens.
    2) Environment variables, then persist to DB if complete.
    """
    # 1) Load from DB first
    result = service._fetch_one(
        "SELECT application_id, client_secret, tenant_id, redirect_uri FROM dcr_azure_app LIMIT 1"
    )

    env_app_id = os.getenv("DCR_AZURE_CLIENT_ID")
    env_secret = os.getenv("DCR_AZURE_CLIENT_SECRET")
    env_tenant = os.getenv("DCR_AZURE_TENANT_ID", "common")

    # Generate redirect URI from DCR_OAUTH_ENDPOINT if available
    env_endpoint = os.getenv("DCR_OAUTH_ENDPOINT")
    env_redirect = os.getenv("DCR_OAUTH_REDIRECT_URI")

    # If DCR_OAUTH_ENDPOINT is set but not DCR_OAUTH_REDIRECT_URI, auto-generate it
    if env_endpoint and not env_redirect:
        # Parse the endpoint to extract protocol and domain
        from urllib.parse import urlparse
        parsed = urlparse(env_endpoint)

        # Extract protocol and domain
        protocol = parsed.scheme  # http or https
        domain = parsed.netloc  # e.g., kimghw.org

        # Generate redirect URI with subdomain based on module_name
        # module_name is used for identifying the specific MCP server (mail_query, onenote, teams, etc.)
        if service.module_name and service.module_name != "default":
            # Replace underscore with hyphen for valid subdomain
            subdomain = service.module_name.replace('_', '-')
            env_redirect = f"{protocol}://{subdomain}.{domain}/oauth/callback"
        else:
            env_redirect = f"{protocol}://{domain}/oauth/callback"

        logger.info(f"🔄 Auto-generated redirect URI from DCR_OAUTH_ENDPOINT: {env_redirect}")

    # Debug logging for environment variables
    logger.info(f"🔍 Environment variables check:")
    logger.info(f"  DCR_AZURE_CLIENT_ID: {'Set' if env_app_id else 'Not set'}")
    logger.info(f"  DCR_AZURE_CLIENT_SECRET: {'Set' if env_secret else 'Not set'}")
    logger.info(f"  DCR_AZURE_TENANT_ID: {env_tenant}")
    logger.info(f"  DCR_OAUTH_ENDPOINT: {env_endpoint if env_endpoint else 'Not set'}")
    logger.info(f"  DCR_OAUTH_REDIRECT_URI: {env_redirect if env_redirect else 'Not set (auto-generated)' if env_endpoint else 'Not set'}")

    if result:
        current_app_id = result[0]
        current_secret = service.crypto.account_decrypt_sensitive_data(result[1]) if result[1] else None
        current_tenant = result[2] or "common"
        current_redirect = result[3]

        service.azure_application_id = current_app_id
        service.azure_client_secret = current_secret
        service.azure_tenant_id = current_tenant
        # ALWAYS prefer env_redirect from DCR_OAUTH_REDIRECT_URI over DB value
        # This ensures .env value takes precedence during runtime
        if env_redirect:
            service.azure_redirect_uri = env_redirect
            if env_redirect != current_redirect:
                logger.info(f"🔄 Using redirect URI from environment: {env_redirect} (DB has: {current_redirect})")
        else:
            service.azure_redirect_uri = current_redirect
            logger.info(f"📌 Using redirect URI from DB: {current_redirect}")

        # Apply env overrides if both id and secret are present
        if env_app_id and env_secret:
            def _norm(v: str | None) -> str:
                return (v or "").strip()

            changes = []
            if _norm(env_app_id) != _norm(current_app_id):
                changes.append("application_id")
            if _norm(env_secret) != _norm(current_secret):
                changes.append("client_secret")
            if env_tenant is not None and _norm(env_tenant) != _norm(current_tenant):
                changes.append("tenant_id")
            if env_redirect is not None and _norm(env_redirect) != _norm(current_redirect):
                changes.append("redirect_uri")

            if changes:
                try:
                    set_clauses = []
                    params = []
                    set_clauses.append("application_id = ?")
                    params.append(env_app_id)
                    set_clauses.append("client_secret = ?")
                    params.append(service.crypto.account_encrypt_sensitive_data(env_secret))
                    if env_tenant is not None:
                        set_clauses.append("tenant_id = ?")
                        params.append(env_tenant)
                    if env_redirect is not None:
                        set_clauses.append("redirect_uri = ?")
                        params.append(env_redirect)

                    update_sql = f"UPDATE dcr_azure_app SET {', '.join(set_clauses)} WHERE application_id = ?"
                    params.append(current_app_id)
                    service._execute_query(update_sql, tuple(params))

                    # Update in-memory
                    service.azure_application_id = env_app_id
                    service.azure_client_secret = env_secret
                    service.azure_tenant_id = env_tenant if env_tenant is not None else current_tenant
                    service.azure_redirect_uri = env_redirect if env_redirect is not None else current_redirect

                    revoke_active_dcr_tokens_on_config_change(service)
                    logger.info(
                        f"♻️ Updated dcr_azure_app from environment and revoked active DCR tokens (changed: {', '.join(changes)})"
                    )
                except Exception as e:
                    logger.error(f"❌ Failed to update dcr_azure_app from environment: {e}")
            else:
                logger.info(f"✅ Loaded Azure config from dcr_azure_app: {service.azure_application_id}")
        else:
            logger.info(f"✅ Loaded Azure config from dcr_azure_app: {service.azure_application_id}")
    else:
        # 2) Fallback to environment and persist if complete
        service.azure_application_id = env_app_id
        service.azure_client_secret = env_secret
        service.azure_tenant_id = env_tenant

        # Use auto-generated or explicit redirect URI
        if env_redirect:
            service.azure_redirect_uri = env_redirect
        elif hasattr(service.config, 'oauth_redirect_uri'):
            service.azure_redirect_uri = service.config.oauth_redirect_uri
        else:
            # If no redirect URI is available, log a warning
            service.azure_redirect_uri = None

        if service.azure_application_id and service.azure_client_secret:
            if service.azure_redirect_uri:
                logger.info(f"✅ Loaded Azure config from environment: {service.azure_application_id}, redirect_uri: {service.azure_redirect_uri}")
            else:
                logger.warning(f"⚠️ Loaded Azure config from environment: {service.azure_application_id}, but redirect_uri is missing")
            save_azure_config_to_db(service)
        else:
            logger.warning("⚠️ No Azure config found. DCR will not work.")

