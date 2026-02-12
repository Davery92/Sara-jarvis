"""
Mission Engine (Phase 2 — Cortana Evolution).

Persistent multi-step tasks that can span multiple heartbeat cycles.
Missions are created via API or by the agent, and advanced by a dedicated
Celery worker every 30 seconds.

States: pending → running → (awaiting_confirm) → done / failed / cancelled
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class MissionEngine:
    """CRUD + step execution for persistent missions."""

    async def create_mission(
        self,
        db: AsyncSession,
        user_id: str,
        title: str,
        steps: List[Dict[str, Any]],
        description: Optional[str] = None,
        source: str = "user",
        priority: str = "normal",
        requires_confirmation: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Create a new mission with steps."""
        try:
            result = await db.execute(text("""
                INSERT INTO autonomy_mission
                (user_id, title, description, source, state, priority,
                 total_steps, requires_confirmation, metadata)
                VALUES (:user_id, :title, :description, :source, 'pending', :priority,
                        :total_steps, :requires_confirmation, CAST(:metadata AS jsonb))
                RETURNING id::text
            """), {
                "user_id": user_id,
                "title": title,
                "description": description,
                "source": source,
                "priority": priority,
                "total_steps": len(steps),
                "requires_confirmation": requires_confirmation,
                "metadata": json.dumps(metadata or {}, default=str),
            })
            row = result.fetchone()
            if not row:
                return None
            mission_id = row[0]

            # Create steps
            for i, step in enumerate(steps):
                await db.execute(text("""
                    INSERT INTO autonomy_mission_step
                    (mission_id, step_index, action_name, action_args, description)
                    VALUES (:mission_id::uuid, :step_index, :action_name,
                            CAST(:action_args AS jsonb), :description)
                    ON CONFLICT (mission_id, step_index) DO NOTHING
                """), {
                    "mission_id": mission_id,
                    "step_index": i,
                    "action_name": step.get("action_name", "unknown"),
                    "action_args": json.dumps(step.get("action_args", {}), default=str),
                    "description": step.get("description"),
                })

            return mission_id
        except Exception as e:
            logger.error(f"Failed to create mission: {e}")
            return None

    async def start_mission(self, db: AsyncSession, mission_id: str) -> bool:
        """Start a pending mission."""
        try:
            result = await db.execute(text("""
                UPDATE autonomy_mission
                SET state = 'running', started_at = NOW(), updated_at = NOW()
                WHERE id = :id::uuid AND state = 'pending'
            """), {"id": mission_id})
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to start mission: {e}")
            return False

    async def advance_mission(self, db: AsyncSession, mission_id: str) -> Dict[str, Any]:
        """
        Execute the next pending step of a mission.

        Idempotent: if the current step is not 'pending', it's a no-op.
        """
        try:
            # Load mission
            result = await db.execute(text("""
                SELECT id::text, user_id, state, current_step_index, total_steps,
                       requires_confirmation, confirmed_at
                FROM autonomy_mission
                WHERE id = :id::uuid
                FOR UPDATE SKIP LOCKED
            """), {"id": mission_id})
            mission = result.fetchone()
            if not mission:
                return {"status": "not_found"}

            m_id, user_id, state, current_idx, total_steps, req_confirm, confirmed_at = mission

            if state not in ("running", "pending"):
                return {"status": "not_runnable", "state": state}

            # Auto-start if pending
            if state == "pending":
                await db.execute(text("""
                    UPDATE autonomy_mission
                    SET state = 'running', started_at = NOW(), updated_at = NOW()
                    WHERE id = :id::uuid
                """), {"id": mission_id})

            if current_idx >= total_steps:
                # All steps done
                await db.execute(text("""
                    UPDATE autonomy_mission
                    SET state = 'done', completed_at = NOW(), updated_at = NOW()
                    WHERE id = :id::uuid
                """), {"id": mission_id})
                return {"status": "completed", "mission_id": m_id}

            # Load current step
            step_result = await db.execute(text("""
                SELECT id::text, action_name, action_args, status
                FROM autonomy_mission_step
                WHERE mission_id = :mid::uuid AND step_index = :idx
            """), {"mid": mission_id, "idx": current_idx})
            step = step_result.fetchone()
            if not step:
                return {"status": "step_not_found", "step_index": current_idx}

            step_id, action_name, action_args, step_status = step

            # Idempotency: skip if already executed
            if step_status != "pending":
                return {"status": "already_executed", "step_status": step_status}

            # Check confirmation requirement
            if req_confirm and not confirmed_at and current_idx == 0:
                await db.execute(text("""
                    UPDATE autonomy_mission
                    SET state = 'awaiting_confirm', updated_at = NOW()
                    WHERE id = :id::uuid
                """), {"id": mission_id})
                return {"status": "awaiting_confirmation"}

            # Execute step
            await db.execute(text("""
                UPDATE autonomy_mission_step
                SET status = 'running', started_at = NOW()
                WHERE id = :id::uuid
            """), {"id": step_id})

            exec_result = await self._execute_step(action_name, action_args or {}, user_id, db)
            success = exec_result.get("success", False)

            if success:
                await db.execute(text("""
                    UPDATE autonomy_mission_step
                    SET status = 'done', result = CAST(:result AS jsonb), completed_at = NOW()
                    WHERE id = :id::uuid
                """), {"id": step_id, "result": json.dumps(exec_result, default=str)})

                new_idx = current_idx + 1
                completed_steps = new_idx
                new_state = "done" if new_idx >= total_steps else "running"

                await db.execute(text("""
                    UPDATE autonomy_mission
                    SET current_step_index = :idx, completed_steps = :completed,
                        state = :state, updated_at = NOW(),
                        completed_at = CASE WHEN :state = 'done' THEN NOW() ELSE completed_at END
                    WHERE id = :id::uuid
                """), {
                    "idx": new_idx, "completed": completed_steps,
                    "state": new_state, "id": mission_id,
                })

                return {
                    "status": "step_completed",
                    "step_index": current_idx,
                    "mission_state": new_state,
                    "result": exec_result,
                }
            else:
                error = exec_result.get("error", "Unknown error")
                await db.execute(text("""
                    UPDATE autonomy_mission_step
                    SET status = 'failed', error_message = :error,
                        result = CAST(:result AS jsonb), completed_at = NOW()
                    WHERE id = :id::uuid
                """), {"id": step_id, "error": error, "result": json.dumps(exec_result, default=str)})

                await db.execute(text("""
                    UPDATE autonomy_mission
                    SET state = 'failed', completed_at = NOW(), updated_at = NOW()
                    WHERE id = :id::uuid
                """), {"id": mission_id})

                return {
                    "status": "step_failed",
                    "step_index": current_idx,
                    "error": error,
                }
        except Exception as e:
            logger.error(f"Failed to advance mission {mission_id}: {e}")
            return {"status": "error", "error": str(e)}

    async def confirm_mission(self, db: AsyncSession, mission_id: str, user_id: Optional[str] = None) -> bool:
        """Confirm a mission that's awaiting confirmation. Scoped by user_id when provided."""
        try:
            conditions = ["id = :id::uuid", "state = 'awaiting_confirm'"]
            params: Dict[str, Any] = {"id": mission_id}
            if user_id:
                conditions.append("user_id = :user_id")
                params["user_id"] = user_id
            where = " AND ".join(conditions)
            result = await db.execute(text(f"""
                UPDATE autonomy_mission
                SET state = 'running', confirmed_at = NOW(), updated_at = NOW()
                WHERE {where}
            """), params)
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to confirm mission: {e}")
            return False

    async def cancel_mission(self, db: AsyncSession, mission_id: str, user_id: Optional[str] = None) -> bool:
        """Cancel a mission. Scoped by user_id when provided."""
        try:
            conditions = ["id = :id::uuid", "state NOT IN ('done', 'failed', 'cancelled')"]
            params: Dict[str, Any] = {"id": mission_id}
            if user_id:
                conditions.append("user_id = :user_id")
                params["user_id"] = user_id
            where = " AND ".join(conditions)
            result = await db.execute(text(f"""
                UPDATE autonomy_mission
                SET state = 'cancelled', completed_at = NOW(), updated_at = NOW()
                WHERE {where}
            """), params)
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to cancel mission: {e}")
            return False

    async def list_missions(
        self,
        db: AsyncSession,
        user_id: str,
        state: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List missions, newest first."""
        conditions = ["user_id = :user_id"]
        params: Dict[str, Any] = {"user_id": user_id, "limit": limit}

        if state:
            conditions.append("state = :state")
            params["state"] = state

        where = " AND ".join(conditions)

        try:
            result = await db.execute(text(f"""
                SELECT id::text, title, description, source, state, priority,
                       total_steps, completed_steps, current_step_index,
                       requires_confirmation, metadata,
                       created_at, started_at, completed_at
                FROM autonomy_mission
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit
            """), params)
            return [
                {
                    "id": r[0], "title": r[1], "description": r[2],
                    "source": r[3], "state": r[4], "priority": r[5],
                    "total_steps": r[6], "completed_steps": r[7],
                    "current_step_index": r[8], "requires_confirmation": r[9],
                    "metadata": r[10],
                    "created_at": r[11].isoformat() if r[11] else None,
                    "started_at": r[12].isoformat() if r[12] else None,
                    "completed_at": r[13].isoformat() if r[13] else None,
                }
                for r in result.fetchall()
            ]
        except Exception as e:
            logger.error(f"Failed to list missions: {e}")
            return []

    async def get_mission(self, db: AsyncSession, mission_id: str) -> Optional[Dict[str, Any]]:
        """Get a mission with its steps."""
        try:
            result = await db.execute(text("""
                SELECT id::text, user_id, title, description, source, state, priority,
                       total_steps, completed_steps, current_step_index,
                       requires_confirmation, metadata,
                       created_at, started_at, completed_at
                FROM autonomy_mission
                WHERE id = :id::uuid
            """), {"id": mission_id})
            row = result.fetchone()
            if not row:
                return None

            mission = {
                "id": row[0], "user_id": row[1], "title": row[2],
                "description": row[3], "source": row[4], "state": row[5],
                "priority": row[6], "total_steps": row[7],
                "completed_steps": row[8], "current_step_index": row[9],
                "requires_confirmation": row[10], "metadata": row[11],
                "created_at": row[12].isoformat() if row[12] else None,
                "started_at": row[13].isoformat() if row[13] else None,
                "completed_at": row[14].isoformat() if row[14] else None,
            }

            # Load steps
            steps_result = await db.execute(text("""
                SELECT id::text, step_index, action_name, action_args, description,
                       status, result, error_message, started_at, completed_at
                FROM autonomy_mission_step
                WHERE mission_id = :mid::uuid
                ORDER BY step_index
            """), {"mid": mission_id})
            mission["steps"] = [
                {
                    "id": s[0], "step_index": s[1], "action_name": s[2],
                    "action_args": s[3], "description": s[4], "status": s[5],
                    "result": s[6], "error_message": s[7],
                    "started_at": s[8].isoformat() if s[8] else None,
                    "completed_at": s[9].isoformat() if s[9] else None,
                }
                for s in steps_result.fetchall()
            ]

            return mission
        except Exception as e:
            logger.error(f"Failed to get mission: {e}")
            return None

    async def _execute_step(
        self,
        action_name: str,
        action_args: Dict[str, Any],
        user_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Execute a single mission step using orchestrator primitives."""
        try:
            from app.services.automation.primitives import execute_primitive, PrimitiveResult
            result = await execute_primitive(
                primitive=action_name,
                action=action_args,
                task_id=None,
                step_state={"user_id": user_id},
                db_session=db,
            )
            return {
                "success": result.status != PrimitiveResult.FAILED,
                "result": result.result,
                "error": result.error,
            }
        except ImportError:
            # Fallback: try UnifiedAgent tool execution
            try:
                from app.services.unified_agent import UnifiedAgent
                agent = UnifiedAgent(user_id)
                result = await agent._execute_tool(action_name, action_args, db)
                return result
            except Exception as e:
                return {"success": False, "error": f"No executor for {action_name}: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_runnable_missions(self, db: AsyncSession) -> List[str]:
        """Get IDs of missions that need to be advanced."""
        try:
            result = await db.execute(text("""
                SELECT id::text
                FROM autonomy_mission
                WHERE state IN ('running', 'pending')
                  AND current_step_index < total_steps
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 0
                        WHEN 'urgent' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'normal' THEN 3
                        WHEN 'low' THEN 4
                    END,
                    created_at
                LIMIT 5
            """))
            return [r[0] for r in result.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get runnable missions: {e}")
            return []


# Module-level singleton
mission_engine = MissionEngine()
