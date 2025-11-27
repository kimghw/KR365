"""PKCE (Proof Key for Code Exchange) Support for OAuth2
RFC 7636 Implementation

PKCE adds security to OAuth2 authorization code flow by:
1. Client generates code_verifier (random string)
2. Client sends code_challenge (SHA256 hash of verifier) with authorization request
3. Client sends code_verifier with token request
4. Server verifies that SHA256(code_verifier) == code_challenge
"""

import hashlib
import base64
import secrets
from typing import Optional

def generate_code_verifier(length: int = 128) -> str:
    """Generate a cryptographically secure code verifier

    Args:
        length: Length of the verifier (43-128 characters)

    Returns:
        URL-safe base64 encoded random string
    """
    if not 43 <= length <= 128:
        raise ValueError("Code verifier length must be between 43 and 128")

    # Generate random bytes
    num_bytes = (length * 3) // 4  # base64 encoding ratio
    random_bytes = secrets.token_bytes(num_bytes)

    # Convert to URL-safe base64 and remove padding
    verifier = base64.urlsafe_b64encode(random_bytes).decode('ascii')
    verifier = verifier.rstrip('=')[:length]

    return verifier

def generate_code_challenge(verifier: str, method: str = "S256") -> str:
    """Generate code challenge from verifier

    Args:
        verifier: The code verifier string
        method: Challenge method ("S256" or "plain")

    Returns:
        Code challenge string
    """
    if method == "plain":
        return verifier
    elif method == "S256":
        # SHA256 hash of verifier
        digest = hashlib.sha256(verifier.encode('ascii')).digest()
        # Convert to URL-safe base64 without padding
        challenge = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
        return challenge
    else:
        raise ValueError(f"Unsupported challenge method: {method}")

def verify_code_verifier(
    verifier: str,
    challenge: str,
    method: str = "S256"
) -> bool:
    """Verify that the code verifier matches the challenge

    Args:
        verifier: The code verifier from token request
        challenge: The code challenge from authorization request
        method: Challenge method used

    Returns:
        True if verifier is valid, False otherwise
    """
    try:
        expected_challenge = generate_code_challenge(verifier, method)
        return expected_challenge == challenge
    except Exception:
        return False

class PKCEValidator:
    """PKCE validation helper for OAuth2 server"""

    def __init__(self):
        self.supported_methods = ["S256", "plain"]

    def validate_challenge_method(self, method: Optional[str]) -> str:
        """Validate and normalize challenge method

        Args:
            method: Requested challenge method

        Returns:
            Normalized method (defaults to S256 if not specified)
        """
        if method is None:
            return "S256"  # Default to most secure method

        if method not in self.supported_methods:
            raise ValueError(f"Unsupported code_challenge_method: {method}")

        return method

    def validate_verifier_format(self, verifier: str) -> bool:
        """Validate code verifier format according to RFC 7636

        Args:
            verifier: Code verifier to validate

        Returns:
            True if valid format
        """
        # RFC 7636: code_verifier = 43-128 characters from [A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~"
        if not 43 <= len(verifier) <= 128:
            return False

        # Check allowed characters
        allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        return all(c in allowed_chars for c in verifier)

    def store_challenge(
        self,
        auth_code: str,
        challenge: str,
        method: str
    ) -> None:
        """Store code challenge with authorization code

        This should be implemented to store in database
        """
        # TODO: Implement database storage
        pass

    def retrieve_challenge(self, auth_code: str) -> tuple[Optional[str], Optional[str]]:
        """Retrieve stored challenge for authorization code

        Returns:
            Tuple of (challenge, method) or (None, None) if not found
        """
        # TODO: Implement database retrieval
        return None, None

# Example usage for client-side PKCE
def create_pkce_challenge_pair():
    """Create a PKCE challenge pair for client use

    Returns:
        Dict with verifier, challenge, and method
    """
    verifier = generate_code_verifier()
    challenge = generate_code_challenge(verifier, "S256")

    return {
        "code_verifier": verifier,
        "code_challenge": challenge,
        "code_challenge_method": "S256"
    }

# Test the implementation
if __name__ == "__main__":
    # Generate PKCE pair
    pkce = create_pkce_challenge_pair()
    print(f"Verifier: {pkce['code_verifier']}")
    print(f"Challenge: {pkce['code_challenge']}")

    # Verify
    is_valid = verify_code_verifier(
        pkce['code_verifier'],
        pkce['code_challenge'],
        pkce['code_challenge_method']
    )
    print(f"Verification: {is_valid}")