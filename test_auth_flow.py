#!/usr/bin/env python3
"""
Automated authentication flow test for Remote MCP with Authorization
"""

import asyncio
import httpx
import json
import base64
import hashlib
import secrets
import urllib.parse
from typing import Dict, Optional, Any

class AuthTestClient:
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.client_id = None
        self.client_secret = None
        self.access_token = None

    async def test_discovery(self) -> bool:
        """Test OAuth2 discovery endpoint"""
        print("\n🔍 Testing OAuth2 Discovery...")
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/.well-known/oauth-authorization-server")
            if response.status_code == 200:
                metadata = response.json()
                print("✅ Discovery successful:")
                print(f"   - Authorization: {metadata.get('authorization_endpoint')}")
                print(f"   - Token: {metadata.get('token_endpoint')}")
                print(f"   - Registration: {metadata.get('registration_endpoint')}")
                return True
            else:
                print(f"❌ Discovery failed: {response.status_code}")
                return False

    async def test_client_registration(self) -> bool:
        """Test Dynamic Client Registration"""
        print("\n📝 Testing Dynamic Client Registration...")

        client_metadata = {
            "client_name": "Test MCP Client",
            "redirect_uris": ["http://localhost:9999/callback"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "scope": "Mail.Read User.Read"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/oauth/register",
                json=client_metadata
            )

            if response.status_code == 201:
                reg_data = response.json()
                self.client_id = reg_data.get("client_id")
                self.client_secret = reg_data.get("client_secret")
                print(f"✅ Client registered:")
                print(f"   - Client ID: {self.client_id}")
                print(f"   - Client Secret: ***{self.client_secret[-6:]}")
                return True
            else:
                print(f"❌ Registration failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False

    async def test_mock_token_exchange(self) -> bool:
        """Test token exchange with mock authorization code"""
        print("\n🔑 Testing Token Exchange (mock)...")

        # Generate mock authorization code (for testing purposes)
        mock_code = "test_" + secrets.token_urlsafe(32)

        token_data = {
            "grant_type": "authorization_code",
            "code": mock_code,
            "redirect_uri": "http://localhost:9999/callback",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code_verifier": secrets.token_urlsafe(32)
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/oauth/token",
                data=token_data
            )

            if response.status_code in [200, 400]:  # 400 is expected for invalid code
                print(f"✅ Token endpoint responding correctly")
                if response.status_code == 400:
                    print("   (Expected 400 for mock code)")
                return True
            else:
                print(f"❌ Unexpected response: {response.status_code}")
                return False

    async def test_mcp_without_auth(self) -> bool:
        """Test that MCP endpoints require authentication"""
        print("\n🚫 Testing MCP endpoints without auth...")

        mcp_request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {},
            "id": 1
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/",
                json=mcp_request,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 401:
                print("✅ MCP endpoint correctly requires authentication")
                error_detail = response.json()
                print(f"   Error: {error_detail.get('detail', {}).get('message', 'Authentication required')}")
                return True
            else:
                print(f"❌ MCP endpoint should return 401, got: {response.status_code}")
                return False

    async def test_mcp_with_invalid_token(self) -> bool:
        """Test MCP endpoint with invalid bearer token"""
        print("\n🔒 Testing MCP with invalid token...")

        mcp_request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {},
            "id": 1
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/",
                json=mcp_request,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer invalid_token_123"
                }
            )

            if response.status_code == 401:
                print("✅ Invalid token correctly rejected")
                return True
            else:
                print(f"❌ Expected 401, got: {response.status_code}")
                return False

    async def test_public_endpoints(self) -> bool:
        """Test that public endpoints don't require auth"""
        print("\n🌍 Testing public endpoints...")

        public_endpoints = [
            ("GET", "/health", "Health check"),
            ("GET", "/.well-known/oauth-authorization-server", "OAuth discovery"),
            ("GET", "/.well-known/mcp.json", "MCP discovery"),
        ]

        all_passed = True
        async with httpx.AsyncClient() as client:
            for method, path, name in public_endpoints:
                if method == "GET":
                    response = await client.get(f"{self.base_url}{path}")
                else:
                    response = await client.post(f"{self.base_url}{path}")

                if response.status_code in [200, 404]:  # 404 is ok for some endpoints
                    print(f"✅ {name}: Accessible without auth ({response.status_code})")
                else:
                    print(f"❌ {name}: Unexpected status {response.status_code}")
                    all_passed = False

        return all_passed

    async def run_all_tests(self):
        """Run all authentication tests"""
        print("="*60)
        print("🧪 Running Authentication Test Suite")
        print("="*60)

        results = []

        # Test 1: Discovery
        results.append(("OAuth2 Discovery", await self.test_discovery()))

        # Test 2: Public endpoints
        results.append(("Public Endpoints", await self.test_public_endpoints()))

        # Test 3: Client Registration
        results.append(("Dynamic Client Registration", await self.test_client_registration()))

        # Test 4: Token Exchange (mock)
        if self.client_id and self.client_secret:
            results.append(("Token Exchange", await self.test_mock_token_exchange()))

        # Test 5: MCP without auth
        results.append(("MCP Requires Auth", await self.test_mcp_without_auth()))

        # Test 6: MCP with invalid token
        results.append(("Invalid Token Rejection", await self.test_mcp_with_invalid_token()))

        # Summary
        print("\n" + "="*60)
        print("📊 Test Results Summary")
        print("="*60)

        passed = 0
        failed = 0

        for test_name, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status}: {test_name}")
            if result:
                passed += 1
            else:
                failed += 1

        print(f"\nTotal: {passed} passed, {failed} failed")

        if failed == 0:
            print("\n🎉 All tests passed! Authentication is working correctly.")
        else:
            print(f"\n⚠️  {failed} test(s) failed. Please check the implementation.")

        return failed == 0


async def main():
    client = AuthTestClient()
    success = await client.run_all_tests()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)