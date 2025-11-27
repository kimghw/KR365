"""Sender blocking logic for email messages"""

from typing import List


class SenderBlocker:
    """발신자 차단 필터"""

    def __init__(self, blocked_senders: List[str]):
        """
        Initialize sender blocker

        Args:
            blocked_senders: List of blocked sender addresses/domains
        """
        self.blocked_senders = [s.lower() for s in blocked_senders]

    def is_blocked(self, sender_email: str) -> bool:
        """
        차단된 발신자인지 확인

        Args:
            sender_email: Sender email address

        Returns:
            True if sender is blocked
        """
        if not sender_email:
            return False

        sender_email = sender_email.lower()
        return any(blocked in sender_email for blocked in self.blocked_senders)

    def filter_messages(self, messages: List) -> List:
        """
        차단된 발신자의 메일 제거

        Args:
            messages: List of email messages

        Returns:
            Filtered list of messages (blocked senders removed)
        """
        filtered = []
        for mail in messages:
            sender_email = self._get_sender_email(mail)
            if not self.is_blocked(sender_email):
                filtered.append(mail)
        return filtered

    @staticmethod
    def _get_sender_email(mail) -> str:
        """
        발신자 이메일 추출

        Args:
            mail: Email message object

        Returns:
            Sender email address (lowercase)
        """
        if mail.from_address and isinstance(mail.from_address, dict):
            email_addr = mail.from_address.get("emailAddress", {})
            return email_addr.get("address", "").lower()
        return ""
