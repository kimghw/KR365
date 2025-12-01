f"""DCR (Dynamic Client Registration) Service V3
RFC 7591 준수 동적 클라이언트 등록 서비스
명확한 Azure/DCR 분리 및 Azure Portal 용어 사용
"""

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from infra.core.database import get_database_manager
from infra.core.logger import get_logger, log_db_operation
from modules.enrollment.account import AccountCryptoHelpers

from .azure_config import ensure_dcr_schema as _ensure_dcr_schema_helper
from .azure_config import load_azure_config as _load_azure_config_helper
from .azure_config import (
    revoke_active_dcr_tokens_on_config_change as _revoke_tokens_helper,
)
from .azure_config import save_azure_config_to_db as _save_azure_config_helper
from .db_service import DCRDatabaseService
from .pkce import verify_pkce as _verify_pkce_helper

logger = get_logger(__name__)


class DCRService:
    """
    Dynamic Client Registration Service V3

    테이블 구조:
    - dcr_azure_app: Azure 앱 정보 (Portal에서 생성)
    - dcr_azure_users: Azure 사용자별 토큰 (Azure AD에서 받음)
    - dcr_clients: Claude 클라이언트 등록 (DCR이 생성)
    - dcr_tokens: Claude 토큰 (DCR이 발급)
    """

    def __init__(self, server_name: str = "default", module_name: str = None):
        from infra.core.config import get_config

        self.config = get_config()
        self.server_name = server_name
        self.module_name = module_name or server_name  # 모듈 이름 (테이블 접미사로 사용)

        # DB 경로 설정: 환경변수 > auth_{module_name}.db
        from pathlib import Path

        db_path_env = os.getenv("DCR_DATABASE_PATH")
        if db_path_env:
            self.db_path = db_path_env
        else:
            # 상대 경로를 절대 경로로 변환
            # module_name이 있으면 그것을 사용, 없으면 server_name 사용
            db_name = self.module_name if self.module_name else self.server_name
            project_root = Path(__file__).parent.parent.parent
            self.db_path = str(project_root / f"data/auth_{db_name}.db")
            logger.info(f"📁 DB path set to: {self.db_path}")

        logger.info(f"📦 Module name: {self.module_name} (tables will use suffix: _{self.module_name})")

        self.crypto = AccountCryptoHelpers()

        # DB 로깅 활성화 여부 (환경변수로 제어) - 가장 먼저 설정
        self.db_logging_enabled = os.getenv("DCR_DB_LOGGING", "false").lower() in [
            "true",
            "1",
            "yes",
            "on",
        ]
        if self.db_logging_enabled:
            logger.info("🔍 DCR Database logging is ENABLED")

        # DCR 전용 데이터베이스 서비스 초기화 (db_path 전달)
        self.db_service = DCRDatabaseService(db_path=self.db_path)

        # 스키마 초기화 (가장 먼저 실행)
        self._ensure_dcr_schema()

        # Azure AD 설정 로드
        self._load_azure_config()

        # 허용된 도메인 목록
        allowed_domains_str = os.getenv("DCR_ALLOWED_DOMAINS", "").strip()
        self.allowed_domains = (
            [
                domain.strip().lower()
                for domain in allowed_domains_str.split(",")
                if domain.strip()
            ]
            if allowed_domains_str
            else []
        )

        # DCR Bearer 토큰 TTL (초)
        ttl_seconds = int(self.config.dcr_access_token_ttl_seconds)
        if ttl_seconds <= 0:
            logger.warning(
                "⚠️ DCR_ACCESS_TOKEN_TTL_SECONDS가 0 이하입니다. 기본값 3600초를 사용합니다."
            )
            ttl_seconds = 3600

        # 환경 변수 설정 여부 확인 및 로그
        env_ttl = os.getenv("DCR_ACCESS_TOKEN_TTL_SECONDS")
        if env_ttl:
            logger.info(f"🔧 Bearer 토큰 TTL: {ttl_seconds}초 (환경 변수에서 설정됨)")
        else:
            logger.info(f"🔧 Bearer 토큰 TTL: {ttl_seconds}초 (하드코딩된 기본값)")

        self.dcr_bearer_ttl_seconds = ttl_seconds

        if self.allowed_domains:
            logger.info(
                f"✅ DCR access restricted to {len(self.allowed_domains)} domain(s): {', '.join(self.allowed_domains)}"
            )
        else:
            logger.warning("⚠️ DCR access allowed for ALL Azure users")

    def _log_db_operation(
        self, operation: str, query: str, params: tuple = (), affected_rows: int = None
    ):
        """데이터베이스 작업 로깅 (DCR_DB_LOGGING=true일 때만 활성화)

        Note: 표준화된 log_db_operation() 헬퍼 함수 사용
        """
        log_db_operation(
            logger=logger,
            operation=operation,
            query=query,
            params=params,
            affected_rows=affected_rows,
            enabled=self.db_logging_enabled
        )

    def _execute_query(self, query: str, params: tuple = (), user_email: str = None, client_id: str = None):
        """SQL 쿼리 실행 헬퍼 (새로운 DB 서비스 사용 + 로깅)"""
        # DB 로깅 (실행 전)
        if self.db_logging_enabled:
            self._log_db_operation("EXECUTE_START", query, params, None)

        try:
            result = self.db_service.execute_query(query, params, user_email, client_id)

            # DB 로깅 (실행 성공)
            if self.db_logging_enabled:
                affected_rows = result if isinstance(result, int) else None
                self._log_db_operation("EXECUTE_SUCCESS", query, params, affected_rows)

                # UPDATE/DELETE인데 영향받은 행이 0인 경우 경고
                if (
                    query.strip().upper().startswith(("UPDATE", "DELETE"))
                    and affected_rows == 0
                ):
                    logger.warning(
                        f"⚠️ {query.split()[0]} query affected 0 rows | Query: {query[:100]} | Params: {params}"
                    )

            return result
        except Exception as e:
            # DB 로깅 (실행 실패)
            if self.db_logging_enabled:
                logger.error(
                    f"❌ DB EXECUTE_ERROR: {str(e)} | Query: {query[:200]} | Params: {params}"
                )
            raise

    def _fetch_one(self, query: str, params: tuple = ()):
        """단일 행 조회 헬퍼 (새로운 DB 서비스 사용 + 로깅)"""
        result = self.db_service.fetch_one(query, params)

        # DB 로깅 (조회 후)
        if self.db_logging_enabled:
            found_rows = 1 if result else 0
            self._log_db_operation("FETCH_ONE", query, params, found_rows)

        # Row 객체를 튜플로 변환 (하위 호환성)
        return tuple(result) if result else None

    def _fetch_all(self, query: str, params: tuple = ()):
        """여러 행 조회 헬퍼 (새로운 DB 서비스 사용 + 로깅)"""
        results = self.db_service.fetch_all(query, params)

        # DB 로깅 (조회 후)
        if self.db_logging_enabled:
            found_rows = len(results) if results else 0
            self._log_db_operation("FETCH_ALL", query, params, found_rows)

        # Row 객체들을 튜플로 변환 (하위 호환성)
        return [tuple(row) for row in results]

    def _load_azure_config(self):
        """dcr_azure_app 테이블 또는 환경변수에서 Azure 설정 로드 (위임)"""
        _load_azure_config_helper(self)

    def _revoke_active_dcr_tokens_on_config_change(self):
        """Azure 설정 변경 시 활성화된 DCR Bearer/refresh 토큰을 revoke 처리 (위임)"""
        _revoke_tokens_helper(self)

    def _ensure_dcr_schema(self):
        """DCR V3 스키마 초기화 (위임)"""
        _ensure_dcr_schema_helper(self)

    def _save_azure_config_to_db(self):
        """환경변수에서 읽은 Azure 설정을 DB에 저장 (위임)"""
        _save_azure_config_helper(self)

    def _get_table_name(self, base_name: str) -> str:
        """Get module-specific table name."""
        if base_name in ["dcr_azure_app", "dcr_azure_users"]:
            # These tables are shared across modules
            return base_name
        elif self.module_name and self.module_name != "default":
            # Module-specific tables
            return f"{base_name}_{self.module_name}"
        else:
            # Default tables (no suffix)
            return base_name

    async def register_client(
        self, request_data: Dict[str, Any], mcp_session_id: str = None
    ) -> Dict[str, Any]:
        """RFC 7591: 동적 클라이언트 등록 (플랫폼별 독립 클라이언트)

        클라이언트 재사용 정책 (우선순위):
        1. **MCP Session 기반 재사용** (최우선)
           - mcp_session_id가 제공되면 같은 세션의 기존 클라이언트 재사용
           - 목적: 동일 MCP 세션 내에서 클라이언트 재생성 방지
           - 조건: mcp_session_id + azure_application_id 일치

        2. **인증된 사용자 클라이언트 재사용**
           - 같은 redirect_uri로 이미 로그인된 클라이언트 재사용
           - 목적: 사용자가 재로그인할 때 기존 클라이언트 활용
           - 조건: azure_application_id + redirect_uri + azure_object_id(NOT NULL) 일치
           - 장점: 기존 토큰 유지, 세션 연속성

        3. **미할당 클라이언트 재사용**
           - 로그인 전 상태의 클라이언트 재사용 (azure_object_id = NULL)
           - 목적: 등록 후 로그인 전 단계의 클라이언트 재활용
           - 조건: azure_application_id + redirect_uri + azure_object_id(NULL) 일치

        4. **새 클라이언트 생성**
           - 위 조건에 해당하지 않으면 새로운 클라이언트 생성
           - 초기 상태: azure_object_id = NULL, 로그인 후 update_client_user() 호출 필요

        Note:
        - 초기 등록 시에는 azure_object_id = NULL
        - 로그인 완료 후 update_client_user()로 사용자 정보 업데이트
        - 단위 테스트: tests/test_dcr_client_reuse.py 참조
        """
        if not all([self.azure_application_id, self.azure_client_secret]):
            raise ValueError("Azure AD configuration not available")

        # 요청 데이터
        client_name = request_data.get("client_name", "MCP Connector")
        redirect_uris = request_data.get("redirect_uris", [])
        grant_types = request_data.get(
            "grant_types", ["authorization_code", "refresh_token"]
        )
        scope = request_data.get(
            "scope", "Mail.Read Mail.Send Calendars.ReadWrite User.Read"
        )

        # redirect_uri가 없으면 에러
        if not redirect_uris:
            raise ValueError("redirect_uris is required")

        primary_redirect_uri = (
            redirect_uris[0] if isinstance(redirect_uris, list) else redirect_uris
        )

        # Get table names
        clients_table = self._get_table_name("dcr_clients")
        tokens_table = self._get_table_name("dcr_tokens")

        # 1. mcp_session_id가 있으면 같은 세션의 기존 클라이언트 재사용 (최우선)
        if mcp_session_id:
            session_query = f"""
            SELECT dcr_client_id, dcr_client_secret, created_at
            FROM {self._get_table_name('dcr_clients')}
            WHERE mcp_session_id = ?
              AND azure_application_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """

            session_client = self._fetch_one(
                session_query, (mcp_session_id, self.azure_application_id)
            )

            if session_client:
                dcr_client_id = session_client[0]
                dcr_client_secret = self.crypto.account_decrypt_sensitive_data(
                    session_client[1]
                )
                issued_at = int(datetime.fromisoformat(session_client[2]).timestamp())

                logger.info(
                    f"♻️ Reusing DCR client for MCP session {mcp_session_id}: {dcr_client_id}"
                )

                return {
                    "client_id": dcr_client_id,
                    "client_secret": dcr_client_secret,
                    "client_id_issued_at": issued_at,
                    "client_secret_expires_at": 0,
                    "grant_types": grant_types,
                    "client_name": client_name,
                    "redirect_uris": redirect_uris,
                    "scope": scope,
                }

        # 2. 같은 사용자의 최근 클라이언트 확인 (로그인 후 재사용)
        user_client_query = f"""
        SELECT dcr_client_id, dcr_client_secret, created_at, azure_object_id
        FROM {self._get_table_name('dcr_clients')}
        WHERE azure_application_id = ?
          AND json_extract(dcr_redirect_uris, '$[0]') = ?
          AND azure_object_id IS NOT NULL
        ORDER BY updated_at DESC
        LIMIT 1
        """

        user_client = self._fetch_one(
            user_client_query, (self.azure_application_id, primary_redirect_uri)
        )

        if user_client:
            # 같은 redirect_uri로 이미 로그인된 클라이언트 재사용
            dcr_client_id = user_client[0]
            dcr_client_secret = self.crypto.account_decrypt_sensitive_data(
                user_client[1]
            )
            issued_at = int(datetime.fromisoformat(user_client[2]).timestamp())
            existing_object_id = user_client[3]

            # mcp_session_id 업데이트
            if mcp_session_id:
                self._execute_query(
                    f"UPDATE {self._get_table_name('dcr_clients')} SET mcp_session_id = ?, updated_at = CURRENT_TIMESTAMP WHERE dcr_client_id = ?",
                    (mcp_session_id, dcr_client_id),
                )

            logger.info(
                f"♻️ Reusing authenticated DCR client for {primary_redirect_uri}: {dcr_client_id} (user: {existing_object_id})"
            )

            return {
                "client_id": dcr_client_id,
                "client_secret": dcr_client_secret,
                "client_id_issued_at": issued_at,
                "client_secret_expires_at": 0,
                "grant_types": grant_types,
                "client_name": client_name,
                "redirect_uris": redirect_uris,
                "scope": scope,
            }

        # 3. 미할당 클라이언트 확인 (로그인 전 상태)
        existing_query = f"""
        SELECT dcr_client_id, dcr_client_secret, created_at, azure_object_id
        FROM {self._get_table_name('dcr_clients')}
        WHERE azure_application_id = ?
          AND json_extract(dcr_redirect_uris, '$[0]') = ?
          AND azure_object_id IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """

        existing_client = self._fetch_one(
            existing_query, (self.azure_application_id, primary_redirect_uri)
        )

        if existing_client:
            # 기존 미할당 클라이언트 재사용 (로그인 전 상태)
            dcr_client_id = existing_client[0]
            dcr_client_secret = self.crypto.account_decrypt_sensitive_data(
                existing_client[1]
            )
            issued_at = int(datetime.fromisoformat(existing_client[2]).timestamp())

            # mcp_session_id 업데이트
            if mcp_session_id:
                self._execute_query(
                    f"UPDATE {self._get_table_name('dcr_clients')} SET mcp_session_id = ?, updated_at = CURRENT_TIMESTAMP WHERE dcr_client_id = ?",
                    (mcp_session_id, dcr_client_id),
                )

            logger.info(
                f"♻️ Reusing unassigned DCR client for {primary_redirect_uri}: {dcr_client_id}"
            )
        else:
            # 새 클라이언트 생성 (사용자 미할당 상태)
            dcr_client_id = f"dcr_{secrets.token_urlsafe(16)}"
            dcr_client_secret = secrets.token_urlsafe(32)
            issued_at = int(datetime.now(timezone.utc).timestamp())

            # dcr_clients 테이블에 저장 (azure_object_id = NULL, mcp_session_id 포함)
            query = f"""
            INSERT INTO {self._get_table_name('dcr_clients')} (
                dcr_client_id, dcr_client_secret, dcr_client_name,
                dcr_redirect_uris, dcr_grant_types, dcr_requested_scope,
                azure_application_id, azure_object_id, user_email, mcp_session_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
            """

            self._execute_query(
                query,
                (
                    dcr_client_id,
                    self.crypto.account_encrypt_sensitive_data(dcr_client_secret),
                    client_name,
                    json.dumps(redirect_uris),
                    json.dumps(grant_types),
                    scope,
                    self.azure_application_id,
                    mcp_session_id,
                ),
            )

            logger.info(
                f"✅ New unassigned DCR client registered: {dcr_client_id} (session: {mcp_session_id})"
            )

        return {
            "client_id": dcr_client_id,
            "client_secret": dcr_client_secret,
            "client_id_issued_at": issued_at,
            # client_secret_expires_at 생략 = 만료되지 않음 (RFC 7591)
            "grant_types": grant_types,
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "scope": scope,
        }

    def update_client_user(
        self,
        dcr_client_id: str,
        azure_object_id: str,
        user_email: str,
        redirect_uri: str,
        inferred_client_name: Optional[str] = None,
    ) -> str:
        """로그인 완료 후 클라이언트에 사용자 정보를 연결

        Args:
            dcr_client_id: 등록된 DCR 클라이언트 ID (새로 생성된 것)
            azure_object_id: Azure 사용자 Object ID
            user_email: 사용자 이메일
            redirect_uri: 클라이언트의 redirect URI
            inferred_client_name: redirect_uri에서 추론된 클라이언트 이름

        Returns:
            사용할 client_id (항상 현재 dcr_client_id 반환)
        """
        import json

        # 1. 현재 클라이언트 정보 조회
        current_client_query = f"""
        SELECT dcr_client_name, azure_object_id, dcr_redirect_uris, azure_application_id
        FROM {self._get_table_name('dcr_clients')}
        WHERE dcr_client_id = ?
        """
        current_client = self._fetch_one(current_client_query, (dcr_client_id,))

        if not current_client:
            raise ValueError(f"Client {dcr_client_id} not found")

        current_client_name = current_client[0]
        current_object_id = current_client[1]
        current_redirect_uris = (
            json.loads(current_client[2]) if current_client[2] else []
        )
        current_azure_app_id = current_client[3]

        # 2. 이미 연결되어 있으면 (동일한 object_id + redirect_uri)
        if (
            current_object_id == azure_object_id
            and redirect_uri in current_redirect_uris
        ):
            # client_name이 다르면 업데이트
            if inferred_client_name and current_client_name != inferred_client_name:
                logger.info(
                    f"🔄 Updating client_name: {current_client_name} -> {inferred_client_name}"
                )
                update_name_query = f"""
                UPDATE {self._get_table_name('dcr_clients')}
                SET dcr_client_name = ?, updated_at = CURRENT_TIMESTAMP
                WHERE dcr_client_id = ?
                """
                self._execute_query(
                    update_name_query, (inferred_client_name, dcr_client_id)
                )
                logger.info(
                    f"✅ Client {dcr_client_id} name updated to {inferred_client_name}"
                )
            else:
                logger.info(
                    f"✅ Client {dcr_client_id} already linked to user {user_email}"
                )
            return dcr_client_id

        # 3. 같은 redirect_uri + object_id + azure_application_id로 기존 클라이언트 검색
        # 가장 최근에 사용된 클라이언트를 찾음
        existing_client_query = f"""
        SELECT dcr_client_id, dcr_client_name, updated_at
        FROM {self._get_table_name('dcr_clients')}
        CROSS JOIN json_each(dcr_redirect_uris)
        WHERE azure_object_id = ?
          AND azure_application_id = ?
          AND json_each.value = ?
          AND dcr_client_id != ?
        ORDER BY updated_at DESC
        LIMIT 1
        """
        existing_client = self._fetch_one(
            existing_client_query,
            (azure_object_id, current_azure_app_id, redirect_uri, dcr_client_id),
        )

        if existing_client:
            existing_client_id = existing_client[0]
            existing_client_name = existing_client[1]
            existing_updated_at = existing_client[2]

            logger.info(
                f"🔍 Found existing client {existing_client_id} (name: {existing_client_name}, last_used: {existing_updated_at}) for same redirect_uri + object_id"
            )
            logger.info(
                f"🗑️ Deleting old client {existing_client_id} and replacing with new client {dcr_client_id}"
            )

            # ===== 트랜잭션으로 안전하게 처리 =====
            try:
                # Use transaction to ensure atomicity
                with self.db_service.transaction():
                    # 3-1) 기존 클라이언트의 활성 토큰들을 새 클라이언트로 이전
                    logger.info(
                        f"📦 Migrating tokens from {existing_client_id} to {dcr_client_id}"
                    )

                    migrate_tokens_query = f"""
                    UPDATE {self._get_table_name('dcr_tokens')}
                    SET dcr_client_id = ?
                    WHERE dcr_client_id = ?
                      AND dcr_status = 'active'
                    """
                    migrated_count = self._execute_query(
                        migrate_tokens_query, (dcr_client_id, existing_client_id)
                    )
                    logger.info(f"✅ Migrated {migrated_count} active tokens")

                    # 3-2) 기존 클라이언트 삭제
                    logger.info(f"🗑️ Deleting old client: {existing_client_id}")

                    delete_old_client_query = f"""
                    DELETE FROM {self._get_table_name('dcr_clients')}
                    WHERE dcr_client_id = ?
                    """
                    deleted_count = self._execute_query(delete_old_client_query, (existing_client_id,))

                    if deleted_count == 0:
                        raise ValueError(f"Failed to delete old client {existing_client_id}")

                    logger.info(f"✅ Old client deleted: {existing_client_id}")

                    # 3-3) 삭제 로그 기록
                    delete_log = {
                        "action": "client_replaced",
                        "deleted_client_id": existing_client_id,
                        "new_client_id": dcr_client_id,
                        "user_email": user_email,
                        "azure_object_id": azure_object_id,
                        "redirect_uri": redirect_uri,
                        "migrated_tokens": migrated_count,
                        "reason": "duplicate_client_detected_and_replaced",
                    }
                    logger.info(f"📝 Client replacement log: {json.dumps(delete_log)}")

            except Exception as e:
                logger.error(f"❌ Client replacement transaction failed: {str(e)}")
                logger.error(f"   Keeping both clients: {existing_client_id} (old), {dcr_client_id} (new)")
                # Transaction will be rolled back automatically
                # Continue with current client (new one) - it's already created
                logger.warning(f"⚠️ Proceeding with new client {dcr_client_id} due to replacement failure")

        # 4. 새로운 연결: 현재 클라이언트에 사용자 정보 + client_name 업데이트
        logger.info(
            f"🔄 Updating client {dcr_client_id} with user info: object_id={azure_object_id}, email={user_email}, name={inferred_client_name or current_client_name}"
        )

        update_query = f"""
        UPDATE {self._get_table_name('dcr_clients')}
        SET azure_object_id = ?, user_email = ?, dcr_client_name = ?, updated_at = CURRENT_TIMESTAMP
        WHERE dcr_client_id = ?
        """

        affected_rows = self._execute_query(
            update_query,
            (
                azure_object_id,
                user_email,
                inferred_client_name or current_client_name,
                dcr_client_id,
            ),
        )

        # UPDATE 결과 검증
        if affected_rows == 0:
            logger.error(
                f"❌ Failed to update client {dcr_client_id} - client not found or update failed"
            )
            # 실제 데이터 확인
            verify_query = f"SELECT dcr_client_id, azure_object_id, user_email FROM {self._get_table_name('dcr_clients')} WHERE dcr_client_id = ?"
            current_data = self._fetch_one(verify_query, (dcr_client_id,))
            if current_data:
                logger.error(
                    f"❌ Client exists but UPDATE failed. Current data: {current_data}"
                )
            else:
                logger.error(f"❌ Client {dcr_client_id} does not exist in database")
            raise ValueError(f"Failed to update client {dcr_client_id}")

        # 업데이트 성공 확인
        verify_query = f"SELECT azure_object_id, user_email, dcr_client_name FROM {self._get_table_name('dcr_clients')} WHERE dcr_client_id = ?"
        updated_data = self._fetch_one(verify_query, (dcr_client_id,))
        if updated_data:
            actual_object_id, actual_email, actual_name = updated_data
            if actual_object_id != azure_object_id:
                logger.error(
                    f"❌ UPDATE verification failed: azure_object_id mismatch. Expected: {azure_object_id}, Actual: {actual_object_id}"
                )
            else:
                logger.info(
                    f"✅ UPDATE verified: azure_object_id={actual_object_id}, email={actual_email}, name={actual_name}"
                )

        if existing_client:
            logger.info(
                f"✅ Replaced old client {existing_client_id} with new client {dcr_client_id} for user {user_email}"
            )
        else:
            logger.info(
                f"✅ Linked new client {dcr_client_id} to user {user_email} (object_id: {azure_object_id}, name: {inferred_client_name or current_client_name})"
            )

        # 5. 항상 현재(새로운) 클라이언트 ID 반환
        return dcr_client_id

    def save_azure_tokens_and_sync(
        self,
        *,
        azure_object_id: str,
        azure_access_token: str,
        azure_refresh_token: Optional[str],
        scope: str,
        user_email: Optional[str],
        user_name: Optional[str],
        azure_expires_at: datetime,
        sync_accounts: bool = True,
    ) -> None:
        f"""Persist Azure tokens to dcr_azure_users and sync to accounts table.

        This centralizes the path for saving Azure tokens so any caller
        (e.g., OAuth callback) can ensure graphapi accounts are updated.
        """
        if not azure_object_id:
            raise ValueError("azure_object_id is required")

        # Ensure dcr_azure_app exists before inserting into dcr_azure_users (FOREIGN KEY constraint)
        # This prevents "FOREIGN KEY constraint failed" when application_id is not in dcr_azure_app
        self._save_azure_config_to_db()

        # Store in dcr_azure_users (encrypted) using UPSERT (no DELETE)
        # NOTE: Avoid INSERT OR REPLACE because REPLACE deletes the existing row,
        # which triggers ON DELETE SET NULL on referencing tables.
        azure_query = """
            INSERT INTO dcr_azure_users (
                object_id, application_id, access_token, refresh_token, expires_at,
                scope, user_email, user_name, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(object_id) DO UPDATE SET
                application_id = excluded.application_id,
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                scope = excluded.scope,
                user_email = excluded.user_email,
                user_name = excluded.user_name,
                updated_at = CURRENT_TIMESTAMP
        """
        self._execute_query(
            azure_query,
            (
                azure_object_id,
                self.azure_application_id,
                self.crypto.account_encrypt_sensitive_data(azure_access_token),
                (
                    self.crypto.account_encrypt_sensitive_data(azure_refresh_token)
                    if azure_refresh_token
                    else None
                ),
                azure_expires_at,
                scope,
                user_email,
                user_name,
            ),
        )

        if sync_accounts:
            # Sync to accounts table using encrypted values
            encrypted_access = self.crypto.account_encrypt_sensitive_data(
                azure_access_token
            )
            encrypted_refresh = (
                self.crypto.account_encrypt_sensitive_data(azure_refresh_token)
                if azure_refresh_token
                else None
            )

            self._sync_with_accounts_table(
                azure_object_id=azure_object_id,
                user_email=user_email,
                user_name=user_name,
                encrypted_access_token=encrypted_access,
                encrypted_refresh_token=encrypted_refresh,
                azure_expires_at=azure_expires_at,
            )

    def get_client(self, dcr_client_id: str) -> Optional[Dict[str, Any]]:
        """DCR 클라이언트 정보 조회"""
        query = f"""
        SELECT dcr_client_id, dcr_client_secret, dcr_client_name, dcr_redirect_uris,
               dcr_grant_types, dcr_requested_scope, azure_application_id
        FROM {self._get_table_name('dcr_clients')}
        WHERE dcr_client_id = ?
        """

        result = self._fetch_one(query, (dcr_client_id,))

        if not result:
            return None

        return {
            "dcr_client_id": result[0],
            "dcr_client_secret": (
                self.crypto.account_decrypt_sensitive_data(result[1])
                if result[1]
                else None
            ),
            "dcr_client_name": result[2],
            "dcr_redirect_uris": json.loads(result[3]) if result[3] else [],
            "dcr_grant_types": json.loads(result[4]) if result[4] else [],
            "dcr_requested_scope": result[5],
            "azure_application_id": result[6],
            # Azure 설정 추가
            "azure_client_secret": self.azure_client_secret,
            "azure_tenant_id": self.azure_tenant_id,
            "azure_redirect_uri": self.azure_redirect_uri,
        }

    def verify_client_credentials(
        self, dcr_client_id: str, dcr_client_secret: str
    ) -> bool:
        f"""클라이언트 인증 정보 검증"""
        client = self.get_client(dcr_client_id)
        if not client:
            return False
        return secrets.compare_digest(
            client.get("dcr_client_secret", ""), dcr_client_secret
        )

    def create_authorization_code(
        self,
        dcr_client_id: str,
        redirect_uri: str,
        scope: str,
        state: Optional[str] = None,
        code_challenge: Optional[str] = None,
        code_challenge_method: Optional[str] = None,
    ) -> str:
        """Authorization code 생성 (PKCE 지원)

        Note: authorization_code는 사용자 로그인 후 리다이렉트 시 전달되는 일회성 코드입니다.
        10분 후 만료되며, 토큰 교환 시 즉시 'expired' 상태로 변경됩니다.
        임시 사용 후 즉시 폐기되므로 암호화하지 않습니다.
        """
        code = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        metadata = {"redirect_uri": redirect_uri, "state": state, "scope": scope}

        if code_challenge:
            metadata["code_challenge"] = code_challenge
            metadata["code_challenge_method"] = code_challenge_method or "plain"

        # Delete old authorization codes for this client (keep only the newest)
        delete_query = f"""
        DELETE FROM {self._get_table_name('dcr_tokens')}
        WHERE dcr_client_id = ?
          AND dcr_token_type = 'authorization_code'
        """
        self._execute_query(delete_query, (dcr_client_id,))

        query = f"""
        INSERT INTO {self._get_table_name('dcr_tokens')} (
            dcr_token_value, dcr_client_id, dcr_token_type, expires_at, dcr_status, metadata
        ) VALUES (?, ?, 'authorization_code', ?, 'active', ?)
        """

        self._execute_query(
            query, (code, dcr_client_id, expires_at, json.dumps(metadata))
        )

        return code

    def verify_authorization_code(
        self,
        code: str,
        dcr_client_id: str,
        redirect_uri: str = None,
        code_verifier: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        f"""Authorization code 검증 (PKCE 지원)"""
        query = f"""
        SELECT dcr_client_id, metadata, expires_at, dcr_status, azure_object_id
        FROM {self._get_table_name('dcr_tokens')}
        WHERE dcr_token_value = ? AND dcr_token_type = 'authorization_code'
        """

        result = self._fetch_one(query, (code,))

        if not result:
            logger.warning(f"❌ Authorization code not found")
            return None

        stored_client_id, metadata_str, expires_at, status, azure_object_id = result
        metadata = json.loads(metadata_str) if metadata_str else {}

        # 검증
        if stored_client_id != dcr_client_id:
            logger.warning(f"❌ Client ID mismatch")
            return None

        if status != "active":
            logger.warning(f"❌ Authorization code already used")
            return None

        # timezone-aware 비교
        expiry_dt = datetime.fromisoformat(expires_at)
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        if expiry_dt < datetime.now(timezone.utc):
            logger.warning(f"❌ Authorization code expired")
            self._execute_query(
                f"UPDATE {self._get_table_name('dcr_tokens')} SET dcr_status = 'expired' WHERE dcr_token_value = ?",
                (code,),
            )
            return None

        if redirect_uri and metadata.get("redirect_uri") != redirect_uri:
            logger.warning(f"❌ Redirect URI mismatch")
            return None

        # PKCE 검증
        if "code_challenge" in metadata:
            if not code_verifier:
                logger.warning(f"❌ PKCE required but no code_verifier")
                return None

            if not self._verify_pkce(
                code_verifier,
                metadata["code_challenge"],
                metadata.get("code_challenge_method", "plain"),
            ):
                logger.warning(f"❌ PKCE verification failed")
                return None

        # Mark as used (atomic operation to prevent race condition)
        affected_rows = self._execute_query(
            f"UPDATE {self._get_table_name('dcr_tokens')} "
            f"SET dcr_status = 'expired' "
            f"WHERE dcr_token_value = ? AND dcr_status = 'active'",
            (code,),
        )

        if affected_rows == 0:
            # 이미 사용되었거나 없는 코드
            logger.warning("❌ Authorization code already used or not found")
            return None

        return {
            "scope": metadata.get("scope"),
            "state": metadata.get("state"),
            "azure_object_id": azure_object_id,
        }

    def verify_refresh_token(
        self, refresh_token: str, dcr_client_id: str
    ) -> Optional[Dict[str, Any]]:
        f"""DCR Refresh 토큰 검증 (RFC 6749)

        Args:
            refresh_token: DCR refresh token (평문)
            dcr_client_id: DCR 클라이언트 ID

        Returns:
            토큰 정보 (azure_object_id, scope, user_name 포함) 또는 None
        """
        # DCR refresh token은 암호화되어 저장되므로 모든 active refresh token을 조회
        query = f"""
        SELECT dcr_client_id, dcr_token_value, azure_object_id, metadata, expires_at, dcr_status
        FROM {self._get_table_name('dcr_tokens')}
        WHERE dcr_token_type = 'refresh'
          AND dcr_status = 'active'
          AND expires_at > CURRENT_TIMESTAMP
        """

        results = self._fetch_all(query)

        if not results:
            logger.warning(f"❌ No active refresh tokens found in DB")
            return None

        # 암호화된 토큰을 하나씩 복호화하여 비교
        for row in results:
            (
                stored_client_id,
                encrypted_token,
                azure_object_id,
                metadata_str,
                expires_at,
                status,
            ) = row

            try:
                # 복호화
                decrypted_token = self.crypto.account_decrypt_sensitive_data(
                    encrypted_token
                )

                # 토큰 비교
                if not secrets.compare_digest(decrypted_token, refresh_token):
                    continue

                # 클라이언트 ID 확인
                if stored_client_id != dcr_client_id:
                    logger.warning(f"❌ Refresh token client ID mismatch")
                    return None

                # 메타데이터 파싱
                metadata = json.loads(metadata_str) if metadata_str else {}

                # Azure Object ID가 없으면 에러
                if not azure_object_id:
                    logger.warning(f"❌ Refresh token has no azure_object_id")
                    return None

                # scope 가져오기 (metadata 또는 dcr_clients 테이블에서)
                scope = metadata.get("scope")
                if not scope:
                    # dcr_clients에서 scope 조회
                    client = self.get_client(dcr_client_id)
                    scope = client.get("dcr_requested_scope", "")

                # user_name 가져오기 (dcr_azure_users 테이블에서)
                user_query = f"""
                SELECT user_name FROM dcr_azure_users WHERE object_id = ?
                """
                user_result = self._fetch_one(user_query, (azure_object_id,))
                user_name = user_result[0] if user_result else None

                logger.info(
                    f"✅ Refresh token verified for client: {dcr_client_id}, user: {azure_object_id}"
                )

                return {
                    "azure_object_id": azure_object_id,
                    "scope": scope,
                    "user_name": user_name,
                }

            except Exception as e:
                logger.error(f"❌ Error decrypting refresh token: {e}")
                continue

        logger.warning(
            f"❌ No matching refresh token found for client: {dcr_client_id}"
        )
        return None

    def store_tokens(
        self,
        dcr_client_id: str,
        dcr_access_token: str,
        dcr_refresh_token: Optional[str],
        expires_in: int,
        scope: str,
        azure_object_id: str,
        azure_access_token: str,
        azure_refresh_token: Optional[str],
        azure_expires_at: datetime,
        user_email: Optional[str] = None,
        user_name: Optional[str] = None,
    ):
        """DCR 토큰 + Azure 토큰 저장 + accounts 테이블 연동"""
        dcr_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # 1) dcr_azure_users에 Azure 토큰 저장 (UPSERT 사용: 기존 행을 삭제하지 않음)
        if azure_object_id:
            azure_query = """
            INSERT INTO dcr_azure_users (
                object_id, application_id, access_token, refresh_token, expires_at,
                scope, user_email, user_name, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(object_id) DO UPDATE SET
                application_id = excluded.application_id,
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                scope = excluded.scope,
                user_email = excluded.user_email,
                user_name = excluded.user_name,
                updated_at = CURRENT_TIMESTAMP
            """

            self._execute_query(
                azure_query,
                (
                    azure_object_id,
                    self.azure_application_id,
                    self.crypto.account_encrypt_sensitive_data(azure_access_token),
                    (
                        self.crypto.account_encrypt_sensitive_data(azure_refresh_token)
                        if azure_refresh_token
                        else None
                    ),
                    azure_expires_at,
                    scope,
                    user_email,
                    user_name,
                ),
            )
            logger.info(
                f"✅ Stored Azure token for object_id: {azure_object_id}, user: {user_email}"
            )

            # accounts 테이블 연동 (암호화된 토큰 전달)
            encrypted_access = self.crypto.account_encrypt_sensitive_data(
                azure_access_token
            )
            encrypted_refresh = (
                self.crypto.account_encrypt_sensitive_data(azure_refresh_token)
                if azure_refresh_token
                else None
            )

            self._sync_with_accounts_table(
                azure_object_id=azure_object_id,
                user_email=user_email,
                user_name=user_name,
                encrypted_access_token=encrypted_access,
                encrypted_refresh_token=encrypted_refresh,
                azure_expires_at=azure_expires_at,
            )

        # 2) 기존 active Bearer 토큰 확인 및 업데이트
        check_bearer_query = f"""
        SELECT COUNT(*) FROM {self._get_table_name('dcr_tokens')}
        WHERE dcr_client_id = ?
          AND azure_object_id = ?
          AND dcr_token_type = 'Bearer'
          AND dcr_status = 'active'
        """
        existing_bearer = self._fetch_one(check_bearer_query, (dcr_client_id, azure_object_id))
        has_bearer = existing_bearer and existing_bearer[0] > 0

        if has_bearer:
            # 기존 Bearer 토큰 업데이트
            update_bearer_query = f"""
            UPDATE {self._get_table_name('dcr_tokens')}
            SET dcr_token_value = ?, expires_at = ?
            WHERE dcr_client_id = ?
              AND azure_object_id = ?
              AND dcr_token_type = 'Bearer'
              AND dcr_status = 'active'
            """
            self._execute_query(
                update_bearer_query,
                (
                    self.crypto.account_encrypt_sensitive_data(dcr_access_token),
                    dcr_expires_at,
                    dcr_client_id,
                    azure_object_id,
                ),
            )
            logger.info(f"✅ Updated DCR Bearer token for client: {dcr_client_id}")
        else:
            # 3) 새 Bearer 토큰 삽입 (최초 발급)
            insert_bearer_query = f"""
            INSERT INTO {self._get_table_name('dcr_tokens')} (
                dcr_token_value, dcr_client_id, dcr_token_type, azure_object_id, expires_at, dcr_status
            ) VALUES (?, ?, 'Bearer', ?, ?, 'active')
            """
            self._execute_query(
                insert_bearer_query,
                (
                    self.crypto.account_encrypt_sensitive_data(dcr_access_token),
                    dcr_client_id,
                    azure_object_id,
                    dcr_expires_at,
                ),
            )
            logger.info(f"✅ Inserted new DCR Bearer token for client: {dcr_client_id}")

        # 4) DCR refresh token 저장 (새로 제공된 경우에만)
        if dcr_refresh_token:
            # 기존 refresh 토큰 확인
            check_refresh_query = f"""
            SELECT COUNT(*) FROM {self._get_table_name('dcr_tokens')}
            WHERE dcr_client_id = ?
              AND dcr_token_type = 'refresh'
              AND dcr_status = 'active'
            """
            existing_refresh = self._fetch_one(check_refresh_query, (dcr_client_id,))
            has_refresh = existing_refresh and existing_refresh[0] > 0

            refresh_expires = datetime.now(timezone.utc) + timedelta(days=30)

            if has_refresh:
                # 기존 refresh 토큰 업데이트
                update_refresh_query = f"""
                UPDATE {self._get_table_name('dcr_tokens')}
                SET dcr_token_value = ?, expires_at = ?, azure_object_id = ?
                WHERE dcr_client_id = ?
                  AND dcr_token_type = 'refresh'
                  AND dcr_status = 'active'
                """
                self._execute_query(
                    update_refresh_query,
                    (
                        self.crypto.account_encrypt_sensitive_data(dcr_refresh_token),
                        refresh_expires,
                        azure_object_id,
                        dcr_client_id,
                    ),
                )
                logger.info(f"✅ Updated DCR refresh token for client: {dcr_client_id}")
            else:
                # 새 refresh 토큰 삽입 (최초 발급)
                insert_refresh_query = f"""
                INSERT INTO {self._get_table_name('dcr_tokens')} (
                    dcr_token_value, dcr_client_id, dcr_token_type, azure_object_id, expires_at, dcr_status
                ) VALUES (?, ?, 'refresh', ?, ?, 'active')
                """
                self._execute_query(
                    insert_refresh_query,
                    (
                        self.crypto.account_encrypt_sensitive_data(dcr_refresh_token),
                        dcr_client_id,
                        azure_object_id,
                        refresh_expires,
                    ),
                )
                logger.info(f"✅ Inserted new DCR refresh token for client: {dcr_client_id}")

        # 5) dcr_clients_{module_name} 테이블 업데이트 (azure_object_id, user_email 등)
        try:
            update_client_query = f"""
            UPDATE {self._get_table_name('dcr_clients')}
            SET azure_object_id = ?,
                user_email = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE dcr_client_id = ?
            """
            self._execute_query(
                update_client_query,
                (azure_object_id, user_email, dcr_client_id)
            )
            logger.info(
                f"✅ Updated dcr_clients table: client_id={dcr_client_id}, "
                f"azure_object_id={azure_object_id}, user_email={user_email}"
            )
        except Exception as e:
            logger.warning(
                f"⚠️ Failed to update dcr_clients table (non-critical): {str(e)}"
            )

        # 6) mail_query.db의 accounts 테이블 동기화 (모듈이 mail_query인 경우에만)
        if self.module_name == "mail_query" and user_email:
            try:
                self._sync_mail_query_accounts(
                    azure_object_id=azure_object_id,
                    user_email=user_email,
                    user_name=user_name,
                    azure_access_token=azure_access_token,
                    azure_refresh_token=azure_refresh_token,
                    azure_expires_at=azure_expires_at,
                )
            except Exception as e:
                logger.warning(
                    f"⚠️ Failed to sync mail_query accounts table (non-critical): {str(e)}"
                )

    def verify_bearer_token(self, token: str) -> Optional[Dict[str, Any]]:
        f"""DCR Bearer 토큰 검증

        Note: dcr_token_value는 암호화되어 저장됨 (store_tokens 참조)
        클라이언트가 보낸 Bearer 토큰을 복호화 후 비교
        """
        query = f"""
        SELECT dcr_client_id, dcr_token_value, azure_object_id
        FROM {self._get_table_name('dcr_tokens')}
        WHERE dcr_token_type = 'Bearer'
          AND dcr_status = 'active'
          AND expires_at > CURRENT_TIMESTAMP
        """

        results = self._fetch_all(query)

        logger.info(
            f"🔍 [verify_bearer_token] Found {len(results) if results else 0} active tokens in DB"
        )

        if not results:
            logger.warning(
                f"⚠️ [verify_bearer_token] No active Bearer tokens found in DB"
            )
            return None

        for i, row in enumerate(results):
            dcr_client_id, encrypted_token, azure_object_id = row
            logger.info(
                f"🔍 [verify_bearer_token] Checking token {i+1}/{len(results)} for client: {dcr_client_id}"
            )

            try:
                # 암호화된 토큰 복호화
                decrypted_token = self.crypto.account_decrypt_sensitive_data(
                    encrypted_token
                )

                # 토큰 비교
                if secrets.compare_digest(decrypted_token, token):
                    logger.info(
                        f"✅ [verify_bearer_token] Token matched for client: {dcr_client_id}"
                    )
                    return {
                        "dcr_client_id": dcr_client_id,
                        "azure_object_id": azure_object_id,
                    }
                else:
                    logger.info(
                        f"❌ [verify_bearer_token] Token did NOT match for client: {dcr_client_id}"
                    )
            except Exception as e:
                logger.error(
                    f"❌ [verify_bearer_token] Token comparison error for client {dcr_client_id}: {e}",
                    exc_info=True,
                )
                continue

        logger.warning(
            f"⚠️ [verify_bearer_token] No matching token found after checking all {len(results)} tokens"
        )
        return None

    def get_azure_tokens_by_object_id(
        self, azure_object_id: str
    ) -> Optional[Dict[str, Any]]:
        f"""Azure Object ID로 Azure 토큰 조회"""
        query = """
        SELECT access_token, refresh_token, scope, expires_at, user_email
        FROM dcr_azure_users
        WHERE object_id = ?
        """

        result = self._fetch_one(query, (azure_object_id,))

        if not result:
            return None

        access_token, refresh_token, scope, expires_at, user_email = result

        # timezone-aware 계산
        if expires_at:
            expiry_dt = datetime.fromisoformat(expires_at)
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        else:
            expiry_dt = None

        return {
            "access_token": self.crypto.account_decrypt_sensitive_data(access_token),
            "refresh_token": (
                self.crypto.account_decrypt_sensitive_data(refresh_token)
                if refresh_token
                else None
            ),
            "scope": scope,
            "user_email": user_email,
            "azure_expires_at": expiry_dt,
        }

    def update_auth_code_with_object_id(self, auth_code: str, azure_object_id: str, user_email: str = None, display_name: str = None):
        """Authorization code에 Azure Object ID 연결

        Args:
            auth_code: Authorization code
            azure_object_id: Azure Object ID
            user_email: 사용자 이메일 (선택)
            display_name: 사용자 표시 이름 (선택)

        Note:
            dcr_tokens의 azure_object_id는 FOREIGN KEY로 dcr_azure_users를 참조하지만,
            dcr_azure_users는 토큰 정보 테이블이므로 여기서는 NULL로 설정합니다.
            실제 사용자-토큰 연결은 token exchange 시점에 이루어집니다.
        """
        # dcr_tokens에 azure_object_id를 NULL로 설정 (FOREIGN KEY constraint 회피)
        # 실제 사용자 정보는 토큰 교환 후 dcr_azure_users에 저장됨
        query = f"""
        UPDATE {self._get_table_name('dcr_tokens')}
        SET azure_object_id = NULL
        WHERE dcr_token_value = ? AND dcr_token_type = 'authorization_code'
        """
        self._execute_query(query, (auth_code,))
        logger.info(f"✅ Updated auth code {auth_code[:10]}... (azure_object_id will be set during token exchange)")

    def is_user_allowed(self, user_email: str) -> bool:
        f"""사용자 허용 여부 확인 (도메인 기반)"""
        if not self.allowed_domains:
            return True

        user_email_lower = user_email.lower().strip()

        # 이메일에서 도메인 추출
        if "@" not in user_email_lower:
            logger.warning(f"❌ Invalid email format: {user_email}")
            return False

        user_domain = user_email_lower.split("@")[1]
        is_allowed = user_domain in self.allowed_domains

        if not is_allowed:
            logger.warning(
                f"❌ Access denied for user: {user_email} (domain: {user_domain})"
            )
        else:
            logger.info(
                f"✅ Access granted for user: {user_email} (domain: {user_domain})"
            )

        return is_allowed

    def _sync_with_accounts_table(
        self,
        azure_object_id: str,
        user_email: Optional[str],
        user_name: Optional[str],
        encrypted_access_token: str,
        encrypted_refresh_token: Optional[str],
        azure_expires_at: datetime,
    ):
        """DCR 인증 완료 시 graphapi.db의 accounts 테이블과 자동 연동 (암호화된 토큰 복사)"""
        try:
            # 이메일 필수 확인
            if not user_email:
                logger.warning(f"User email missing, cannot sync to accounts table")
                return

            # graphapi.db 연결 (get_database_manager가 자동으로 DB와 테이블 생성)
            db_manager = get_database_manager()

            # user_id는 이메일의 로컬 파트 사용 (예: kimghw@krs.co.kr -> kimghw)
            auto_user_id = user_email.split("@")[0] if "@" in user_email else user_email

            # user_id로 계정 조회 (이메일로도 확인)
            existing = db_manager.fetch_one(
                "SELECT id, user_id, email FROM accounts WHERE user_id = ? OR email = ?",
                (auto_user_id, user_email),
            )

            if not existing:
                # 계정이 없으면 생성
                logger.info(
                    f"🆕 Creating new account for user_id: {auto_user_id}, email: {user_email}"
                )

                # OAuth 정보: DCR 설정 사용
                oauth_client_id = self.azure_application_id
                oauth_tenant_id = self.azure_tenant_id
                oauth_redirect_uri = self.azure_redirect_uri
                oauth_client_secret = self.azure_client_secret

                # DCR 테이블에서 실제 사용자의 scope 가져오기
                azure_token = self._fetch_one(
                    "SELECT scope FROM dcr_azure_users WHERE object_id = ?",
                    (azure_object_id,),
                )

                # DCR 테이블의 scope를 그대로 사용 (OAuth 2.0 표준: 공백 구분)
                # 없으면 환경변수 기본값 사용
                if azure_token and azure_token[0]:
                    delegated_permissions = azure_token[0]
                else:
                    delegated_permissions = os.getenv(
                        "DCR_OAUTH_SCOPE", "offline_access User.Read Mail.ReadWrite"
                    )

                # 계정 생성 (이미 암호화된 토큰 그대로 복사)
                db_manager.execute_query(
                    """
                    INSERT INTO accounts (
                        user_id, user_name, email,
                        oauth_client_id, oauth_client_secret, oauth_tenant_id, oauth_redirect_uri,
                        delegated_permissions, auth_type,
                        access_token, refresh_token, token_expiry,
                        status, is_active, created_at, updated_at, last_used_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Authorization Code Flow', ?, ?, ?, 'ACTIVE', 1, datetime('now'), datetime('now'), datetime('now'))
                """,
                    (
                        auto_user_id,
                        user_name or auto_user_id,
                        user_email,
                        oauth_client_id,
                        self.crypto.account_encrypt_sensitive_data(oauth_client_secret),
                        oauth_tenant_id,
                        oauth_redirect_uri,
                        delegated_permissions,  # 공백 구분 문자열 그대로 저장
                        encrypted_access_token,  # 이미 암호화됨
                        encrypted_refresh_token,  # 이미 암호화됨
                        azure_expires_at.isoformat() if azure_expires_at else None,
                    ),
                )
                logger.info(
                    f"✅ Created new account in graphapi.db for {auto_user_id} ({user_email})"
                )
            else:
                # 기존 계정 업데이트 (이미 암호화된 토큰 그대로 복사)
                existing_user_id = existing["user_id"]
                db_manager.execute_query(
                    """
                    UPDATE accounts
                    SET access_token = ?, refresh_token = ?, token_expiry = ?,
                        status = 'ACTIVE', last_used_at = datetime('now'), updated_at = datetime('now')
                    WHERE user_id = ?
                """,
                    (
                        encrypted_access_token,  # 이미 암호화됨
                        encrypted_refresh_token,  # 이미 암호화됨
                        azure_expires_at.isoformat() if azure_expires_at else None,
                        existing_user_id,
                    ),
                )
                logger.info(
                    f"✅ Updated account tokens in graphapi.db for {existing_user_id} ({user_email})"
                )

        except Exception as e:
            logger.error(f"Failed to sync with accounts table: {e}")
            # 실패해도 DCR 인증은 계속 진행

    def _sync_mail_query_accounts(
        self,
        azure_object_id: str,
        user_email: str,
        user_name: Optional[str],
        azure_access_token: str,
        azure_refresh_token: Optional[str],
        azure_expires_at: datetime,
    ):
        """mail_query.db의 accounts 테이블과 동기화"""
        try:
            # mail_query.db 연결
            from modules.outlook_mcp.implementations.database_manager import get_mail_query_database

            mail_db = get_mail_query_database()

            # 토큰 암호화
            encrypted_access = self.crypto.account_encrypt_sensitive_data(azure_access_token)
            encrypted_refresh = (
                self.crypto.account_encrypt_sensitive_data(azure_refresh_token)
                if azure_refresh_token
                else None
            )

            # user_id는 이메일의 로컬 파트 사용 (예: kimghw@krs.co.kr -> kimghw)
            auto_user_id = user_email.split("@")[0] if "@" in user_email else user_email

            # 기존 계정 조회
            existing = mail_db.fetch_one(
                "SELECT id, user_id, email FROM accounts WHERE user_id = ? OR email = ?",
                (auto_user_id, user_email),
            )

            if not existing:
                # 계정 생성
                logger.info(
                    f"🆕 Creating new account in mail_query.db for user_id: {auto_user_id}, email: {user_email}"
                )

                # DCR 테이블에서 사용자의 scope 가져오기
                azure_token = self._fetch_one(
                    "SELECT scope FROM dcr_azure_users WHERE object_id = ?",
                    (azure_object_id,),
                )

                delegated_permissions = azure_token[0] if azure_token and azure_token[0] else "offline_access User.Read Mail.ReadWrite"

                mail_db.execute_query(
                    """
                    INSERT INTO accounts (
                        user_id, user_name, email,
                        oauth_client_id, oauth_client_secret, oauth_tenant_id, oauth_redirect_uri,
                        delegated_permissions, auth_type,
                        access_token, refresh_token, token_expiry,
                        status, is_active, created_at, updated_at, last_used_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Authorization Code Flow', ?, ?, ?, 'active', 1, datetime('now'), datetime('now'), datetime('now'))
                    """,
                    (
                        auto_user_id,
                        user_name or auto_user_id,
                        user_email,
                        self.azure_application_id,
                        self.crypto.account_encrypt_sensitive_data(self.azure_client_secret),
                        self.azure_tenant_id,
                        self.azure_redirect_uri,
                        delegated_permissions,
                        encrypted_access,
                        encrypted_refresh,
                        azure_expires_at.isoformat() if azure_expires_at else None,
                    ),
                )
                logger.info(
                    f"✅ Created new account in mail_query.db for {auto_user_id} ({user_email})"
                )
            else:
                # 기존 계정 업데이트
                existing_user_id = existing["user_id"]
                mail_db.execute_query(
                    """
                    UPDATE accounts
                    SET access_token = ?, refresh_token = ?, token_expiry = ?,
                        status = 'active', last_used_at = datetime('now'), updated_at = datetime('now')
                    WHERE user_id = ?
                    """,
                    (
                        encrypted_access,
                        encrypted_refresh,
                        azure_expires_at.isoformat() if azure_expires_at else None,
                        existing_user_id,
                    ),
                )
                logger.info(
                    f"✅ Updated account tokens in mail_query.db for {existing_user_id} ({user_email})"
                )

        except Exception as e:
            logger.error(f"Failed to sync with mail_query accounts table: {e}")
            import traceback
            traceback.print_exc()
            # 실패해도 DCR 인증은 계속 진행

    # PKCE Helper Methods
    def _verify_pkce(
        self, code_verifier: str, code_challenge: str, method: str = "plain"
    ) -> bool:
        """PKCE 검증 (위임)"""
        return _verify_pkce_helper(code_verifier, code_challenge, method)

    def cleanup_stale_clients(self, hours: int = 24) -> int:
        """오래된 미사용 클라이언트 정리

        변경사항: merged 상태 제거 (이제 직접 삭제하므로 불필요)

        Args:
            hours: 정리 대상 시간 (기본값: 24시간)

        Returns:
            정리된 클라이언트 수
        """
        try:
            # 1. 생성되었지만 한 번도 사용되지 않은 클라이언트 삭제
            # (azure_object_id가 NULL이고 오래된 클라이언트)
            unused_cleanup_query = f"""
            DELETE FROM {self._get_table_name('dcr_clients')}
            WHERE azure_object_id IS NULL
              AND datetime(created_at) < datetime('now', ? || ' hours')
              AND dcr_client_id NOT IN (
                  SELECT DISTINCT dcr_client_id
                  FROM {self._get_table_name('dcr_tokens')}
                  WHERE dcr_status = 'active'
              )
            """

            # 2. 만료된 토큰 정리
            expired_tokens_query = f"""
            UPDATE {self._get_table_name('dcr_tokens')}
            SET dcr_status = 'expired'
            WHERE dcr_status = 'active'
              AND datetime(expires_at) < datetime('now')
            """

            # 실행
            unused_count = self._execute_query(unused_cleanup_query, (f"-{hours}",))
            expired_count = self._execute_query(expired_tokens_query)

            logger.info(
                f"🧹 Cleanup completed: {unused_count} unused clients removed, {expired_count} tokens expired"
            )

            return unused_count

        except Exception as e:
            logger.error(f"❌ Cleanup failed: {e}")
            return 0

    def get_client_merge_history(self, client_id: str) -> list:
        """특정 클라이언트의 병합 이력 조회

        변경사항: merged 상태가 제거되어 항상 빈 리스트 반환

        Args:
            client_id: 조회할 클라이언트 ID

        Returns:
            병합 이력 리스트 (항상 빈 리스트)
        """
        # merged 상태가 제거되어 더 이상 병합 이력이 없음
        logger.info(
            f"Client merge history requested for {client_id}, but merge tracking is disabled"
        )
        return []
