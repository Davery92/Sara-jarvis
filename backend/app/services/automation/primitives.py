"""
Primitive executors for automation tasks.

These are the ONLY things automations can do - limited, safe operations.
"""
import os
import logging
import aiohttp
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PrimitiveResult(Enum):
    """Result status for primitive execution."""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CONDITION_NOT_MET = "condition_not_met"


@dataclass
class ExecutionResult:
    """Result of executing a primitive."""
    status: PrimitiveResult
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    # For delay primitive, indicates next wake offset
    delay_seconds: int = 0


class PrimitiveExecutor:
    """Executes automation primitives safely."""

    def __init__(self, db_session=None):
        self.db = db_session

    async def execute(
        self,
        primitive: str,
        action: Dict[str, Any],
        task_id: str,
        step_state: Dict[str, Any]
    ) -> ExecutionResult:
        """
        Execute a primitive action.

        Args:
            primitive: The primitive type (home_assistant, notify, etc.)
            action: The action definition dict
            task_id: ID of the automation task
            step_state: Current execution state

        Returns:
            ExecutionResult with status and any data
        """
        executor_map = {
            "home_assistant": self._execute_home_assistant,
            "notify": self._execute_notify,
            "delay": self._execute_delay,
            "store_state": self._execute_store_state,
            "check_state": self._execute_check_state,
            "http_request": self._execute_http_request,
        }

        executor = executor_map.get(primitive)
        if not executor:
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error=f"Unknown primitive: {primitive}"
            )

        try:
            return await executor(action, task_id, step_state)
        except Exception as e:
            logger.error(f"Primitive {primitive} failed: {e}", exc_info=True)
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error=str(e)
            )

    async def _execute_home_assistant(
        self,
        action: Dict[str, Any],
        task_id: str,
        step_state: Dict[str, Any]
    ) -> ExecutionResult:
        """Execute Home Assistant service call."""
        from app.services.ha_control_service import ha_control

        entity_id = action.get("entity_id")
        service = action.get("service")
        params = action.get("params", {})

        if not entity_id or not service:
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error="entity_id and service are required"
            )

        try:
            # Parse the service into domain and service name
            if "." in service:
                domain, service_name = service.split(".", 1)
            else:
                # Infer domain from entity_id
                domain = entity_id.split(".")[0]
                service_name = service

            # Map common service names to HA control methods
            if domain == "light":
                if service_name == "turn_on":
                    result = await ha_control.turn_on_light(entity_id, **params)
                elif service_name == "turn_off":
                    result = await ha_control.turn_off_light(entity_id)
                elif service_name == "toggle":
                    result = await ha_control.toggle_light(entity_id)
                else:
                    result = await ha_control.call_service(domain, service_name, entity_id, **params)

            elif domain == "switch":
                if service_name == "turn_on":
                    result = await ha_control.turn_on_switch(entity_id)
                elif service_name == "turn_off":
                    result = await ha_control.turn_off_switch(entity_id)
                elif service_name == "toggle":
                    result = await ha_control.toggle_switch(entity_id)
                else:
                    result = await ha_control.call_service(domain, service_name, entity_id, **params)

            elif domain == "climate":
                if service_name == "set_hvac_mode":
                    hvac_mode = params.get("hvac_mode", "heat")
                    result = await ha_control.set_climate_mode(entity_id, hvac_mode)
                elif service_name == "set_temperature":
                    temp = params.get("temperature")
                    result = await ha_control.set_climate_temperature(entity_id, temp)
                else:
                    result = await ha_control.call_service(domain, service_name, entity_id, **params)

            elif domain == "cover":
                if service_name == "open_cover":
                    result = await ha_control.open_cover(entity_id)
                elif service_name == "close_cover":
                    result = await ha_control.close_cover(entity_id)
                elif service_name == "set_cover_position":
                    position = params.get("position", 50)
                    result = await ha_control.set_cover_position(entity_id, position)
                else:
                    result = await ha_control.call_service(domain, service_name, entity_id, **params)

            elif domain == "lock":
                if service_name == "lock":
                    result = await ha_control.lock(entity_id)
                elif service_name == "unlock":
                    result = await ha_control.unlock(entity_id)
                else:
                    result = await ha_control.call_service(domain, service_name, entity_id, **params)

            elif domain == "scene":
                result = await ha_control.activate_scene(entity_id)

            elif domain == "media_player":
                if service_name == "media_play":
                    result = await ha_control.media_play(entity_id)
                elif service_name == "media_pause":
                    result = await ha_control.media_pause(entity_id)
                elif service_name == "media_stop":
                    result = await ha_control.media_stop(entity_id)
                elif service_name == "volume_set":
                    volume = params.get("volume_level", 0.5)
                    result = await ha_control.set_volume(entity_id, volume)
                else:
                    result = await ha_control.call_service(domain, service_name, entity_id, **params)

            else:
                # Generic service call
                result = await ha_control.call_service(domain, service_name, entity_id, **params)

            logger.info(f"[Automation {task_id}] HA action: {domain}.{service_name} on {entity_id}")
            return ExecutionResult(
                status=PrimitiveResult.SUCCESS,
                result={"action": f"{domain}.{service_name}", "entity_id": entity_id, "response": result}
            )

        except Exception as e:
            logger.error(f"[Automation {task_id}] HA action failed: {e}")
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error=f"Home Assistant error: {e}"
            )

    async def _execute_notify(
        self,
        action: Dict[str, Any],
        task_id: str,
        step_state: Dict[str, Any]
    ) -> ExecutionResult:
        """Send mobile push notification."""
        from app.services.unified_notification import send_notification

        message = action.get("message", "")
        title = action.get("title", "Sara Automation")
        priority = action.get("priority", "default")
        data = action.get("data", {})

        # Get user_id from step_state or the automation task
        user_id = step_state.get("user_id")
        if not user_id:
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error="user_id not available for notification"
            )

        # Add automation context to data
        data["automation_task_id"] = task_id
        data["automation_type"] = "automation_alert"

        try:
            result = await send_notification(
                user_id=user_id,
                title=title,
                message=message,
                priority=priority,
                category="automation",
                topic=f"automation:{task_id}",
                source="automation_primitives",
                extra_push_data=data,
            )

            if result.get("sent"):
                logger.info(f"[Automation {task_id}] Sent notification: {title}")
                return ExecutionResult(
                    status=PrimitiveResult.SUCCESS,
                    result={"title": title, "message": message}
                )
            else:
                return ExecutionResult(
                    status=PrimitiveResult.FAILED,
                    error=f"Failed to send push notification: {result.get('reason', 'unknown')}"
                )

        except Exception as e:
            logger.error(f"[Automation {task_id}] Notification failed: {e}")
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error=f"Notification error: {e}"
            )

    async def _execute_delay(
        self,
        action: Dict[str, Any],
        task_id: str,
        step_state: Dict[str, Any]
    ) -> ExecutionResult:
        """
        Set a delay before the next action.

        This doesn't actually sleep - it returns a delay_seconds value
        that the orchestrator uses to set next_wake_at.
        """
        seconds = action.get("seconds", 0)

        if seconds <= 0:
            return ExecutionResult(
                status=PrimitiveResult.SUCCESS,
                result={"delayed": False},
                delay_seconds=0
            )

        logger.info(f"[Automation {task_id}] Delay: {seconds}s before next step")
        return ExecutionResult(
            status=PrimitiveResult.SUCCESS,
            result={"delayed": True, "delay_seconds": seconds},
            delay_seconds=seconds
        )

    async def _execute_store_state(
        self,
        action: Dict[str, Any],
        task_id: str,
        step_state: Dict[str, Any]
    ) -> ExecutionResult:
        """
        Store a value for later comparison.

        Can either store a literal value or fetch from HA entity.
        """
        from sqlalchemy import text

        key = action.get("key")
        if not key:
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error="key is required for store_state"
            )

        # Get the value to store
        value = None
        value_source = action.get("value_source")

        if value_source:
            # Fetch from HA entity
            entity_id = value_source.get("entity_id")
            if entity_id:
                from app.services.ha_control_service import ha_control
                try:
                    state = await ha_control.get_state(entity_id)
                    value = state.get("state")
                    # Optionally get an attribute
                    attr_name = value_source.get("attribute")
                    if attr_name:
                        value = state.get("attributes", {}).get(attr_name, value)
                except Exception as e:
                    return ExecutionResult(
                        status=PrimitiveResult.FAILED,
                        error=f"Failed to fetch HA state: {e}"
                    )
        else:
            # Use literal value
            value = action.get("value")

        if not self.db:
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error="Database session not available"
            )

        try:
            # Upsert the state value
            result = await self.db.execute(
                text("""
                    INSERT INTO automation_state_store (task_id, key, value, previous_value, updated_at)
                    VALUES (:task_id, :key, :value::jsonb, NULL, NOW())
                    ON CONFLICT (task_id, key) DO UPDATE SET
                        previous_value = automation_state_store.value,
                        value = :value::jsonb,
                        updated_at = NOW()
                    RETURNING previous_value
                """),
                {"task_id": task_id, "key": key, "value": str(value) if value is not None else "null"}
            )
            row = result.fetchone()
            previous_value = row[0] if row else None
            await self.db.commit()

            logger.info(f"[Automation {task_id}] Stored state '{key}': {value} (was: {previous_value})")
            return ExecutionResult(
                status=PrimitiveResult.SUCCESS,
                result={"key": key, "value": value, "previous_value": previous_value}
            )

        except Exception as e:
            logger.error(f"[Automation {task_id}] store_state failed: {e}")
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error=f"Failed to store state: {e}"
            )

    async def _execute_check_state(
        self,
        action: Dict[str, Any],
        task_id: str,
        step_state: Dict[str, Any]
    ) -> ExecutionResult:
        """
        Check stored state against a condition.

        If condition is not met, returns CONDITION_NOT_MET which
        can be used to skip subsequent actions.
        """
        from sqlalchemy import text

        key = action.get("key")
        condition = action.get("condition")  # equals, not_equals, changed, contains
        expected = action.get("expected")

        if not key or not condition:
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error="key and condition are required for check_state"
            )

        if not self.db:
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error="Database session not available"
            )

        try:
            result = await self.db.execute(
                text("""
                    SELECT value, previous_value FROM automation_state_store
                    WHERE task_id = :task_id AND key = :key
                """),
                {"task_id": task_id, "key": key}
            )
            row = result.fetchone()

            if not row:
                logger.warning(f"[Automation {task_id}] No stored state for key '{key}'")
                return ExecutionResult(
                    status=PrimitiveResult.CONDITION_NOT_MET,
                    result={"key": key, "reason": "no_stored_state"}
                )

            value = row[0]
            previous_value = row[1]

            # Evaluate condition
            condition_met = False
            if condition == "equals":
                condition_met = str(value) == str(expected)
            elif condition == "not_equals":
                condition_met = str(value) != str(expected)
            elif condition == "changed":
                condition_met = value != previous_value
            elif condition == "contains":
                condition_met = str(expected) in str(value) if value else False
            elif condition == "greater_than":
                try:
                    condition_met = float(value) > float(expected)
                except (ValueError, TypeError):
                    condition_met = False
            elif condition == "less_than":
                try:
                    condition_met = float(value) < float(expected)
                except (ValueError, TypeError):
                    condition_met = False
            else:
                return ExecutionResult(
                    status=PrimitiveResult.FAILED,
                    error=f"Unknown condition: {condition}"
                )

            if condition_met:
                logger.info(f"[Automation {task_id}] Condition met: {key} {condition} {expected}")
                return ExecutionResult(
                    status=PrimitiveResult.SUCCESS,
                    result={
                        "key": key,
                        "condition": condition,
                        "expected": expected,
                        "actual": value,
                        "met": True
                    }
                )
            else:
                logger.info(f"[Automation {task_id}] Condition NOT met: {key} {condition} {expected} (actual: {value})")
                return ExecutionResult(
                    status=PrimitiveResult.CONDITION_NOT_MET,
                    result={
                        "key": key,
                        "condition": condition,
                        "expected": expected,
                        "actual": value,
                        "met": False
                    }
                )

        except Exception as e:
            logger.error(f"[Automation {task_id}] check_state failed: {e}")
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error=f"Failed to check state: {e}"
            )

    async def _execute_http_request(
        self,
        action: Dict[str, Any],
        task_id: str,
        step_state: Dict[str, Any]
    ) -> ExecutionResult:
        """
        Make HTTP request to a registered endpoint.

        Only endpoints in the registered_endpoint table can be called.
        """
        from sqlalchemy import text

        endpoint_name = action.get("endpoint_name")
        path = action.get("path", "/")
        method = action.get("method", "GET").upper()
        body = action.get("body")
        timeout_seconds = action.get("timeout_seconds", 30)

        if not endpoint_name:
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error="endpoint_name is required"
            )

        if not self.db:
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error="Database session not available"
            )

        try:
            # Look up the registered endpoint
            result = await self.db.execute(
                text("""
                    SELECT base_url, auth_type, auth_header, auth_secret_env,
                           allowed_paths, allowed_methods, is_active
                    FROM registered_endpoint
                    WHERE name = :name
                """),
                {"name": endpoint_name}
            )
            row = result.fetchone()

            if not row:
                return ExecutionResult(
                    status=PrimitiveResult.FAILED,
                    error=f"Endpoint '{endpoint_name}' not registered"
                )

            base_url, auth_type, auth_header, auth_secret_env, allowed_paths, allowed_methods, is_active = row

            if not is_active:
                return ExecutionResult(
                    status=PrimitiveResult.FAILED,
                    error=f"Endpoint '{endpoint_name}' is disabled"
                )

            # Check if method is allowed
            if allowed_methods and method not in allowed_methods:
                return ExecutionResult(
                    status=PrimitiveResult.FAILED,
                    error=f"Method {method} not allowed for endpoint '{endpoint_name}'"
                )

            # Check if path is allowed
            if allowed_paths:
                path_allowed = any(
                    path.startswith(allowed_path) or path == allowed_path
                    for allowed_path in allowed_paths
                )
                if not path_allowed:
                    return ExecutionResult(
                        status=PrimitiveResult.FAILED,
                        error=f"Path '{path}' not allowed for endpoint '{endpoint_name}'"
                    )

            # Build headers
            headers = {"Content-Type": "application/json"}

            if auth_type != "none" and auth_secret_env:
                secret = os.getenv(auth_secret_env)
                if secret:
                    if auth_type == "bearer":
                        headers[auth_header or "Authorization"] = f"Bearer {secret}"
                    elif auth_type == "api_key":
                        headers[auth_header or "X-API-Key"] = secret
                    elif auth_type == "basic":
                        import base64
                        headers[auth_header or "Authorization"] = f"Basic {base64.b64encode(secret.encode()).decode()}"

            # Make the request
            url = f"{base_url.rstrip('/')}{path}"

            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    json=body if method in ("POST", "PUT", "PATCH") else None,
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds)
                ) as response:
                    response_text = await response.text()

                    if response.status >= 400:
                        logger.warning(
                            f"[Automation {task_id}] HTTP {method} {url} returned {response.status}: {response_text[:200]}"
                        )
                        return ExecutionResult(
                            status=PrimitiveResult.FAILED,
                            error=f"HTTP {response.status}: {response_text[:200]}"
                        )

                    # Try to parse as JSON
                    try:
                        response_data = await response.json()
                    except:
                        response_data = {"text": response_text[:1000]}

                    logger.info(f"[Automation {task_id}] HTTP {method} {url} -> {response.status}")
                    return ExecutionResult(
                        status=PrimitiveResult.SUCCESS,
                        result={
                            "status_code": response.status,
                            "response": response_data
                        }
                    )

        except aiohttp.ClientError as e:
            logger.error(f"[Automation {task_id}] HTTP request failed: {e}")
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error=f"HTTP error: {e}"
            )
        except Exception as e:
            logger.error(f"[Automation {task_id}] http_request failed: {e}")
            return ExecutionResult(
                status=PrimitiveResult.FAILED,
                error=str(e)
            )


async def execute_primitive(
    primitive: str,
    action: Dict[str, Any],
    task_id: str,
    step_state: Dict[str, Any],
    db_session=None
) -> ExecutionResult:
    """
    Convenience function to execute a primitive.

    Args:
        primitive: The primitive type
        action: The action definition
        task_id: The automation task ID
        step_state: Current execution state
        db_session: Optional database session for state operations

    Returns:
        ExecutionResult
    """
    executor = PrimitiveExecutor(db_session)
    return await executor.execute(primitive, action, task_id, step_state)
