"""
Azure Application Management via Microsoft Graph API

Azure Portal의 App Registration에 Redirect URI를 프로그래밍 방식으로 추가/관리
"""

import os
import requests
from typing import List, Optional, Dict, Any
from infra.core.logger import get_logger

logger = get_logger(__name__)


class AzureAppManager:
    """Microsoft Graph API를 통한 Azure 앱 관리"""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        object_id: Optional[str] = None
    ):
        """
        Args:
            tenant_id: Azure AD Tenant ID
            client_id: Azure Application (Client) ID
            client_secret: Azure Client Secret
            object_id: Azure Application Object ID (선택사항 - 자동 조회 가능)
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.object_id = object_id
        self.access_token = None

    def _get_app_access_token(self) -> str:
        """Application.ReadWrite.All 권한으로 앱 전용 토큰 발급"""
        if self.access_token:
            return self.access_token

        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }

        try:
            response = requests.post(token_url, data=data, timeout=30)
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data["access_token"]
            logger.info("✅ Graph API 앱 전용 토큰 발급 성공")
            return self.access_token
        except Exception as e:
            logger.error(f"❌ Graph API 토큰 발급 실패: {e}")
            raise

    def _get_application_object_id(self) -> str:
        """Application (Client) ID로부터 Object ID 조회"""
        if self.object_id:
            return self.object_id

        token = self._get_app_access_token()
        url = f"https://graph.microsoft.com/v1.0/applications?$filter=appId eq '{self.client_id}'"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("value") and len(data["value"]) > 0:
                self.object_id = data["value"][0]["id"]
                logger.info(f"✅ Application Object ID 조회 성공: {self.object_id}")
                return self.object_id
            else:
                raise ValueError(f"Application not found for client_id: {self.client_id}")
        except Exception as e:
            logger.error(f"❌ Object ID 조회 실패: {e}")
            raise

    def get_current_redirect_uris(self) -> Dict[str, List[str]]:
        """현재 등록된 Redirect URI 목록 조회

        Returns:
            {
                "web": ["https://example.com/callback"],
                "spa": ["https://example.com/spa-callback"],
                "publicClient": ["http://localhost"]
            }
        """
        object_id = self._get_application_object_id()
        token = self._get_app_access_token()
        url = f"https://graph.microsoft.com/v1.0/applications/{object_id}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            app_data = response.json()

            redirect_uris = {
                "web": app_data.get("web", {}).get("redirectUris", []),
                "spa": app_data.get("spa", {}).get("redirectUris", []),
                "publicClient": app_data.get("publicClient", {}).get("redirectUris", [])
            }

            logger.info(f"✅ 현재 Redirect URIs 조회 완료")
            return redirect_uris
        except Exception as e:
            logger.error(f"❌ Redirect URIs 조회 실패: {e}")
            raise

    def add_web_redirect_uris(self, new_uris: List[str], app_type: str = "web") -> bool:
        """Web Redirect URI 추가 (기존 URI는 유지)

        Args:
            new_uris: 추가할 URI 목록
            app_type: "web", "spa", "publicClient" 중 하나

        Returns:
            성공 여부
        """
        if not new_uris:
            logger.warning("추가할 URI가 없습니다")
            return False

        object_id = self._get_application_object_id()
        token = self._get_app_access_token()

        # 현재 URIs 조회
        current_uris = self.get_current_redirect_uris()
        current_list = current_uris.get(app_type, [])

        # 중복 제거하고 병합
        updated_list = list(set(current_list + new_uris))

        if len(updated_list) == len(current_list):
            logger.info("이미 모든 URI가 등록되어 있습니다")
            return True

        # PATCH 요청으로 업데이트
        url = f"https://graph.microsoft.com/v1.0/applications/{object_id}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # app_type에 따른 body 구성
        body = {
            app_type: {
                "redirectUris": updated_list
            }
        }

        try:
            response = requests.patch(url, headers=headers, json=body, timeout=30)
            response.raise_for_status()

            added_uris = set(updated_list) - set(current_list)
            logger.info(f"✅ Redirect URI 추가 성공 ({app_type}): {list(added_uris)}")
            return True
        except Exception as e:
            logger.error(f"❌ Redirect URI 추가 실패: {e}")
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            return False

    def remove_web_redirect_uris(self, uris_to_remove: List[str], app_type: str = "web") -> bool:
        """Web Redirect URI 제거

        Args:
            uris_to_remove: 제거할 URI 목록
            app_type: "web", "spa", "publicClient" 중 하나

        Returns:
            성공 여부
        """
        if not uris_to_remove:
            logger.warning("제거할 URI가 없습니다")
            return False

        object_id = self._get_application_object_id()
        token = self._get_app_access_token()

        # 현재 URIs 조회
        current_uris = self.get_current_redirect_uris()
        current_list = current_uris.get(app_type, [])

        # 지정된 URI 제거
        updated_list = [uri for uri in current_list if uri not in uris_to_remove]

        if len(updated_list) == len(current_list):
            logger.info("제거할 URI가 현재 목록에 없습니다")
            return True

        # PATCH 요청으로 업데이트
        url = f"https://graph.microsoft.com/v1.0/applications/{object_id}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        body = {
            app_type: {
                "redirectUris": updated_list
            }
        }

        try:
            response = requests.patch(url, headers=headers, json=body, timeout=30)
            response.raise_for_status()

            removed_uris = set(current_list) - set(updated_list)
            logger.info(f"✅ Redirect URI 제거 성공 ({app_type}): {list(removed_uris)}")
            return True
        except Exception as e:
            logger.error(f"❌ Redirect URI 제거 실패: {e}")
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            return False


def auto_register_redirect_uri_from_env() -> bool:
    """환경변수에서 설정을 읽어 자동으로 Redirect URI 등록

    환경변수:
        - DCR_AZURE_TENANT_ID
        - DCR_AZURE_CLIENT_ID
        - DCR_AZURE_CLIENT_SECRET
        - AUTO_REGISTER_OAUTH_REDIRECT_URI (등록할 URI)
        - AZURE_APP_OBJECT_ID (선택사항)

    Returns:
        성공 여부
    """
    tenant_id = os.getenv("DCR_AZURE_TENANT_ID", "common")
    client_id = os.getenv("DCR_AZURE_CLIENT_ID")
    client_secret = os.getenv("DCR_AZURE_CLIENT_SECRET")
    redirect_uri = os.getenv("AUTO_REGISTER_OAUTH_REDIRECT_URI")
    object_id = os.getenv("AZURE_APP_OBJECT_ID")

    if not all([client_id, client_secret, redirect_uri]):
        logger.warning("⚠️ Azure 앱 설정 또는 Redirect URI가 환경변수에 없습니다")
        return False

    if tenant_id == "common":
        logger.error("❌ AUTO_REGISTER를 사용하려면 DCR_AZURE_TENANT_ID가 'common'이 아닌 실제 Tenant ID여야 합니다")
        return False

    try:
        manager = AzureAppManager(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            object_id=object_id
        )

        logger.info(f"🔄 Redirect URI 자동 등록 시도: {redirect_uri}")
        success = manager.add_web_redirect_uris([redirect_uri], app_type="web")

        if success:
            logger.info(f"✅ Redirect URI 자동 등록 완료: {redirect_uri}")

        return success
    except Exception as e:
        logger.error(f"❌ Redirect URI 자동 등록 실패: {e}")
        return False
