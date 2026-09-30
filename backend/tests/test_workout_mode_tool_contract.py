"""Workout-mode tool invocation contract (Sara repair plan R07, evidence
J06_trial2_START_WORKOUT_TOOL_COMPLETELY_BROKEN).

Confirmed mechanism: `ToolRegistry.execute_tool` always dispatches as
`tool.execute(user_id, **parameters)` — `user_id` is ALWAYS the first
positional argument. `WorkoutModeStartTool.execute`'s first parameter used
to be `template_id`, so the real user_id string silently landed in
`template_id` instead. `WorkoutModeLogTool`/`WorkoutModeCompleteTool`
declared a REQUIRED `action` parameter first, which is worse: the model's
own `action=...` keyword collided with the positional user_id
(`TypeError: execute() got multiple values for argument 'action'`) on every
call. None of the three ever received a `db` session from the registry
either (only a fixed allowlist of context kwargs is ever injected), and all
three returned plain dicts instead of ToolResult, which
`ToolRegistry.execute_tool`'s `if result.success:` cannot read.

These tests call `execute()` exactly the way the registry does — a
positional user_id plus the model's own keyword arguments — and assert a
real ToolResult comes back with no TypeError/AttributeError, for all three
tools.
"""
import pytest

from app.tools.base import ToolResult


class _FakeDBSession:
    def close(self):
        pass


def _fake_get_db():
    yield _FakeDBSession()


@pytest.fixture(autouse=True)
def _patch_db(monkeypatch):
    monkeypatch.setattr("app.db.session.get_db", _fake_get_db)


class TestStartWorkoutContract:
    @pytest.mark.asyncio
    async def test_user_id_is_not_bound_into_template_id(self, monkeypatch):
        from app.tools.fitness.workout_mode import WorkoutModeStartTool
        import app.services.workout_session_service as svc_mod

        seen = {}

        async def _fake_start_workout(user_id, template_id, db):
            seen["user_id"] = user_id
            seen["template_id"] = template_id
            return {"session": {"id": "s1", "workout_snapshot": {"template_name": "Push Day", "exercises": []}}}

        monkeypatch.setattr(svc_mod.workout_session_service, "start_workout", _fake_start_workout)

        tool = WorkoutModeStartTool()
        # Exactly the registry's real call shape: tool.execute(user_id, **parameters)
        result = await tool.execute("user-a", template_id="tpl-123")

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert seen["user_id"] == "user-a"
        assert seen["template_id"] == "tpl-123"

    @pytest.mark.asyncio
    async def test_missing_template_returns_a_readable_tool_result_not_a_dict(self, monkeypatch):
        from app.tools.fitness.workout_mode import WorkoutModeStartTool
        import app.services.workout_session_service as svc_mod

        async def _fake_start_workout(*a, **kw):
            raise AssertionError("should not be called with no template")

        monkeypatch.setattr(svc_mod.workout_session_service, "start_workout", _fake_start_workout)

        # No template_id/template_name at all -> the tool's own
        # "which workout would you like" branch, before ever calling the
        # service — must not raise before getting there.
        async def _fake_execute(db, user_id, query, params):
            class _Q:
                def fetchall(self):
                    return []
            return _Q()

        tool = WorkoutModeStartTool()
        # Patch db.execute used for the template list lookup
        class _FakeDB:
            def execute(self, *a, **kw):
                class _Q:
                    def fetchall(self):
                        return []
                return _Q()
            def close(self):
                pass

        monkeypatch.setattr("app.db.session.get_db", lambda: iter([_FakeDB()]))

        result = await tool.execute("user-a")
        assert isinstance(result, ToolResult)
        assert result.success is False


class TestWorkoutModeLogContract:
    @pytest.mark.asyncio
    async def test_action_keyword_does_not_collide_with_positional_user_id(self, monkeypatch):
        """This is the sharper failure: `action` used to be the first
        declared parameter, so the model's own `action=...` kwarg collided
        with the positionally-passed user_id and raised TypeError on every
        single call, regardless of db/user_id presence."""
        from app.tools.fitness.workout_mode import WorkoutModeLogTool
        import app.services.workout_session_service as svc_mod

        async def _fake_get_active_session(user_id, db):
            return {"id": "sess-1", "workout_snapshot": {"exercises": []}, "current_exercise_index": 0}

        async def _fake_log_set(**kwargs):
            return {"logged": {"weight": 135, "reps": 8}, "next_set": None, "total_sets_completed": 1, "total_volume": 1080}

        monkeypatch.setattr(svc_mod.workout_session_service, "get_active_session", _fake_get_active_session)
        monkeypatch.setattr(svc_mod.workout_session_service, "log_set", _fake_log_set)

        tool = WorkoutModeLogTool()
        result = await tool.execute("user-a", action="log_set", weight=135, reps=8)

        assert isinstance(result, ToolResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_active_session_is_a_clean_failure_not_a_typeerror(self, monkeypatch):
        from app.tools.fitness.workout_mode import WorkoutModeLogTool
        import app.services.workout_session_service as svc_mod

        async def _fake_get_active_session(user_id, db):
            return None

        monkeypatch.setattr(svc_mod.workout_session_service, "get_active_session", _fake_get_active_session)

        tool = WorkoutModeLogTool()
        result = await tool.execute("user-a", action="skip_exercise")

        assert isinstance(result, ToolResult)
        assert result.success is False


class TestEndWorkoutContract:
    @pytest.mark.asyncio
    async def test_action_keyword_does_not_collide_with_positional_user_id(self, monkeypatch):
        from app.tools.fitness.workout_mode import WorkoutModeCompleteTool
        import app.services.workout_session_service as svc_mod

        async def _fake_complete_workout(user_id, db):
            return {"summary": {"duration_minutes": 45, "total_sets": 12, "total_volume": 5000, "exercises_completed": 4}}

        monkeypatch.setattr(svc_mod.workout_session_service, "complete_workout", _fake_complete_workout)

        tool = WorkoutModeCompleteTool()
        result = await tool.execute("user-a", action="complete")

        assert isinstance(result, ToolResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_abandon_action(self, monkeypatch):
        from app.tools.fitness.workout_mode import WorkoutModeCompleteTool
        import app.services.workout_session_service as svc_mod

        async def _fake_abandon_workout(user_id, db):
            return {}

        monkeypatch.setattr(svc_mod.workout_session_service, "abandon_workout", _fake_abandon_workout)

        tool = WorkoutModeCompleteTool()
        result = await tool.execute("user-a", action="abandon")

        assert isinstance(result, ToolResult)
        assert result.success is True
