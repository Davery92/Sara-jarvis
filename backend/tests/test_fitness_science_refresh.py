"""Step 28.6: the refresh queues and digests. It never accepts or applies.

This file exists because the dangerous version of a monthly literature
refresh is the helpful one: it finds a paper, decides the paper is good,
and adjusts a calorie target. Every assertion here is about the line
between "there is something new to read" and "something changed".

Three guarantees:

* **Nothing is accepted.** Not by the refresh, not as a side effect of
  ingesting a discovered record. `trg_science_accept_needs_event` makes the
  database agree, so this is a constraint rather than a convention.
* **Nothing is applied.** No target revision, no program change, no
  recommendation. A paper is evidence for a conversation.
* **Failure is visible as failure.** `attempted_at` always,
  `finished_at`/`succeeded` only on success — because a job that has failed
  every month for four months otherwise shows a recent timestamp and reads
  as healthy. Same class of lie as `DBScheduler` marking `last_status =
  'success'` at dispatch time.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_science_refresh.py
"""
import asyncio
import json
import os
import uuid
from typing import List

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

DIM = 1024


def _vector(seed: float = 0.1) -> List[float]:
    return [seed] * DIM


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def athlete(pg):
    unusable_hash = "$2b$12$" + "x" * 53
    uid = f"s28r-{uuid.uuid4().hex[:17]}"
    pg.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
    """), {"id": uid, "e": f"{uid}@s28.invalid", "p": unusable_hash})
    pg.commit()
    yield uid
    pg.rollback()
    for table in ("fitness_science_chunk", "fitness_science_curation_event",
                  "fitness_science_annotation", "fitness_science_revision",
                  "fitness_science_record", "fitness_science_refresh_run",
                  "say_candidate"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"),
                       {"u": uid})
            pg.commit()
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
    pg.commit()


@pytest.fixture
def stub_embeddings(monkeypatch):
    from app.services import embeddings as facade

    async def one(text_value, capability="embedding"):
        return _vector()

    async def batch(texts, capability="embedding"):
        return [_vector() for _ in texts]

    monkeypatch.setattr(facade, "get_embedding", one)
    monkeypatch.setattr(facade, "get_embeddings_batch", batch)


@pytest.fixture
def no_delivery(monkeypatch):
    """Keep the digest out of the delivery path.

    The digest goes through `say_candidate`, which needs an async session
    factory and the whole Mind V2 chain. What is being tested here is
    whether the refresh *decides* to send one, so the send is stubbed and
    recorded.
    """
    sent = []

    async def capture(db, user_id, outcome):
        sent.append({
            "user_id": user_id, "queued": outcome.queued_unreviewed,
            "retracted": list(outcome.retractions_flagged),
        })
        return True

    from app.services.fitness import science
    monkeypatch.setattr(science, "_send_digest", capture)
    return sent


def _candidate(**over):
    from app.schemas.fitness_coach import ScienceTopic, SourceType
    from app.services.fitness.science import RefreshCandidate

    body = {
        "title": "Weekly set volume and hypertrophy",
        "url": "https://example.invalid/new-paper",
        "doi": "10.1234/new",
        "source_type": SourceType.RCT,
        "topics": (ScienceTopic.HYPERTROPHY,),
    }
    body.update(over)
    return RefreshCandidate(**body)


def _discovery(*candidates, raises=None):
    async def discover(topics):
        if raises is not None:
            raise raises
        return list(candidates)
    return discover


# ─────────────────────────────────────────────────────────────────────────
# Nothing is accepted and nothing is applied
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_discovered_paper_is_queued_unreviewed(
    pg, athlete, stub_embeddings, no_delivery, monkeypatch,
):
    from app.services.fitness import science

    body = ("Methods\nForty men trained for twelve weeks. " * 30)

    async def fetch(url):
        return body.encode(), "text/plain"

    monkeypatch.setattr(science, "fetch_source", fetch)

    outcome = asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(_candidate()),
    ))
    assert outcome.succeeded is True
    assert outcome.queued_unreviewed == 1

    row = pg.execute(text("""
        SELECT status, discovered_by, discovered_run_id
        FROM fitness_science_record WHERE user_id = :u
    """), {"u": athlete}).fetchone()
    assert row.status == "unreviewed"
    assert row.discovered_by == "refresh"
    assert row.discovered_run_id == outcome.run_id


@requires_pg
def test_a_refresh_accepts_nothing_even_across_many_candidates(
    pg, athlete, stub_embeddings, no_delivery, monkeypatch,
):
    """The guarantee stated as the thing a reader would check: count the
    accepted rows and the curation events afterwards."""
    from app.schemas.fitness_coach import ScienceTopic, SourceType
    from app.services.fitness import science

    async def fetch(url):
        # Distinct text per URL. Identical bodies would be caught by the
        # content-hash dedup, which is correct behaviour and would make
        # this test pass for the wrong reason.
        return (
            f"Results\nSomething happened at {url}. " * 30
        ).encode(), "text/plain"

    monkeypatch.setattr(science, "fetch_source", fetch)

    candidates = [
        _candidate(
            title=f"Paper {index}", doi=f"10.1234/p{index}",
            url=f"https://example.invalid/p{index}",
            source_type=SourceType.META_ANALYSIS,
            topics=(ScienceTopic.NUTRITION,),
        )
        for index in range(5)
    ]
    outcome = asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(*candidates),
    ))
    assert outcome.queued_unreviewed == 5

    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_science_record
        WHERE user_id = :u AND status <> 'unreviewed'
    """), {"u": athlete}).scalar() == 0
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_science_curation_event
        WHERE user_id = :u
    """), {"u": athlete}).scalar() == 0


@requires_pg
def test_a_refresh_changes_no_target_and_no_recommendation(
    pg, athlete, stub_embeddings, no_delivery, monkeypatch,
):
    """§28.6: never auto-applies target changes. Counted directly, because
    this is the failure that would be worst and quietest."""
    from app.services.fitness import science

    async def fetch(url):
        return ("Results\nCalories matter. " * 30).encode(), "text/plain"

    monkeypatch.setattr(science, "fetch_source", fetch)

    before = {}
    for table in ("fitness_target_revision", "fitness_coach_recommendation",
                  "fitness_coach_review"):
        try:
            before[table] = pg.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = :u"
            ), {"u": athlete}).scalar()
        except Exception:
            pg.rollback()

    asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(_candidate()),
    ))

    for table, count in before.items():
        assert pg.execute(text(
            f"SELECT COUNT(*) FROM {table} WHERE user_id = :u"
        ), {"u": athlete}).scalar() == count, table


def test_the_refresh_module_writes_no_targets():
    """A structural check beside the behavioural one: the statements that
    would do it are not in the module."""
    from app.services.fitness import science
    from app.tasks import fitness_science as task_module

    for module in (science, task_module):
        code = _code_without_prose(module.__file__)
        for forbidden in ("fitness_target_revision", "create_target_revision",
                          "fitness_coach_recommendation",
                          "accept_recommendation"):
            assert forbidden not in code, (module.__name__, forbidden)


def _code_without_prose(path: str) -> str:
    """Source with comments and docstrings removed.

    Both modules *name* the tables they must not touch, in the prose that
    explains why. A scan that counted those would be a test of the
    documentation, and would push the explanation out of the file to stay
    green.
    """
    import ast as ast_module

    tree = ast_module.parse(open(path).read())
    for node in ast_module.walk(tree):
        if not isinstance(node, (ast_module.Module, ast_module.ClassDef,
                                 ast_module.FunctionDef,
                                 ast_module.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast_module.Expr)
                and isinstance(body[0].value, ast_module.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast_module.Pass()]
    return ast_module.unparse(ast_module.fix_missing_locations(tree))


def test_the_outcome_shape_cannot_report_an_acceptance():
    """§28.6 as a type: there is no field for "accepted", so a future change
    that started accepting would have to add one — and this test names the
    rule it broke."""
    from app.schemas.fitness_coach import ScienceRefreshOutcome

    fields = set(ScienceRefreshOutcome.model_fields)
    for forbidden in ("accepted", "accepted_count", "applied",
                      "targets_changed", "promoted"):
        assert forbidden not in fields, forbidden
    assert "queued_unreviewed" in fields


# ─────────────────────────────────────────────────────────────────────────
# Dedup
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_known_doi_is_skipped_without_a_fetch(
    pg, athlete, stub_embeddings, no_delivery, monkeypatch,
):
    """Re-reading the same paper every month is waste, and re-queueing it is
    the repetitive-nag pattern in a cron."""
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )
    from app.services.fitness import science

    body = ("Methods\nA study. " * 30).encode()
    asyncio.run(science.register_source(
        pg, athlete,
        ScienceRegisterInput(
            title="Already have it", source_type=SourceType.RCT,
            topics=[ScienceTopic.HYPERTROPHY], doi="10.1234/new",
        ),
        content=body, mime_type="text/plain",
    ))

    fetched = []

    async def fetch(url):
        fetched.append(url)
        return body, "text/plain"

    monkeypatch.setattr(science, "fetch_source", fetch)
    outcome = asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(_candidate()),
    ))
    assert outcome.duplicates_skipped == 1
    assert outcome.queued_unreviewed == 0
    assert fetched == [], "a known DOI should not cost a download"


@requires_pg
def test_a_candidate_with_no_identifier_is_discarded(
    pg, athlete, no_delivery,
):
    """It cannot be cited and cannot be told apart from the next one that
    arrives."""
    from app.services.fitness import science

    outcome = asyncio.run(science.refresh_library(
        pg, athlete,
        discover=_discovery(_candidate(doi=None, url=None)),
    ))
    assert outcome.queued_unreviewed == 0
    assert outcome.duplicates_skipped == 1
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_science_record WHERE user_id = :u
    """), {"u": athlete}).scalar() == 0


@requires_pg
def test_one_unfetchable_candidate_does_not_fail_the_run(
    pg, athlete, stub_embeddings, no_delivery, monkeypatch,
):
    """The queue is the product. A single dead URL should not cost the other
    twenty-four papers."""
    from app.services.fitness import science

    async def fetch(url):
        if "broken" in url:
            raise science.ScienceError(
                "404", science.ScienceIngestFailure.FETCH_FAILED,
            )
        return ("Results\nFine. " * 40).encode(), "text/plain"

    monkeypatch.setattr(science, "fetch_source", fetch)
    outcome = asyncio.run(science.refresh_library(
        pg, athlete,
        discover=_discovery(
            _candidate(title="Broken", doi="10.1/broken",
                       url="https://example.invalid/broken"),
            _candidate(title="Fine", doi="10.1/fine",
                       url="https://example.invalid/fine"),
        ),
    ))
    assert outcome.succeeded is True
    assert outcome.queued_unreviewed == 1
    assert outcome.candidates_seen == 2


@requires_pg
def test_the_candidate_count_is_capped(pg, athlete, no_delivery):
    """The point is a readable queue, not a crawl."""
    from app.services.fitness import science

    many = [
        _candidate(title=f"P{i}", doi=f"10.1/{i}", url=f"https://x.invalid/{i}")
        for i in range(science.MAX_REFRESH_CANDIDATES + 10)
    ]
    outcome = asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(*many), ingest=False,
    ))
    assert outcome.candidates_seen == science.MAX_REFRESH_CANDIDATES


# ─────────────────────────────────────────────────────────────────────────
# Retractions are flagged, not applied
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_an_upstream_retraction_is_flagged_with_its_affected_reviews(
    pg, athlete, stub_embeddings, no_delivery,
):
    """§28.6: flag retractions for impacted reviews. A review whose evidence
    was withdrawn needs a person to decide whether its advice still
    stands — and the refresh must not decide that."""
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )
    from app.services.fitness import science

    result = asyncio.run(science.register_source(
        pg, athlete,
        ScienceRegisterInput(
            title="A paper later withdrawn", source_type=SourceType.RCT,
            topics=[ScienceTopic.HYPERTROPHY], doi="10.1234/withdrawn",
        ),
        content=("Results\nSomething. " * 40).encode(),
        mime_type="text/plain",
    ))

    review_id = _review_citing(pg, athlete, result.record_id)
    assert review_id

    outcome = asyncio.run(science.refresh_library(
        pg, athlete,
        discover=_discovery(_candidate(
            doi="10.1234/withdrawn", retracted=True,
            url="https://example.invalid/withdrawn",
        )),
    ))
    assert outcome.retractions_flagged == [result.record_id]
    assert review_id in outcome.affected_review_ids

    # Flagged, NOT applied: the record's own status is untouched, because
    # marking it retracted is a curation decision with a reason.
    status = pg.execute(text("""
        SELECT status, retracted_at FROM fitness_science_record WHERE id = :id
    """), {"id": result.record_id}).fetchone()
    assert status.status == "unreviewed"
    assert status.retracted_at is None


def _review_citing(pg, user_id, record_id):
    """A completed review whose stored citations name this record."""
    import hashlib

    review_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_coach_review (
            id, user_id, kind, status, period_start, period_end,
            input_state, input_hash, state_schema_version,
            analytics_version, collected_at, prompt_version, requested_by,
            revision, attempt, output_schema_version, output, summary,
            science_citations, created_at, updated_at
        ) VALUES (
            :id, :u, 'weekly', 'complete', CURRENT_DATE - 28, CURRENT_DATE,
            '{}'::jsonb, :hash, 1, 1, NOW(), 'v1', 'user', 1, 1, 1,
            '{"summary": "A summary."}'::jsonb, 'A summary.',
            CAST(:citations AS JSONB), NOW(), NOW()
        )
    """), {
        "id": review_id, "u": user_id,
        "hash": hashlib.sha256(review_id.encode()).hexdigest(),
        "citations": json.dumps([{
            "record_id": record_id, "revision": 1,
            "chunk_id": str(uuid.uuid4()), "ranking_policy_version": 1,
        }]),
    })
    pg.commit()
    return review_id


# ─────────────────────────────────────────────────────────────────────────
# The run row tells the truth about failure
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_failed_discovery_records_an_attempt_not_a_success(pg, athlete):
    """The core of the §3 lie this avoids: one `last_run_at` would show a
    job that has failed every month as recently healthy."""
    from app.services.fitness import science

    outcome = asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(raises=RuntimeError("search is down")),
    ))
    assert outcome.succeeded is False
    assert "search is down" in (outcome.detail or "")

    row = pg.execute(text("""
        SELECT attempted_at, finished_at, succeeded, detail
        FROM fitness_science_refresh_run WHERE id = :id
    """), {"id": outcome.run_id}).fetchone()
    assert row.attempted_at is not None
    assert row.finished_at is None
    assert row.succeeded is False
    assert "search is down" in row.detail


@requires_pg
def test_a_successful_run_records_both_timestamps(pg, athlete, no_delivery):
    from app.services.fitness import science

    outcome = asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(),
    ))
    row = pg.execute(text("""
        SELECT attempted_at, finished_at, succeeded
        FROM fitness_science_refresh_run WHERE id = :id
    """), {"id": outcome.run_id}).fetchone()
    assert row.succeeded is True
    assert row.finished_at is not None


@requires_pg
def test_the_database_refuses_a_success_with_no_finish_time(pg, athlete):
    """The constraint, not just the code path that respects it."""
    from sqlalchemy.exc import DBAPIError, IntegrityError

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_science_refresh_run
                (id, user_id, succeeded) VALUES (:id, :u, TRUE)
        """), {"id": str(uuid.uuid4()), "u": athlete})
        pg.commit()
    pg.rollback()


@requires_pg
def test_no_discovery_source_is_an_honest_no_op(pg, athlete):
    """§28.7: this plan is not a supplied scientific corpus. A refresh that
    invented plausible papers would be worse than an empty library, so with
    nothing configured it says exactly that."""
    from app.services.fitness import science

    outcome = asyncio.run(science.refresh_library(pg, athlete, discover=None))
    assert outcome.succeeded is False
    assert outcome.candidates_seen == 0
    assert "not a supplied scientific corpus" in (outcome.detail or "")
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_science_record WHERE user_id = :u
    """), {"u": athlete}).scalar() == 0


def test_the_task_wires_no_discovery_by_default():
    from app.tasks.fitness_science import _configured_discovery

    assert _configured_discovery() is None


def test_the_task_requires_an_explicit_owner():
    """There is no default owner in this subsystem, and a task that guessed
    one would file papers into somebody else's library."""
    from app.tasks.fitness_science import refresh_library_task

    for bad in ("", "   ", None):
        with pytest.raises(ValueError) as excinfo:
            refresh_library_task.run(bad)
        assert "explicit user_id" in str(excinfo.value)


def test_the_task_runs_on_the_low_priority_lane():
    """Nothing waits on a paper being ingested, and the `health` lane
    carries the morning rollups."""
    from app.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert routes["app.tasks.fitness_science.*"]["queue"] == "low_priority"
    assert "app.tasks.fitness_science" in celery_app.conf.include


# ─────────────────────────────────────────────────────────────────────────
# The digest
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_quiet_run_sends_nothing(pg, athlete, monkeypatch):
    """A monthly "no new papers" message is the nag pattern this codebase
    has already been through."""
    from app.services.fitness import science

    sent = []

    async def capture(db, user_id, outcome):
        sent.append(outcome)
        return True

    monkeypatch.setattr(science, "_send_digest", capture)
    outcome = asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(),
    ))
    assert outcome.digest_sent is False
    assert sent == [], "the digest was called for an empty run"


@requires_pg
def test_one_digest_per_run_names_what_is_waiting(
    pg, athlete, stub_embeddings, monkeypatch,
):
    from app.services.fitness import science

    async def fetch(url):
        return ("Results\nSomething. " * 40).encode(), "text/plain"

    monkeypatch.setattr(science, "fetch_source", fetch)

    captured = {}

    async def fake_create(db, user_id, **kwargs):
        captured.update(kwargs)
        captured["user_id"] = user_id
        return uuid.uuid4()

    import app.services.say_candidate as say_module
    monkeypatch.setattr(say_module, "create_candidate", fake_create)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def commit(self):
            return None

    import app.db.session as session_module
    monkeypatch.setattr(
        session_module, "get_async_session_factory", lambda: _FakeSession,
    )

    outcome = asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(_candidate()),
    ))
    assert outcome.digest_sent is True
    assert captured["source"] == "fitness_science"
    # "inform", not "alert": a queue of papers to read is not urgent, and
    # reaching for alert is how a library notice interrupts a workout.
    assert captured["kind"] == "inform"
    assert "1 new paper" in captured["summary"]
    assert "Nothing was accepted or applied" in captured["summary"]
    # One per run, keyed on the run id.
    assert captured["dedupe_key"] == f"science_digest:{outcome.run_id}"


@requires_pg
def test_a_failed_digest_does_not_claim_to_have_been_sent(
    pg, athlete, stub_embeddings, monkeypatch,
):
    """Reporting "digest sent" when it was not is the lie worth avoiding;
    the records are queued either way and the library screen shows them."""
    from app.services.fitness import science

    async def fetch(url):
        return ("Results\nSomething. " * 40).encode(), "text/plain"

    monkeypatch.setattr(science, "fetch_source", fetch)

    import app.db.session as session_module
    def explode():
        raise RuntimeError("no async session factory here")
    monkeypatch.setattr(
        session_module, "get_async_session_factory", explode,
    )

    outcome = asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(_candidate()),
    ))
    assert outcome.queued_unreviewed == 1
    assert outcome.digest_sent is False
    row = pg.execute(text("""
        SELECT digest_sent, queued_unreviewed
        FROM fitness_science_refresh_run WHERE id = :id
    """), {"id": outcome.run_id}).fetchone()
    assert row.digest_sent is False
    assert row.queued_unreviewed == 1


@requires_pg
def test_the_validated_outcome_round_trips(pg, athlete, no_delivery):
    """The API shape is produced from the in-process one, so a field that
    stops validating is caught here rather than in a route."""
    from app.services.fitness import science

    outcome = asyncio.run(science.refresh_library(
        pg, athlete, discover=_discovery(),
    ))
    validated = outcome.validated()
    assert validated.run_id == outcome.run_id
    assert validated.queued_unreviewed == 0
    assert validated.digest_sent is False
