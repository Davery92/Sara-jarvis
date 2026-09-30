"""MTP (multi-token prediction) request controls and capability negotiation.

Chat harness repair Phase 7. The MTPLX server on the local chat lane
supports native draft-head speculative decoding (`generation_mode=mtp`,
`depth` 1-3) but every request path omitted the fields, so chat ran AR the
whole time despite the server having loaded the MTP-capable model and
"turbo" profile — `generation_mode=ar`, effective depth 0, no verify calls,
even though `/health` reports `native_draft_head` and
`exact_speculative_sampling` as loaded runtime capabilities.

The default here stays "ar", NOT "mtp": gotcha_mtplx_mtp_derails_qwen38_27b.md
documents that MTP speculative decoding corrupts tool-bearing replies on
this exact model/pack (Qwen3.8-27B on the M3 Ultra) — `--generation-mode ar`
is what's clean, and the server's own `/health` currently reports
`default_generation_mode: "ar"` too. This module makes MTP a request-time
switch (`LOCAL_GENERATION_MODE=mtp`) for once the parity/regression suite in
Phase 7 §"MTP correctness validation" has re-verified the current build —
not something this repair flips on by itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def generation_request_fields(mode: str, depth: int) -> Dict[str, Any]:
    """Top-level request fields for a local-lane chat completion.

    Always explicit, per the plan: "Do not rely exclusively on the server
    default." `depth` is only meaningful (and only sent nonzero) in mtp mode.
    """
    mode = (mode or "ar").strip().lower()
    if mode not in ("ar", "mtp"):
        mode = "ar"
    return {
        "generation_mode": mode,
        "depth": depth if mode == "mtp" else 0,
    }


@dataclass
class MTPCapability:
    reachable: bool
    supports_native_draft_head: bool = False
    depth_min: Optional[int] = None
    depth_max: Optional[int] = None
    server_default_mode: Optional[str] = None
    raw: Optional[dict] = None


async def check_mtp_capability(base_url: str, timeout: float = 5.0) -> MTPCapability:
    """GET {base_url}/health and read the backend's advertised MTP support.

    Never raises — an unreachable server is reported as unreachable, not a
    startup-fatal error (Phase 7 §"Capability negotiation").
    """
    import httpx

    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[: -len("/v1")]
    url = f"{url}/health"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"[mtp] capability check failed ({base_url}): {e}")
        return MTPCapability(reachable=False)

    backend = ((data.get("startup") or {}).get("backend")) or {}
    caps = set(backend.get("runtime_capabilities") or [])
    draft = backend.get("draft_semantics") or {}
    return MTPCapability(
        reachable=True,
        supports_native_draft_head="native_draft_head" in caps,
        depth_min=draft.get("minimum"),
        depth_max=draft.get("maximum"),
        server_default_mode=data.get("default_generation_mode"),
        raw=data,
    )


def is_requested_depth_supported(cap: MTPCapability, requested_depth: int) -> bool:
    if not cap.reachable or not cap.supports_native_draft_head:
        return False
    if cap.depth_min is not None and requested_depth < cap.depth_min:
        return False
    if cap.depth_max is not None and requested_depth > cap.depth_max:
        return False
    return True


async def log_mtp_capability_at_startup(base_url: str, requested_mode: str, requested_depth: int) -> MTPCapability:
    """Startup diagnostic: record requested vs. available generation mode so
    a misconfigured LOCAL_GENERATION_MODE=mtp against an unsupporting/
    unreachable server is visible immediately, not discovered from a user
    report (Phase 7 §"Capability negotiation" steps 1-4)."""
    cap = await check_mtp_capability(base_url)
    if requested_mode == "mtp":
        if not cap.reachable:
            logger.warning(f"[mtp] local lane degraded: server unreachable for capability check ({base_url})")
        elif not is_requested_depth_supported(cap, requested_depth):
            logger.warning(
                f"[mtp] local lane degraded: requested depth {requested_depth} not supported "
                f"(native_draft_head={cap.supports_native_draft_head}, "
                f"range={cap.depth_min}-{cap.depth_max}) — requests will still ask for mtp "
                f"and the server may fall back to ar per-request"
            )
        else:
            logger.info(f"[mtp] capability confirmed: depth {requested_depth} supported ({cap.depth_min}-{cap.depth_max})")
    else:
        logger.info(
            f"[mtp] local lane running generation_mode={requested_mode} "
            f"(server advertises native_draft_head={cap.supports_native_draft_head}, "
            f"default={cap.server_default_mode})"
        )
    return cap


def check_response_generation_mode(
    *, requested_mode: str, requested_depth: int, mtplx_stats: Dict[str, Any],
) -> Optional[Dict[str, str]]:
    """Compare what a local-lane request asked for against the server's own
    `mtplx_stats` on the response. Returns a fallback-reason dict when they
    disagree, or None when the request got what it asked for.

    Phase 7 requires every fallback be visible rather than silently omitted;
    this is the check that decides whether one happened. Two shapes count:
    the server reporting a different generation_mode than requested (an
    explicit rejection), or mtp being requested but verify_calls staying at
    zero (asked for speculative decoding, got none — a silent no-op).
    """
    if requested_mode != "mtp":
        return None  # ar requested ar delivered is not a fallback by definition

    actual_mode = mtplx_stats.get("generation_mode")
    if actual_mode != "mtp":
        return {"failure_category": f"server_ran_{actual_mode or 'unknown'}_instead_of_mtp"}

    if not mtplx_stats.get("verify_calls"):
        return {"failure_category": "mtp_requested_zero_verify_calls"}

    actual_depth = mtplx_stats.get("mtp_depth")
    if actual_depth != requested_depth:
        return {"failure_category": f"depth_mismatch_requested_{requested_depth}_got_{actual_depth}"}

    return None


def record_mtp_fallback(
    *, model: str, endpoint: str, requested_mode: str, requested_depth: int,
    failure_category: str, ar_recovery_ok: bool,
) -> None:
    """Structured, greppable system event for an MTP->AR fallback. Every
    fallback must be visible — never a silent downgrade (Phase 7 requirement:
    "Every fallback must emit a structured system event... Never silently
    omit the MTP fields.")."""
    logger.warning(
        "mtp_fallback: model=%s endpoint=%s requested_mode=%s requested_depth=%s "
        "failure_category=%s ar_recovery_ok=%s",
        model, endpoint, requested_mode, requested_depth, failure_category, ar_recovery_ok,
    )
