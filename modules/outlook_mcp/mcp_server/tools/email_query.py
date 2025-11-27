"""Email query tool for MCP server"""

import asyncio
import logging
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from infra.core import get_logger
from modules.outlook_mcp.implementations.database_manager import get_mail_query_database
from infra.utils.datetime_parser import parse_date_range as util_parse_date_range, Timezone
from modules.outlook_mail_query import (
    MailQuerySeverFilters,
    MailQueryOrchestrator,
    MailQueryRequest,
    PaginationOptions,
    KeywordFilter
)
from modules.mail_process import AttachmentDownloader, FileConverterOrchestrator, EmailSaver
from modules.mail_process.client_filter import ClientFilter
from modules.mail_process.client_filter.filters.keyword_filter import KeywordFilter as KeywordFilterLogic
from modules.outlook_mcp.mcp_server.prompts import get_format_email_results_prompt

logger = get_logger(__name__)


class EmailQueryTool:
    """Tool for querying and retrieving emails"""

    def __init__(self, config):
        """
        Initialize email query tool

        Args:
            config: Configuration object
        """
        self.config = config
        self.email_saver = EmailSaver(output_dir=Path(self.config.emails_dir))
        self.attachment_downloader = AttachmentDownloader(
            output_dir=str(self.config.attachments_dir)
        )
        self.file_converter = FileConverterOrchestrator()
        # Define KST timezone (UTC+9) - for backward compatibility
        self.KST = timezone(timedelta(hours=9))

    def parse_datetime_kst_to_utc(self, date_str: str) -> datetime:
        """
        DEPRECATED: Use infra.utils.datetime_parser instead

        Kept for backward compatibility only.
        """
        from infra.utils.datetime_parser import parse_start_date
        # Return timezone-naive for backward compatibility
        return parse_start_date(date_str, input_tz=Timezone.KST, output_tz=Timezone.UTC).replace(tzinfo=None)

    def parse_date_range(self, arguments: Dict[str, Any]) -> tuple:
        """
        Parse date range from arguments using new datetime_parser utility

        Args:
            arguments: Tool arguments containing date parameters

        Returns:
            Tuple of (start_date, end_date, days_back)
        """
        start_date_str = arguments.get("start_date")
        end_date_str = arguments.get("end_date")
        days_back = arguments.get("days_back", self.config.default_days_back)

        # Use new datetime parser utility
        start_date, end_date, calculated_days = util_parse_date_range(
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            days_back=days_back,
            input_tz=Timezone.KST,
            output_tz=Timezone.UTC
        )

        # Convert to timezone-naive for backward compatibility with MailQuerySeverFilters
        start_date = start_date.replace(tzinfo=None)
        end_date = end_date.replace(tzinfo=None)

        logger.info(f"📅 Date range parsed: {start_date_str} ~ {end_date_str} ({calculated_days} days)")
        logger.info(f"   Start (UTC): {start_date}")
        logger.info(f"   End (UTC):   {end_date}")

        return start_date, end_date, calculated_days

    async def validate_and_prepare_user(self, arguments: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        """
        Validate query parameters and prepare user_id with auto-authentication if needed

        Args:
            arguments: Tool arguments containing:
                - user_id (optional): 특정 계정 지정
                - use_recent_account (bool): True이면 최근 사용 계정 자동 선택

        Returns:
            Tuple of (user_id, error_message). If error_message is not None, user_id should be ignored.
        """
        from datetime import datetime, timezone

        user_id = arguments.get("user_id")
        # Convert string to boolean for use_recent_account
        use_recent_account_str = arguments.get("use_recent_account", "no")
        use_recent_account = use_recent_account_str in ["yes", "true", True]

        # Case 1: user_id 제공
        if user_id:
            logger.info(f"✅ 지정된 user_id 사용: {user_id}")

        # Case 2: use_recent_account=True
        elif use_recent_account:
            logger.info("use_recent_account=true - 최근 사용 계정 자동 선택")
            from ..handlers import get_default_user_id
            user_id = get_default_user_id()

            if not user_id:
                return None, """❌ Error: use_recent_account=true이지만 사용 가능한 계정이 없습니다.

다음 중 하나를 선택하세요:
1. user_id를 제공하여 특정 계정 조회
2. register_account로 계정을 먼저 등록"""

            logger.info(f"✅ 최근 사용 계정 선택: {user_id}")
            # Update arguments with auto-selected user_id
            arguments["user_id"] = user_id

        # Case 3: 둘 다 없음
        else:
            return None, """❌ Error: user_id 또는 use_recent_account=true가 필요합니다.

다음 중 하나를 선택하세요:
1. user_id를 제공하여 특정 계정 조회
2. use_recent_account=true로 설정하여 최근 사용 계정 사용"""

        # Check token validity
        db = get_mail_query_database()
        account = db.fetch_one(
            "SELECT access_token, token_expiry FROM accounts WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )

        if not account:
            return None, f"❌ Error: 계정을 찾을 수 없습니다: {user_id}"

        # Convert sqlite3.Row to dict for .get() method
        account_dict = dict(account)
        access_token = account_dict.get('access_token')
        token_expiry = account_dict.get('token_expiry')

        # Check if authentication is required
        requires_auth = False
        if not access_token or not token_expiry:
            requires_auth = True
            logger.warning(f"⚠️  토큰이 없음: {user_id}")
        else:
            # Check token expiry
            try:
                if isinstance(token_expiry, str):
                    if '.' in token_expiry:
                        token_expiry = token_expiry.split('.')[0]
                    expiry_dt = datetime.fromisoformat(token_expiry.replace('Z', '+00:00'))
                else:
                    expiry_dt = token_expiry

                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)

                now = datetime.now(timezone.utc)
                if expiry_dt <= now:
                    requires_auth = True
                    logger.warning(f"⚠️  토큰 만료됨: {user_id} (만료: {expiry_dt})")
            except Exception as e:
                requires_auth = True
                logger.error(f"⚠️  토큰 만료 시간 파싱 실패: {e}")

        # If authentication required, start authentication automatically
        if requires_auth:
            logger.info(f"🔐 인증 필요 - 자동으로 start_authentication 시작: {user_id}")

            try:
                # Import here to avoid circular dependency
                from modules.enrollment.auth import get_auth_orchestrator, AuthStartRequest

                orchestrator = get_auth_orchestrator()
                request = AuthStartRequest(user_id=user_id)
                response = await orchestrator.auth_orchestrator_start_authentication(request)

                error_msg = f"""⚠️  계정 인증이 필요합니다: {user_id}

🔐 OAuth 인증이 자동으로 시작되었습니다.

세션 ID: {response.session_id}
만료 시간: {response.expires_at}

🌐 **인증 URL:**

```
{response.auth_url}
```

[Microsoft 로그인 페이지 열기]({response.auth_url})

✅ 브라우저에서 로그인 후 권한 승인을 완료하면 자동으로 인증이 완료됩니다.
   인증 완료 후 다시 `query_email`을 실행하세요."""

                return None, error_msg

            except Exception as e:
                logger.error(f"❌ 자동 인증 시작 실패: {str(e)}")
                return None, f"❌ Error: 인증 필요하지만 자동 인증 시작 실패: {str(e)}\n수동으로 start_authentication을 실행하세요."

        # Validation successful - token is valid
        return user_id, None

    def validate_parameters(self, arguments: Dict[str, Any]) -> Optional[str]:
        """
        Validate query parameters (called after validate_and_prepare_user)

        Args:
            arguments: Tool arguments

        Returns:
            Error message if validation fails, None otherwise
        """
        # Check for conflicting parameters
        conversation_with = arguments.get("conversation_with", [])
        sender_address = arguments.get("sender_address")
        recipient_address = arguments.get("recipient_address")

        if conversation_with and sender_address:
            return "Error: conversation_with cannot be used with sender_address"
        if conversation_with and recipient_address:
            return "Error: conversation_with cannot be used with recipient_address"
        if sender_address and recipient_address:
            return "Error: sender_address and recipient_address cannot be used together"

        return None


    def filter_messages(self, messages: List, user_id: str, filters: Dict) -> List:
        """
        Filter messages: Keyword → Conversation (blocking은 mail_query에서 처리됨)

        Args:
            messages: List of email messages
            user_id: User ID
            filters: Filter parameters (conversation_with, recipient_address, keyword_filter)

        Returns:
            Filtered list of messages
        """
        conversation_with = filters.get("conversation_with", [])
        recipient_address = filters.get("recipient_address")
        keyword_filter = filters.get("keyword_filter")

        # 1순위: 키워드 필터
        if keyword_filter:
            messages = KeywordFilterLogic.apply(
                messages,
                and_keywords=keyword_filter.and_keywords,
                or_keywords=keyword_filter.or_keywords,
                not_keywords=keyword_filter.not_keywords
            )

        # Apply conversation filter
        if conversation_with:
            messages = ConversationFilter.filter_conversation(messages, user_id, conversation_with)
            return messages

        # Apply recipient filter
        if recipient_address:
            # Filter for sent mails to specific recipient
            filtered_messages = []
            for mail in messages:
                sender_email = ""
                if mail.from_address and isinstance(mail.from_address, dict):
                    email_addr = mail.from_address.get("emailAddress", {})
                    sender_email = email_addr.get("address", "").lower()

                # Only include if this is a sent mail from the user
                if sender_email and f"{user_id}@" in sender_email:
                    # Check recipients
                    if hasattr(mail, "to_recipients") and mail.to_recipients:
                        for recipient in mail.to_recipients:
                            if isinstance(recipient, dict):
                                recip_addr = recipient.get("emailAddress", {})
                                if isinstance(recip_addr, dict):
                                    recip_email = recip_addr.get("address", "").lower()
                                    if recip_email == recipient_address.lower():
                                        filtered_messages.append(mail)
                                        break
            return filtered_messages

        return messages

    async def format_email_info(self, mail, index: int, user_id: str, save_emails: bool,
                          download_attachments: bool, graph_client=None, access_token=None) -> Dict[str, Any]:
        """
        Format email information for display and storage

        Args:
            mail: Email message object
            index: Email index
            user_id: User ID
            save_emails: Whether to save emails
            download_attachments: Whether to download attachments
            graph_client: Graph API client for attachment download
            access_token: Access token for Graph API (needed for large attachments)

        Returns:
            Formatted email information dictionary
        """
        # Extract sender info
        sender = "Unknown"
        sender_email = None
        if mail.from_address and isinstance(mail.from_address, dict):
            email_addr = mail.from_address.get("emailAddress", {})
            sender_email = email_addr.get("address", "Unknown")
            sender = sender_email
            sender_name = email_addr.get("name", "")
            if sender_name:
                sender = f"{sender_name} <{sender_email}>"

        # Save email if requested
        mail_saved_path = None
        if save_emails:
            try:
                # Convert mail object to dictionary for EmailSaver
                from pathlib import Path
                email_dict = {
                    'id': mail.id,
                    'subject': mail.subject,
                    'received_date_time': mail.received_date_time,
                    'from': mail.from_address,
                    'body': mail.body,
                    'to_recipients': getattr(mail, 'to_recipients', []),
                    'cc_recipients': getattr(mail, 'cc_recipients', []),
                }
                # Create email directory based on user_id and date
                email_dir = Path(f"./data/emails/{user_id}/{mail.received_date_time.strftime('%Y%m%d')}")
                saved_info = await self.email_saver.save_email(email_dict, email_dir=email_dir)
                mail_saved_path = saved_info.get('text_path')
                logger.info(f"Email saved: {mail_saved_path}")
            except Exception as e:
                logger.error(f"Failed to save email: {str(e)}")

        # Convert received time to KST for display
        received_kst = mail.received_date_time.replace(tzinfo=timezone.utc).astimezone(self.KST)

        # Collect mail info
        mail_info = {
            "id": mail.id,
            "subject": mail.subject,
            "sender": sender,
            "sender_email": sender_email or "unknown@email.com",
            "received_date": received_kst.strftime("%Y-%m-%d %H:%M"),
            "received_date_time": mail.received_date_time,
            "has_attachments": mail.has_attachments,
            "is_read": mail.is_read,
            "importance": mail.importance,
            "attachments": [],
            "saved_path": mail_saved_path
        }

        # Add body content if available
        if mail.body:
            content_type = mail.body.get("contentType", "text")
            content = mail.body.get("content", "")

            if content_type.lower() == "html":
                # Simple HTML stripping
                import re
                text_content = re.sub("<[^<]+?>", "", content)
                text_content = text_content.replace("&nbsp;", " ")
                text_content = text_content.replace("&lt;", "<")
                text_content = text_content.replace("&gt;", ">")
                text_content = text_content.replace("&amp;", "&")
                # Don't truncate - include full body
                mail_info["body"] = text_content
            else:
                # Don't truncate - include full body
                mail_info["body"] = content
        elif mail.body_preview:
            mail_info["body_preview"] = mail.body_preview

        # Process attachments if requested (병렬 처리)
        if download_attachments and mail.has_attachments and hasattr(mail, "attachments"):
            if mail.attachments:
                # Semaphore로 동시 다운로드 수 제한 (최대 3개)
                semaphore = asyncio.Semaphore(3)

                async def process_with_semaphore(attachment):
                    """Semaphore를 사용한 첨부파일 처리"""
                    async with semaphore:
                        return await self.process_attachment(
                            attachment, mail.id, user_id, graph_client, access_token
                        )

                # 모든 첨부파일을 병렬로 처리
                tasks = [process_with_semaphore(att) for att in mail.attachments]
                att_infos = await asyncio.gather(*tasks, return_exceptions=True)

                # 결과 수집 (예외 제외)
                for att_info in att_infos:
                    if isinstance(att_info, Exception):
                        logger.warning(f"첨부파일 처리 중 오류 발생: {att_info}")
                        continue
                    if att_info:
                        mail_info["attachments"].append(att_info)

        return mail_info

    async def process_attachment(self, attachment: Dict, mail_id: str, user_id: str,
                          graph_client, access_token=None) -> Optional[Dict]:
        """
        Process a single attachment

        Args:
            attachment: Attachment data
            mail_id: Email ID
            user_id: User ID
            graph_client: Graph API client
            access_token: Access token for Graph API (needed for large attachments)

        Returns:
            Attachment information or None if processing failed
        """
        try:
            att_name = attachment.get("name", "unknown")
            att_size = attachment.get("size", 0)
            att_id = attachment.get("id")

            # Skip if too large
            if att_size > self.config.max_file_size_mb * 1024 * 1024:
                logger.warning(f"Attachment too large: {att_name} ({att_size} bytes)")
                return {
                    "name": att_name,
                    "size": att_size,
                    "status": "skipped_too_large"
                }

            # Download attachment
            if att_id and graph_client:
                saved_result = await self.attachment_downloader.download_and_save(
                    graph_client=graph_client,
                    user_id=user_id,
                    message_id=mail_id,
                    attachment=attachment,
                    access_token=access_token
                )

                if saved_result and saved_result.get("file_path"):
                    saved_path = saved_result["file_path"]
                    result = {
                        "name": att_name,
                        "size": att_size,
                        "saved_path": str(saved_path),
                        "status": "downloaded"
                    }

                    # Convert to text if possible
                    try:
                        text_content = self.file_converter.convert_to_text(Path(saved_path))
                        if text_content and not text_content.startswith("Error:"):
                            # Calculate token count before truncation
                            original_token_count = len(text_content) // 4

                            # Limit text length to prevent excessive token usage
                            max_length = 5000
                            is_truncated = False
                            if len(text_content) > max_length:
                                text_content = text_content[:max_length] + f"\n\n... (truncated, total {len(text_content)} chars, ~{original_token_count} tokens)"
                                is_truncated = True

                            result["text_content"] = text_content
                            result["token_count"] = len(text_content) // 4
                            result["original_token_count"] = original_token_count
                            result["is_truncated"] = is_truncated
                            result["status"] = "converted"
                            logger.info(f"Successfully converted attachment to text: {att_name} ({len(text_content)} chars, ~{result['token_count']} tokens)")

                            # Delete attachment file after successful conversion if cleanup is enabled
                            if self.config.cleanup_after_query:
                                try:
                                    import os
                                    file_path = Path(saved_path)
                                    parent_dir = file_path.parent

                                    # Delete the file
                                    os.remove(saved_path)
                                    logger.info(f"Deleted attachment file after conversion: {saved_path}")
                                    result["file_deleted"] = True

                                    # Try to delete parent directory if empty
                                    try:
                                        if parent_dir.exists() and not any(parent_dir.iterdir()):
                                            parent_dir.rmdir()
                                            logger.info(f"Deleted empty directory: {parent_dir}")

                                            # Try to delete grandparent directory if empty (user_id folder)
                                            grandparent_dir = parent_dir.parent
                                            if grandparent_dir.exists() and not any(grandparent_dir.iterdir()):
                                                grandparent_dir.rmdir()
                                                logger.info(f"Deleted empty directory: {grandparent_dir}")
                                    except Exception as dir_error:
                                        # Ignore directory deletion errors (not critical)
                                        logger.debug(f"Could not delete empty directory: {str(dir_error)}")

                                except Exception as delete_error:
                                    logger.warning(f"Failed to delete attachment file: {saved_path} - {str(delete_error)}")
                                    result["file_deleted"] = False
                        else:
                            logger.warning(f"Failed to convert attachment: {att_name} - {text_content}")
                    except Exception as e:
                        logger.warning(f"Could not convert attachment to text: {att_name} - {str(e)}")

                    return result

            return {
                "name": att_name,
                "size": att_size,
                "status": "failed"
            }

        except Exception as e:
            logger.error(f"Error processing attachment: {str(e)}")
            return None

    async def query_email(self, arguments: Dict[str, Any]) -> str:
        """
        Handle mail query with attachments

        Args:
            arguments: Tool arguments

        Returns:
            Query result as formatted string
        """
        try:
            # Validate and prepare user (auto-select, auto-authenticate)
            user_id, error = await self.validate_and_prepare_user(arguments)
            if error:
                return error

            # Validate parameters
            error = self.validate_parameters(arguments)
            if error:
                return error

            # Extract parameters (user_id is already set by validate_and_prepare_user)
            # user_id = arguments.get("user_id")  # Already validated above
            max_mails = arguments.get("max_mails", self.config.default_max_mails)
            include_body = arguments.get("include_body", True)
            download_attachments = arguments.get("download_attachments", False)
            save_emails = arguments.get("save_emails", True)
            save_csv = arguments.get("save_csv", False)
            output_format = arguments.get("output_format", "text")

            # Parse date range
            try:
                start_date, end_date, days_back = self.parse_date_range(arguments)
            except ValueError as e:
                return f"Error: {str(e)}"

            # Create mail query
            orchestrator = MailQueryOrchestrator()

            # Setup filters - keyword_filter will be applied client-side, not server-side
            keyword_filter = None

            # Handle keyword_filter parameter (structured)
            keyword_filter_dict = arguments.get("keyword_filter")
            if keyword_filter_dict:
                keyword_filter = KeywordFilter(**keyword_filter_dict)

            # Handle legacy keyword parameter (simple string)
            keyword = arguments.get("keyword")
            if keyword and not keyword_filter:
                # Convert simple keyword to and_keywords for backward compatibility
                keyword_filter = KeywordFilter(and_keywords=[keyword])

            # Traditional filtering with date range
            filters = MailQuerySeverFilters(date_from=start_date, date_to=end_date)

            if arguments.get("sender_address"):
                filters.sender_address = arguments["sender_address"]

            if arguments.get("subject_contains"):
                filters.subject_contains = arguments["subject_contains"]

            # Setup fields
            select_fields = [
                "id", "subject", "from", "sender", "receivedDateTime",
                "bodyPreview", "hasAttachments", "importance", "isRead"
            ]
            if include_body:
                select_fields.append("body")
            if download_attachments:
                select_fields.append("attachments")

            # Adjust query for conversation filters or keyword
            conversation_with = arguments.get("conversation_with", [])
            recipient_address = arguments.get("recipient_address")

            # If using client-side filters (keyword_filter, conversation_with, recipient_address),
            # fetch more emails to filter from
            if keyword_filter or conversation_with or recipient_address:
                if "toRecipients" not in select_fields:
                    select_fields.append("toRecipients")
                # Fetch more emails when using client-side filtering
                query_max_mails = min(max_mails * 3, 500)  # Get more for filtering
            else:
                query_max_mails = max_mails

            # Create request (blocked_senders를 mail_query에 전달)
            request = MailQueryRequest(
                user_id=user_id,
                filters=filters,
                pagination=PaginationOptions(top=query_max_mails, skip=0, max_pages=1),
                select_fields=select_fields,
                blocked_senders=self.config.blocked_senders,  # ⭐ mail_query에서 blocking 처리
            )

            # Execute query
            async with orchestrator:
                response = await orchestrator.mail_query_user_emails(request)
                graph_client = orchestrator.graph_client if download_attachments else None

                # Get access token for attachment download (needed for large files without contentBytes)
                access_token = None
                if download_attachments and graph_client:
                    from infra.core.token_service import get_token_service
                    token_service = get_token_service()
                    access_token = await token_service.get_valid_access_token(user_id)

            # ⭐ Always apply blocking + optional filters (client-side filtering)
            response.messages = self.filter_messages(
                response.messages,
                user_id,
                {
                    "keyword_filter": keyword_filter,
                    "conversation_with": conversation_with,
                    "recipient_address": recipient_address
                }
            )
            # Limit to max_mails after filtering
            response.messages = response.messages[:max_mails]

            # Update last_used_at for the account
            try:
                from datetime import datetime, timezone
                db = get_mail_query_database()
                now_utc = datetime.now(timezone.utc).isoformat()
                db.execute_query(
                    "UPDATE accounts SET last_used_at = ? WHERE user_id = ?",
                    (now_utc, user_id)
                )
                logger.info(f"✅ last_used_at 업데이트 완료: {user_id}")
            except Exception as e:
                logger.warning(f"⚠️  last_used_at 업데이트 실패 (무시됨): {str(e)}")

            # Format results
            result_text = await self.format_results(
                response.messages,
                user_id,
                start_date,
                end_date,
                days_back,
                arguments,
                save_emails,
                download_attachments,
                graph_client,
                access_token,
                save_csv,
                output_format
            )

            return result_text

        except Exception as e:
            logger.error(f"Error in query_email: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return f"Error querying emails: {str(e)}"

    async def format_results(self, messages: List, user_id: str, start_date, end_date,
                       days_back: int, filters: Dict, save_emails: bool,
                       download_attachments: bool, graph_client, access_token, save_csv: bool,
                       output_format: str = "text") -> str:
        """
        Format query results for display

        Args:
            messages: List of email messages
            user_id: User ID
            start_date: Query start date
            end_date: Query end date
            days_back: Number of days queried
            filters: Applied filters
            save_emails: Whether emails were saved
            download_attachments: Whether attachments were downloaded
            graph_client: Graph API client
            access_token: Access token for Graph API (needed for large attachments)
            save_csv: Whether to save as CSV
            output_format: Output format style (text or json)

        Returns:
            Formatted result string
        """
        result_text = f"📧 메일 조회 결과 - {user_id}\n"
        result_text += f"{'='*60}\n"

        # Display date range info (convert UTC back to KST for display)
        if start_date and end_date:
            start_kst = start_date.replace(tzinfo=timezone.utc).astimezone(self.KST)
            end_kst = end_date.replace(tzinfo=timezone.utc).astimezone(self.KST)
            result_text += f"조회 기간: {start_kst.strftime('%Y-%m-%d %H:%M')} ~ "
            result_text += f"{end_kst.strftime('%Y-%m-%d %H:%M')} KST ({days_back}일간)\n"
        else:
            result_text += f"조회 기간: 최근 {days_back}일\n"

        # Display filters if applied
        if filters.get("conversation_with"):
            result_text += f"대화 필터: {', '.join(filters['conversation_with'])}\n"
        if filters.get("sender_address"):
            result_text += f"발신자 필터: {filters['sender_address']}\n"
        if filters.get("recipient_address"):
            result_text += f"수신자 필터: {filters['recipient_address']}\n"
        if filters.get("subject_contains"):
            result_text += f"제목 필터: '{filters['subject_contains']}' 포함\n"

        # Process each mail first to get accurate count
        processed_mails = []
        mail_map = {}  # mail_info와 원본 mail 객체 매핑
        for i, mail in enumerate(messages, 1):
            mail_info = await self.format_email_info(
                mail, i, user_id, save_emails, download_attachments, graph_client, access_token
            )

            if mail_info:  # Skip if None (blocked sender)
                processed_mails.append(mail_info)
                mail_map[mail_info['id']] = mail

        # Display result summary
        filtered_count = len(processed_mails)
        result_text += f"조회된 메일: {filtered_count}개"

        # Show what was included in the query
        query_details = []
        if filters.get("include_body"):
            query_details.append("본문 포함")
        else:
            query_details.append("제목만")

        if download_attachments:
            query_details.append("첨부파일 다운로드")

        if query_details:
            result_text += f" ({', '.join(query_details)})"

        result_text += "\n\n"

        # Display each mail
        for i, mail_info in enumerate(processed_mails, 1):
            mail = mail_map.get(mail_info['id'])

            # Add to result text
            result_text += f"\n[{i}] {mail_info['subject']}\n"
            result_text += f"   발신자: {mail_info['sender']}\n"
            result_text += f"   수신일: {mail_info['received_date']} KST\n"
            result_text += f"   읽음: {'✓' if mail_info['is_read'] else '✗'}\n"
            result_text += f"   첨부: {'📎' if mail_info['has_attachments'] else '-'}\n"

            if save_emails and mail_info.get('saved_path'):
                result_text += f"   💾 저장됨: {mail_info['saved_path']}\n"

            # Include body preview if available
            if filters.get("include_body"):
                if mail_info.get("body"):
                    # Show full body without any truncation
                    result_text += f"   내용: {mail_info['body']}\n"
                elif mail_info.get("body_preview"):
                    result_text += f"   미리보기: {mail_info['body_preview']}\n"

            # Show attachment info
            if mail_info.get("attachments"):
                result_text += f"   첨부파일 ({len(mail_info['attachments'])}개):\n"
                for att in mail_info["attachments"]:
                    status = att.get("status", "unknown")
                    result_text += f"     - {att['name']} ({att['size']:,} bytes) [{status}]\n"

                    # Include token count if converted
                    if att.get("token_count"):
                        token_info = f"~{att['token_count']} tokens"
                        if att.get("is_truncated"):
                            token_info += f" (원본: ~{att['original_token_count']} tokens)"
                        result_text += f"       🔢 토큰: {token_info}\n"

                    # Include converted text content if available
                    if att.get("text_content"):
                        result_text += f"       📄 내용:\n{att['text_content']}\n"

        # Save to CSV if requested
        if save_csv and processed_mails:
            csv_path = self.save_emails_to_csv(processed_mails, user_id)
            result_text += f"\n\n📊 CSV 파일 저장됨: {csv_path}"

        result_text += f"\n\n✅ 총 {len(processed_mails)}개의 이메일이 처리되었습니다."

        # Add query options summary
        result_text += self._get_query_options_summary(filters, download_attachments)

        # Add formatting instructions from prompts.py
        result_text += f"\n\n{'='*80}\n"
        result_text += "📋 **결과 포맷팅 요청**\n"
        result_text += f"{'='*80}\n\n"
        result_text += self._get_format_instructions(user_id, output_format)

        return result_text

    def _get_query_options_summary(self, filters: Dict, download_attachments: bool) -> str:
        """현재 조회 옵션 상태와 추가 옵션 안내"""
        summary = f"\n\n{'='*80}\n"
        summary += "📌 **조회 옵션 상태**\n"
        summary += f"{'='*80}\n"

        # Current options
        include_body = filters.get("include_body", False)
        keyword = filters.get("keyword")
        keyword_filter = filters.get("keyword_filter")

        summary += "\n**현재 활성화된 옵션:**\n"
        active_options = []

        if include_body:
            active_options.append("✅ 본문 포함 (`include_body: true`)")
        else:
            active_options.append("❌ 제목만 조회 (본문 미포함)")

        if download_attachments:
            active_options.append("✅ 첨부파일 다운로드 (`download_attachments: true`)")
        else:
            active_options.append("❌ 첨부파일 미다운로드")

        if keyword:
            active_options.append(f"✅ 키워드 검색: '{keyword}' (`keyword: \"{keyword}\"`)")
        elif keyword_filter:
            active_options.append(f"✅ 고급 키워드 필터 적용 (`keyword_filter`)")
        else:
            active_options.append("❌ 키워드 검색 미사용")

        for option in active_options:
            summary += f"- {option}\n"

        # Suggestions for inactive options
        summary += "\n**📢 사용 가능한 조회 방법:**\n"
        suggestions = []

        suggestions.append("- **메일 목록 조회**: \"최근 3개월 간 kimghw 계정에서 송수신한 메일 조회해줘\"")
        suggestions.append("- **메일 본문 조회**: \"최근 한달 간 kimghw 계정에서 송수신한 메일을 본문 포함하여 제공해줘\"")
        suggestions.append("- **첨부파일 포함 조회**: \"최근 한달 간 kimghw 계정에 송수신한 메일을 본문과 첨부파일 내용까지 조회해줘\"")
        suggestions.append("- **키워드 검색**: \"최근 3개월 간 'PL25032' 키워드에 대해 kimghw 계정에 송수신한 메일을 본문, 첨부파일까지 포함해서 조회해줘\"")

        for suggestion in suggestions:
            summary += f"{suggestion}\n"

        summary += "\n💡 위 표현으로 다시 질문해주세요."

        return summary

    def _get_format_instructions(self, user_id: str, output_format: str = "text") -> str:
        """Get email formatting instructions from prompts.py"""
        # Map output_format to format_style
        format_style = "table" if output_format == "text" else "json"
        return get_format_email_results_prompt(
            format_style=format_style,
            include_attachments=True,
            user_id=user_id
        )

    def save_emails_to_csv(self, emails: List[Dict[str, Any]], user_id: str) -> Path:
        """
        Save email data to CSV file

        Args:
            emails: List of email dictionaries
            user_id: User ID

        Returns:
            Path to saved CSV file
        """
        # Create output directory
        csv_dir = Path(self.config.save_directory) / user_id / "exports"
        csv_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = csv_dir / f"email_metadata_{timestamp}.csv"

        # Write CSV
        with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
            if emails:
                # Define field names
                fieldnames = [
                    'subject', 'sender', 'sender_email', 'received_date',
                    'has_attachments', 'is_read', 'importance', 'body_preview'
                ]

                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for email in emails:
                    row = {
                        'subject': email.get('subject', ''),
                        'sender': email.get('sender', ''),
                        'sender_email': email.get('sender_email', ''),
                        'received_date': email.get('received_date', ''),
                        'has_attachments': email.get('has_attachments', False),
                        'is_read': email.get('is_read', False),
                        'importance': email.get('importance', 'normal'),
                        'body_preview': email.get('body', '')[:200] if email.get('body') else email.get('body_preview', '')[:200]
                    }
                    writer.writerow(row)

        logger.info(f"CSV file saved: {csv_file}")
        return csv_file
