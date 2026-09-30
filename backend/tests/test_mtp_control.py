"""MTP request controls and capability negotiation (chat harness repair
Phase 7). The server loads the MTP-capable model/profile but every request
path omitted generation_mode/depth, so chat silently ran AR the whole time.
"""
import pytest

from app.services.mtp_control import (
    MTPCapability,
    check_mtp_capability,
    check_response_generation_mode,
    generation_request_fields,
    is_requested_depth_supported,
    log_mtp_capability_at_startup,
    record_mtp_fallback,
)


class TestGenerationRequestFields:
    def test_ar_mode_sends_zero_depth(self):
        fields = generation_request_fields("ar", 3)
        assert fields == {"generation_mode": "ar", "depth": 0}

    def test_mtp_mode_sends_requested_depth(self):
        fields = generation_request_fields("mtp", 3)
        assert fields == {"generation_mode": "mtp", "depth": 3}

    def test_unknown_mode_falls_back_to_ar(self):
        fields = generation_request_fields("turbo", 3)
        assert fields["generation_mode"] == "ar"
        assert fields["depth"] == 0

    def test_fields_are_always_present_never_relying_on_server_default(self):
        fields = generation_request_fields("ar", 3)
        assert "generation_mode" in fields
        assert "depth" in fields


class TestDepthSupport:
    def test_unreachable_server_is_never_supported(self):
        cap = MTPCapability(reachable=False)
        assert is_requested_depth_supported(cap, 3) is False

    def test_no_native_draft_head_is_not_supported(self):
        cap = MTPCapability(reachable=True, supports_native_draft_head=False)
        assert is_requested_depth_supported(cap, 3) is False

    def test_depth_within_range_is_supported(self):
        cap = MTPCapability(reachable=True, supports_native_draft_head=True, depth_min=1, depth_max=3)
        assert is_requested_depth_supported(cap, 3) is True

    def test_depth_outside_range_is_not_supported(self):
        cap = MTPCapability(reachable=True, supports_native_draft_head=True, depth_min=1, depth_max=3)
        assert is_requested_depth_supported(cap, 5) is False


class TestCheckMtpCapability:
    @pytest.mark.asyncio
    async def test_parses_the_actual_health_response_shape(self, monkeypatch):
        """Matches the real /health payload observed on the chat lane on
        2026-09-16: native_draft_head + exact_speculative_sampling loaded,
        draft depth range 1-3 default 3, but default_generation_mode="ar"."""
        health_payload = {
            "ok": True,
            "model": "qwen3.8-27b",
            "generation_mode": "ar",
            "default_generation_mode": "ar",
            "startup": {
                "backend": {
                    "runtime_capabilities": [
                        "target_logits", "native_draft_head", "exact_speculative_sampling",
                    ],
                    "draft_semantics": {
                        "supported": True, "request_field": "depth",
                        "default": 3, "minimum": 1, "maximum": 3,
                    },
                }
            },
        }

        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return health_payload

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                assert url == "http://example.local:8082/health"
                return _FakeResponse()

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

        cap = await check_mtp_capability("http://example.local:8082/v1")

        assert cap.reachable is True
        assert cap.supports_native_draft_head is True
        assert cap.depth_min == 1
        assert cap.depth_max == 3
        assert cap.server_default_mode == "ar"

    @pytest.mark.asyncio
    async def test_unreachable_server_does_not_raise(self, monkeypatch):
        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                raise ConnectionError("no route to host")

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

        cap = await check_mtp_capability("http://example.local:8082/v1")
        assert cap.reachable is False
        assert cap.supports_native_draft_head is False


class TestStartupLogging:
    @pytest.mark.asyncio
    async def test_never_raises_regardless_of_capability(self, monkeypatch):
        async def _fake_check(base_url, timeout=5.0):
            return MTPCapability(reachable=False)

        monkeypatch.setattr("app.services.mtp_control.check_mtp_capability", _fake_check)
        cap = await log_mtp_capability_at_startup("http://example.local:8082/v1", "mtp", 3)
        assert cap.reachable is False


class TestCheckResponseGenerationMode:
    def test_ar_requested_ar_delivered_is_not_a_fallback(self):
        assert check_response_generation_mode(
            requested_mode="ar", requested_depth=0, mtplx_stats={"generation_mode": "ar"},
        ) is None

    def test_mtp_requested_and_delivered_with_verify_calls_is_not_a_fallback(self):
        stats = {"generation_mode": "mtp", "mtp_depth": 3, "verify_calls": 4}
        assert check_response_generation_mode(requested_mode="mtp", requested_depth=3, mtplx_stats=stats) is None

    def test_server_silently_ran_ar_instead_of_mtp(self):
        stats = {"generation_mode": "ar", "mtp_depth": 0, "verify_calls": 0}
        result = check_response_generation_mode(requested_mode="mtp", requested_depth=3, mtplx_stats=stats)
        assert result is not None
        assert "ar" in result["failure_category"]

    def test_mtp_requested_but_zero_verify_calls(self):
        stats = {"generation_mode": "mtp", "mtp_depth": 3, "verify_calls": 0}
        result = check_response_generation_mode(requested_mode="mtp", requested_depth=3, mtplx_stats=stats)
        assert result is not None
        assert "zero_verify_calls" in result["failure_category"]

    def test_depth_mismatch_is_flagged(self):
        stats = {"generation_mode": "mtp", "mtp_depth": 1, "verify_calls": 2}
        result = check_response_generation_mode(requested_mode="mtp", requested_depth=3, mtplx_stats=stats)
        assert result is not None
        assert "depth_mismatch" in result["failure_category"]


class TestRecordMtpFallback:
    def test_never_raises(self):
        record_mtp_fallback(
            model="qwen3.8-27b", endpoint="http://example.local:8082/v1",
            requested_mode="mtp", requested_depth=3,
            failure_category="runtime_error", ar_recovery_ok=True,
        )
