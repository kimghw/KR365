#!/usr/bin/env python3
"""Test include_body parameter preprocessing"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.mail_query_MCP.mcp_server.utils import preprocess_arguments


def test_include_body_preprocessing():
    """Test include_body preprocessing in context of full argument set"""

    print("\n" + "="*80)
    print("Testing include_body Preprocessing in Email Query Context")
    print("="*80 + "\n")

    test_cases = [
        {
            "input": {
                "user_id": "kimghw",
                "start_date": "2025-10-28",
                "end_date": "2025-11-04",
                "max_mails": "10",
                "include_body": "yes",
                "download_attachments": "no",
                "save_emails": "false",
            },
            "expected_include_body": True,
            "description": "include_body='yes' with other params",
        },
        {
            "input": {
                "user_id": "kimghw",
                "include_body": "no",
                "max_mails": 5,
            },
            "expected_include_body": False,
            "description": "include_body='no' minimal params",
        },
        {
            "input": {
                "user_id": "kimghw",
                "include_body": "true",
            },
            "expected_include_body": True,
            "description": "include_body='true'",
        },
        {
            "input": {
                "user_id": "kimghw",
                "include_body": "false",
            },
            "expected_include_body": False,
            "description": "include_body='false'",
        },
        {
            "input": {
                "user_id": "kimghw",
                "include_body": "YES",
            },
            "expected_include_body": True,
            "description": "include_body='YES' (uppercase)",
        },
        {
            "input": {
                "user_id": "kimghw",
                "include_body": "No",
            },
            "expected_include_body": False,
            "description": "include_body='No' (capitalized)",
        },
    ]

    passed = 0
    failed = 0

    for test_case in test_cases:
        input_args = test_case["input"]
        expected = test_case["expected_include_body"]
        description = test_case["description"]

        result = preprocess_arguments(input_args.copy())
        actual = result.get("include_body")

        print(f"\n{'='*80}")
        print(f"Test: {description}")
        print(f"  Input: include_body='{input_args['include_body']}'")
        print(f"  Expected: {expected}")
        print(f"  Actual: {actual}")

        if actual == expected:
            print(f"  ✅ PASS")
            passed += 1
        else:
            print(f"  ❌ FAIL")
            failed += 1

        # Show other boolean conversions
        print(f"\n  Other boolean fields:")
        for key in ["download_attachments", "save_emails"]:
            if key in result:
                print(f"    {key}: {result[key]} (type: {type(result[key]).__name__})")

    print("\n" + "="*80)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*80 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = test_include_body_preprocessing()
    sys.exit(0 if success else 1)
