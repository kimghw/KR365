#!/usr/bin/env python3
"""Test boolean conversion flow through handlers"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.mail_query_MCP.mcp_server.utils import preprocess_arguments


def test_handler_flow():
    """Simulate the handler flow"""

    print("\n" + "="*80)
    print("Testing Handler Boolean Conversion Flow")
    print("="*80 + "\n")

    # Simulate arguments coming from Claude Desktop
    raw_arguments = {
        "user_id": "kimghw",
        "start_date": "2025-10-28",
        "end_date": "2025-11-04",
        "max_mails": "10",
        "include_body": "yes",
        "download_attachments": "no",
        "save_emails": "false",
    }

    print("Step 1: Raw arguments from Claude Desktop")
    print(f"  include_body: {raw_arguments['include_body']} (type: {type(raw_arguments['include_body']).__name__})")
    print(f"  download_attachments: {raw_arguments['download_attachments']} (type: {type(raw_arguments['download_attachments']).__name__})")

    # Step 2: preprocess_arguments (line 340 in handlers.py)
    processed_arguments = preprocess_arguments(raw_arguments.copy())

    print("\nStep 2: After preprocess_arguments()")
    print(f"  include_body: {processed_arguments['include_body']} (type: {type(processed_arguments['include_body']).__name__})")
    print(f"  download_attachments: {processed_arguments['download_attachments']} (type: {type(processed_arguments['download_attachments']).__name__})")

    # OLD CODE (removed): This was the bug
    # for key in ["include_body", "download_attachments", "save_emails", "save_csv"]:
    #     if key in processed_arguments:
    #         processed_arguments[key] = processed_arguments[key] == "yes"

    # Validate
    print("\n" + "="*80)
    print("Validation:")
    print("="*80)

    if processed_arguments['include_body'] == True:
        print("✅ include_body='yes' correctly converted to True")
    else:
        print(f"❌ include_body='yes' incorrectly converted to {processed_arguments['include_body']}")

    if processed_arguments['download_attachments'] == False:
        print("✅ download_attachments='no' correctly converted to False")
    else:
        print(f"❌ download_attachments='no' incorrectly converted to {processed_arguments['download_attachments']}")

    if processed_arguments['save_emails'] == False:
        print("✅ save_emails='false' correctly converted to False")
    else:
        print(f"❌ save_emails='false' incorrectly converted to {processed_arguments['save_emails']}")

    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    test_handler_flow()
