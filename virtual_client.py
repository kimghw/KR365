#!/usr/bin/env python3
"""
Virtual Client for Testing Remote MCP with Authorization
Based on: https://loginov-rocks.medium.com/build-remote-mcp-with-authorization-a2f394c669a8

This script simulates what Claude does when connecting to a remote MCP server
with OAuth2 authorization.
"""

import json
import hashlib
import base64
import secrets
import time
import asyncio
import httpx
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlencode, parse_qs, urlparse

# Configuration
MCP_SERVER_URL = "http://localhost:8001"
MCP_ENDPOINT = "/mcp"  # For Streamable HTTP
SSE_ENDPOINT = "/sse"  # For SSE transport
CLIENT_NAME = "virtual_client"
REDIRECT_URI = "http://localhost:9999/callback"
SCOPE = "Mail.Read User.Read"


class VirtualMCPClient:
    """Virtual client that simulates Claude's behavior for testing MCP with authorization"""

    def __init__(self, server_url: str = MCP_SERVER_URL):
        self.server_url = server_url
        self.client_id = None
        self.client_secret = None
        self.access_token = None
        self.refresh_token = None
        self.session_id = None

        # PKCE parameters
        self.code_verifier = None
        self.code_challenge = None
        self.state = None

        print(f"🚀 Virtual MCP Client initialized")
        print(f"   Server URL: {server_url}")
        print()

    def generate_pkce(self) -> Tuple[str, str]:
        """Generate PKCE code verifier and challenge"""
        # Generate code verifier
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')

        # Generate code challenge (S256)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode('utf-8').rstrip('=')

        return verifier, challenge

    async def discover_authorization_server(self) -> Dict[str, Any]:
        """Step 1: Discover OAuth authorization server metadata"""
        print("📍 Step 1: Discovering authorization server...")

        url = f"{self.server_url}/.well-known/oauth-authorization-server"

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            metadata = response.json()

        print("✅ Authorization server discovered:")
        print(f"   - Authorization endpoint: {metadata.get('authorization_endpoint')}")
        print(f"   - Token endpoint: {metadata.get('token_endpoint')}")
        print(f"   - Registration endpoint: {metadata.get('registration_endpoint')}")
        print()

        return metadata

    async def register_client(self, metadata: Dict[str, Any]) -> None:
        """Step 2: Register as OAuth client (Dynamic Client Registration)"""
        print("📍 Step 2: Registering OAuth client...")

        registration_endpoint = metadata.get('registration_endpoint')

        payload = {
            "client_name": CLIENT_NAME,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # Public client
            "scope": SCOPE,
            "redirect_uris": [REDIRECT_URI]
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(registration_endpoint, json=payload)
            response.raise_for_status()
            registration = response.json()

        self.client_id = registration.get('client_id')
        self.client_secret = registration.get('client_secret')

        print("✅ Client registered:")
        print(f"   - Client ID: {self.client_id}")
        print(f"   - Client Secret: {'***' + self.client_secret[-10:] if self.client_secret else 'None (public client)'}")
        print()

    def build_authorization_url(self, metadata: Dict[str, Any]) -> str:
        """Step 3: Build authorization URL with PKCE"""
        print("📍 Step 3: Building authorization URL...")

        # Generate PKCE parameters
        self.code_verifier, self.code_challenge = self.generate_pkce()
        self.state = secrets.token_urlsafe(32)

        authorization_endpoint = metadata.get('authorization_endpoint')

        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': REDIRECT_URI,
            'scope': SCOPE,
            'state': self.state,
            'code_challenge': self.code_challenge,
            'code_challenge_method': 'S256'
        }

        auth_url = f"{authorization_endpoint}?{urlencode(params)}"

        print("✅ Authorization URL built with PKCE:")
        print(f"   - Code challenge: {self.code_challenge[:20]}...")
        print(f"   - State: {self.state[:20]}...")
        print()

        return auth_url

    async def exchange_code_for_tokens(self, code: str, metadata: Dict[str, Any]) -> None:
        """Step 4: Exchange authorization code for tokens"""
        print("📍 Step 4: Exchanging authorization code for tokens...")

        token_endpoint = metadata.get('token_endpoint')

        payload = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': self.client_id,
            'redirect_uri': REDIRECT_URI,
            'code_verifier': self.code_verifier
        }

        if self.client_secret:
            payload['client_secret'] = self.client_secret

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_endpoint,
                data=payload,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            response.raise_for_status()
            tokens = response.json()

        self.access_token = tokens.get('access_token')
        self.refresh_token = tokens.get('refresh_token')

        print("✅ Tokens received:")
        print(f"   - Access token: {'Bearer ' + self.access_token[:20]}...")
        print(f"   - Token type: {tokens.get('token_type')}")
        print(f"   - Expires in: {tokens.get('expires_in')} seconds")
        print(f"   - Refresh token: {'Yes' if self.refresh_token else 'No'}")
        print()

    async def initialize_mcp_session(self) -> None:
        """Step 5: Initialize MCP session (Streamable HTTP)"""
        print("📍 Step 5: Initializing MCP session...")

        url = f"{self.server_url}{MCP_ENDPOINT}"

        # MCP Initialize request
        mcp_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "clientInfo": {
                    "name": "virtual_client",
                    "version": "1.0.0"
                },
                "capabilities": {}
            }
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=mcp_request, headers=headers)
            response.raise_for_status()

            # Extract session ID from headers
            self.session_id = response.headers.get('X-Session-Id')

            result = response.json()

        print("✅ MCP session initialized:")
        print(f"   - Session ID: {self.session_id}")
        print(f"   - Server name: {result.get('result', {}).get('serverInfo', {}).get('name')}")
        print(f"   - Protocol version: {result.get('result', {}).get('protocolVersion')}")
        print()

        return result

    async def list_mcp_tools(self) -> None:
        """Step 6: List available MCP tools"""
        print("📍 Step 6: Listing MCP tools...")

        url = f"{self.server_url}{MCP_ENDPOINT}"

        mcp_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'X-Session-Id': self.session_id
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=mcp_request, headers=headers)
            response.raise_for_status()
            result = response.json()

        tools = result.get('result', {}).get('tools', [])

        print(f"✅ Found {len(tools)} tools:")
        for tool in tools:
            print(f"   - {tool.get('name')}: {tool.get('description')}")
        print()

        return result

    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        """Step 7: Call an MCP tool"""
        print(f"📍 Step 7: Calling MCP tool '{tool_name}'...")

        url = f"{self.server_url}{MCP_ENDPOINT}"

        mcp_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'X-Session-Id': self.session_id
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=mcp_request, headers=headers)
            response.raise_for_status()
            result = response.json()

        print("✅ Tool response received:")
        print(json.dumps(result.get('result', {}), indent=2))
        print()

        return result

    async def refresh_access_token(self, metadata: Dict[str, Any]) -> None:
        """Refresh the access token"""
        print("📍 Refreshing access token...")

        token_endpoint = metadata.get('token_endpoint')

        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id
        }

        if self.client_secret:
            payload['client_secret'] = self.client_secret

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_endpoint,
                data=payload,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            response.raise_for_status()
            tokens = response.json()

        self.access_token = tokens.get('access_token')
        new_refresh_token = tokens.get('refresh_token')
        if new_refresh_token:
            self.refresh_token = new_refresh_token

        print("✅ Token refreshed successfully")
        print()

    async def close_mcp_session(self) -> None:
        """Close the MCP session"""
        if not self.session_id:
            return

        print("📍 Closing MCP session...")

        url = f"{self.server_url}{MCP_ENDPOINT}"

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'X-Session-Id': self.session_id
        }

        async with httpx.AsyncClient() as client:
            response = await client.delete(url, headers=headers)
            # Don't raise for status - session might already be closed

        print("✅ MCP session closed")
        print()


async def simulate_authorization_code(auth_url: str) -> str:
    """
    Simulate user authorization and return authorization code.
    In a real scenario, this would involve:
    1. Opening the auth_url in a browser
    2. User logging in and granting permissions
    3. Capturing the authorization code from the redirect
    """
    print("⚠️  Manual Authorization Required:")
    print("-" * 60)
    print("Please complete the authorization flow manually:")
    print()
    print("1. Open this URL in your browser:")
    print(f"   {auth_url}")
    print()
    print("2. Complete the authorization (login, grant permissions)")
    print()
    print("3. After redirect, copy the 'code' parameter from the URL")
    print("   Example: http://localhost:9999/callback?code=XXXXX&state=...")
    print()
    print("-" * 60)

    code = input("Enter the authorization code: ").strip()
    return code


async def test_full_flow():
    """Test the complete OAuth2 + MCP flow"""
    print("=" * 60)
    print("🧪 Testing Remote MCP with Authorization")
    print("=" * 60)
    print()

    client = VirtualMCPClient()

    try:
        # Step 1: Discover authorization server
        metadata = await client.discover_authorization_server()

        # Step 2: Register as OAuth client
        await client.register_client(metadata)

        # Step 3: Build authorization URL
        auth_url = client.build_authorization_url(metadata)

        # Step 4: Simulate authorization (manual step)
        auth_code = await simulate_authorization_code(auth_url)

        # Step 5: Exchange code for tokens
        await client.exchange_code_for_tokens(auth_code, metadata)

        # Step 6: Initialize MCP session
        await client.initialize_mcp_session()

        # Step 7: List available tools
        await client.list_mcp_tools()

        # Step 8: Call a tool (example)
        print("📍 Step 8: Testing tool call...")
        print("   (Attempting to call 'query_email' tool)")
        print()

        try:
            await client.call_mcp_tool("query_email", {
                "days_back": 7,
                "max_results": 5
            })
        except Exception as e:
            print(f"   ⚠️ Tool call failed (expected if no email data): {e}")
            print()

        # Step 9: Test token refresh
        if client.refresh_token:
            print("📍 Step 9: Testing token refresh...")
            await asyncio.sleep(2)  # Wait a bit
            await client.refresh_access_token(metadata)

        # Step 10: Close session
        await client.close_mcp_session()

        print("=" * 60)
        print("✅ All tests completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def test_without_auth():
    """Test that unauthenticated requests are properly rejected"""
    print("=" * 60)
    print("🧪 Testing Unauthenticated Access (should fail)")
    print("=" * 60)
    print()

    url = f"{MCP_SERVER_URL}{MCP_ENDPOINT}"

    # Try to access without token
    mcp_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=mcp_request)

            if response.status_code == 401:
                print("✅ Unauthenticated request properly rejected (401)")
            else:
                print(f"❌ Unexpected response: {response.status_code}")
                print(response.text)
    except Exception as e:
        print(f"❌ Error: {e}")

    print()


def main():
    """Main entry point"""
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "--no-auth":
            asyncio.run(test_without_auth())
        else:
            print(f"Unknown option: {sys.argv[1]}")
            print("Usage: python test_virtual_client.py [--no-auth]")
    else:
        asyncio.run(test_full_flow())


if __name__ == "__main__":
    main()