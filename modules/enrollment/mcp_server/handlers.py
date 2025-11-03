"""Authentication and Account MCP Handlers

This module provides MCP handlers for authentication and account management.
Integrates both MCP tool definitions and business logic.
"""

import json
import os
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from mcp.types import Tool, TextContent

from infra.core.database import get_database_manager
from infra.core.logger import get_logger
from modules.enrollment.auth import get_auth_orchestrator, AuthStartRequest
from modules.enrollment.auth._auth_helpers import auth_validate_oauth_credentials

logger = get_logger(__name__)


class AuthAccountHandlers:
    """Authentication and Account handlers for MCP server"""

    def __init__(self):
        """Initialize authentication and account handlers"""
        self.db = get_database_manager()
        self.project_root = Path(__file__).parent.parent.parent.parent  # MailQueryWithMCP root
        self.enrollment_dir = self.project_root / "data" / "enrollment"

        # Initialize database tables
        self._initialize_tables()

        logger.info("✅ AuthAccountHandlers initialized")

    def _initialize_tables(self):
        """Create database tables if they don't exist"""
        try:
            # accounts 테이블 생성
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL UNIQUE,
                    user_name TEXT,
                    email TEXT NOT NULL,
                    oauth_client_id TEXT NOT NULL,
                    oauth_client_secret TEXT NOT NULL,
                    oauth_tenant_id TEXT NOT NULL,
                    oauth_redirect_uri TEXT,
                    enrollment_file_path TEXT,
                    delegated_permissions TEXT,
                    auth_type TEXT DEFAULT 'Authorization Code Flow',
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    access_token TEXT,
                    refresh_token TEXT,
                    token_expiry TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    last_sync_time TEXT,
                    last_used_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Add last_used_at column if it doesn't exist (for existing databases)
            try:
                self.db.execute_query("""
                    ALTER TABLE accounts ADD COLUMN last_used_at TEXT
                """)
                logger.info("✅ Added last_used_at column to accounts table")
            except Exception as e:
                # Column already exists or other error - safe to ignore
                if "duplicate column name" not in str(e).lower():
                    logger.debug(f"last_used_at column may already exist: {str(e)}")

            # account_audit_logs 테이블 생성
            self.db.execute_query("""
                CREATE TABLE IF NOT EXISTS account_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (account_id) REFERENCES accounts(id)
                )
            """)

            logger.info("✅ Database tables initialized (accounts, account_audit_logs)")

        except Exception as e:
            logger.error(f"Failed to initialize tables: {str(e)}")
            raise

    async def handle_list_tools(self) -> List[Tool]:
        """
        List all available tools (authentication + account)

        Returns:
            List of Tool objects
        """
        return [
            Tool(
                name="register_account",
                description="Register a new email account with OAuth credentials. Saves account to database for future authentication. Use 'use_env_vars' to control whether to load from environment variables.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "use_env_vars": {
                            "type": "boolean",
                            "description": "If true, loads all account information from AUTO_REGISTER_* environment variables. Set to true when you don't have user_id, oauth_client_id, oauth_client_secret, or oauth_tenant_id readily available and want to use environment variables instead. If false (default), you must provide all required parameters directly."
                        },
                        "user_id": {
                            "type": "string",
                            "description": "User ID (e.g., 'kimghw'). Required if use_env_vars is false"
                        },
                        "email": {
                            "type": "string",
                            "description": "Email address (e.g., 'kimghw@krs.co.kr'). Required if use_env_vars is false"
                        },
                        "user_name": {
                            "type": "string",
                            "description": "User display name. Optional, defaults to user_id if not provided"
                        },
                        "oauth_client_id": {
                            "type": "string",
                            "description": "Microsoft Azure App OAuth Client ID. Required if use_env_vars is false"
                        },
                        "oauth_client_secret": {
                            "type": "string",
                            "description": "Microsoft Azure App OAuth Client Secret. Required if use_env_vars is false"
                        },
                        "oauth_tenant_id": {
                            "type": "string",
                            "description": "Microsoft Azure AD Tenant ID. Required if use_env_vars is false"
                        },
                        "oauth_redirect_uri": {
                            "type": "string",
                            "description": "OAuth redirect URI. Optional, defaults based on RENDER environment if not provided"
                        },
                    },
                    "required": []
                }
            ),
            Tool(
                name="get_account_status",
                description="Get detailed status and authentication information for a specific account. Shows token status, expiry time, and account details.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "User ID to query"
                        }
                    },
                    "required": ["user_id"]
                }
            ),
            Tool(
                name="start_authentication",
                description="Start OAuth authentication flow for a registered account. Returns an authentication URL that MUST be opened in a browser to complete Microsoft login.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "User ID (must be already registered). Required if use_auto_select is false."
                        },
                        "use_auto_select": {
                            "type": "boolean",
                            "description": "If true, automatically selects the most recently created active account from the database. Set to true when you don't have a specific user_id. If false (default), user_id is required."
                        }
                    },
                    "required": []
                }
            ),
            Tool(
                name="list_active_accounts",
                description="List all active accounts with detailed information including token status and creation date.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
        ]

    async def handle_call_tool(self, name: str, arguments: dict, authenticated_user_id: str = None) -> List[TextContent]:
        """
        Handle tool calls

        Args:
            name: Tool name
            arguments: Tool arguments
            authenticated_user_id: User ID from OAuth authentication

        Returns:
            List of TextContent with tool results
        """
        logger.info(f"🔐 [Auth/Account Handler] Handling tool: {name} (user: {authenticated_user_id})")

        try:
            if name == "register_account":
                result = await self._register_account(arguments)
                return [TextContent(type="text", text=result)]

            elif name == "get_account_status":
                result = await self._get_account_status(arguments)
                return [TextContent(type="text", text=result)]

            elif name == "start_authentication":
                result = await self._start_authentication(arguments)
                return [TextContent(type="text", text=result)]

            elif name == "list_active_accounts":
                result = await self._list_active_accounts(authenticated_user_id)
                return [TextContent(type="text", text=result)]

            else:
                error_msg = f"Unknown tool: {name}"
                logger.error(error_msg)
                return [TextContent(type="text", text=f"❌ Error: {error_msg}")]

        except Exception as e:
            error_msg = f"Tool '{name}' failed: {str(e)}"
            logger.error(error_msg)
            return [TextContent(type="text", text=f"❌ Error: {error_msg}")]

    # ========================================================================
    # Private implementation methods
    # ========================================================================

    async def _register_account(self, arguments: Dict[str, Any]) -> str:
        """
        Register a new account with OAuth credentials

        Args:
            arguments: Dict containing:
                - use_env_vars (bool): If True, load from AUTO_REGISTER_* environment variables
                - user_id, email, oauth_* credentials: Required if use_env_vars is False

        Returns:
            Registration result message
        """
        try:
            # Check if using environment variables
            use_env_vars = arguments.get("use_env_vars", False)

            if use_env_vars:
                # Load all data from environment variables
                user_id = os.getenv("AUTO_REGISTER_USER_ID")
                email = os.getenv("AUTO_REGISTER_EMAIL")
                oauth_client_id = os.getenv("AUTO_REGISTER_OAUTH_CLIENT_ID")
                oauth_client_secret = os.getenv("AUTO_REGISTER_OAUTH_CLIENT_SECRET")
                oauth_tenant_id = os.getenv("AUTO_REGISTER_OAUTH_TENANT_ID")
                user_name = os.getenv("AUTO_REGISTER_USER_NAME") or (user_id if user_id else "")
                oauth_redirect_uri = os.getenv("AUTO_REGISTER_OAUTH_REDIRECT_URI")

                # Load delegated permissions from environment variable
                delegated_permissions_env = os.getenv("AUTO_REGISTER_DELEGATED_PERMISSIONS")
                if delegated_permissions_env:
                    # Parse comma-separated permissions
                    delegated_permissions = [p.strip() for p in delegated_permissions_env.split(",") if p.strip()]
                else:
                    # Use default permissions if not specified
                    delegated_permissions = ["Mail.ReadWrite", "Mail.Send", "offline_access"]

                # Validate that all required env vars are set
                missing_env_vars = []
                if not user_id:
                    missing_env_vars.append("AUTO_REGISTER_USER_ID")
                if not email:
                    missing_env_vars.append("AUTO_REGISTER_EMAIL")
                if not oauth_client_id:
                    missing_env_vars.append("AUTO_REGISTER_OAUTH_CLIENT_ID")
                if not oauth_client_secret:
                    missing_env_vars.append("AUTO_REGISTER_OAUTH_CLIENT_SECRET")
                if not oauth_tenant_id:
                    missing_env_vars.append("AUTO_REGISTER_OAUTH_TENANT_ID")

                if missing_env_vars:
                    return f"""❌ Error: use_env_vars=true이지만 필수 환경변수가 설정되지 않았습니다:
{chr(10).join(f'  - {var}' for var in missing_env_vars)}

환경변수를 설정하거나 use_env_vars=false로 직접 파라미터를 전달하세요."""

                logger.info(f"✅ 환경변수에서 계정 정보 로드: {user_id} ({email})")
                logger.info(f"   - Permissions: {', '.join(delegated_permissions)}")

            else:
                # Load from arguments
                user_id = arguments.get("user_id")
                email = arguments.get("email")
                oauth_client_id = arguments.get("oauth_client_id")
                oauth_client_secret = arguments.get("oauth_client_secret")
                oauth_tenant_id = arguments.get("oauth_tenant_id")
                user_name = arguments.get("user_name") or (user_id if user_id else "")
                oauth_redirect_uri = arguments.get("oauth_redirect_uri")

                # Load delegated permissions from arguments
                delegated_permissions = arguments.get("delegated_permissions")
                if not delegated_permissions:
                    # Use default permissions if not specified
                    delegated_permissions = ["Mail.ReadWrite", "Mail.Send", "offline_access"]

                # Validate required fields
                missing_fields = []
                if not user_id:
                    missing_fields.append("user_id")
                if not email:
                    missing_fields.append("email")
                if not oauth_client_id:
                    missing_fields.append("oauth_client_id")
                if not oauth_client_secret:
                    missing_fields.append("oauth_client_secret")
                if not oauth_tenant_id:
                    missing_fields.append("oauth_tenant_id")

                if missing_fields:
                    return f"""❌ Error: 필수 파라미터가 누락되었습니다: {', '.join(missing_fields)}

다음 중 하나를 선택하세요:
1. 누락된 파라미터를 모두 제공
2. use_env_vars=true로 설정하여 환경변수 사용"""

                logger.info(f"✅ 파라미터로부터 계정 정보 로드: {user_id} ({email})")
                logger.info(f"   - Permissions: {', '.join(delegated_permissions)}")

            # Set default redirect URI if not provided
            if not oauth_redirect_uri:
                oauth_redirect_uri = (
                    "https://mailquery-mcp-server.onrender.com/enrollment/callback"
                    if os.getenv("RENDER")
                    else "http://localhost:9999/enrollment/callback"
                )

            # Validate OAuth credentials format
            is_valid, error_msg = auth_validate_oauth_credentials(
                oauth_client_id,
                oauth_client_secret,
                oauth_tenant_id
            )
            if not is_valid:
                logger.error(f"OAuth 자격 증명 검증 실패: {error_msg}")
                return f"❌ OAuth 자격 증명 포맷 오류:\n{error_msg}"

            # Check if account exists
            existing = self.db.fetch_one(
                "SELECT id, user_id FROM accounts WHERE user_id = ?",
                (user_id,)
            )

            # Create enrollment file
            enrollment_file = self.enrollment_dir / f"{user_id}.yaml"

            # Validate delegated_permissions scope before creating enrollment data
            from modules.enrollment.account._scope_validator import validate_delegated_scope

            permissions_str = delegated_permissions
            if isinstance(delegated_permissions, list):
                permissions_str = ' '.join(delegated_permissions)

            is_valid, valid_scopes, invalid_scopes = validate_delegated_scope(permissions_str)

            if not is_valid:
                logger.warning(
                    f"⚠️ 허용되지 않은 scope 발견: {invalid_scopes}\n"
                    f"   허용된 scope만 사용합니다: {valid_scopes}"
                )

            enrollment_data = {
                "account": {
                    "email": email,
                    "name": user_name,
                    "user_id": user_id
                },
                "microsoft_graph": {
                    "client_id": oauth_client_id,
                    "client_secret": oauth_client_secret,
                    "tenant_id": oauth_tenant_id
                },
                "oauth": {
                    "auth_type": "Authorization Code Flow",
                    "redirect_uri": oauth_redirect_uri,
                    "delegated_permissions": valid_scopes  # Use only validated scopes
                }
            }

            # Save enrollment file
            self.enrollment_dir.mkdir(parents=True, exist_ok=True)

            # 호출 스택 정보 가져오기
            import traceback
            import inspect

            # 현재 함수 정보
            current_frame = inspect.currentframe()
            caller_frame = current_frame.f_back if current_frame else None
            caller_function = caller_frame.f_code.co_name if caller_frame else "unknown"
            caller_file = caller_frame.f_code.co_filename if caller_frame else "unknown"
            caller_line = caller_frame.f_lineno if caller_frame else 0

            logger.warning(f"📄 YAML 파일 생성 시작:")
            logger.warning(f"   ├─ 파일 경로: {enrollment_file}")
            logger.warning(f"   ├─ 생성 함수: _register_account")
            logger.warning(f"   ├─ 호출자: {caller_function}")
            logger.warning(f"   └─ 호출 위치: {caller_file}:{caller_line}")

            # 호출 스택 출력
            stack = traceback.extract_stack()
            logger.warning(f"📋 호출 스택 추적 (최근 5개):")
            for i, frame in enumerate(stack[-5:], 1):
                logger.warning(f"   [{i}] {frame.filename}:{frame.lineno} in {frame.name}")

            with open(enrollment_file, 'w', encoding='utf-8') as f:
                yaml.dump(enrollment_data, f, default_flow_style=False, allow_unicode=True)

            logger.warning(f"✅ YAML 파일 생성 완료: {enrollment_file}")

            # Encrypt client secret
            from modules.enrollment.account import AccountCryptoHelpers
            crypto_helper = AccountCryptoHelpers()
            encrypted_secret = crypto_helper.account_encrypt_sensitive_data(oauth_client_secret)

            # Permissions JSON (use only validated scopes)
            permissions_json = json.dumps(valid_scopes)

            # Prepare source information message
            if use_env_vars:
                source_info = "\n데이터 소스: 환경변수 사용"
            else:
                source_info = "\n데이터 소스: 직접 입력"

            if existing:
                # Update existing account
                from datetime import datetime, timezone
                current_time = datetime.now(timezone.utc).isoformat()

                self.db.execute_query("""
                    UPDATE accounts
                    SET user_name = ?, email = ?,
                        oauth_client_id = ?, oauth_client_secret = ?,
                        oauth_tenant_id = ?, oauth_redirect_uri = ?,
                        enrollment_file_path = ?,
                        delegated_permissions = ?,
                        auth_type = COALESCE(auth_type, 'Authorization Code Flow'),
                        updated_at = ?
                    WHERE user_id = ?
                """, (user_name, email, oauth_client_id, encrypted_secret, oauth_tenant_id,
                      oauth_redirect_uri, str(enrollment_file), permissions_json, current_time, user_id))

                logger.info(f"Account updated: {user_id}")

                return f"""✅ 계정 업데이트 완료

사용자 ID: {user_id}
이메일: {email}
Enrollment 파일: {enrollment_file}
상태: 업데이트됨{source_info}

다음 단계:
start_authentication 도구로 OAuth 인증을 진행하세요."""

            else:
                # Insert new account
                from datetime import datetime, timezone
                current_time = datetime.now(timezone.utc).isoformat()

                self.db.execute_query("""
                    INSERT INTO accounts (
                        user_id, user_name, email,
                        oauth_client_id, oauth_client_secret, oauth_tenant_id, oauth_redirect_uri,
                        enrollment_file_path, delegated_permissions, auth_type,
                        status, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Authorization Code Flow', 'ACTIVE', 1, ?, ?)
                """, (user_id, user_name, email, oauth_client_id, encrypted_secret, oauth_tenant_id,
                      oauth_redirect_uri, str(enrollment_file), permissions_json, current_time, current_time))

                logger.info(f"New account registered: {user_id}")

                return f"""✅ 계정 등록 완료

사용자 ID: {user_id}
이메일: {email}
Enrollment 파일: {enrollment_file}
권한: {', '.join(delegated_permissions)}
상태: 새로 생성됨{source_info}

다음 단계:
start_authentication 도구로 OAuth 인증을 진행하세요."""

        except Exception as e:
            error_msg = f"계정 등록 실패: {str(e)}"
            logger.error(error_msg)
            return f"❌ Error: {error_msg}"

    async def _get_account_status(self, arguments: Dict[str, Any]) -> str:
        """
        Get detailed status of specific account

        Args:
            arguments: Dict containing user_id (optional - auto-selects if empty)

        Returns:
            Account status information
        """
        try:
            user_id = arguments.get("user_id", "").strip()

            # user_id가 없으면 데이터베이스에서 활성 계정 자동 선택
            if not user_id:
                active_account = self.db.fetch_one(
                    "SELECT user_id FROM accounts WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
                )
                if not active_account:
                    return "❌ Error: 활성 계정이 없습니다. 계정을 먼저 등록하세요."
                user_id = active_account['user_id']
                logger.info(f"Auto-selected user_id: {user_id}")

            account = self.db.fetch_one(
                """
                SELECT user_id, user_name, email, status, is_active,
                       access_token, refresh_token, token_expiry,
                       oauth_client_id, oauth_tenant_id, enrollment_file_path,
                       last_sync_time, created_at, updated_at
                FROM accounts
                WHERE user_id = ?
                """,
                (user_id,)
            )

            # 폴백 1: 계정이 없음
            if not account:
                return self._format_enrollment_template(
                    user_id,
                    reason="계정을 찾을 수 없습니다"
                )

            account_dict = dict(account)

            # 토큰 상태 상세 진단
            has_access_token = bool(account_dict.get('access_token'))
            has_refresh_token = bool(account_dict.get('refresh_token'))
            token_expiry = account_dict.get('token_expiry')

            token_status = "❌ 토큰 없음"
            token_detail = ""
            if has_access_token or has_refresh_token:
                if token_expiry:
                    try:
                        expiry_dt = datetime.fromisoformat(
                            token_expiry.replace("Z", "+00:00")
                        )
                        # 타임존 정보가 없으면 UTC로 간주
                        if expiry_dt.tzinfo is None:
                            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                        now_utc = datetime.now(timezone.utc)

                        if expiry_dt < now_utc:
                            token_status = f"❌ 만료됨"
                            token_detail = f"만료 시간: {token_expiry}"
                        else:
                            remaining = expiry_dt - now_utc
                            hours = remaining.total_seconds() / 3600
                            token_status = f"✅ 유효"
                            token_detail = f"만료까지: {hours:.1f}시간 ({token_expiry})"
                    except Exception as e:
                        logger.warning(f"토큰 만료 시간 파싱 실패: {e}")
                        token_status = "⚠️  토큰 있으나 만료시간 파싱 실패"
                        token_detail = f"원본 값: {token_expiry}"
                else:
                    token_status = "⚠️  토큰 있으나 만료시간 없음"
                    token_detail = ""
            else:
                token_detail = "start_authentication 도구로 인증하세요"

            # OAuth 설정 상태
            has_oauth = all([
                account_dict.get('oauth_client_id'),
                account_dict.get('oauth_tenant_id')
            ])
            oauth_status = "✅ 설정됨" if has_oauth else "❌ 설정 안됨"

            # enrollment 파일 상태
            enrollment_path = account_dict.get('enrollment_file_path')
            if enrollment_path and Path(enrollment_path).exists():
                enrollment_status = "✅ 존재함"
            elif enrollment_path:
                enrollment_status = f"⚠️  경로 있으나 파일 없음"
            else:
                enrollment_status = "❌ 경로 없음"

            # 활성 상태
            is_active = account_dict.get('is_active', False)
            active_status = "✅ 활성" if is_active else "❌ 비활성"

            result = f"""📊 계정 상태 상세 정보

사용자 ID: {account_dict.get('user_id', 'N/A')}
이름: {account_dict.get('user_name', 'N/A')}
이메일: {account_dict.get('email', 'N/A')}

상태: {account_dict.get('status', 'N/A')}
활성 상태: {active_status}

🔐 토큰 정보:
  Access Token: {'✅ 있음' if has_access_token else '❌ 없음'}
  Refresh Token: {'✅ 있음' if has_refresh_token else '❌ 없음'}
  토큰 유효성: {token_status}
  {token_detail}

⚙️  OAuth 설정: {oauth_status}
📁 Enrollment 파일: {enrollment_status}

마지막 동기화: {account_dict.get('last_sync_time', 'N/A')}
생성일: {account_dict.get('created_at', 'N/A')}
수정일: {account_dict.get('updated_at', 'N/A')}"""

            # 권장 사항 추가
            recommendations = []
            if not has_oauth:
                recommendations.append("⚠️  OAuth 설정이 없습니다 → register_account 도구로 등록하세요")
            if not (has_access_token or has_refresh_token):
                recommendations.append("⚠️  토큰이 없습니다 → start_authentication 도구로 인증하세요")
            elif token_status.startswith("❌ 만료"):
                recommendations.append("⚠️  토큰이 만료되었습니다 → start_authentication 도구로 재인증하세요")
            if not is_active:
                recommendations.append("⚠️  계정이 비활성화되었습니다 → 활성화 필요")

            if recommendations:
                result += "\n\n📌 권장 사항:\n  " + "\n  ".join(recommendations)

            return result

        except Exception as e:
            error_msg = f"계정 상태 조회 실패: {str(e)}"
            logger.error(error_msg)
            return f"❌ Error: {error_msg}"

    async def _start_authentication(self, arguments: Dict[str, Any]) -> str:
        """
        Start OAuth authentication process

        Args:
            arguments: Dict containing:
                - user_id (optional): 특정 계정 지정
                - use_auto_select (bool): True이면 최신 활성 계정 자동 선택

        Returns:
            Authentication URL or error message
        """
        try:
            user_id = arguments.get("user_id", "").strip()
            use_auto_select = arguments.get("use_auto_select", False)

            # Case 1: user_id 제공
            if user_id:
                logger.info(f"✅ 지정된 user_id 사용: {user_id}")

            # Case 2: use_auto_select=True
            elif use_auto_select:
                logger.info("use_auto_select=true - 최신 활성 계정 자동 선택")
                active_account = self.db.fetch_one(
                    "SELECT user_id FROM accounts WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
                )
                if not active_account:
                    return """❌ Error: use_auto_select=true이지만 활성 계정이 없습니다.

다음 중 하나를 선택하세요:
1. user_id를 제공하여 특정 계정 인증
2. register_account로 계정을 먼저 등록"""

                user_id = active_account['user_id']
                logger.info(f"✅ 자동 선택된 계정: {user_id}")

            # Case 3: 둘 다 없음
            else:
                return """❌ Error: user_id 또는 use_auto_select=true가 필요합니다.

다음 중 하나를 선택하세요:
1. user_id를 제공하여 특정 계정 인증
2. use_auto_select=true로 설정하여 자동 계정 선택"""

            # Use AuthOrchestrator (환경변수 기반 자동 등록 포함)
            # AuthOrchestrator가 계정 존재 확인 및 자동 등록을 처리
            orchestrator = get_auth_orchestrator()
            request = AuthStartRequest(user_id=user_id)
            response = await orchestrator.auth_orchestrator_start_authentication(request)

            return f"""🔐 OAuth 인증 시작

사용자 ID: {user_id}
세션 ID: {response.session_id}
만료 시간: {response.expires_at}

🌐 **인증 URL:**

```
{response.auth_url}
```

[Microsoft 로그인 페이지 열기]({response.auth_url})

⚠️  **중요:** 위 링크를 클릭하거나 URL을 브라우저에 붙여넣어 Microsoft 로그인을 완료해야 합니다.
브라우저에서 로그인 후 권한 승인을 완료하면 자동으로 인증이 완료됩니다.

✅ 인증 완료 후 `get_account_status` 도구로 상태를 확인할 수 있습니다."""

        except Exception as e:
            error_msg = f"인증 시작 실패: {str(e)}"
            logger.error(error_msg)

            # 폴백 3: 인증 시작 실패 → 상세 진단 정보 반환
            return self._format_auth_failure_diagnosis(user_id, str(e))

    async def _list_active_accounts(self, authenticated_user_id: str = None) -> str:
        """
        List active accounts (filtered by authenticated user)

        Args:
            authenticated_user_id: User ID from OAuth authentication

        Returns:
            Formatted list of active accounts
        """
        try:
            # Only show accounts for the authenticated user
            if authenticated_user_id:
                query = """
                    SELECT user_id, user_name, email, status,
                           oauth_tenant_id, oauth_client_id,
                           token_expiry, created_at
                    FROM accounts
                    WHERE is_active = 1 AND user_id = ?
                    ORDER BY user_id
                """
                accounts = self.db.fetch_all(query, (authenticated_user_id,))
            else:
                # Fallback: show all active accounts (backward compatibility)
                query = """
                    SELECT user_id, user_name, email, status,
                           oauth_tenant_id, oauth_client_id,
                           token_expiry, created_at
                    FROM accounts
                    WHERE is_active = 1
                    ORDER BY user_id
                """
                accounts = self.db.fetch_all(query)

            if not accounts:
                return "활성화된 계정이 없습니다."

            account_list = ["📊 활성 계정 목록:\n", "=" * 50 + "\n"]

            for idx, account in enumerate(accounts, 1):
                account_dict = dict(account)
                user_id = account_dict.get('user_id', 'N/A')
                email = account_dict.get('email', 'N/A')
                tenant_id = account_dict.get('oauth_tenant_id', '')
                client_id = account_dict.get('oauth_client_id', '')
                created_at = account_dict.get('created_at', 'N/A')

                account_list.append(f"\n{idx}. {user_id} ({email})\n")

                if tenant_id:
                    account_list.append(f"   Tenant: {tenant_id}\n")
                if client_id:
                    account_list.append(f"   Client: {client_id[:8]}...\n")
                if created_at:
                    account_list.append(f"   Created: {created_at}\n")

                # Token status
                token_expiry = account_dict.get('token_expiry')
                if token_expiry:
                    try:
                        expiry_dt = datetime.fromisoformat(
                            token_expiry.replace("Z", "+00:00")
                        )
                        # 타임존 정보가 없으면 UTC로 간주
                        if expiry_dt.tzinfo is None:
                            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                        now_utc = datetime.now(timezone.utc)
                        token_status = "만료" if expiry_dt < now_utc else "유효"
                        account_list.append(f"   Token: {token_status}\n")
                    except Exception as e:
                        logger.warning(f"토큰 만료 시간 파싱 실패: {e}")
                        account_list.append(f"   Token: 있음 (만료 시간 파싱 실패)\n")
                else:
                    account_list.append(f"   Token: 없음\n")

            return "".join(account_list)

        except Exception as e:
            logger.error(f"Error listing active accounts: {str(e)}")
            return f"❌ Error: Failed to list accounts - {str(e)}"

    # ========================================================================
    # Fallback helper methods
    # ========================================================================

    def _format_enrollment_template(
        self,
        user_id: str,
        email: str = "",
        reason: str = "계정이 등록되지 않았습니다"
    ) -> str:
        """
        enrollment 파일 양식을 텍스트로 반환

        Args:
            user_id: 사용자 ID
            email: 이메일 주소 (선택)
            reason: 양식 반환 이유

        Returns:
            enrollment 파일 양식 텍스트
        """
        email_placeholder = email if email else "your-email@example.com"

        return f"""❌ {reason}: {user_id}

📝 올바른 enrollment 파일 양식:

파일 경로: enrollment/{user_id}.yaml

---
account:
  email: {email_placeholder}
  name: YOUR NAME
  user_id: {user_id}
microsoft_graph:
  client_id: YOUR_AZURE_APP_CLIENT_ID
  client_secret: YOUR_AZURE_APP_CLIENT_SECRET
  tenant_id: YOUR_AZURE_TENANT_ID
oauth:
  auth_type: Authorization Code Flow
  delegated_permissions:
  - Mail.ReadWrite
  - Mail.Send
  - offline_access
  redirect_uri: http://localhost:9999/enrollment/callback
---

📌 다음 단계:
1. 위 양식대로 enrollment/{user_id}.yaml 파일을 생성하세요
2. Azure Portal에서 App 등록 후 client_id, client_secret, tenant_id를 입력하세요
3. register_account 도구를 사용하여 계정을 등록하세요
4. start_authentication 도구로 OAuth 인증을 진행하세요

💡 또는 register_account 도구에 직접 OAuth 정보를 입력하여 등록할 수도 있습니다."""

    def _format_auth_failure_diagnosis(self, user_id: str, error_message: str) -> str:
        """
        인증 실패 시 상세 진단 정보 반환

        Args:
            user_id: 사용자 ID
            error_message: 에러 메시지

        Returns:
            상세 진단 정보 텍스트
        """
        try:
            # 계정 정보 조회
            account = self.db.fetch_one(
                """SELECT user_id, email, status, is_active,
                          access_token, refresh_token, token_expiry,
                          oauth_client_id, oauth_tenant_id,
                          enrollment_file_path
                   FROM accounts WHERE user_id = ?""",
                (user_id,)
            )

            if not account:
                return f"""❌ 인증 실패: 계정을 찾을 수 없습니다

사용자 ID: {user_id}
에러: {error_message}

📌 해결 방법:
1. 입력한 user_id가 올바른지 확인하세요
2. register_account 도구로 계정을 먼저 등록하세요"""

            account_dict = dict(account)

            # 토큰 상태 진단
            has_access_token = bool(account_dict.get('access_token'))
            has_refresh_token = bool(account_dict.get('refresh_token'))
            token_expiry = account_dict.get('token_expiry')

            token_status = "❌ 토큰 없음"
            if has_access_token or has_refresh_token:
                if token_expiry:
                    try:
                        expiry_dt = datetime.fromisoformat(
                            token_expiry.replace("Z", "+00:00")
                        )
                        # 타임존 정보가 없으면 UTC로 간주
                        if expiry_dt.tzinfo is None:
                            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                        now_utc = datetime.now(timezone.utc)

                        if expiry_dt < now_utc:
                            token_status = f"⚠️  토큰 만료됨 ({token_expiry})"
                        else:
                            token_status = f"✅ 토큰 유효 (만료: {token_expiry})"
                    except Exception as e:
                        logger.warning(f"토큰 만료 시간 파싱 실패: {e}")
                        token_status = f"⚠️  토큰 있으나 만료시간 파싱 실패 ({token_expiry})"
                else:
                    token_status = "⚠️  토큰 있으나 만료시간 없음"

            # OAuth 설정 진단
            has_oauth_config = all([
                account_dict.get('oauth_client_id'),
                account_dict.get('oauth_tenant_id')
            ])
            oauth_status = "✅ 설정됨" if has_oauth_config else "❌ 설정 안됨"

            # enrollment 파일 진단
            enrollment_path = account_dict.get('enrollment_file_path')
            enrollment_status = "❌ 경로 없음"
            if enrollment_path:
                file_path = Path(enrollment_path)
                if file_path.exists():
                    enrollment_status = f"✅ 존재함 ({enrollment_path})"
                else:
                    enrollment_status = f"⚠️  경로 있으나 파일 없음 ({enrollment_path})"

            return f"""❌ 인증 실패 진단 리포트

📋 입력 정보:
  사용자 ID: {user_id}

📊 데이터베이스 계정 상태:
  이메일: {account_dict.get('email', 'N/A')}
  상태: {account_dict.get('status', 'N/A')}
  활성화: {'✅ 예' if account_dict.get('is_active') else '❌ 아니오'}

🔐 토큰 상태:
  Access Token: {'✅ 있음' if has_access_token else '❌ 없음'}
  Refresh Token: {'✅ 있음' if has_refresh_token else '❌ 없음'}
  토큰 유효성: {token_status}

⚙️  OAuth 설정:
  Client ID: {'✅ 설정됨' if account_dict.get('oauth_client_id') else '❌ 없음'}
  Tenant ID: {'✅ 설정됨' if account_dict.get('oauth_tenant_id') else '❌ 없음'}
  전체 OAuth 설정: {oauth_status}

📁 Enrollment 파일:
  {enrollment_status}

🔍 에러 메시지:
  {error_message}

📌 권장 해결 방법:
"""
            # 문제별 해결 방법 제시
            solutions = []

            if not has_oauth_config:
                solutions.append("1. OAuth 설정이 없습니다 → register_account 도구로 OAuth 정보를 등록하세요")

            if not (has_access_token or has_refresh_token):
                solutions.append("2. 토큰이 없습니다 → start_authentication 도구로 인증을 진행하세요")
            elif token_status.startswith("⚠️"):
                solutions.append("2. 토큰이 만료되었습니다 → start_authentication 도구로 재인증하세요")

            if not account_dict.get('is_active'):
                solutions.append("3. 계정이 비활성화되었습니다 → 데이터베이스에서 is_active를 1로 변경하세요")

            if not enrollment_path or not Path(enrollment_path).exists():
                solutions.append(f"4. enrollment 파일이 없습니다 → enrollment/{user_id}.yaml 파일을 생성하세요")

            if not solutions:
                solutions.append("• 로그를 확인하여 추가 정보를 확인하세요")
                solutions.append("• Microsoft 로그인 시 올바른 계정으로 로그인했는지 확인하세요")

            return f"{f'  ' + chr(10) + '  '.join(solutions)}"

        except Exception as e:
            logger.error(f"진단 정보 생성 실패: {str(e)}")
            return f"""❌ 인증 실패

사용자 ID: {user_id}
에러: {error_message}

⚠️  상세 진단 정보를 생성하는데 실패했습니다: {str(e)}

📌 기본 해결 방법:
1. get_account_status 도구로 계정 상태를 확인하세요
2. list_active_accounts 도구로 등록된 계정 목록을 확인하세요
3. 필요시 register_account 도구로 계정을 다시 등록하세요"""
