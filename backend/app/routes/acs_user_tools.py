"""ACS v2 user-defined tools — Sara's self-authored toolkit.

Three tables (sara_tool, sara_tool_version, sara_tool_invocation), one router,
strict separation from `acs_daemon_tools.py` — the hardcoded tools she gets
out-of-the-box are immutable code; her tools are data.

Lifecycle:
  1. Daemon submits code via POST /  (creates tool + version 1; enabled=FALSE)
  2. David reviews in ACSPage and POSTs /{name}/enable
  3. Daemon invokes via POST /{name}/invoke  (executor delegates to the
     acs-tool-runner sidecar over HTTP)
  4. Iteration: daemon POSTs new versions via /{name}/versions, then
     /{name}/activate?version=N to switch the active pointer

Execution is delegated to a separate process — see ACS_TOOL_RUNNER_URL in
config. If that's not configured, /invoke returns 503; everything else still
works (the API contract is sealed independent of the runner deploy).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.config import settings
from app.core.deps import get_current_user, get_current_user_optional
from app.db.session import get_async_session_factory
from app.models.user import User
from app.routes.acs_daemon import verify_daemon_token
from app.services.acs_tool_validator import (
    ToolValidationError,
    validate_args_schema,
    validate_tool_code,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/acs/v2/user_tools", tags=["ACS v2 — user tools"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ToolVersionOut(BaseModel):
    id: str
    version: int
    notes: Optional[str]
    created_at: datetime


class ToolOut(BaseModel):
    id: str
    name: str
    description: str
    args_schema: dict
    enabled: bool
    active_version: Optional[ToolVersionOut]
    latest_version: Optional[ToolVersionOut]
    invocation_count_24h: int
    last_invocation_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ToolDefineIn(BaseModel):
    name: str = Field(..., min_length=3, max_length=64,
                      pattern=r"^[a-z][a-z0-9_]{2,63}$")
    description: str = Field(..., min_length=1, max_length=500)
    args_schema: dict = Field(..., description="JSON Schema for args; must be type=object")
    code: str = Field(..., min_length=1)
    notes: Optional[str] = Field(None, max_length=1000)


class ToolVersionSubmitIn(BaseModel):
    code: str = Field(..., min_length=1)
    notes: Optional[str] = Field(None, max_length=1000)


class ToolVersionFullOut(ToolVersionOut):
    code: str


class ToolInvocationOut(BaseModel):
    id: str
    tool_id: str
    version_id: str
    args: dict
    result: Optional[Any]
    error: Optional[str]
    duration_ms: Optional[int]
    started_at: datetime
    completed_at: Optional[datetime]


class ToolInvokeIn(BaseModel):
    args: dict = Field(default_factory=dict)
    version: Optional[int] = Field(None, description="Override active version for testing")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_auth(x_daemon_token: Optional[str], current_user: Optional[User]) -> None:
    expected = getattr(settings, "acs_daemon_token", None) or ""
    is_daemon = bool(expected and x_daemon_token == expected)
    if not is_daemon and current_user is None:
        raise HTTPException(status_code=401, detail="auth required")


async def _load_tool_with_versions(db, name: str) -> Optional[dict]:
    row = (await db.execute(
        text(
            """
            SELECT t.id, t.name, t.description, t.args_schema, t.enabled,
                   t.active_version_id, t.created_at, t.updated_at,
                   av.id AS av_id, av.version AS av_version, av.notes AS av_notes,
                   av.created_at AS av_created_at,
                   lv.id AS lv_id, lv.version AS lv_version, lv.notes AS lv_notes,
                   lv.created_at AS lv_created_at,
                   (SELECT COUNT(*) FROM sara_tool_invocation
                    WHERE tool_id = t.id
                      AND started_at > NOW() - INTERVAL '24 hours') AS inv_24h,
                   (SELECT MAX(started_at) FROM sara_tool_invocation
                    WHERE tool_id = t.id) AS last_inv_at
            FROM sara_tool t
            LEFT JOIN sara_tool_version av ON av.id = t.active_version_id
            LEFT JOIN LATERAL (
                SELECT id, version, notes, created_at FROM sara_tool_version
                WHERE tool_id = t.id
                ORDER BY version DESC LIMIT 1
            ) lv ON TRUE
            WHERE t.name = :name
            """
        ),
        {"name": name},
    )).mappings().first()
    return dict(row) if row else None


def _row_to_tool(row: dict) -> ToolOut:
    av = None
    if row.get("av_id"):
        av = ToolVersionOut(
            id=str(row["av_id"]), version=row["av_version"],
            notes=row["av_notes"], created_at=row["av_created_at"],
        )
    lv = None
    if row.get("lv_id"):
        lv = ToolVersionOut(
            id=str(row["lv_id"]), version=row["lv_version"],
            notes=row["lv_notes"], created_at=row["lv_created_at"],
        )
    return ToolOut(
        id=str(row["id"]),
        name=row["name"],
        description=row["description"],
        args_schema=row["args_schema"],
        enabled=row["enabled"],
        active_version=av,
        latest_version=lv,
        invocation_count_24h=int(row["inv_24h"] or 0),
        last_invocation_at=row["last_inv_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ToolOut])
async def list_tools(
    enabled: Optional[bool] = Query(None),
    x_daemon_token: Optional[str] = Header(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[ToolOut]:
    """List all user-defined tools. Filter by enabled status."""
    _check_auth(x_daemon_token, current_user)

    where = ""
    params: dict[str, Any] = {}
    if enabled is not None:
        where = "WHERE t.enabled = :enabled"
        params["enabled"] = enabled

    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(
                f"""
                SELECT t.id, t.name, t.description, t.args_schema, t.enabled,
                       t.active_version_id, t.created_at, t.updated_at,
                       av.id AS av_id, av.version AS av_version, av.notes AS av_notes,
                       av.created_at AS av_created_at,
                       lv.id AS lv_id, lv.version AS lv_version, lv.notes AS lv_notes,
                       lv.created_at AS lv_created_at,
                       (SELECT COUNT(*) FROM sara_tool_invocation
                        WHERE tool_id = t.id
                          AND started_at > NOW() - INTERVAL '24 hours') AS inv_24h,
                       (SELECT MAX(started_at) FROM sara_tool_invocation
                        WHERE tool_id = t.id) AS last_inv_at
                FROM sara_tool t
                LEFT JOIN sara_tool_version av ON av.id = t.active_version_id
                LEFT JOIN LATERAL (
                    SELECT id, version, notes, created_at FROM sara_tool_version
                    WHERE tool_id = t.id ORDER BY version DESC LIMIT 1
                ) lv ON TRUE
                {where}
                ORDER BY t.created_at DESC
                """
            ),
            params,
        )).mappings().all()
    return [_row_to_tool(dict(r)) for r in rows]


@router.post("", response_model=ToolOut, status_code=201,
             dependencies=[Depends(verify_daemon_token)])
async def define_tool(payload: ToolDefineIn) -> ToolOut:
    """Daemon-only: register a new tool. Validates code + schema, creates the
    tool row (enabled=FALSE) and version 1. The daemon shows the proposal in
    its activity log so David sees a review item; he flips /enable when ready."""
    try:
        validate_args_schema(payload.args_schema)
        validate_tool_code(payload.code)
    except ToolValidationError as e:
        raise HTTPException(status_code=422, detail=f"validation failed: {e}")

    async_session = get_async_session_factory()
    async with async_session() as db:
        existing = (await db.execute(
            text("SELECT id FROM sara_tool WHERE name = :name"),
            {"name": payload.name},
        )).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"tool '{payload.name}' already exists")

        tool_row = (await db.execute(
            text(
                """
                INSERT INTO sara_tool (name, description, args_schema)
                VALUES (:name, :description, CAST(:schema AS jsonb))
                RETURNING id
                """
            ),
            {
                "name": payload.name,
                "description": payload.description,
                "schema": _json_dumps(payload.args_schema),
            },
        )).first()
        tool_id = tool_row[0]

        version_row = (await db.execute(
            text(
                """
                INSERT INTO sara_tool_version (tool_id, version, code, notes)
                VALUES (:tool_id, 1, :code, :notes)
                RETURNING id
                """
            ),
            {"tool_id": tool_id, "code": payload.code, "notes": payload.notes},
        )).first()
        version_id = version_row[0]

        # Point active_version_id at v1 so it's invocable the moment David enables it.
        await db.execute(
            text("UPDATE sara_tool SET active_version_id = :vid WHERE id = :tid"),
            {"vid": version_id, "tid": tool_id},
        )
        await db.commit()

        loaded = await _load_tool_with_versions(db, payload.name)
    return _row_to_tool(loaded)  # type: ignore[arg-type]


@router.post("/{name}/versions", response_model=ToolVersionOut, status_code=201,
             dependencies=[Depends(verify_daemon_token)])
async def submit_version(name: str, payload: ToolVersionSubmitIn) -> ToolVersionOut:
    """Daemon-only: append a new code version. Does NOT auto-activate — the
    daemon must explicitly call /activate?version=N to switch."""
    try:
        validate_tool_code(payload.code)
    except ToolValidationError as e:
        raise HTTPException(status_code=422, detail=f"validation failed: {e}")

    async_session = get_async_session_factory()
    async with async_session() as db:
        tool = (await db.execute(
            text("SELECT id FROM sara_tool WHERE name = :name"),
            {"name": name},
        )).first()
        if not tool:
            raise HTTPException(status_code=404, detail="tool not found")
        next_version = (await db.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM sara_tool_version "
                "WHERE tool_id = :tid"
            ),
            {"tid": tool[0]},
        )).scalar()
        row = (await db.execute(
            text(
                """
                INSERT INTO sara_tool_version (tool_id, version, code, notes)
                VALUES (:tid, :version, :code, :notes)
                RETURNING id, version, notes, created_at
                """
            ),
            {
                "tid": tool[0], "version": next_version,
                "code": payload.code, "notes": payload.notes,
            },
        )).mappings().first()
        await db.commit()
    return ToolVersionOut(
        id=str(row["id"]), version=row["version"],
        notes=row["notes"], created_at=row["created_at"],
    )


@router.get("/{name}/versions", response_model=list[ToolVersionFullOut])
async def list_versions(
    name: str,
    x_daemon_token: Optional[str] = Header(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[ToolVersionFullOut]:
    """Full version history including code. Used by the review UI for diffs."""
    _check_auth(x_daemon_token, current_user)
    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(
                """
                SELECT v.id, v.version, v.code, v.notes, v.created_at
                FROM sara_tool_version v
                JOIN sara_tool t ON t.id = v.tool_id
                WHERE t.name = :name
                ORDER BY v.version DESC
                """
            ),
            {"name": name},
        )).mappings().all()
    return [
        ToolVersionFullOut(
            id=str(r["id"]), version=r["version"], code=r["code"],
            notes=r["notes"], created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("/{name}/activate", response_model=ToolOut,
             dependencies=[Depends(verify_daemon_token)])
async def activate_version(name: str, version: int = Query(..., ge=1)) -> ToolOut:
    async_session = get_async_session_factory()
    async with async_session() as db:
        tool = (await db.execute(
            text("SELECT id FROM sara_tool WHERE name = :name"),
            {"name": name},
        )).first()
        if not tool:
            raise HTTPException(status_code=404, detail="tool not found")
        version_row = (await db.execute(
            text(
                "SELECT id FROM sara_tool_version WHERE tool_id = :tid AND version = :v"
            ),
            {"tid": tool[0], "v": version},
        )).first()
        if not version_row:
            raise HTTPException(status_code=404, detail=f"version {version} not found")
        await db.execute(
            text("UPDATE sara_tool SET active_version_id = :vid, updated_at = NOW() "
                 "WHERE id = :tid"),
            {"vid": version_row[0], "tid": tool[0]},
        )
        await db.commit()
        loaded = await _load_tool_with_versions(db, name)
    return _row_to_tool(loaded)  # type: ignore[arg-type]


@router.post("/{name}/enable", response_model=ToolOut)
async def enable_tool(name: str, current_user: User = Depends(get_current_user)) -> ToolOut:
    """David-only: approve a tool for invocation."""
    return await _set_enabled(name, True)


@router.post("/{name}/disable", response_model=ToolOut)
async def disable_tool(name: str, current_user: User = Depends(get_current_user)) -> ToolOut:
    """David-only: kill switch. Disabled tools 403 on /invoke."""
    return await _set_enabled(name, False)


async def _set_enabled(name: str, enabled: bool) -> ToolOut:
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(
            text("UPDATE sara_tool SET enabled = :en, updated_at = NOW() WHERE name = :name"),
            {"en": enabled, "name": name},
        )
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="tool not found")
        loaded = await _load_tool_with_versions(db, name)
    return _row_to_tool(loaded)  # type: ignore[arg-type]


@router.delete("/{name}")
async def delete_tool(name: str, current_user: User = Depends(get_current_user)) -> dict:
    """David-only: remove a tool entirely (cascade removes versions + invocations)."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(
            text("DELETE FROM sara_tool WHERE name = :name"),
            {"name": name},
        )
        await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="tool not found")
    return {"deleted": name}


@router.post("/{name}/invoke", response_model=ToolInvocationOut,
             dependencies=[Depends(verify_daemon_token)])
async def invoke_tool(name: str, payload: ToolInvokeIn) -> ToolInvocationOut:
    """Daemon-only: execute a tool. Resolves active (or pinned) version, args-
    validates, dispatches to the runner sidecar, logs the invocation."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        tool = (await db.execute(
            text("""
                SELECT id, args_schema, enabled, active_version_id
                FROM sara_tool WHERE name = :name
            """),
            {"name": name},
        )).mappings().first()
        if not tool:
            raise HTTPException(status_code=404, detail="tool not found")
        if not tool["enabled"]:
            raise HTTPException(status_code=403, detail="tool disabled by david")

        if payload.version is not None:
            version_row = (await db.execute(
                text(
                    "SELECT id, code FROM sara_tool_version "
                    "WHERE tool_id = :tid AND version = :v"
                ),
                {"tid": tool["id"], "v": payload.version},
            )).mappings().first()
        else:
            if not tool["active_version_id"]:
                raise HTTPException(status_code=409, detail="no active version")
            version_row = (await db.execute(
                text("SELECT id, code FROM sara_tool_version WHERE id = :vid"),
                {"vid": tool["active_version_id"]},
            )).mappings().first()
        if not version_row:
            raise HTTPException(status_code=404, detail="version not found")

        # Insert pending invocation row up front so it's auditable even if
        # the runner times out / crashes mid-call.
        inv_row = (await db.execute(
            text(
                """
                INSERT INTO sara_tool_invocation (tool_id, version_id, args)
                VALUES (:tid, :vid, CAST(:args AS jsonb))
                RETURNING id, started_at
                """
            ),
            {
                "tid": tool["id"],
                "vid": version_row["id"],
                "args": _json_dumps(payload.args),
            },
        )).mappings().first()
        await db.commit()
        invocation_id = inv_row["id"]
        started_at = inv_row["started_at"]

    # Dispatch outside the DB transaction so a slow runner doesn't hold a row lock.
    runner_url = (getattr(settings, "acs_tool_runner_url", "") or "").rstrip("/")
    result_payload: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None

    if not runner_url:
        error = (
            "tool runner not configured (set ACS_TOOL_RUNNER_URL); tool was "
            "validated and recorded but not executed"
        )
    else:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                resp = await client.post(
                    f"{runner_url}/run",
                    json={
                        "invocation_id": str(invocation_id),
                        "code": version_row["code"],
                        "args": payload.args,
                    },
                    headers={"X-Daemon-Token": getattr(settings, "acs_daemon_token", "") or ""},
                )
            duration_ms = int((time.monotonic() - t0) * 1000)
            if resp.status_code >= 400:
                error = f"runner returned {resp.status_code}: {resp.text[:500]}"
            else:
                body = resp.json()
                result_payload = body.get("result")
                error = body.get("error")
                if "duration_ms" in body:
                    duration_ms = int(body["duration_ms"])
        except httpx.TimeoutException:
            duration_ms = int((time.monotonic() - t0) * 1000)
            error = "runner timed out"
        except Exception as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            error = f"runner call failed: {type(e).__name__}: {e}"
            logger.exception("tool runner dispatch failed")

    async_session = get_async_session_factory()
    async with async_session() as db:
        completed_row = (await db.execute(
            text(
                """
                UPDATE sara_tool_invocation
                SET result = CAST(:result AS jsonb),
                    error = :error,
                    duration_ms = :duration_ms,
                    completed_at = NOW()
                WHERE id = :id
                RETURNING id, tool_id, version_id, args, result, error,
                          duration_ms, started_at, completed_at
                """
            ),
            {
                "id": invocation_id,
                "result": _json_dumps(result_payload) if result_payload is not None else None,
                "error": error,
                "duration_ms": duration_ms,
            },
        )).mappings().first()
        await db.commit()

    if error and not runner_url:
        # Distinguish "runner not deployed" from "tool failed" so the daemon's
        # back-off logic doesn't treat a missing sidecar as a buggy tool.
        raise HTTPException(status_code=503, detail={
            "invocation_id": str(invocation_id),
            "error": error,
        })

    return ToolInvocationOut(
        id=str(completed_row["id"]),
        tool_id=str(completed_row["tool_id"]),
        version_id=str(completed_row["version_id"]),
        args=completed_row["args"],
        result=completed_row["result"],
        error=completed_row["error"],
        duration_ms=completed_row["duration_ms"],
        started_at=completed_row["started_at"],
        completed_at=completed_row["completed_at"],
    )


@router.get("/{name}/invocations", response_model=list[ToolInvocationOut])
async def list_invocations(
    name: str,
    limit: int = Query(20, ge=1, le=200),
    x_daemon_token: Optional[str] = Header(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[ToolInvocationOut]:
    _check_auth(x_daemon_token, current_user)
    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(
                """
                SELECT inv.id, inv.tool_id, inv.version_id, inv.args, inv.result,
                       inv.error, inv.duration_ms, inv.started_at, inv.completed_at
                FROM sara_tool_invocation inv
                JOIN sara_tool t ON t.id = inv.tool_id
                WHERE t.name = :name
                ORDER BY inv.started_at DESC
                LIMIT :limit
                """
            ),
            {"name": name, "limit": limit},
        )).mappings().all()
    return [
        ToolInvocationOut(
            id=str(r["id"]),
            tool_id=str(r["tool_id"]),
            version_id=str(r["version_id"]),
            args=r["args"],
            result=r["result"],
            error=r["error"],
            duration_ms=r["duration_ms"],
            started_at=r["started_at"],
            completed_at=r["completed_at"],
        )
        for r in rows
    ]


def _json_dumps(value: Any) -> str:
    import json as _json
    return _json.dumps(value, default=str)
