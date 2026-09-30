"""Harness/thinking/personality plan, Phase 0: the redacted effective-
settings and code-provenance diagnostic. See app/routes/debug_runtime.py's
module docstring for what "code_provenance" does and does not prove.
"""
import pytest

from app.routes.debug_runtime import chat_runtime, _WATCHED_FILES, _HASH_AT_STARTUP


def test_watched_files_all_resolve_to_real_paths():
    """A typo in _WATCHED_FILES would make the report silently useless
    (every hash None) rather than fail loudly — catch that here instead."""
    for name, hashed in _HASH_AT_STARTUP.items():
        assert hashed is not None, f"{name} ({_WATCHED_FILES[name]}) did not hash — bad path?"
        assert len(hashed) == 64  # sha256 hexdigest


@pytest.mark.asyncio
async def test_chat_runtime_reports_effective_settings_without_secrets(db_session, monkeypatch):
    from app.services.soul_loader import bust_soul_cache
    bust_soul_cache()  # a real DB call earlier in the suite may have cached content

    class _FakeUser:
        id = "test-user"

    result = await chat_runtime(current_user=_FakeUser(), db=db_session)

    # Model / thinking / budgets: present, and typed sensibly.
    assert result["model"]["chat_default_model_global"]
    assert isinstance(result["thinking"]["enabled"], bool)
    assert result["budgets"]["chat_max_output_tokens"] > 0
    assert result["budgets"]["forced_final_max_tokens"] == 1200

    # Prompt: a hash and a length, never the content or the soul text.
    prompt = result["prompt"]
    assert len(prompt["sample_prompt_sha256"]) == 64
    assert prompt["sample_prompt_chars"] > 0
    dumped = str(result)
    assert "Who Sara Is" not in dumped  # a soul-section heading would mean content leaked
    assert "## " not in dumped  # markdown headings only occur inside actual prompt content

    # Code provenance: every watched file reported, each with a boolean
    # verdict, not a bare hash the caller has to compare by hand.
    provenance = {row["module"]: row for row in result["code_provenance"]}
    assert set(provenance) == set(_WATCHED_FILES)
    for row in provenance.values():
        assert isinstance(row["disk_still_matches_what_this_process_loaded"], bool)


def test_provenance_flags_a_file_edited_after_process_start(monkeypatch, tmp_path):
    """The whole point of this endpoint: prove it actually catches drift,
    not just that it returns a well-shaped dict. Simulates "process
    startup" by hashing a temp file, edits the temp file (simulating an
    on-disk change after the process's module import), and confirms
    `_code_provenance()` reports `disk_still_matches_what_this_process_loaded
    = False` for it — the same signal that would have caught the real
    main_simple.py/chat_reasoning.py staleness this phase was written to
    detect (see the module docstring)."""
    import app.routes.debug_runtime as runtime_mod

    probe = tmp_path / "probe.py"
    probe.write_text("# v1 — what the process loaded at startup\n")

    monkeypatch.setitem(runtime_mod._WATCHED_FILES, "probe", str(probe))
    monkeypatch.setitem(runtime_mod._HASH_AT_STARTUP, "probe", runtime_mod._hash_file(str(probe)))

    row_before_edit = {r["module"]: r for r in runtime_mod._code_provenance()}["probe"]
    assert row_before_edit["disk_still_matches_what_this_process_loaded"] is True

    probe.write_text("# v2 — changed on disk after 'process start'\n")

    row_after_edit = {r["module"]: r for r in runtime_mod._code_provenance()}["probe"]
    assert row_after_edit["disk_still_matches_what_this_process_loaded"] is False
    assert row_after_edit["hash_on_disk_now"] != row_after_edit["hash_at_process_startup"]
