#!/usr/bin/env python3
"""
Bootstrap the Daily Brief stable layer for a user.
Run inside the backend container or locally with proper env vars.
"""
import asyncio
import sys
import os

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def main():
    from app.db.session import SessionLocal
    from app.services.daily_brief.brief_service import daily_brief_service

    # Get user ID from args or use default (David)
    user_id = sys.argv[1] if len(sys.argv) > 1 else "64f37c56-85cb-4590-8de9-adfc17d343ed"

    print(f"🚀 Bootstrapping Daily Brief for user {user_id[:8]}...")

    db = SessionLocal()
    try:
        success = await daily_brief_service.bootstrap_stable_layer(user_id, db)
        if success:
            print("✅ Successfully bootstrapped stable layer!")

            # Show what was created
            stable_path = daily_brief_service._get_layer_path(user_id, "stable")
            if stable_path.exists():
                content = stable_path.read_text()
                print(f"\n📝 Stable layer ({len(content)} chars):")
                print("-" * 60)
                print(content[:2000] + ("..." if len(content) > 2000 else ""))
        else:
            print("❌ Bootstrap failed - check logs")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
