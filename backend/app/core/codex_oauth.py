"""Codex/ChatGPT OAuth helpers extracted from main_simple.py."""

import base64
import hashlib
import json
import logging
import os
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse, parse_qsl, urlencode

import httpx
from sqlalchemy import text

from app.core.app_state import get_app_state
from app.core import config

from fastapi import Request

CODEX_JWT_CLAIM_PATH = "https://api.openai.com/auth"

logger = logging.getLogger(__name__)

def _decode_jwt_payload(token: str) -> Optional[Dict[str, Any]]:
    try:
        parts = (token or "").split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None


def _extract_codex_account_id_from_token(token: str) -> Optional[str]:
    payload = _decode_jwt_payload(token) or {}
    auth_claim = payload.get(CODEX_JWT_CLAIM_PATH) or {}
    account_id = auth_claim.get("chatgpt_account_id")
    if isinstance(account_id, str) and account_id:
        return account_id
    return None


def _extract_codex_email_from_token(token: str) -> Optional[str]:
    payload = _decode_jwt_payload(token) or {}
    email = payload.get("email")
    if isinstance(email, str) and email:
        return email
    return None


def _build_pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _append_query_params(url: str, params: Dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return parsed._replace(query=urlencode(query)).geturl()


def _resolve_frontend_return_url(request: Request, requested: Optional[str] = None) -> str:
    default_url = f"{config.settings.frontend_url.rstrip('/')}/settings"
    candidate = (requested or "").strip()
    if not candidate:
        return default_url
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return default_url
    allowed_hosts = {
        urlparse(default_url).netloc,
        request.headers.get("x-forwarded-host", ""),
        request.headers.get("host", ""),
    }
    if parsed.netloc not in {h for h in allowed_hosts if h}:
        return default_url
    return candidate


def _resolve_backend_public_url(request: Request) -> str:
    env_override = os.getenv("BACKEND_PUBLIC_URL", "").strip()
    if env_override:
        return env_override.rstrip("/")
    configured = (config.settings.backend_url or "").strip()
    if configured:
        return configured.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def _upsert_app_settings(settings_map: Dict[str, Any], updated_by: str = "system") -> None:
    if not settings_map:
        return
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        for key, value in settings_map.items():
            db.execute(text("""
                INSERT INTO app_settings (key, value, updated_at, updated_by)
                VALUES (:key, :value, CURRENT_TIMESTAMP, :updated_by)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at,
                    updated_by = EXCLUDED.updated_by
            """), {"key": key, "value": str(value), "updated_by": updated_by})
        db.commit()
    finally:
        db.close()


def _load_codex_oauth_from_db() -> None:
    """Hydrate in-memory Codex OAuth globals from app_settings if present."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT key, value
            FROM app_settings
            WHERE key IN (
                'codex_oauth_access_token',
                'codex_oauth_refresh_token',
                'codex_oauth_expires_at',
                'codex_oauth_account_id',
                'codex_oauth_email'
            )
        """)).fetchall()
        kv = {k: v for k, v in rows}
        get_app_state().codex_oauth_access_token = kv.get("codex_oauth_access_token", get_app_state().codex_oauth_access_token or "")
        get_app_state().codex_oauth_refresh_token = kv.get("codex_oauth_refresh_token", get_app_state().codex_oauth_refresh_token or "")
        get_app_state().codex_oauth_expires_at = kv.get("codex_oauth_expires_at", get_app_state().codex_oauth_expires_at or "")
        get_app_state().codex_oauth_account_id = kv.get("codex_oauth_account_id", get_app_state().codex_oauth_account_id or "")
        get_app_state().codex_oauth_email = kv.get("codex_oauth_email", get_app_state().codex_oauth_email or "")
    except Exception as e:
        logger.warning(f"Failed loading Codex OAuth state from database: {e}")
    finally:
        db.close()


def _apply_codex_oauth_token_data(token_data: Dict[str, Any], updated_by: str = "codex-oauth") -> None:
    """Persist Codex OAuth token data and switch active AI provider to Codex."""
    get_app_state().codex_oauth_access_token = token_data["access_token"]
    get_app_state().codex_oauth_refresh_token = token_data["refresh_token"]
    get_app_state().codex_oauth_expires_at = token_data["expires_at"]
    get_app_state().codex_oauth_account_id = token_data["account_id"]
    get_app_state().codex_oauth_email = token_data["email"]

    get_app_state().ai_provider = "codex"
    get_app_state().openai_base_url = get_app_state().codex_default_base_url
    get_app_state().openai_model = get_app_state().codex_default_model
    config.settings.ai_provider = get_app_state().ai_provider
    config.settings.openai_base_url = get_app_state().openai_base_url
    config.settings.openai_model = get_app_state().openai_model

    _upsert_app_settings(
        {
            "ai_provider": get_app_state().ai_provider,
            "openai_base_url": get_app_state().openai_base_url,
            "openai_model": get_app_state().openai_model,
            "codex_oauth_access_token": get_app_state().codex_oauth_access_token,
            "codex_oauth_refresh_token": get_app_state().codex_oauth_refresh_token,
            "codex_oauth_expires_at": get_app_state().codex_oauth_expires_at,
            "codex_oauth_account_id": get_app_state().codex_oauth_account_id,
            "codex_oauth_email": get_app_state().codex_oauth_email,
        },
        updated_by=updated_by,
    )


async def _codex_exchange_authorization_code(code: str, verifier: str, redirect_uri: str) -> Dict[str, Any]:
    form = {
        "grant_type": "authorization_code",
        "client_id": get_app_state().codex_oauth_client_id,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            get_app_state().codex_oauth_token_url,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        detail = resp.text[:500]
        raise HTTPException(status_code=400, detail=f"Codex OAuth token exchange failed: {detail}")
    payload = resp.json()
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not access_token or not refresh_token or not isinstance(expires_in, (int, float)):
        raise HTTPException(status_code=400, detail="Codex OAuth token response missing required fields")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    account_id = _extract_codex_account_id_from_token(access_token)
    if not account_id:
        raise HTTPException(status_code=400, detail="Codex OAuth token missing account claim")
    email = _extract_codex_email_from_token(access_token)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at.isoformat(),
        "account_id": account_id,
        "email": email or "",
    }


async def _codex_refresh_tokens(refresh_token: str) -> Dict[str, Any]:
    form = {
        "grant_type": "refresh_token",
        "client_id": get_app_state().codex_oauth_client_id,
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            get_app_state().codex_oauth_token_url,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Codex OAuth refresh failed: {resp.status_code} {resp.text[:250]}")
    payload = resp.json()
    access_token = payload.get("access_token")
    new_refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not access_token or not new_refresh or not isinstance(expires_in, (int, float)):
        raise RuntimeError("Codex OAuth refresh response missing required fields")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    account_id = _extract_codex_account_id_from_token(access_token)
    if not account_id:
        raise RuntimeError("Codex OAuth refresh token missing account claim")
    email = _extract_codex_email_from_token(access_token) or get_app_state().codex_oauth_email
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "expires_at": expires_at.isoformat(),
        "account_id": account_id,
        "email": email or "",
    }


async def _ensure_codex_access_token(updated_by: str = "system", min_valid_seconds: int = 60) -> Optional[str]:
    if not get_app_state().codex_oauth_access_token or not get_app_state().codex_oauth_refresh_token:
        _load_codex_oauth_from_db()
    if not get_app_state().codex_oauth_access_token or not get_app_state().codex_oauth_refresh_token:
        return None
    expires_at = _safe_parse_iso_datetime(get_app_state().codex_oauth_expires_at)
    now = datetime.now(timezone.utc)
    if expires_at and expires_at > now + timedelta(seconds=min_valid_seconds):
        return get_app_state().codex_oauth_access_token
    refreshed = await _codex_refresh_tokens(get_app_state().codex_oauth_refresh_token)
    get_app_state().codex_oauth_access_token = refreshed["access_token"]
    get_app_state().codex_oauth_refresh_token = refreshed["refresh_token"]
    get_app_state().codex_oauth_expires_at = refreshed["expires_at"]
    get_app_state().codex_oauth_account_id = refreshed["account_id"]
    get_app_state().codex_oauth_email = refreshed["email"]
    _upsert_app_settings(
        {
            "codex_oauth_access_token": get_app_state().codex_oauth_access_token,
            "codex_oauth_refresh_token": get_app_state().codex_oauth_refresh_token,
            "codex_oauth_expires_at": get_app_state().codex_oauth_expires_at,
            "codex_oauth_account_id": get_app_state().codex_oauth_account_id,
            "codex_oauth_email": get_app_state().codex_oauth_email,
        },
        updated_by=updated_by,
    )
    return get_app_state().codex_oauth_access_token

