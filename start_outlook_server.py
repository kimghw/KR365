#!/usr/bin/env python3
"""Start Outlook MCP server with correct database configuration"""

import os
import subprocess
import sys

# Set environment variables
os.environ["DCR_DATABASE_PATH"] = "/home/kimghw/KR365/data/auth_mail_query.db"
os.environ["DATABASE_MAIL_QUERY_PATH"] = "/home/kimghw/KR365/data/mail_query.db"
os.environ["MAIL_API_PORT"] = "8001"
os.environ["DCR_OAUTH_REDIRECT_URI"] = "https://outlook.kimghw.org/oauth/azure_callback"

print("🚀 Starting Outlook MCP server...")
print(f"📂 DCR Database: {os.environ['DCR_DATABASE_PATH']}")
print(f"📂 Mail Query Database: {os.environ['DATABASE_MAIL_QUERY_PATH']}")
print(f"🌐 Port: {os.environ['MAIL_API_PORT']}")

# Start the server
subprocess.run([
    sys.executable,
    "modules/outlook_mcp/entrypoints/run_fastapi.py",
    "--port", "8001"
])