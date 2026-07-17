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
    "embedding": Capability(
        "embedding", "embedding_model", None,
        default_model="bge-m3",
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


def rename_model(old: str, new: str) -> Dict[str, object]:
    """Rewrite every app_settings row whose value is exactly `old` model name to
    `new`, in one operation. This is the "rename = one action" primitive: no
    hunting across bg_llm_primary/fallback, openai_model, openai_notification.

    Returns {updated_keys, count}. (The ACS daemon's own ACS_LLM_MODEL env on
    the VM is outside the DB and still needs its deploy — surfaced here so it's
    not silently missed.)"""
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

    logger.info(f"[llm_broker] renamed model {old!r} -> {new!r} across {len(updated)} keys: {updated}")
    return {
        "old": old, "new": new,
        "updated_keys": updated, "count": len(updated),
        "note": "ACS daemon ACS_LLM_MODEL env on the sara-VM is outside the DB — redeploy it if this model backs the daemon.",
    }
