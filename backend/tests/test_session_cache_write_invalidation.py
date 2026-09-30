"""Read caches are invalidated by writes — reliable-assistant plan D1.

Finding 22 (`C05_AMBIGUOUS_DELETE_CORRECT_EXPLICIT_BULK_DELETE_STALE_CACHE_
FALSE_DENIAL`): `session_cache` held eight read tools per conversation for 30
minutes with no write-invalidation of any kind, so a reminder created one turn
earlier was reported as "possibly never actually created" — the log shows
"Cache HIT" immediately before the false claim. The study flagged it as a
plausible common root cause for several other false-denial findings.
"""

import json
import uuid

import fakeredis
import pytest

from app.services.operation_contract import domain_for_tool
from app.services.session_cache import SessionToolCache


@pytest.fixture
def cache():
    return SessionToolCache(fakeredis.FakeStrictRedis(), ttl_minutes=30)


@pytest.fixture
def conv():
    return str(uuid.uuid4())


class TestDomainMapping:
    @pytest.mark.parametrize("tool,domain", [
        ("reminders_create", "reminders"),
        ("reminders_list", "reminders"),
        ("reminders_cancel", "reminders"),
        ("notes_search", "notes"),
        ("notes_edit", "notes"),
        ("notes_create", "notes"),
        ("timers_status", "timers"),
        ("timers_start", "timers"),
        ("daily_task_create", "daily_task"),
        ("daily_task_complete", "daily_task"),
        ("calendar_create", "calendar"),
        ("calendar_list", "calendar"),
        ("list_add", "list"),
        ("list_view", "list"),
        ("food_log_create", "food"),
        ("food_log_summary", "food"),
        ("workout_log_create", "fitness"),
        ("template_update", "fitness"),
        ("documents_search", "documents"),
        ("memory_search", "memory"),
        ("standing_order_create", "automation"),
        ("cancel_research_plan", "research_plan"),
        ("resolve_thread", "thread"),
    ])
    def test_a_write_and_the_read_it_invalidates_agree_on_the_name(self, tool, domain):
        # The whole mechanism depends on this: a write and the read it must
        # invalidate have to land on the same domain string.
        assert domain_for_tool(tool) == domain

    def test_an_unknown_tool_still_gets_a_stable_domain(self):
        assert domain_for_tool("some_future_tool_create") == "some"
        assert domain_for_tool("") == "unknown"


class TestInvalidation:
    def test_the_finding_22_sequence(self, cache, conv):
        # Turn 1: a reminders_list read is cached.
        cache.set(conv, "reminders_list", {}, json.dumps({"reminders": []}))
        assert cache.get(conv, "reminders_list", {}) is not None

        # Turn 2: a reminder is actually created.
        dropped = cache.invalidate_for_write(conv, "reminders_create")
        assert dropped >= 1

        # Turn 3: the follow-up read must reach the database, not the stale
        # "no reminders" answer that produced the false denial.
        assert cache.get(conv, "reminders_list", {}) is None

    def test_a_write_invalidates_every_cached_read_in_its_domain(self, cache, conv):
        cache.set(conv, "notes_search", {"query": "dana"}, "hit-1")
        cache.set(conv, "notes_search", {"query": "priya"}, "hit-2")
        cache.set(conv, "notes_list", {}, "hit-3")
        assert cache.invalidate_for_write(conv, "notes_edit") >= 3
        assert cache.get(conv, "notes_search", {"query": "dana"}) is None
        assert cache.get(conv, "notes_search", {"query": "priya"}) is None
        assert cache.get(conv, "notes_list", {}) is None

    def test_an_unrelated_domain_survives(self, cache, conv):
        cache.set(conv, "notes_search", {"query": "dana"}, "notes")
        cache.set(conv, "documents_search", {"query": "lease"}, "docs")
        cache.invalidate_for_write(conv, "reminders_create")
        assert cache.get(conv, "notes_search", {"query": "dana"}) == "notes"
        assert cache.get(conv, "documents_search", {"query": "lease"}) == "docs"

    def test_memory_is_invalidated_by_any_write(self, cache, conv):
        # Memories summarize activity across domains, so a note written now
        # legitimately changes what a memory search should return.
        cache.set(conv, "memory_search", {"query": "dana"}, "stale")
        cache.invalidate_for_write(conv, "reminders_create")
        assert cache.get(conv, "memory_search", {"query": "dana"}) is None

    def test_another_conversations_cache_is_untouched(self, cache, conv):
        other = str(uuid.uuid4())
        cache.set(conv, "reminders_list", {}, "mine")
        cache.set(other, "reminders_list", {}, "theirs")
        cache.invalidate_for_write(conv, "reminders_create")
        assert cache.get(conv, "reminders_list", {}) is None
        assert cache.get(other, "reminders_list", {}) == "theirs"

    def test_invalidating_an_empty_domain_is_a_no_op(self, cache, conv):
        assert cache.invalidate_for_write(conv, "reminders_create") == 0

    def test_an_uncacheable_tool_is_never_indexed(self, cache, conv):
        cache.set(conv, "reminders_create", {"title": "x"}, "should not cache")
        assert cache.get(conv, "reminders_create", {"title": "x"}) is None


class TestFailClosedOnIndexFailure:
    def test_an_entry_that_cannot_be_indexed_is_not_cached(self, conv):
        """A cache entry with no invalidation index is worse than no cache
        entry: it can only ever serve a read that a later write contradicts."""
        redis = fakeredis.FakeStrictRedis()
        cache = SessionToolCache(redis, ttl_minutes=30)

        def _boom(*a, **kw):
            raise RuntimeError("redis SADD unavailable")

        redis.sadd = _boom
        cache.set(conv, "reminders_list", {}, "value")
        assert cache.get(conv, "reminders_list", {}) is None
