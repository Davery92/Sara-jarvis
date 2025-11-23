#!/usr/bin/env python3
"""
Generate TypeScript types from tool definitions
Run this after modifying tool schemas
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.tools.registry import tool_registry
from app.tools.migrate_to_v2 import auto_migrate_all_tools
from app.tools.registry_v2 import registry_v2


def main():
    print("🔄 Migrating existing tools to V2 registry...")

    # Get all tools from existing registry
    all_tools = tool_registry.get_all_tools()
    print(f"Found {len(all_tools)} tools to migrate")

    # Migrate them
    auto_migrate_all_tools(all_tools)

    print(f"✅ Migrated {len(registry_v2.tools)} tools successfully")

    # Show categories
    print("\n📂 Tools by category:")
    for category in registry_v2.categories:
        tool_names = registry_v2.categories[category]
        if tool_names:
            print(f"  {category.value}: {len(tool_names)} tools")

    # Generate TypeScript types
    print("\n🔧 Generating TypeScript types...")

    ios_types_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../../ios-app/src/types/tools.generated.ts')
    )

    web_types_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../../frontend/src/types/tools.generated.ts')
    )

    # Generate for iOS
    try:
        registry_v2.generate_typescript_types(output_path=ios_types_path)
        print(f"✅ iOS types: {ios_types_path}")
    except Exception as e:
        print(f"⚠️  Failed to generate iOS types: {e}")

    # Generate for Web
    try:
        registry_v2.generate_typescript_types(output_path=web_types_path)
        print(f"✅ Web types: {web_types_path}")
    except Exception as e:
        print(f"⚠️  Failed to generate Web types: {e}")

    # Export JSON schema
    schema_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../app/tools/schemas.json')
    )

    try:
        registry_v2.export_schema_json(output_path=schema_path)
        print(f"✅ JSON schemas: {schema_path}")
    except Exception as e:
        print(f"⚠️  Failed to export JSON schemas: {e}")

    print("\n✨ Type generation complete!")
    print("\n📋 Summary:")
    print(f"  Total tools: {len(registry_v2.tools)}")
    print(f"  Categories: {len([c for c in registry_v2.categories if registry_v2.categories[c]])}")
    print(f"  TypeScript interfaces generated: {len(registry_v2.tools) * 2}")  # params + result


if __name__ == "__main__":
    main()
