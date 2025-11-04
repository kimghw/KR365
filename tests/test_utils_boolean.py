#!/usr/bin/env python3
"""Test boolean field handling in utils.preprocess_arguments"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.mail_query_MCP.mcp_server.utils import preprocess_arguments


def test_boolean_values():
    """Test various boolean value formats"""

    test_cases = [
        # True cases
        ({"include_body": "true"}, True, "lowercase true"),
        ({"include_body": "True"}, True, "capitalized True"),
        ({"include_body": "TRUE"}, True, "uppercase TRUE"),
        ({"include_body": "yes"}, True, "lowercase yes"),
        ({"include_body": "Yes"}, True, "capitalized Yes"),
        ({"include_body": "YES"}, True, "uppercase YES"),
        ({"include_body": "y"}, True, "lowercase y"),
        ({"include_body": "Y"}, True, "uppercase Y"),
        ({"include_body": "1"}, True, "string 1"),
        ({"include_body": True}, True, "boolean True"),

        # False cases
        ({"include_body": "false"}, False, "lowercase false"),
        ({"include_body": "False"}, False, "capitalized False"),
        ({"include_body": "FALSE"}, False, "uppercase FALSE"),
        ({"include_body": "no"}, False, "lowercase no"),
        ({"include_body": "No"}, False, "capitalized No"),
        ({"include_body": "NO"}, False, "uppercase NO"),
        ({"include_body": "n"}, False, "lowercase n"),
        ({"include_body": "N"}, False, "uppercase N"),
        ({"include_body": "0"}, False, "string 0"),
        ({"include_body": False}, False, "boolean False"),
        ({"include_body": ""}, False, "empty string"),
    ]

    print("\n" + "="*80)
    print("Boolean Field Conversion Test")
    print("="*80 + "\n")

    passed = 0
    failed = 0

    for input_args, expected, description in test_cases:
        result = preprocess_arguments(input_args.copy())
        actual = result.get("include_body")

        if actual == expected:
            print(f"✅ PASS: {description:30s} | Input: {str(input_args['include_body']):10s} | Output: {actual}")
            passed += 1
        else:
            print(f"❌ FAIL: {description:30s} | Input: {str(input_args['include_body']):10s} | Expected: {expected}, Got: {actual}")
            failed += 1

    print("\n" + "="*80)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*80 + "\n")

    # Test all boolean fields
    print("\n" + "="*80)
    print("Testing All Boolean Fields")
    print("="*80 + "\n")

    bool_fields = [
        "include_body",
        "download_attachments",
        "has_attachments_filter",
        "execute",
        "use_defaults",
        "save_emails",
        "save_csv",
    ]

    for field in bool_fields:
        test_input = {field: "yes"}
        result = preprocess_arguments(test_input)
        status = "✅" if result[field] == True else "❌"
        print(f"{status} {field:30s}: 'yes' -> {result[field]}")

    return failed == 0


if __name__ == "__main__":
    success = test_boolean_values()
    sys.exit(0 if success else 1)
