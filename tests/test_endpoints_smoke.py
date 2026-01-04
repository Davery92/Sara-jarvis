"""
Smoke tests for critical API endpoints.
Run after each refactor batch to ensure nothing is broken.
"""
import httpx
import asyncio
import sys

BASE_URL = "http://localhost:8000"

async def test_health():
    """Test health endpoint"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health")
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        print("✅ /health OK")
        return True

async def test_root():
    """Test root endpoint"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/")
        assert response.status_code == 200, f"Root failed: {response.status_code}"
        print("✅ / OK")
        return True

async def test_auth_me_unauthorized():
    """Test that /auth/me returns 401 without auth"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/auth/me")
        # Should be 401 or 403 without auth
        assert response.status_code in [401, 403], f"Auth check failed: {response.status_code}"
        print("✅ /auth/me (unauthorized) OK")
        return True

async def test_shadow_active():
    """Test shadow/active endpoint (appears to be polled frequently)"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/shadow/active")
        assert response.status_code == 200, f"Shadow active failed: {response.status_code}"
        print("✅ /shadow/active OK")
        return True

async def run_all_tests():
    """Run all smoke tests"""
    print("\n" + "="*50)
    print("SMOKE TEST SUITE")
    print("="*50 + "\n")

    tests = [
        test_health,
        test_root,
        test_auth_me_unauthorized,
        test_shadow_active,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            failed += 1

    print("\n" + "="*50)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*50 + "\n")

    return failed == 0

if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
