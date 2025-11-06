"""Utility functions for MCP Server"""

import json
from typing import Any, Dict


def clean_backslashes(obj):
    """Clean backslashes from all string values recursively"""
    if isinstance(obj, str):
        return obj.replace("\\", "")
    elif isinstance(obj, dict):
        return {k: clean_backslashes(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_backslashes(item) for item in obj]
    return obj


def preprocess_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Preprocess arguments from Claude Desktop"""

    # Clean backslashes from all string values
    arguments = clean_backslashes(arguments)

    # Special handling for integer fields
    int_fields = ["days_back", "max_mails", "limit"]
    for field in int_fields:
        if field in arguments and isinstance(arguments[field], str):
            cleaned_value = arguments[field].strip().strip("'").strip('"')
            try:
                arguments[field] = int(cleaned_value)
            except ValueError:
                pass

    # Handle string-wrapped JSON
    if "extracted_period" in arguments and isinstance(
        arguments["extracted_period"], str
    ):
        try:
            arguments["extracted_period"] = json.loads(arguments["extracted_period"])
        except:
            pass

    if "extracted_keywords" in arguments and isinstance(
        arguments["extracted_keywords"], str
    ):
        try:
            arguments["extracted_keywords"] = json.loads(
                arguments["extracted_keywords"]
            )
        except:
            pass

    # Handle string "null" to actual null
    null_fields = ["extracted_organization", "category", "query_scope", "intent"]
    for key in null_fields:
        if key in arguments and arguments[key] == "null":
            arguments[key] = None

    # Handle boolean fields
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
        if field in arguments:
            if isinstance(arguments[field], str):
                lower_value = arguments[field].lower()
                arguments[field] = lower_value in ("true", "yes", "y", "1")

    # Set default query_context if not provided
    if "query_context" not in arguments:
        arguments["query_context"] = {"is_first_query": "yes", "conversation_turn": 1}

    return arguments
