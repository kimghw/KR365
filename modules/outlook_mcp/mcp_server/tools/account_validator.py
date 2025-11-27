"""Account input validation module"""

import re
from typing import Dict, List, Optional, Tuple


class AccountValidator:
    """Validator for account enrollment data"""

    # Valid OAuth permission patterns
    VALID_PERMISSIONS = [
        "Mail.Read",
        "Mail.ReadWrite",
        "Mail.Send",
        "Files.Read",
        "Files.ReadWrite",
        "Files.ReadWrite.All",
        "Sites.Read.All",
        "Sites.ReadWrite.All",
        "offline_access",
        "User.Read",
        "Calendars.ReadWrite"
    ]

    @staticmethod
    def validate_user_id(user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Validate user ID format

        Args:
            user_id: User ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not user_id:
            return False, "user_id cannot be empty"

        if not isinstance(user_id, str):
            return False, "user_id must be a string"

        # Check length (3-50 characters)
        if len(user_id) < 3:
            return False, "user_id must be at least 3 characters long"
        if len(user_id) > 50:
            return False, "user_id must be at most 50 characters long"

        # Check allowed characters: alphanumeric, underscore, hyphen, dot
        if not re.match(r'^[a-zA-Z0-9._-]+$', user_id):
            return False, "user_id can only contain letters, numbers, dots, underscores, and hyphens"

        # Must start with alphanumeric
        if not re.match(r'^[a-zA-Z0-9]', user_id):
            return False, "user_id must start with a letter or number"

        return True, None

    @staticmethod
    def validate_email(email: str) -> Tuple[bool, Optional[str]]:
        """
        Validate email address format

        Args:
            email: Email address to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not email:
            return False, "email cannot be empty"

        if not isinstance(email, str):
            return False, "email must be a string"

        # Basic email regex pattern
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return False, "email format is invalid (expected: user@domain.com)"

        # Check length
        if len(email) > 254:
            return False, "email is too long (max 254 characters)"

        # Check local part (before @)
        local_part = email.split('@')[0]
        if len(local_part) > 64:
            return False, "email local part is too long (max 64 characters)"

        return True, None

    @staticmethod
    def validate_oauth_client_id(client_id: str) -> Tuple[bool, Optional[str]]:
        """
        Validate OAuth Client ID format

        Args:
            client_id: Client ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not client_id:
            return False, "oauth_client_id cannot be empty"

        if not isinstance(client_id, str):
            return False, "oauth_client_id must be a string"

        # Azure App Client ID is typically a GUID (36 characters with hyphens)
        # Format: 8-4-4-4-12 hexadecimal digits
        guid_pattern = r'^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$'
        if not re.match(guid_pattern, client_id):
            return False, "oauth_client_id must be a valid GUID format (e.g., 12345678-1234-1234-1234-123456789012)"

        return True, None

    @staticmethod
    def validate_oauth_client_secret(client_secret: str) -> Tuple[bool, Optional[str]]:
        """
        Validate OAuth Client Secret format

        Args:
            client_secret: Client Secret to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not client_secret:
            return False, "oauth_client_secret cannot be empty"

        if not isinstance(client_secret, str):
            return False, "oauth_client_secret must be a string"

        # Client secret should be at least 8 characters
        if len(client_secret) < 8:
            return False, "oauth_client_secret is too short (minimum 8 characters)"

        # Check for reasonable maximum length
        if len(client_secret) > 256:
            return False, "oauth_client_secret is too long (maximum 256 characters)"

        return True, None

    @staticmethod
    def validate_oauth_tenant_id(tenant_id: str) -> Tuple[bool, Optional[str]]:
        """
        Validate OAuth Tenant ID format

        Args:
            tenant_id: Tenant ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not tenant_id:
            return False, "oauth_tenant_id cannot be empty"

        if not isinstance(tenant_id, str):
            return False, "oauth_tenant_id must be a string"

        # Tenant ID is also a GUID
        guid_pattern = r'^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$'
        if not re.match(guid_pattern, tenant_id):
            return False, "oauth_tenant_id must be a valid GUID format (e.g., 12345678-1234-1234-1234-123456789012)"

        return True, None

    @staticmethod
    def validate_redirect_uri(redirect_uri: str) -> Tuple[bool, Optional[str]]:
        """
        Validate OAuth Redirect URI format

        Args:
            redirect_uri: Redirect URI to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not redirect_uri:
            return False, "oauth_redirect_uri cannot be empty"

        if not isinstance(redirect_uri, str):
            return False, "oauth_redirect_uri must be a string"

        # Check if it's a valid URL
        url_pattern = r'^https?://[a-zA-Z0-9.-]+(:[0-9]+)?(/.*)?$'
        if not re.match(url_pattern, redirect_uri):
            return False, "oauth_redirect_uri must be a valid HTTP/HTTPS URL"

        return True, None

    @classmethod
    def validate_permissions(cls, permissions: List[str]) -> Tuple[bool, Optional[str]]:
        """
        Validate delegated permissions list

        Args:
            permissions: List of permission strings

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not permissions:
            return False, "delegated_permissions cannot be empty"

        if not isinstance(permissions, list):
            return False, "delegated_permissions must be a list"

        # Check each permission
        invalid_perms = []
        for perm in permissions:
            if not isinstance(perm, str):
                return False, f"permission must be a string, got: {type(perm)}"
            if perm not in cls.VALID_PERMISSIONS:
                invalid_perms.append(perm)

        if invalid_perms:
            return False, f"invalid permissions: {', '.join(invalid_perms)}. Valid permissions: {', '.join(cls.VALID_PERMISSIONS)}"

        return True, None

    @classmethod
    def validate_enrollment_data(cls, data: Dict) -> Tuple[bool, List[str]]:
        """
        Validate all enrollment data

        Args:
            data: Dictionary containing enrollment data

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Validate user_id
        user_id = data.get("user_id")
        is_valid, error = cls.validate_user_id(user_id)
        if not is_valid:
            errors.append(f"user_id: {error}")

        # Validate email
        email = data.get("email")
        is_valid, error = cls.validate_email(email)
        if not is_valid:
            errors.append(f"email: {error}")

        # Validate oauth_client_id
        client_id = data.get("oauth_client_id")
        is_valid, error = cls.validate_oauth_client_id(client_id)
        if not is_valid:
            errors.append(f"oauth_client_id: {error}")

        # Validate oauth_client_secret
        client_secret = data.get("oauth_client_secret")
        is_valid, error = cls.validate_oauth_client_secret(client_secret)
        if not is_valid:
            errors.append(f"oauth_client_secret: {error}")

        # Validate oauth_tenant_id
        tenant_id = data.get("oauth_tenant_id")
        is_valid, error = cls.validate_oauth_tenant_id(tenant_id)
        if not is_valid:
            errors.append(f"oauth_tenant_id: {error}")

        # Validate oauth_redirect_uri (if provided)
        redirect_uri = data.get("oauth_redirect_uri")
        if redirect_uri:
            is_valid, error = cls.validate_redirect_uri(redirect_uri)
            if not is_valid:
                errors.append(f"oauth_redirect_uri: {error}")

        # Validate delegated_permissions (if provided)
        permissions = data.get("delegated_permissions")
        if permissions:
            is_valid, error = cls.validate_permissions(permissions)
            if not is_valid:
                errors.append(f"delegated_permissions: {error}")

        return len(errors) == 0, errors
