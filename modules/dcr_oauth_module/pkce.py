"""
PKCE helper for DCR OAuth module.
"""

import base64
import hashlib
import secrets


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "plain") -> bool:
    if method == "plain":
        return secrets.compare_digest(code_verifier, code_challenge)
    if method == "S256":
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        calculated_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
        return secrets.compare_digest(calculated_challenge, code_challenge)
    return False

