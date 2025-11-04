"""Attachment Manager Handlers

첨부파일 관리 기능을 제공하는 Handler + Tool 통합 클래스
- 키워드 기반 필터링 및 저장
- 환경설정 기반 저장 경로 관리
- 텍스트 추출 및 LLM 전달 (옵션)
AuthHandlers 패턴을 따라 MCP 레이어와 비즈니스 로직을 통합
"""

import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from mcp.types import Tool, TextContent

from infra.core.config import get_config
from infra.core.logger import get_logger
from infra.utils.datetime_parser import parse_date_range, Timezone
from modules.mail_query import (
    MailQueryOrchestrator,
    MailQueryRequest,
    MailQuerySeverFilters,
)
from modules.mail_process import AttachmentDownloader

logger = get_logger(__name__)
config = get_config()


class AttachmentFilterConfig:
    """첨부파일 필터링 설정"""

    def __init__(
        self,
        keywords: List[str],
        save_paths: List[str],
        case_sensitive: bool = False
    ):
        """
        Args:
            keywords: 필터링할 키워드 리스트 (1개 이상)
            save_paths: 저장할 경로 리스트 (1개 이상 가능)
            case_sensitive: 대소문자 구분 여부
        """
        self.keywords = keywords
        self.save_paths = [Path(p) for p in save_paths]
        self.case_sensitive = case_sensitive

        # 저장 경로 생성
        for path in self.save_paths:
            path.mkdir(parents=True, exist_ok=True)


class AttachmentFilterHandlers:
    """
    첨부파일 필터링 핸들러 (Mixin pattern)

    Handler + Tool 통합 (AuthHandlers 패턴)
    - Handler 부분: MCP Tool 정의, 라우팅
    - Tool 부분: 비즈니스 로직 (메일 조회, 필터링, 저장)
    """

    def __init__(self):
        """Initialize attachment filter handlers"""
        self.attachment_downloader = AttachmentDownloader(
            output_dir="./filtered_attachments"
        )
        logger.info("✅ AttachmentFilterHandlers initialized")

    # ========================================================================
    # Handler 부분 (MCP 레이어)
    # ========================================================================

    def get_attachment_filter_tools(self) -> List[Tool]:
        """
        Get list of attachment manager MCP tools

        Returns:
            List of attachment manager Tool objects
        """
        return [
            Tool(
                name="attachmentManager",
                description="""첨부파일 관리 도구: 특정 기간 동안의 메일을 조회하여 첨부파일명에 키워드가 포함된 파일을 관리합니다.

⭐ 주요 기능:
- 첨부파일 키워드 검색 및 자동 다운로드
- OneDrive /emails_llm 폴더에 자동 저장 (실패 시 로컬 저장)
- 임시 파일 자동 정리 (다운로드 후 삭제)

💡 query_email과의 차이점:
- query_email: 첨부파일 분석만 가능 (OneDrive 저장 불가)
- attachmentManager: 첨부파일 OneDrive 저장 + 키워드 검색

환경설정 기본값:
- 첨부파일 저장: 활성화 (OneDrive /emails_llm 또는 로컬: {})
- 텍스트 추출 및 LLM 전달: 비활성화 (기본값)

조회 전략 (권장):
1. 사용자가 지정한 start_date ~ end_date 기간으로 먼저 조회
2. 결과가 없으면 start_date를 3개월씩 과거로 이동하며 반복 조회
3. 최대 1년 전까지 조회 (총 4회 시도 권장)
4. 예시:
   - 1차: 2025-08-01 ~ 2025-10-16 (2개월)
   - 2차: 2025-05-01 ~ 2025-08-01 (3개월)
   - 3차: 2025-02-01 ~ 2025-05-01 (3개월)
   - 4차: 2024-11-01 ~ 2025-02-01 (3개월)

사용자 입력값이 환경설정보다 우선 적용됩니다.""".format(config.attachment_default_save_path),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "User ID (e.g., 'ejlee', 'yhjoe', 'kimghw')"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "시작 날짜 (ISO 형식, e.g., '2025-01-01')"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "종료 날짜 (ISO 형식, e.g., '2025-01-31')"
                        },
                        "filename_keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "첨부파일명에서 검색할 키워드 리스트 (1개 이상, OR 조건)",
                            "minItems": 1
                        },
                        "save_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "저장할 경로 리스트 (절대 경로, 옵션 - 미지정 시 환경설정 기본 경로 사용)",
                            "minItems": 1
                        },
                        "save_enabled": {
                            "type": "boolean",
                            "description": "첨부파일 저장 활성화 여부 (옵션 - 미지정 시 환경설정 기본값 사용)"
                        },
                        "extract_text": {
                            "type": "boolean",
                            "description": "텍스트 추출 후 LLM 전달 여부 (옵션 - 미지정 시 환경설정 기본값 사용)"
                        },
                        "case_sensitive": {
                            "type": "boolean",
                            "description": "대소문자 구분 여부",
                            "default": False
                        },
                        "sender_filter": {
                            "type": "string",
                            "description": "발신자 이메일 필터 (옵션)"
                        },
                        "subject_filter": {
                            "type": "string",
                            "description": "메일 제목 키워드 필터 (옵션, 부분 매칭)"
                        }
                    },
                    "required": ["user_id", "start_date", "end_date", "filename_keywords"]
                }
            ),
        ]

    async def handle_attachment_filter_tool(
        self,
        name: str,
        arguments: dict
    ) -> List[TextContent]:
        """
        Handle attachment manager tool calls

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            List of TextContent with tool results
        """
        logger.info(f"📎 [Attachment Manager Handler] Handling tool: {name}")

        try:
            if name == "attachmentManager":
                result = await self._attachment_manager(arguments)
                return [TextContent(type="text", text=result)]
            else:
                error_msg = f"Unknown attachment manager tool: {name}"
                logger.error(error_msg)
                return [TextContent(type="text", text=f"❌ Error: {error_msg}")]

        except Exception as e:
            error_msg = f"Attachment manager tool '{name}' failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return [TextContent(type="text", text=f"❌ Error: {error_msg}")]

    def is_attachment_filter_tool(self, tool_name: str) -> bool:
        """
        Check if tool name is an attachment manager tool

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if tool belongs to attachment manager handler
        """
        return tool_name in ["attachmentManager"]

    # ========================================================================
    # Tool 부분 (비즈니스 로직)
    # ========================================================================

    def _match_keywords(
        self,
        filename: str,
        keywords: List[str],
        case_sensitive: bool
    ) -> bool:
        """
        첨부파일명이 키워드 중 하나라도 포함하는지 확인 (OR 조건)

        Args:
            filename: 첨부파일명
            keywords: 키워드 리스트
            case_sensitive: 대소문자 구분 여부

        Returns:
            True if any keyword matches
        """
        if not case_sensitive:
            filename = filename.lower()
            keywords = [k.lower() for k in keywords]

        for keyword in keywords:
            if keyword in filename:
                logger.debug(f"Keyword '{keyword}' matched in '{filename}'")
                return True

        return False

    def _cleanup_empty_temp_folders(self, user_id: str):
        """
        임시 폴더에서 빈 폴더 정리

        Args:
            user_id: 사용자 ID
        """
        try:
            import shutil
            temp_base = Path("./filtered_attachments") / user_id

            if not temp_base.exists():
                return

            deleted_folders = 0

            # 하위 폴더들을 역순으로 순회 (자식 폴더부터 삭제)
            for folder in sorted(temp_base.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                if folder.is_dir():
                    try:
                        # 폴더가 비어있으면 삭제
                        if not any(folder.iterdir()):
                            folder.rmdir()
                            deleted_folders += 1
                            logger.debug(f"빈 폴더 삭제: {folder}")
                    except Exception as e:
                        logger.debug(f"폴더 삭제 실패: {folder} - {str(e)}")

            # user_id 폴더도 비어있으면 삭제
            if temp_base.exists() and not any(temp_base.iterdir()):
                temp_base.rmdir()
                deleted_folders += 1
                logger.info(f"🗑️ 사용자 임시 폴더 삭제: {temp_base}")

            if deleted_folders > 0:
                logger.info(f"🗑️ 빈 폴더 {deleted_folders}개 정리 완료")

        except Exception as e:
            logger.warning(f"⚠️ 임시 폴더 정리 중 오류: {str(e)}")

    async def _upload_to_onedrive(
        self,
        graph_client,
        user_id: str,
        file_path: Path,
        access_token: str,
        target_folder_url: str = None
    ) -> Optional[str]:
        """
        OneDrive/SharePoint 폴더에 파일 업로드

        Args:
            graph_client: Graph API client
            user_id: 사용자 ID
            file_path: 업로드할 로컬 파일 경로
            access_token: 액세스 토큰
            target_folder_url: SharePoint 공유 URL (없으면 OneDrive 루트)

        Returns:
            업로드된 파일의 OneDrive URL (실패 시 None)
        """
        try:
            import base64
            import urllib.parse
            import httpx

            # 기본 OneDrive 경로 (공유 폴더 없으면)
            if not target_folder_url:
                # OneDrive emails_llm 폴더에 저장
                upload_url = f"https://graph.microsoft.com/v1.0/me/drive/root:/emails_llm/{file_path.name}:/content"
            else:
                # SharePoint 공유 링크를 드라이브 아이템으로 변환
                # URL을 base64url로 인코딩 (padding 없이)
                encoded_url = base64.urlsafe_b64encode(target_folder_url.encode()).decode().rstrip('=')
                # 'u!' 접두사 추가 (sharing link identifier)
                sharing_token = f"u!{encoded_url}"

                # 공유 링크에서 드라이브 아이템 정보 가져오기
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"https://graph.microsoft.com/v1.0/shares/{sharing_token}/driveItem",
                        headers={"Authorization": f"Bearer {access_token}"}
                    )

                    if response.status_code != 200:
                        logger.warning(f"⚠️ SharePoint 폴더 접근 실패: {response.status_code}")
                        return None

                    folder_info = response.json()
                    folder_id = folder_info.get("id")
                    drive_id = folder_info.get("parentReference", {}).get("driveId")

                    if not folder_id or not drive_id:
                        logger.warning("⚠️ SharePoint 폴더 ID를 가져올 수 없습니다")
                        return None

                    # 드라이브 아이템에 파일 업로드
                    upload_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{folder_id}:/{file_path.name}:/content"

            # 파일 업로드
            async with httpx.AsyncClient() as client:
                with open(file_path, 'rb') as f:
                    file_data = f.read()

                upload_response = await client.put(
                    upload_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/octet-stream"
                    },
                    content=file_data,
                    timeout=60.0
                )

                if upload_response.status_code in [200, 201]:
                    uploaded_item = upload_response.json()
                    web_url = uploaded_item.get("webUrl")
                    logger.info(f"✅ OneDrive 업로드 성공: {file_path.name}")
                    return web_url
                else:
                    logger.warning(f"⚠️ OneDrive 업로드 실패: {upload_response.status_code}")
                    return None

        except Exception as e:
            logger.warning(f"⚠️ OneDrive 업로드 중 오류: {str(e)}")
            return None

    def _extract_text_from_file(self, file_path: Path) -> Optional[str]:
        """
        파일에서 텍스트 추출 (PDF, DOCX, TXT 등)

        Args:
            file_path: 파일 경로

        Returns:
            추출된 텍스트 (실패 시 None)
        """
        try:
            file_ext = file_path.suffix.lower()

            # TXT 파일
            if file_ext == ".txt":
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()

            # PDF 파일 (PyPDF2 사용, 설치 필요)
            elif file_ext == ".pdf":
                try:
                    import PyPDF2
                    with open(file_path, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        text = ""
                        for page in reader.pages:
                            text += page.extract_text() + "\n"
                        return text.strip()
                except ImportError:
                    logger.warning("PyPDF2가 설치되지 않아 PDF 텍스트 추출을 건너뜁니다.")
                    return None

            # DOCX 파일 (python-docx 사용, 설치 필요)
            elif file_ext == ".docx":
                try:
                    import docx
                    doc = docx.Document(file_path)
                    text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
                    return text.strip()
                except ImportError:
                    logger.warning("python-docx가 설치되지 않아 DOCX 텍스트 추출을 건너뜁니다.")
                    return None

            # 기타 파일 형식은 지원하지 않음
            else:
                logger.debug(f"지원하지 않는 파일 형식: {file_ext}")
                return None

        except Exception as e:
            logger.error(f"텍스트 추출 실패: {file_path} - {str(e)}")
            return None

    async def _attachment_manager(
        self,
        arguments: Dict[str, Any]
    ) -> str:
        """
        첨부파일 관리 메인 로직: 메일 조회 → 첨부파일 필터링 → 저장/텍스트 추출

        사용자 입력값 우선 처리:
        1. save_enabled: 사용자 입력 > 환경설정
        2. extract_text: 사용자 입력 > 환경설정
        3. save_paths: 사용자 입력 > 환경설정 기본 경로

        Args:
            arguments: {
                user_id, start_date, end_date,
                filename_keywords,
                save_paths (optional),
                save_enabled (optional),
                extract_text (optional),
                case_sensitive, sender_filter (optional),
                subject_filter (optional)
            }

        Returns:
            Success message with saved files info and/or extracted text
        """
        try:
            # 1. 파라미터 추출 및 환경설정 통합 (사용자 입력 우선)
            user_id = arguments["user_id"]
            start_date_str = arguments["start_date"]
            end_date_str = arguments["end_date"]
            filename_keywords = arguments["filename_keywords"]

            # 사용자 입력 > 환경설정 (save_enabled)
            save_enabled = arguments.get("save_enabled")
            if save_enabled is None:
                save_enabled = config.attachment_save_enabled
                logger.info(f"save_enabled: 환경설정 사용 = {save_enabled}")
            else:
                logger.info(f"save_enabled: 사용자 입력 = {save_enabled}")

            # 사용자 입력 > 환경설정 (extract_text)
            extract_text = arguments.get("extract_text")
            if extract_text is None:
                extract_text = config.attachment_text_extraction_enabled
                logger.info(f"extract_text: 환경설정 사용 = {extract_text}")
            else:
                logger.info(f"extract_text: 사용자 입력 = {extract_text}")

            # 사용자 입력 > 환경설정 (save_paths)
            save_paths = arguments.get("save_paths")
            if not save_paths:
                save_paths = [config.attachment_default_save_path]
                logger.info(f"save_paths: 환경설정 기본 경로 사용 = {save_paths}")
            else:
                logger.info(f"save_paths: 사용자 입력 = {save_paths}")

            case_sensitive = arguments.get("case_sensitive", False)
            sender_filter = arguments.get("sender_filter")
            subject_filter = arguments.get("subject_filter")

            logger.info("=" * 80)
            logger.info("attachmentManager 시작")
            logger.info(f"user_id: {user_id}")
            logger.info(f"기간: {start_date_str} ~ {end_date_str}")
            logger.info(f"키워드: {filename_keywords}")
            logger.info(f"저장 활성화: {save_enabled}")
            logger.info(f"텍스트 추출: {extract_text}")
            if save_enabled:
                logger.info(f"저장 경로: {save_paths}")
            logger.info(f"대소문자 구분: {case_sensitive}")
            if sender_filter:
                logger.info(f"발신자 필터: {sender_filter}")
            if subject_filter:
                logger.info(f"제목 필터: {subject_filter}")

            # 2. 날짜 파싱 - datetime_parser 유틸리티 사용
            start_date, end_date, calculated_days = parse_date_range(
                start_date_str=start_date_str,
                end_date_str=end_date_str,
                days_back=None,
                input_tz=Timezone.KST,
                output_tz=Timezone.UTC
            )

            # Convert to timezone-naive for backward compatibility
            start_date = start_date.replace(tzinfo=None)
            end_date = end_date.replace(tzinfo=None)

            logger.info(f"📅 Date range parsed: {start_date_str} ~ {end_date_str} ({calculated_days} days)")
            logger.info(f"   Start (UTC): {start_date}")
            logger.info(f"   End (UTC):   {end_date}")

            # 3. 필터링 설정 생성
            filter_config = AttachmentFilterConfig(
                keywords=filename_keywords,
                save_paths=save_paths,
                case_sensitive=case_sensitive
            )

            # 4. 메일 조회
            logger.info(f"메일 조회 시작: user_id={user_id}")

            filters = MailQuerySeverFilters(
                date_from=start_date,
                date_to=end_date
            )

            if sender_filter:
                filters.sender_address = sender_filter

            if subject_filter:
                filters.subject_contains = subject_filter

            select_fields = [
                "id", "subject", "from", "receivedDateTime",
                "hasAttachments", "attachments"
            ]

            async with MailQueryOrchestrator() as orchestrator:
                mail_request = MailQueryRequest(
                    user_id=user_id,
                    filters=filters,
                    select_fields=select_fields,
                )

                response = await orchestrator.mail_query_user_emails(mail_request)

                logger.info(f"메일 조회 완료: {len(response.messages)}개")

                # 5. 첨부파일 필터링, 저장 및 텍스트 추출
                saved_files = []
                extracted_texts = []
                total_attachments = 0
                matched_attachments = 0

                for mail in response.messages:
                    if not mail.has_attachments:
                        continue

                    if not hasattr(mail, 'attachments') or not mail.attachments:
                        continue

                    # 제목 필터 적용 (클라이언트 사이드)
                    if subject_filter:
                        mail_subject = mail.subject or ""
                        if subject_filter.lower() not in mail_subject.lower():
                            logger.debug(f"제목 필터 불일치, 건너뜀: {mail_subject}")
                            continue

                    for attachment in mail.attachments:
                        total_attachments += 1
                        attachment_name = attachment.get("name", "")

                        # 키워드 매칭 확인
                        if not self._match_keywords(
                            attachment_name,
                            filter_config.keywords,
                            filter_config.case_sensitive
                        ):
                            logger.debug(f"키워드 불일치, 건너뜀: {attachment_name}")
                            continue

                        matched_attachments += 1
                        logger.info(f"키워드 매칭: {attachment_name}")

                        # 첨부파일 다운로드
                        try:
                            # 토큰 확보
                            access_token = await orchestrator.token_service.get_valid_access_token(user_id)

                            att_result = await self.attachment_downloader.download_and_save(
                                graph_client=orchestrator.graph_client,
                                user_id=user_id,
                                message_id=mail.id,
                                attachment=attachment,
                                email_date=mail.received_date_time,
                                sender_email=mail.from_address.get("emailAddress", {}).get("address") if mail.from_address else None,
                                email_subject=mail.subject,
                                access_token=access_token
                            )

                            if att_result:
                                original_path = Path(att_result["file_path"])
                                file_size = att_result.get("size", 0)

                                # 저장 활성화된 경우 파일 저장
                                if save_enabled:
                                    # OneDrive에 업로드 시도
                                    onedrive_url = await self._upload_to_onedrive(
                                        graph_client=orchestrator.graph_client,
                                        user_id=user_id,
                                        file_path=original_path,
                                        access_token=access_token,
                                        target_folder_url=None
                                    )

                                    if onedrive_url:
                                        # OneDrive 업로드 성공
                                        logger.info(f"📤 OneDrive 저장 성공: {attachment_name}")
                                        saved_files.append({
                                            "filename": attachment_name,
                                            "path": onedrive_url,
                                            "location": "OneDrive",
                                            "size": file_size,
                                            "mail_subject": mail.subject,
                                            "mail_date": mail.received_date_time.isoformat() if mail.received_date_time else None
                                        })
                                    else:
                                        # OneDrive 실패 → 로컬 저장
                                        logger.info(f"📁 OneDrive 실패, 로컬 저장: {attachment_name}")

                                        # 모든 저장 경로에 복사
                                        for save_path in filter_config.save_paths:
                                            target_path = save_path / original_path.name

                                            # 중복 파일명 처리
                                            counter = 1
                                            while target_path.exists():
                                                name, ext = target_path.stem, target_path.suffix
                                                target_path = save_path / f"{name}_{counter}{ext}"
                                                counter += 1

                                            # 파일 복사
                                            import shutil
                                            shutil.copy2(original_path, target_path)
                                            logger.info(f"파일 저장 완료: {target_path}")

                                            # saved_files에 추가
                                            saved_files.append({
                                                "filename": attachment_name,
                                                "path": str(target_path),
                                                "location": "로컬",
                                                "size": file_size,
                                                "mail_subject": mail.subject,
                                                "mail_date": mail.received_date_time.isoformat() if mail.received_date_time else None
                                            })
                                            logger.info(f"saved_files에 추가: {attachment_name} (총 {len(saved_files)}개)")

                                # 텍스트 추출 활성화된 경우 텍스트 추출
                                if extract_text:
                                    extracted_text = self._extract_text_from_file(original_path)
                                    if extracted_text:
                                        extracted_texts.append({
                                            "filename": attachment_name,
                                            "text": extracted_text,
                                            "mail_subject": mail.subject,
                                            "mail_date": mail.received_date_time.isoformat() if mail.received_date_time else None
                                        })
                                        logger.info(f"텍스트 추출 완료: {attachment_name} ({len(extracted_text)} 문자)")

                                # 임시 파일 삭제 (OneDrive 업로드 후 또는 로컬 복사 후)
                                try:
                                    if original_path.exists():
                                        original_path.unlink()
                                        logger.info(f"🗑️ 임시 파일 삭제: {original_path}")
                                except Exception as e:
                                    logger.warning(f"⚠️ 임시 파일 삭제 실패: {original_path} - {str(e)}")

                        except Exception as e:
                            logger.error(f"첨부파일 다운로드/저장 실패: {attachment_name} - {str(e)}")
                            continue

                logger.info("=" * 80)
                logger.info(f"첨부파일 필터링 완료: 총 {total_attachments}개 중 {matched_attachments}개 매칭")
                if save_enabled:
                    logger.info(f"저장된 파일: {len(saved_files)}개")
                if extract_text:
                    logger.info(f"텍스트 추출 완료: {len(extracted_texts)}개")

                # 6. 임시 폴더 정리 (빈 폴더 삭제)
                self._cleanup_empty_temp_folders(user_id)

                # 7. 결과 포맷팅
                result_text = self._format_manager_results(
                    user_id=user_id,
                    start_date=start_date,
                    end_date=end_date,
                    keywords=filename_keywords,
                    save_paths=filter_config.save_paths if save_enabled else None,
                    total_mails=len(response.messages),
                    total_attachments=total_attachments,
                    matched_attachments=matched_attachments,
                    saved_files=saved_files if save_enabled else [],
                    extracted_texts=extracted_texts if extract_text else [],
                    save_enabled=save_enabled,
                    extract_text=extract_text,
                    sender_filter=sender_filter,
                    subject_filter=subject_filter
                )

                return result_text

        except Exception as e:
            error_msg = f"첨부파일 관리 실패: {str(e)}"
            logger.error(error_msg, exc_info=True)
            logger.error("=" * 80)
            return f"❌ Error: {error_msg}"

    def _format_manager_results(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime,
        keywords: List[str],
        save_paths: Optional[List[Path]],
        total_mails: int,
        total_attachments: int,
        matched_attachments: int,
        saved_files: List[Dict[str, Any]],
        extracted_texts: List[Dict[str, Any]],
        save_enabled: bool,
        extract_text: bool,
        sender_filter: Optional[str] = None,
        subject_filter: Optional[str] = None
    ) -> str:
        """결과 포맷팅 (저장 및/또는 텍스트 추출)"""

        result = f"""📎 첨부파일 관리 결과 - {user_id}
{'='*80}

📅 조회 기간: {start_date.date()} ~ {end_date.date()}
🔍 키워드: {', '.join(f"'{k}'" for k in keywords)}
"""

        # 저장 경로 정보
        if save_enabled and save_paths:
            result += f"📁 저장 경로:\n"
            result += chr(10).join(f"  • {path}" for path in save_paths) + "\n"

        # 필터 정보 추가
        if sender_filter or subject_filter:
            result += "\n🔧 필터:\n"
            if sender_filter:
                result += f"  • 발신자: {sender_filter}\n"
            if subject_filter:
                result += f"  • 제목: '{subject_filter}'\n"

        result += f"""
📊 통계:
  • 조회된 메일: {total_mails}개
  • 전체 첨부파일: {total_attachments}개
  • 키워드 매칭: {matched_attachments}개
"""

        if save_enabled:
            result += f"  • 저장된 파일: {len(saved_files)}개\n"
        if extract_text:
            result += f"  • 텍스트 추출: {len(extracted_texts)}개\n"

        result += "\n"

        # 저장된 파일 목록
        if save_enabled and saved_files:
            result += f"{'='*80}\n"
            result += "💾 저장된 파일 목록:\n\n"

            for i, file_info in enumerate(saved_files, 1):
                result += f"[{i}] {file_info['filename']}\n"
                result += f"   경로: {file_info['path']}\n"
                result += f"   크기: {file_info['size']:,} bytes\n"
                result += f"   메일: {file_info['mail_subject']}\n"
                result += f"   날짜: {file_info['mail_date']}\n\n"

        # 추출된 텍스트 (LLM 전달용)
        if extract_text and extracted_texts:
            result += f"{'='*80}\n"
            result += "📄 추출된 텍스트 (LLM 전달용):\n\n"

            for i, text_info in enumerate(extracted_texts, 1):
                result += f"[{i}] {text_info['filename']}\n"
                result += f"   메일: {text_info['mail_subject']}\n"
                result += f"   날짜: {text_info['mail_date']}\n"
                result += f"   텍스트 길이: {len(text_info['text'])} 문자\n"
                result += f"   텍스트 미리보기:\n"
                # 처음 500자만 표시
                preview = text_info['text'][:500]
                if len(text_info['text']) > 500:
                    preview += "..."
                result += f"   {preview}\n\n"

        # 매칭된 파일이 없는 경우에만 경고 표시
        if matched_attachments == 0:
            result += "⚠️  키워드와 매칭되는 첨부파일이 없습니다.\n"
        elif save_enabled and not saved_files:
            result += "⚠️  파일이 매칭되었으나 저장에 실패했습니다.\n"
        elif not save_enabled and not extract_text:
            result += f"ℹ️  {matched_attachments}개 파일이 매칭되었으나 저장 및 텍스트 추출이 비활성화되어 있습니다.\n"

        result += f"{'='*80}\n"
        result += "✅ 첨부파일 관리 완료\n"

        return result
