"""Regression tests for heartbeat/background audit fixes."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis

from app.routes.autonomy_missions import MissionActionRequest, mission_action
from app.services.agent_dispatch import AgentDispatchService
from app.services.autonomy.coordination import WorkerCoordinator
from app.services.background_task_service import BackgroundTaskService


def _extract_user_filter_value(conditions) -> str | None:
    for condition in conditions:
        left = getattr(condition, "left", None)
        right = getattr(condition, "right", None)
        if getattr(left, "key", None) == "user_id":
            return getattr(right, "value", None)
    return None


class _CapturingQuery:
    def __init__(self, owner_task, owner_user_id: str):
        self._owner_task = owner_task
        self._owner_user_id = owner_user_id
        self.conditions = ()

    def filter(self, *conditions):
        self.conditions = conditions
        return self

    def first(self):
        user_filter = _extract_user_filter_value(self.conditions)
        if user_filter is None:
            # Simulate id-only lookup leaking another user's task.
            return self._owner_task
        if user_filter == self._owner_user_id:
            return self._owner_task
        return None


class _QueryOnlyDB:
    def __init__(self, query):
        self._query = query

    def query(self, _model):
        return self._query

    def commit(self):
        return None


class _SingleTaskQuery:
    def __init__(self, task):
        self._task = task

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._task


class _TaskDB:
    def __init__(self, task):
        self._query = _SingleTaskQuery(task)
        self.commits = 0

    def query(self, _model):
        return self._query

    def commit(self):
        self.commits += 1


def test_resume_task_wrong_user_returns_error():
    service = AgentDispatchService()
    owner_task = SimpleNamespace(id="task-1", user_id="owner")
    query = _CapturingQuery(owner_task=owner_task, owner_user_id="owner")
    db = _QueryOnlyDB(query)

    with patch.object(service, "_get_bridge") as mock_get_bridge:
        result = asyncio.run(
            service.resume_task(
                db=db,
                task_id="task-1",
                user_id="intruder",
                instruction="Continue",
            )
        )

    assert result["error"] == "Task not found"
    assert _extract_user_filter_value(query.conditions) == "intruder"
    assert mock_get_bridge.call_count == 0


def test_get_task_detail_wrong_user_returns_none():
    service = AgentDispatchService()
    owner_task = SimpleNamespace(id="task-1", user_id="owner")
    query = _CapturingQuery(owner_task=owner_task, owner_user_id="owner")
    db = _QueryOnlyDB(query)

    detail = asyncio.run(
        service.get_task_detail(
            db=db,
            task_id="task-1",
            user_id="intruder",
        )
    )

    assert detail is None
    assert _extract_user_filter_value(query.conditions) == "intruder"


def test_mission_action_resume_passes_user_id():
    db = MagicMock()
    current_user = SimpleNamespace(id="user-1")
    mission = {"user_id": "user-1", "mission_metadata": {"task_id": "task-9"}}

    with patch(
        "app.routes.autonomy_missions.mission_engine.get_mission",
        new=AsyncMock(return_value=mission),
    ), patch(
        "app.services.agent_dispatch.agent_dispatch_service.resume_task",
        new=AsyncMock(return_value={"status": "running"}),
    ) as mock_resume:
        result = asyncio.run(
            mission_action(
                mission_id="mission-1",
                request=MissionActionRequest(action="clarify", message="extra context"),
                current_user=current_user,
                db=db,
            )
        )

    assert result["success"] is True
    assert mock_resume.await_count == 1
    assert mock_resume.await_args.kwargs["user_id"] == "user-1"


def test_provide_clarification_fires_run_task_and_clears_question():
    service = BackgroundTaskService()
    task = SimpleNamespace(
        id="task-1",
        status="needs_clarification",
        clarification_response=None,
        clarification_question="Need more context",
        task_metadata={},
        user_id="user-1",
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = task

    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return MagicMock()

    with patch("asyncio.create_task", side_effect=fake_create_task):
        ok = asyncio.run(
            service.provide_clarification(
                db=db,
                task_id="task-1",
                response="Here is the answer",
            )
        )

    assert ok is True
    assert task.status == "running"
    assert task.clarification_response == "Here is the answer"
    assert task.clarification_question is None
    assert len(scheduled) == 1
    db.commit.assert_called_once()


def test_run_task_consumes_clarification_once():
    service = BackgroundTaskService()
    task = SimpleNamespace(
        id="task-1",
        user_id="user-1",
        status="needs_clarification",
        task_type="research",
        original_query="Find updates",
        workspace_folder_id=None,
        task_metadata={},
        created_at=datetime.utcnow(),
        started_at=None,
        completed_at=None,
        result_note_id=None,
        error_message=None,
        clarification_response="Only include pricing changes",
        clarification_question="Any constraints?",
    )
    db = _TaskDB(task)

    orchestrator = SimpleNamespace(
        run_task=AsyncMock(
            return_value={"response": "Done", "total_duration_ms": 10, "iterations": 1}
        )
    )

    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return MagicMock()

    with patch.object(service, "_create_orchestrator", return_value=orchestrator), patch.object(
        service,
        "_create_result_note",
        new=AsyncMock(return_value=SimpleNamespace(id="note-1")),
    ), patch("asyncio.create_task", side_effect=fake_create_task):
        asyncio.run(service.run_task(db=db, task_id="task-1"))
        asyncio.run(service.run_task(db=db, task_id="task-1"))

    first_query = orchestrator.run_task.await_args_list[0].args[0]
    second_query = orchestrator.run_task.await_args_list[1].args[0]

    assert "[Additional context from user: Only include pricing changes]" in first_query
    assert second_query == "Find updates"
    assert task.clarification_response is None
    assert task.clarification_question is None
    assert len(scheduled) == 2  # completion notification on each run


def test_release_wrong_owner_preserves_lock():
    coordinator = WorkerCoordinator()
    coordinator._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    acquired = asyncio.run(coordinator.acquire_exclusive("worker-A", "lock-group"))
    assert acquired is True

    asyncio.run(coordinator.release_exclusive("lock-group", "worker-B"))
    holder = asyncio.run(coordinator.get_lock_holder("lock-group"))
    assert holder == "worker-A"


def test_release_correct_owner_deletes_lock():
    coordinator = WorkerCoordinator()
    coordinator._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    acquired = asyncio.run(coordinator.acquire_exclusive("worker-A", "lock-group"))
    assert acquired is True

    asyncio.run(coordinator.release_exclusive("lock-group", "worker-A"))
    holder = asyncio.run(coordinator.get_lock_holder("lock-group"))
    assert holder is None
