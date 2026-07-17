"""
Automation admin routes for managing registered endpoints and system-wide settings.

These endpoints should be restricted to admin users in production.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from functools import lru_cache
import logging

from app.db.session import get_db
from app.core.config import settings
from app.core.deps import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/automation/admin", tags=["automation-admin"])


# Pydantic models
class RegisteredEndpointCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    base_url: str = Field(..., max_length=500)
    auth_type: str = Field(default="none")  # none, bearer, api_key, basic
    auth_header: Optional[str] = Field(default=None, max_length=100)
    auth_secret_env: Optional[str] = Field(default=None, max_length=100)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=600)
    allowed_paths: Optional[List[str]] = []
    allowed_methods: Optional[List[str]] = ["GET"]


class RegisteredEndpointUpdate(BaseModel):
    description: Optional[str] = None
    base_url: Optional[str] = None
    auth_type: Optional[str] = None
    auth_header: Optional[str] = None
    auth_secret_env: Optional[str] = None
    rate_limit_per_minute: Optional[int] = None
    allowed_paths: Optional[List[str]] = None
    allowed_methods: Optional[List[str]] = None
    is_active: Optional[bool] = None


class RegisteredEndpointResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    base_url: str
    auth_type: str
    auth_header: Optional[str]
    auth_secret_env: Optional[str]  # Only show env var name, not actual secret
    rate_limit_per_minute: int
    allowed_paths: List[str]
    allowed_methods: List[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@lru_cache(maxsize=1)
def _automation_admin_allowlist() -> set[str]:
    """Parse automation admin allowlist once per process."""
    raw = (settings.automation_admin_emails or "").strip()
    if not raw:
        return set()
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


def _user_has_admin_role(db: Session, user_id: str) -> bool:
    """
    True when user has an explicit admin-like role in app_user_role.
    Falls back safely if role table is not migrated yet.
    """
    try:
        row = db.execute(
            text("""
                SELECT role
                FROM app_user_role
                WHERE user_id = :user_id
                LIMIT 1
            """),
            {"user_id": user_id},
        ).fetchone()
    except Exception:
        return False

    if not row:
        return False
    return str(row[0] or "").lower() in {"admin", "owner"}


def require_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Restrict automation-admin endpoints to explicit role-based admin users,
    with allowlist fallback for legacy deployments.
    """
    if _user_has_admin_role(db, current_user.id):
        return current_user

    allowlist = _automation_admin_allowlist()
    if allowlist and (current_user.email or "").lower() in allowlist:
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Admin privileges required. Assign role=admin/owner in app_user_role "
            "or configure AUTOMATION_ADMIN_EMAILS for legacy allowlist access."
        ),
    )


@router.get("/endpoints", response_model=List[RegisteredEndpointResponse])
async def list_endpoints(
    db: Session = Depends(get_db),
    admin_user = Depends(require_admin)
):
    """List all registered endpoints."""
    try:
        result = db.execute(
            text("""
                SELECT id, name, description, base_url, auth_type, auth_header,
                       auth_secret_env, rate_limit_per_minute, allowed_paths,
                       allowed_methods, is_active, created_at, updated_at
                FROM registered_endpoint
                ORDER BY name
            """)
        )

        endpoints = []
        for row in result.fetchall():
            endpoints.append(RegisteredEndpointResponse(
                id=row[0],
                name=row[1],
                description=row[2],
                base_url=row[3],
                auth_type=row[4],
                auth_header=row[5],
                auth_secret_env=row[6],
                rate_limit_per_minute=row[7],
                allowed_paths=row[8] or [],
                allowed_methods=row[9] or ["GET"],
                is_active=row[10],
                created_at=row[11],
                updated_at=row[12]
            ))

        return endpoints

    except Exception as e:
        logger.error(f"Error listing endpoints: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/endpoints", response_model=RegisteredEndpointResponse)
async def create_endpoint(
    endpoint: RegisteredEndpointCreate,
    db: Session = Depends(get_db),
    admin_user = Depends(require_admin)
):
    """Create a new registered endpoint."""
    try:
        # Check if name already exists
        result = db.execute(
            text("SELECT 1 FROM registered_endpoint WHERE name = :name"),
            {"name": endpoint.name}
        )
        if result.fetchone():
            raise HTTPException(status_code=400, detail=f"Endpoint '{endpoint.name}' already exists")

        # Validate auth settings
        if endpoint.auth_type != "none":
            if not endpoint.auth_secret_env:
                raise HTTPException(
                    status_code=400,
                    detail="auth_secret_env is required when auth_type is not 'none'"
                )

        # Insert
        result = db.execute(
            text("""
                INSERT INTO registered_endpoint
                (name, description, base_url, auth_type, auth_header, auth_secret_env,
                 rate_limit_per_minute, allowed_paths, allowed_methods, is_active, created_at, updated_at)
                VALUES (:name, :description, :base_url, :auth_type, :auth_header, :auth_secret_env,
                        :rate_limit, :paths::jsonb, :methods::jsonb, TRUE, NOW(), NOW())
                RETURNING id, created_at, updated_at
            """),
            {
                "name": endpoint.name,
                "description": endpoint.description,
                "base_url": endpoint.base_url,
                "auth_type": endpoint.auth_type,
                "auth_header": endpoint.auth_header,
                "auth_secret_env": endpoint.auth_secret_env,
                "rate_limit": endpoint.rate_limit_per_minute,
                "paths": str(endpoint.allowed_paths or []).replace("'", '"'),
                "methods": str(endpoint.allowed_methods or ["GET"]).replace("'", '"')
            }
        )
        row = result.fetchone()
        db.commit()

        return RegisteredEndpointResponse(
            id=row[0],
            name=endpoint.name,
            description=endpoint.description,
            base_url=endpoint.base_url,
            auth_type=endpoint.auth_type,
            auth_header=endpoint.auth_header,
            auth_secret_env=endpoint.auth_secret_env,
            rate_limit_per_minute=endpoint.rate_limit_per_minute,
            allowed_paths=endpoint.allowed_paths or [],
            allowed_methods=endpoint.allowed_methods or ["GET"],
            is_active=True,
            created_at=row[1],
            updated_at=row[2]
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/endpoints/{endpoint_id}", response_model=RegisteredEndpointResponse)
async def update_endpoint(
    endpoint_id: int,
    updates: RegisteredEndpointUpdate,
    db: Session = Depends(get_db),
    admin_user = Depends(require_admin)
):
    """Update a registered endpoint."""
    try:
        # Build dynamic update query
        update_fields = []
        params = {"id": endpoint_id}

        if updates.description is not None:
            update_fields.append("description = :description")
            params["description"] = updates.description
        if updates.base_url is not None:
            update_fields.append("base_url = :base_url")
            params["base_url"] = updates.base_url
        if updates.auth_type is not None:
            update_fields.append("auth_type = :auth_type")
            params["auth_type"] = updates.auth_type
        if updates.auth_header is not None:
            update_fields.append("auth_header = :auth_header")
            params["auth_header"] = updates.auth_header
        if updates.auth_secret_env is not None:
            update_fields.append("auth_secret_env = :auth_secret_env")
            params["auth_secret_env"] = updates.auth_secret_env
        if updates.rate_limit_per_minute is not None:
            update_fields.append("rate_limit_per_minute = :rate_limit")
            params["rate_limit"] = updates.rate_limit_per_minute
        if updates.allowed_paths is not None:
            update_fields.append("allowed_paths = :paths::jsonb")
            params["paths"] = str(updates.allowed_paths).replace("'", '"')
        if updates.allowed_methods is not None:
            update_fields.append("allowed_methods = :methods::jsonb")
            params["methods"] = str(updates.allowed_methods).replace("'", '"')
        if updates.is_active is not None:
            update_fields.append("is_active = :is_active")
            params["is_active"] = updates.is_active

        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        update_fields.append("updated_at = NOW()")

        query = f"""
            UPDATE registered_endpoint
            SET {', '.join(update_fields)}
            WHERE id = :id
            RETURNING id, name, description, base_url, auth_type, auth_header,
                      auth_secret_env, rate_limit_per_minute, allowed_paths,
                      allowed_methods, is_active, created_at, updated_at
        """

        result = db.execute(text(query), params)
        row = result.fetchone()
        db.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Endpoint not found")

        return RegisteredEndpointResponse(
            id=row[0],
            name=row[1],
            description=row[2],
            base_url=row[3],
            auth_type=row[4],
            auth_header=row[5],
            auth_secret_env=row[6],
            rate_limit_per_minute=row[7],
            allowed_paths=row[8] or [],
            allowed_methods=row[9] or ["GET"],
            is_active=row[10],
            created_at=row[11],
            updated_at=row[12]
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/endpoints/{endpoint_id}")
async def delete_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    admin_user = Depends(require_admin)
):
    """Delete a registered endpoint."""
    try:
        result = db.execute(
            text("""
                DELETE FROM registered_endpoint
                WHERE id = :id
                RETURNING name
            """),
            {"id": endpoint_id}
        )
        row = result.fetchone()
        db.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Endpoint not found")

        return {"success": True, "message": f"Endpoint '{row[0]}' deleted"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/system-stats")
async def get_system_stats(
    db: Session = Depends(get_db),
    admin_user = Depends(require_admin)
):
    """Get system-wide automation statistics."""
    try:
        # Task counts by status
        result = db.execute(
            text("""
                SELECT status, COUNT(*)
                FROM automation_task
                GROUP BY status
            """)
        )
        status_counts = dict(result.fetchall())

        # Executions in last 24h
        result = db.execute(
            text("""
                SELECT COUNT(*), SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)
                FROM automation_execution_log
                WHERE started_at > NOW() - INTERVAL '24 hours'
            """)
        )
        row = result.fetchone()
        executions_24h = row[0] or 0
        successes_24h = row[1] or 0
        failures_24h = row[2] or 0

        # Most active tasks
        result = db.execute(
            text("""
                SELECT t.name, t.user_id, COUNT(*) as exec_count
                FROM automation_execution_log l
                JOIN automation_task t ON l.task_id = t.id
                WHERE l.started_at > NOW() - INTERVAL '24 hours'
                GROUP BY t.id, t.name, t.user_id
                ORDER BY exec_count DESC
                LIMIT 10
            """)
        )
        most_active = [{"name": r[0], "user_id": r[1][:8], "executions": r[2]} for r in result.fetchall()]

        # Endpoint usage
        result = db.execute(
            text("SELECT COUNT(*) FROM registered_endpoint WHERE is_active = TRUE")
        )
        active_endpoints = result.scalar() or 0

        return {
            "task_status_counts": status_counts,
            "total_tasks": sum(status_counts.values()),
            "active_tasks": status_counts.get("active", 0),
            "executions_24h": executions_24h,
            "success_rate_24h": (successes_24h / executions_24h * 100) if executions_24h > 0 else 0,
            "failures_24h": failures_24h,
            "most_active_tasks": most_active,
            "active_endpoints": active_endpoints
        }

    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
