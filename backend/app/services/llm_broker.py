"""
The model broker (ONE_MIND §3.7 — "one broker").

Today model choice is smeared across the organism: `app_settings` holds four+
model-selection axes (`openai_model`, `chat_default_model`,
`bg_llm_primary/fallback_model`, `openai_notification_model`, plus embedding and
an RPG model), and the same model name is duplicated across several rows — so
renaming one model means touching config, env, *and* multiple DB rows (see
gotcha_model_rename_app_settings). Callers hard-code which key they read.

The broker inverts that: callers declare a **capability class** (chat / kernel /
utility / notification / embedding / vision / rpg) and the broker owns the
model + endpoint + failover behind it. It reads the existing app_settings keys
(no schema change, no runtime-resolution change — additive and safe), so
callers can migrate onto `resolve(capability)` incrementally. And it provides
`rename_model(old, new)` that rewrites *every* app_settings row holding a model
name in one operation — making "a rename is one action" true instead of a
scavenger hunt.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Capability:
    name: str
    model_key: str            # app_settings key holding the model name
    url_key: Optional[str]    # app_settings key holding the endpoint (or None)
    fallback_model_key: Optional[str] = None
    fallback_url_key: Optional[str] = None
    default_model: str = ""
    default_url: str = ""


# The capability classes. This table is the single map from "what a caller
# needs" to "which knob holds it." Adding a capability = one row here.
CAPABILITIES: Dict[str, Capability] = {
    # David-facing conversation — the strong reasoning model.
    "chat": Capability(
        "chat", "chat_default_model", None,
        default_model="claude-sonnet-5",
    ),
    # Background cognition: deliberation / kernel ambient turns / consolidation.
    # Primary + fallback, both endpoint-bearing.
    "kernel": Capability(
        "kernel", "bg_llm_primary_model", "bg_llm_primary_url",
        fallback_model_key="bg_llm_fallback_model", fallback_url_key="bg_llm_fallback_url",
        default_model="qwen3.6-27b", default_url="http://100.104.68.115:8081/v1",
    ),
    # Cheap utility calls (~15 sites currently reading openai_model directly).
    "utility": Capability(
        "utility", "openai_model", "bg_llm_primary_url",
        default_model="qwen3.6-27b", default_url="http://100.104.68.115:8081/v1",
    ),
    # Notification phrasing / composer.
    "notification": Capability(
        "notification", "openai_notification_model", "bg_llm_primary_url",
        default_model="qwen3.6-27b", default_url="http://100.104.68.115:8081/v1",
    ),
    # Presence-latency follow-up, ruling 1 (2026-07-31): split embedding
    # traffic by who's waiting on it. "embedding" serves real chat turns —
    # the fast GPU host (~20-100ms) — and must never queue behind
    # background cognition's own embedding calls. "embedding_cognition" is
    # for exactly that background work (consolidation, PKG ingestion,
    # ambient-turn processing, lesson matching) — routed to the CPU
    # embedding container that already runs in the stack as an idle
    # fallback (1-3.5s is irrelevant when nothing interactive is waiting).
    # Same "presence and cognition never share a blocking resource" rule
    # the chat-model routing fix already enforces, applied one layer down.
    #
    # Ruling 1 20-turn measurement (2026-07-31) found the split alone
    # hadn't fixed anything: the app_settings row for embedding_base_url
    # still held "http://embeddings:8100" (the CPU container) from before
    # this split existed, silently overriding the GPU default below on
    # every resolve() — so "embedding" was quietly routing to the same
    # host as "embedding_cognition" the whole time. real turns showed
    # 2.5-3.4s embedding steps that measured 20-100ms in isolation against
    # the GPU host directly, which is what surfaced it. Fixed by updating
    # the DB row; leaving this note so a future stale override doesn't
    # cost someone another multi-hour trace to rediscover.
    "embedding": Capability(
        "embedding", "embedding_model", "embedding_base_url",
        default_model="bge-m3", default_url="http://10.185.1.8:8100",
    ),
    "embedding_cognition": Capability(
        "embedding_cognition", "embedding_model", "embedding_cognition_base_url",
        default_model="bge-m3", default_url="http://embeddings:8100",
    ),
    "rpg": Capability(
        "rpg", "temerant_rpg_model", None,
        default_model="gpt-5.3-codex",
    ),
}

# Every app_settings key that holds a *model name* — the set rename_model
# rewrites. Derived from CAPABILITIES so it can't drift.
_MODEL_NAME_KEYS = sorted({
    cap.model_key for cap in CAPABILITIES.values()
} | {
    cap.fallback_model_key for cap in CAPABILITIES.values() if cap.fallback_model_key
})


def _get_settings(keys: List[str]) -> Dict[str, str]:
    try:
        from sqlalchemy import text
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            rows = db.execute(
                text("SELECT key, value FROM app_settings WHERE key = ANY(:keys)"),
                {"keys": keys},
            ).fetchall()
            return {r[0]: r[1] for r in rows}
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"[llm_broker] settings read failed: {e}")
        return {}


def resolve(capability: str) -> Dict[str, Optional[str]]:
    """Resolve a capability class to its model + endpoint (+ failover).

    Returns {capability, model, base_url, fallback_model, fallback_url}. Falls
    back to the capability's compiled defaults if the app_settings row is
    missing, so a caller never gets None for the model."""
    cap = CAPABILITIES.get(capability)
    if not cap:
        raise ValueError(f"unknown capability: {capability!r} (known: {sorted(CAPABILITIES)})")

    wanted = [k for k in (cap.model_key, cap.url_key, cap.fallback_model_key, cap.fallback_url_key) if k]
    vals = _get_settings(wanted)

    return {
        "capability": cap.name,
        "model": vals.get(cap.model_key) or cap.default_model,
        "base_url": (vals.get(cap.url_key) if cap.url_key else None) or (cap.default_url or None),
        "fallback_model": vals.get(cap.fallback_model_key) if cap.fallback_model_key else None,
        "fallback_url": vals.get(cap.fallback_url_key) if cap.fallback_url_key else None,
    }


def all_capabilities() -> Dict[str, Dict[str, Optional[str]]]:
    """The full class→model map — the auditable view for the Dial / settings."""
    return {name: resolve(name) for name in CAPABILITIES}


async def get_broker_client(capability: str):
    """Arc 6.2 (work-order item 6): the client-factory layer `resolve()`
    was missing — until this, nothing outside the two admin settings
    endpoints ever actually called `resolve()`, so "migrate call sites
    to llm_broker capability classes" had no factory to migrate *onto*.
    Returns a plain `openai.AsyncOpenAI` client pointed at the
    capability's resolved model/endpoint, for callers that build their
    own request payloads and just need model+base_url (the shape most
    of the ~15 raw `openai_model` call sites already use).

    Deliberately NOT wired into `app/core/llm.py`'s two existing hubs
    (`get_background_llm_client()`/`llm_client`) this pass — those are
    the most widely-used, business-critical LLM clients in the whole
    system (compose/judge/curiosity/sara_journal/verification_loop all
    route through them), and `BackgroundLLMClient` already has its own
    DB-persisted-override mechanism for `bg_llm_*` settings
    (`_load_persisted_ai_setting_overrides()`) that substantially
    achieves "rename = one row" for that axis already, just via older,
    parallel code rather than this broker. Rewiring that internal
    resolution path is real, valuable follow-up work — not something
    to do as a drive-by inside an unrelated client-factory addition."""
    cap = resolve(capability)
    from openai import AsyncOpenAI
    from app.core.config import settings
    return AsyncOpenAI(
        base_url=cap["base_url"],
        api_key=getattr(settings, "openai_api_key", "") or "not-needed",
    ), cap["model"]


# app_settings key -> the main_simple.py module-level global it seeded at
# import time. Item 2.5 dry-run (2026-07-31): rename_model() only ever
# wrote the DB — proven by a real dry-run (renamed openai_model, immediately
# reverted) that GET /settings/ai, backed by main_simple.py's OPENAI_MODEL
# global, kept showing the OLD name with no restart, while llm_broker.
# resolve() (a fresh DB read every call) correctly showed the new one
# instantly. "Rename = one action" was only true for broker-based callers.
# Rather than migrate the ~15 main_simple.py call sites still reading these
# globals directly onto resolve() (a much larger, riskier change touching
# the app's hottest file again), rename_model() now also pokes the already-
# running process's cached copies directly — the same thing the /settings/
# ai PATCH endpoint's `global ...; OPENAI_MODEL = ...` lines do, just
# triggered from here too.
_GLOBAL_NAME_BY_SETTINGS_KEY: Dict[str, str] = {
    "openai_model": "OPENAI_MODEL",
    "chat_default_model": "CHAT_DEFAULT_MODEL",
    "openai_notification_model": "OPENAI_NOTIFICATION_MODEL",
    "bg_llm_primary_model": "BG_LLM_PRIMARY_MODEL",
    "bg_llm_fallback_model": "BG_LLM_FALLBACK_MODEL",
    "embedding_model": "EMBEDDING_MODEL",
}


def _refresh_main_simple_globals(updated_keys: List[str], new_value: str) -> List[str]:
    """Best-effort: push the new model name into the already-running
    process's main_simple.py globals for every key that has one. Returns
    the global names actually updated (for the caller's proof-of-work).
    Import is local and defensive — llm_broker must stay usable from
    contexts where main_simple hasn't been imported (tests, scripts)."""
    refreshed: List[str] = []
    try:
        import sys
        main_simple = sys.modules.get("app.main_simple")
        if main_simple is None:
            return refreshed
        for key in updated_keys:
            global_name = _GLOBAL_NAME_BY_SETTINGS_KEY.get(key)
            if global_name and hasattr(main_simple, global_name):
                setattr(main_simple, global_name, new_value)
                refreshed.append(global_name)
    except Exception as e:
        logger.debug(f"[llm_broker] main_simple global refresh skipped: {e}")
    return refreshed


def rename_model(old: str, new: str) -> Dict[str, object]:
    """Rewrite every app_settings row whose value is exactly `old` model name to
    `new`, in one operation. This is the "rename = one action" primitive: no
    hunting across bg_llm_primary/fallback, openai_model, openai_notification —
    and, since the 2026-07-31 dry-run found the gap, no restart needed either
    for the still-legacy main_simple.py call sites (see
    _refresh_main_simple_globals above).

    Returns {updated_keys, refreshed_globals, count}. (The ACS daemon's own
    ACS_LLM_MODEL env on the VM is outside the DB and still needs its
    deploy — surfaced here so it's not silently missed.)"""
    updated: List[str] = []
    try:
        from sqlalchemy import text
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            rows = db.execute(
                text("SELECT key, value FROM app_settings WHERE key = ANY(:keys) AND value = :old"),
                {"keys": _MODEL_NAME_KEYS, "old": old},
            ).fetchall()
            for key, _ in rows:
                db.execute(
                    text("UPDATE app_settings SET value = :new WHERE key = :key"),
                    {"new": new, "key": key},
                )
                updated.append(key)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[llm_broker] rename_model failed: {e}")
        return {"error": str(e), "updated_keys": updated, "count": len(updated)}

    refreshed_globals = _refresh_main_simple_globals(updated, new)

    logger.info(
        f"[llm_broker] renamed model {old!r} -> {new!r} across {len(updated)} keys: {updated} "
        f"(live-refreshed globals: {refreshed_globals})"
    )
    return {
        "old": old, "new": new,
        "updated_keys": updated, "count": len(updated),
        "refreshed_globals": refreshed_globals,
        "note": "ACS daemon ACS_LLM_MODEL env on the sara-VM is outside the DB — redeploy it if this model backs the daemon.",
    }
