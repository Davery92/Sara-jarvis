"""
Celery tasks for the research delegation system.

- run_research_plan: Long-running task that drives the executor
- answer_research_question: Sara auto-answers agent questions via ACS deliberation
- check_stuck_research: Periodic check for unanswered questions
"""

import asyncio
import json
import logging
import os

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run async coroutine from sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(
    name="app.tasks.research.run_research_plan",
    bind=True,
    max_retries=1,
    soft_time_limit=21600,  # 6 hours soft
    time_limit=22000,       # ~6.1 hours hard
    queue="cognitive",
)
def run_research_plan(self, plan_id: str, user_id: str):
    """Execute a research plan from start to finish."""
    logger.info("Starting research plan task: %s", plan_id)

    try:
        _run_async(_run_research(plan_id, user_id))
        logger.info("Research plan task completed: %s", plan_id)
    except Exception as e:
        logger.error("Research plan task failed: %s — %s", plan_id, e, exc_info=True)
        # Update status to failed
        try:
            _run_async(_mark_failed(plan_id, str(e)))
        except Exception:
            pass
        raise


async def _run_research(plan_id: str, user_id: str):
    from app.services.research.executor import ResearchExecutor

    executor = ResearchExecutor(plan_id, user_id)
    await executor.run()


async def _mark_failed(plan_id: str, error: str):
    from sqlalchemy import text
    from app.db.session import get_db

    db = next(get_db())
    try:
        db.execute(
            text("""
                UPDATE research_plan
                SET status = 'failed', error_log = :error, updated_at = NOW()
                WHERE id = :id
            """),
            {"id": plan_id, "error": error},
        )
        db.commit()
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.research.answer_research_question",
    bind=True,
    max_retries=2,
    soft_time_limit=120,
    time_limit=180,
    queue="cognitive",
)
def answer_research_question(self, message_id: str, plan_id: str):
    """Have Sara autonomously answer a research agent's question."""
    logger.info("Sara answering research question: %s", message_id)

    try:
        _run_async(_answer_question(message_id, plan_id))
    except Exception as e:
        logger.error("Failed to answer research question: %s", e, exc_info=True)
        raise self.retry(countdown=60, exc=e)


async def _answer_question(message_id: str, plan_id: str):
    from sqlalchemy import text
    from app.db.session import get_db
    from app.core.llm import BackgroundLLMClient
    from app.services.research.context import build_sara_answer_context

    db = next(get_db())

    try:
        # Load the question
        result = db.execute(
            text("SELECT * FROM research_message WHERE id = :id"),
            {"id": message_id},
        )
        msg_row = result.fetchone()
        if not msg_row or msg_row.status != "pending":
            return

        question = msg_row.content
        step_index = msg_row.step_index

        # Load the plan
        result = db.execute(
            text("SELECT * FROM research_plan WHERE id = :id"),
            {"id": plan_id},
        )
        plan_row = result.fetchone()
        if not plan_row:
            return

        plan = dict(plan_row._mapping)
        if isinstance(plan.get("steps"), str):
            plan["steps"] = json.loads(plan["steps"])

        # Gather prior findings
        prior_findings = []
        for i, s in enumerate(plan.get("steps", [])):
            if s.get("status") == "complete" and s.get("findings"):
                prior_findings.append({
                    "title": s.get("title", f"Step {i+1}"),
                    "summary": s["findings"].get("summary", ""),
                })

        # Build Sara's prompt
        sara_prompt = build_sara_answer_context(plan, step_index, question, prior_findings)

        # Use Sara's main LLM (BackgroundLLMClient) to answer
        llm = BackgroundLLMClient()
        response = await llm.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Sara, an AI assistant. A research agent you delegated work to "
                        "has a question about the research plan you created. Help guide it."
                    ),
                },
                {"role": "user", "content": sara_prompt},
            ],
            temperature=0.5,
        )

        answer_text = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not answer_text:
            answer_text = "I'm not sure about this — please use your best judgment and continue."

        # Store Sara's answer
        import uuid

        answer_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO research_message (id, plan_id, direction, content, step_index, status)
                VALUES (:id, :plan_id, 'sara_to_agent', :content, :step_index, 'answered')
            """),
            {
                "id": answer_id,
                "plan_id": plan_id,
                "content": answer_text,
                "step_index": step_index,
            },
        )

        # Mark the original question as answered
        db.execute(
            text("""
                UPDATE research_message
                SET status = 'answered', answered_at = NOW()
                WHERE id = :id
            """),
            {"id": message_id},
        )

        db.commit()
        logger.info("Sara answered research question %s", message_id)

    finally:
        db.close()


@celery_app.task(
    name="app.tasks.research.check_stuck_research",
    queue="low_priority",
)
def check_stuck_research():
    """Periodic task: check for unanswered research questions and auto-answer them."""
    _run_async(_check_stuck())


async def _check_stuck():
    from sqlalchemy import text
    from app.db.base import SessionLocal

    # Use a self-contained sync session and END the read transaction explicitly.
    # The old code used `next(get_db())` (whose generator finally never runs) inside
    # this async fn and left the connection INTRANS in the sync pool — poisoning it
    # so the next pool_pre_ping (e.g. the tunables cache reload) failed with
    # "can't change 'autocommit' now: connection in transaction status INTRANS".
    rows = []
    db = SessionLocal()
    try:
        result = db.execute(
            text("""
                SELECT rm.id, rm.plan_id
                FROM research_message rm
                JOIN research_plan rp ON rp.id = rm.plan_id
                WHERE rm.direction = 'agent_to_sara'
                  AND rm.status = 'pending'
                  AND rm.created_at < NOW() - INTERVAL '2 minutes'
                  AND rp.status IN ('running', 'stuck')
            """)
        )
        rows = result.fetchall()
        db.rollback()  # end the read txn — never return the connection INTRANS
    finally:
        db.close()

    # Dispatch outside the DB session.
    for row in rows:
        logger.info("Auto-triggering Sara answer for message %s", row.id)
        answer_research_question.delay(row.id, row.plan_id)
