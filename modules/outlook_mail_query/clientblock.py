"""Client-side sender blocking logic for email messages"""

from typing import List, Optional
from .mail_query_schema import GraphMailItem


class ClientBlocker:
    """클라이언트 사이드 발신자 차단 필터"""

    def __init__(self, blocked_senders: Optional[List[str]] = None):
        """
        Initialize client-side sender blocker

        Args:
            blocked_senders: List of blocked sender addresses/domains/patterns
                           Examples: ["noreply@", "block@krs.co.kr", "@spam.com"]
        """
        self.blocked_senders = [s.lower() for s in (blocked_senders or [])]

    def is_blocked(self, sender_email: str) -> bool:
        """
        차단된 발신자인지 확인 (부분 문자열 매칭)

        Args:
            sender_email: Sender email address

        Returns:
            True if sender is blocked

        Examples:
            >>> blocker = ClientBlocker(["noreply@", "spam.com"])
            >>> blocker.is_blocked("noreply@github.com")
            True
            >>> blocker.is_blocked("user@spam.com")
            True
            >>> blocker.is_blocked("user@example.com")
            False
        """
        if not sender_email:
            return False

        sender_email = sender_email.lower()
        return any(blocked in sender_email for blocked in self.blocked_senders)

    def filter_messages(self, messages: List[GraphMailItem]) -> List[GraphMailItem]:
        """
        차단된 발신자의 메일 제거

        Args:
            messages: List of email messages

        Returns:
            Filtered list of messages (blocked senders removed)
        """
        if not self.blocked_senders:
            return messages

        filtered = []
        for mail in messages:
            sender_email = self._get_sender_email(mail)
            if not self.is_blocked(sender_email):
                filtered.append(mail)
        return filtered

    @staticmethod
    def _get_sender_email(mail: GraphMailItem) -> str:
        """
        발신자 이메일 추출

        Args:
            mail: Email message object (GraphMailItem)

        Returns:
            Sender email address (lowercase)
        """
        if mail.from_address and isinstance(mail.from_address, dict):
            email_addr = mail.from_address.get("emailAddress", {})
            return email_addr.get("address", "").lower()
        return ""
