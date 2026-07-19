"""Core routes — root, health, tools, diagnostics."""

import logging
import os
from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.core.health_state import STARTUP_HEALTH

logger = logging.getLogger(__name__)

ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Sara")

router = APIRouter(tags=["Core"])


@router.get("/")
async def root():
    return {"message": f"Welcome to {ASSISTANT_NAME} Personal Hub API", "version": "1.0.0-simple"}


@router.get("/health")
async def health():
    from app.services.solo_mode_service import solo_mode_service

    critical_failures = STARTUP_HEALTH.get("critical_failures", [])
    if critical_failures:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    response = {
        "status": overall_status,
        "assistant": ASSISTANT_NAME,
        "services": {
            "database": STARTUP_HEALTH["database"]["status"],
            "embedding": STARTUP_HEALTH["embedding_service"]["status"],
            "llm": STARTUP_HEALTH["llm_service"]["status"],
            "neo4j": STARTUP_HEALTH["neo4j"]["status"]
        },
        "startup_time": STARTUP_HEALTH.get("startup_time"),
        "critical_failures": critical_failures
    }

    if solo_mode_service.is_solo_mode():
        response.update({
            "mode": "jarvis",
            "user": "owner",
            "solo_mode": True
        })
    else:
        response.update({
            "mode": "sara",
            "user": "multi-tenant",
            "solo_mode": False
        })

    return response


@router.get("/health/version")
async def health_version():
    """Deployed git SHA + build time (Phase 7 version truth). Compared against the
    daemon/fleet-reported versions by the interoception self-check to flag drift."""
    from app.core.version import get_version
    return get_version()


@router.get("/api/health/llm-status")
async def get_llm_status(current_user=Depends(get_current_user)):
    """Get LLM endpoint failover status for monitoring."""
    from app.core.llm import get_llm_client
    llm_failover_client = get_llm_client()
    return llm_failover_client.get_status()


@router.get("/tools")
async def list_tools():
    """List available AI tools (name and description)"""
    from app.tools.registry import tool_registry

    tools = []
    try:
        for t in tool_registry.get_all_tools():
            tools.append({
                "name": getattr(t, "name", "unknown"),
                "description": getattr(t, "description", "")
            })
    except Exception as e:
        logger.error(f"Failed to enumerate tools: {e}")
    return {"tools": tools}


@router.get("/search/health")
async def search_health():
    """Check connectivity to SearXNG and reranker endpoints"""
    from app.services.search_service import search_service

    searx_url = f"{search_service.searx_base}/search"
    status = {"searxng": {"base": search_service.searx_base, "ok": False, "error": None}}
    try:
        r = await search_service.http.get(searx_url, params={"q": "ping", "format": "json", "language": search_service.lang})
        status["searxng"]["ok"] = r.status_code == 200
        if r.status_code != 200:
            status["searxng"]["error"] = f"HTTP {r.status_code}"
    except Exception as e:
        status["searxng"]["error"] = str(e)

    status["reranker"] = {"base": search_service.reranker_base, "model": search_service.reranker_model}
    return status
