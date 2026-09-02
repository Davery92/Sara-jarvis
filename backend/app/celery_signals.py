"""Outcome contracts (M1) — make scheduled tasks honest about their effect.

The DBScheduler marks `last_status='success'` at DISPATCH time — so a task that
runs and then returns an error (or raises) still showed green. That's the exact
"78/78 jobs success while one failed hourly" lie the audit found.

These signal handlers correct it from the task's ACTUAL result:
- A task that returns an outcome contract `{"effect": "error"|"error_*", ...}`
  → the scheduled_job is marked failed and the miss is recorded to task_failure
  (interoception's ledger).
- A task that raises → same.
- Success needs no write here (dispatch already marked it, and the next good run
  self-heals a prior failure).

Low overhead: writes happen only on a miss/failure, which is rare.
"""
import logging

from celery.signals import task_postrun, worker_process_init

logger = logging.getLogger(__name__)


@worker_process_init.connect
def _wire_token_accounting(**_kwargs):
    """Follow-up plan §7: give the worker a token-usage callback.

    `core/llm._record_background_usage` reports every background model call to
    whatever callback is registered — but the only place that ever registered
    one was `main_simple.startup_event`, which Celery never runs. Appraisal,
    judge, deliberation and compose all live here, so every one of their calls
    was attributed to nobody and `token_usage` held chat rows and nothing else.

    The synchronous writer, not `queue_token_usage`: a prefork child has no
    long-lived event loop to drain an asyncio queue (see record_token_usage_sync).
    """
    try:
        from app.core.llm import set_token_usage_callback
        from app.services.token_usage_service import record_token_usage_sync

        set_token_usage_callback(record_token_usage_sync)
        logger.info("Token usage accounting wired for this worker process")
    except Exception as e:
        logger.warning(f"Token usage accounting not wired in worker: {e}")


def _is_contract_miss(retval) -> tuple[bool, str | None]:
    if isinstance(retval, dict):
        eff = str(retval.get("effect") or "")
        if eff == "error" or eff.startswith("error"):
            return True, str(retval)[:300]
        # Explicit failure contracts some tasks use. `failed` must be a FLAG:
        # a task that reports how many sub-items failed (`{"failed": 1}` out of
        # 7 handled) is reporting normal partial progress, not its own failure.
        failed = retval.get("failed")
        if isinstance(failed, bool):
            failed_flag = failed
        elif isinstance(failed, str):
            failed_flag = bool(failed)
        else:
            failed_flag = False
        if retval.get("ok") is False or failed_flag:
            return True, str(retval)[:300]
    return False, None


def _mark_job_failed(task_name: str, detail: str | None, record_ledger: bool):
    """Correct scheduled_job.last_status. If record_ledger, also write task_failure
    (used for contract-misses — a raise is already logged by interoception)."""
    from app.db.base import SessionLocal
    from sqlalchemy import text
    try:
        with SessionLocal() as db:
            # Only touch rows that are actually scheduled jobs for this task.
            res = db.execute(text("""
                UPDATE scheduled_job SET last_status = 'failed', last_error = :err
                WHERE task_name = :t
            """), {"t": task_name, "err": (detail or "outcome contract miss")[:500]})
            if res.rowcount and record_ledger:
                db.execute(text("""
                    INSERT INTO task_failure
                      (task_name, error_class, error_message, occurrences, first_seen, last_seen, resolved)
                    VALUES (:t, 'ContractMiss', :msg, 1, NOW(), NOW(), FALSE)
                    ON CONFLICT (task_name, error_class) DO UPDATE SET
                        occurrences = task_failure.occurrences + 1,
                        last_seen = NOW(), resolved = FALSE,
                        error_message = EXCLUDED.error_message
                """), {"t": task_name, "msg": (detail or "outcome contract miss")[:500]})
            db.commit()
    except Exception as e:
        logger.debug(f"outcome-contract status update skipped for {task_name}: {e}")


@task_postrun.connect
def _on_postrun(task_id=None, task=None, retval=None, state=None, **kw):
    try:
        name = getattr(task, "name", None)
        if not name or not name.startswith("app.tasks."):
            return
        # A raise: state is FAILURE. Interoception already logged the task_failure
        # ledger row; we just correct the scheduler's dispatch-time "success" lie.
        if state and str(state).upper() == "FAILURE":
            _mark_job_failed(name, "raised", record_ledger=False)
            return
        # A returned error contract (no raise): the ledger doesn't know yet.
        miss, detail = _is_contract_miss(retval)
        if miss:
            logger.info(f"⚖️ Outcome-contract miss: {name} → {detail}")
            _mark_job_failed(name, detail, record_ledger=True)
    except Exception:
        pass
