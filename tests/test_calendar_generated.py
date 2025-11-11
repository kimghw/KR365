#!/usr/bin/env python3
"""
Test script for Calendar generated handlers
원본과 생성된 handlers가 동일한 기능을 제공하는지 검증
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def test_handlers():
    """Test both original and generated Calendar handlers"""

    print("=" * 60)
    print("Testing Calendar Handlers")
    print("=" * 60)

    # Test original handlers
    print("\n1. Testing ORIGINAL handlers...")
    from modules.calendar_mcp.handlers_original import CalendarHandlers as OriginalHandlers

    try:
        original = OriginalHandlers()
        original_tools = await original.handle_list_tools()
        print(f"✅ Original handlers loaded: {len(original_tools)} tools")

        for tool in original_tools:
            print(f"   - {tool.name}: {tool.description[:50]}...")

    except Exception as e:
        print(f"❌ Original handlers failed: {e}")
        return False

    # Test generated handlers
    print("\n2. Testing GENERATED handlers...")
    from modules.calendar_mcp.handlers_generated import CalendarHandlers as GeneratedHandlers

    try:
        generated = GeneratedHandlers()
        generated_tools = await generated.handle_list_tools()
        print(f"✅ Generated handlers loaded: {len(generated_tools)} tools")

        for tool in generated_tools:
            print(f"   - {tool.name}: {tool.description[:50]}...")

    except Exception as e:
        print(f"❌ Generated handlers failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Compare tools
    print("\n3. Comparing tools...")

    # Compare tool count
    if len(original_tools) != len(generated_tools):
        print(f"❌ Tool count mismatch: {len(original_tools)} vs {len(generated_tools)}")
        return False
    print(f"✅ Tool count matches: {len(original_tools)}")

    # Compare tool names
    original_names = {t.name for t in original_tools}
    generated_names = {t.name for t in generated_tools}

    if original_names != generated_names:
        print(f"❌ Tool names mismatch:")
        print(f"   Original: {original_names}")
        print(f"   Generated: {generated_names}")
        return False
    print(f"✅ Tool names match: {original_names}")

    # Compare tool descriptions
    for orig, gen in zip(sorted(original_tools, key=lambda x: x.name),
                        sorted(generated_tools, key=lambda x: x.name)):
        if orig.name == gen.name:
            if orig.description == gen.description:
                print(f"✅ {orig.name}: descriptions match")
            else:
                print(f"⚠️  {orig.name}: descriptions differ")
                print(f"     Original: {orig.description[:80]}...")
                print(f"     Generated: {gen.description[:80]}...")

    print("\n" + "=" * 60)
    print("✅ Calendar handler test completed!")
    print(f"   Original: {len(original_tools)} tools")
    print(f"   Generated: {len(generated_tools)} tools")
    print("=" * 60)

    return True


if __name__ == "__main__":
    success = asyncio.run(test_handlers())
    sys.exit(0 if success else 1)