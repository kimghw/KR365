"""
Dynamic Client Registration (DCR) OAuth Module (Simplified)

RFC 7591 준수 동적 클라이언트 등록 서비스
토큰 공유 없는 독립적인 서비스별 인증
"""

from .dcr_service import DCRService

__all__ = ["DCRService"]