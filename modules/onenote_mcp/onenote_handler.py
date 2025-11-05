"""
OneNote Graph API Handler
Microsoft Graph API를 사용한 OneNote 작업 처리
"""

import httpx
from typing import Optional, List, Dict, Any
from infra.core.logger import get_logger
from infra.core.database import get_database_manager
from infra.core.token_service import TokenService

logger = get_logger(__name__)


class OneNoteHandler:
    """OneNote Graph API 작업 처리 핸들러"""

    def __init__(self):
        self.db = get_database_manager()
        self.token_service = TokenService()
        # v1.0 API 사용 (Beta보다 빠르고 안정적)
        self.graph_base_url = "https://graph.microsoft.com/v1.0"
        # self.graph_base_url = "https://graph.microsoft.com/beta"

    def _normalize_onenote_id(self, entity_id: str) -> str:
        """
        OneNote Entity ID를 Graph API 형식으로 정규화
        SharePoint URL의 GUID는 1- 접두사가 없지만, Graph API는 필요함

        Args:
            entity_id: Notebook/Section/Page ID

        Returns:
            정규화된 ID (1- 접두사 포함)
        """
        if not entity_id:
            return entity_id

        # 이미 1- 접두사가 있으면 그대로 반환
        if entity_id.startswith("1-"):
            return entity_id

        # GUID 형식인지 확인 (8-4-4-4-12 형식)
        import re
        guid_pattern = r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        if re.match(guid_pattern, entity_id):
            logger.info(f"🔧 OneNote ID 정규화: {entity_id} → 1-{entity_id}")
            return f"1-{entity_id}"

        # 다른 형식이면 그대로 반환
        return entity_id

    async def _get_access_token(self, user_id: str) -> Optional[str]:
        """
        사용자 ID로 유효한 액세스 토큰 조회 (자동 갱신 포함)

        Args:
            user_id: 사용자 ID

        Returns:
            유효한 액세스 토큰 또는 None
        """
        try:
            # TokenService를 사용하여 토큰 유효성 확인 및 자동 갱신
            return await self.token_service.get_valid_access_token(user_id)
        except Exception as e:
            logger.error(f"❌ 토큰 조회 실패: {str(e)}")
            return None

    async def list_notebooks(self, user_id: str) -> Dict[str, Any]:
        """
        사용자의 노트북 목록 조회

        Args:
            user_id: 사용자 ID

        Returns:
            노트북 목록
        """
        try:
            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.graph_base_url}/me/onenote/notebooks",
                    headers=headers,
                    timeout=30.0
                )

                if response.status_code == 200:
                    data = response.json()
                    notebooks = data.get("value", [])
                    logger.info(f"✅ 노트북 {len(notebooks)}개 조회 성공")
                    return {
                        "success": True,
                        "notebooks": notebooks
                    }
                else:
                    error_msg = f"노트북 조회 실패: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"노트북 조회 오류: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}

    async def list_all_sections(self, user_id: str, top: int = 10) -> Dict[str, Any]:
        """
        전체 섹션 목록 조회 (노트북 무관)

        Args:
            user_id: 사용자 ID
            top: 조회할 섹션 개수 (기본 10)

        Returns:
            섹션 목록
        """
        try:
            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.graph_base_url}/me/onenote/sections?$top={top}",
                    headers=headers,
                    timeout=30.0
                )

                if response.status_code == 200:
                    data = response.json()
                    sections = data.get("value", [])
                    logger.info(f"✅ 전체 섹션 {len(sections)}개 조회 성공")
                    return {
                        "success": True,
                        "sections": sections
                    }
                else:
                    error_msg = f"전체 섹션 조회 실패: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"전체 섹션 조회 오류: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}

    async def create_section(self, user_id: str, notebook_id: str, section_name: str) -> Dict[str, Any]:
        """
        노트북에 새 섹션 생성

        Args:
            user_id: 사용자 ID
            notebook_id: 노트북 ID
            section_name: 생성할 섹션 이름

        Returns:
            생성된 섹션 정보
        """
        try:
            # ID 정규화
            notebook_id = self._normalize_onenote_id(notebook_id)

            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            body = {
                "displayName": section_name
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.graph_base_url}/me/onenote/notebooks/{notebook_id}/sections",
                    headers=headers,
                    json=body,
                    timeout=30.0
                )

                if response.status_code == 201:
                    data = response.json()
                    logger.info(f"✅ 섹션 생성 성공: {data.get('id')} ({section_name})")
                    return {
                        "success": True,
                        "section": data
                    }
                else:
                    error_msg = f"섹션 생성 실패: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"섹션 생성 오류: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}

    async def list_sections(self, user_id: str) -> Dict[str, Any]:
        """
        모든 섹션 목록 조회 (notebook 거치지 않고 직접 조회)

        Args:
            user_id: 사용자 ID

        Returns:
            섹션 목록
        """
        import time
        start_time = time.time()

        try:
            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient() as client:
                # notebook 없이 모든 섹션 직접 조회
                api_start = time.time()
                response = await client.get(
                    f"{self.graph_base_url}/me/onenote/sections",
                    headers=headers,
                    timeout=30.0
                )
                api_time = time.time() - api_start

                if response.status_code == 200:
                    data = response.json()
                    sections = data.get("value", [])
                    total_time = time.time() - start_time
                    logger.info(f"✅ 섹션 {len(sections)}개 조회 성공 (총 {total_time:.2f}초, API {api_time:.2f}초)")
                    return {
                        "success": True,
                        "sections": sections,
                        "response_time": {
                            "total": total_time,
                            "api": api_time
                        }
                    }
                else:
                    error_msg = f"섹션 조회 실패: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"섹션 조회 오류: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}

    async def list_pages(self, user_id: str, section_id: str = None) -> Dict[str, Any]:
        """
        페이지 목록 조회 (모든 페이지 또는 특정 섹션의 페이지)

        Args:
            user_id: 사용자 ID
            section_id: 섹션 ID (선택, 없으면 모든 페이지 조회)

        Returns:
            페이지 목록
        """
        import time
        start_time = time.time()

        try:
            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            # 섹션 ID가 있으면 특정 섹션의 페이지, 없으면 모든 페이지 조회
            if section_id:
                # ID 정규화
                section_id = self._normalize_onenote_id(section_id)
                url = f"{self.graph_base_url}/me/onenote/sections/{section_id}/pages"
            else:
                url = f"{self.graph_base_url}/me/onenote/pages"

            async with httpx.AsyncClient() as client:
                api_start = time.time()
                response = await client.get(
                    url,
                    headers=headers,
                    timeout=30.0
                )
                api_time = time.time() - api_start

                if response.status_code == 200:
                    data = response.json()
                    pages = data.get("value", [])
                    total_time = time.time() - start_time
                    logger.info(f"✅ 페이지 {len(pages)}개 조회 성공 (총 {total_time:.2f}초, API {api_time:.2f}초)")
                    return {
                        "success": True,
                        "pages": pages,
                        "response_time": {
                            "total": total_time,
                            "api": api_time
                        }
                    }
                else:
                    error_msg = f"페이지 조회 실패: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"페이지 조회 오류: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}

    async def get_page_content(self, user_id: str, page_id: str) -> Dict[str, Any]:
        """
        페이지 내용 조회

        Args:
            user_id: 사용자 ID
            page_id: 페이지 ID

        Returns:
            페이지 내용 (HTML)
        """
        try:
            # ID 정규화
            page_id = self._normalize_onenote_id(page_id)

            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }

            async with httpx.AsyncClient() as client:
                # 페이지 메타데이터 조회
                meta_response = await client.get(
                    f"{self.graph_base_url}/me/onenote/pages/{page_id}",
                    headers=headers,
                    timeout=30.0
                )

                if meta_response.status_code != 200:
                    error_msg = f"페이지 메타데이터 조회 실패: {meta_response.status_code}"
                    logger.error(error_msg)
                    return {"success": False, "message": error_msg}

                meta_data = meta_response.json()

                # 페이지 컨텐츠 조회
                content_headers = {
                    "Authorization": f"Bearer {access_token}",
                }
                content_response = await client.get(
                    f"{self.graph_base_url}/me/onenote/pages/{page_id}/content",
                    headers=content_headers,
                    timeout=30.0
                )

                if content_response.status_code == 200:
                    logger.info(f"✅ 페이지 컨텐츠 조회 성공: {page_id}")
                    return {
                        "success": True,
                        "page_id": page_id,
                        "title": meta_data.get("title", ""),
                        "content": content_response.text,
                        "content_type": "html"
                    }
                else:
                    error_msg = f"페이지 컨텐츠 조회 실패: {content_response.status_code}"
                    logger.error(error_msg)
                    return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"페이지 컨텐츠 조회 오류: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}

    async def create_page(
        self,
        user_id: str,
        section_id: str,
        title: str,
        content: str
    ) -> Dict[str, Any]:
        """
        새 페이지 생성

        Args:
            user_id: 사용자 ID
            section_id: 섹션 ID
            title: 페이지 제목
            content: 페이지 내용 (HTML)

        Returns:
            생성된 페이지 정보
        """
        try:
            # ID 정규화
            section_id = self._normalize_onenote_id(section_id)

            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            # HTML 컨텐츠 구성
            html_content = f"""
<!DOCTYPE html>
<html>
  <head>
    <title>{title}</title>
  </head>
  <body>
    {content}
  </body>
</html>
"""

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "text/html"
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.graph_base_url}/me/onenote/sections/{section_id}/pages",
                    headers=headers,
                    content=html_content,
                    timeout=30.0
                )

                if response.status_code == 201:
                    data = response.json()
                    logger.info(f"✅ 페이지 생성 성공: {data.get('id')}")
                    return {
                        "success": True,
                        "page_id": data.get("id"),
                        "title": data.get("title"),
                        "content_url": data.get("contentUrl")
                    }
                else:
                    error_msg = f"페이지 생성 실패: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"페이지 생성 오류: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}

    async def update_page(
        self,
        user_id: str,
        page_id: str,
        content: str
    ) -> Dict[str, Any]:
        """
        페이지 업데이트 (append 방식)

        Args:
            user_id: 사용자 ID
            page_id: 페이지 ID
            content: 추가할 내용 (HTML)

        Returns:
            업데이트 결과
        """
        try:
            # ID 정규화
            page_id = self._normalize_onenote_id(page_id)

            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            # PATCH 요청용 JSON 형식
            patch_data = [
                {
                    "target": "body",
                    "action": "append",
                    "content": content
                }
            ]

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    f"{self.graph_base_url}/me/onenote/pages/{page_id}/content",
                    headers=headers,
                    json=patch_data,
                    timeout=30.0
                )

                if response.status_code == 204:
                    logger.info(f"✅ 페이지 업데이트 성공: {page_id}")
                    return {
                        "success": True,
                        "page_id": page_id,
                        "message": "페이지가 성공적으로 업데이트되었습니다"
                    }
                else:
                    error_msg = f"페이지 업데이트 실패: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"페이지 업데이트 오류: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}

    async def delete_page(
        self,
        user_id: str,
        page_id: str
    ) -> Dict[str, Any]:
        """
        페이지 삭제

        Args:
            user_id: 사용자 ID
            page_id: 페이지 ID

        Returns:
            삭제 결과
        """
        try:
            # ID 정규화
            page_id = self._normalize_onenote_id(page_id)

            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            headers = {
                "Authorization": f"Bearer {access_token}"
            }

            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.graph_base_url}/me/onenote/pages/{page_id}",
                    headers=headers,
                    timeout=30.0
                )

                if response.status_code == 204:
                    logger.info(f"✅ 페이지 삭제 성공: {page_id}")
                    return {
                        "success": True,
                        "page_id": page_id,
                        "message": "페이지가 성공적으로 삭제되었습니다"
                    }
                else:
                    error_msg = f"페이지 삭제 실패: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return {"success": False, "message": error_msg}

        except Exception as e:
            error_msg = f"페이지 삭제 오류: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}
