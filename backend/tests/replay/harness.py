"""Replay one of the 2026-09-09/10 turns against the real assembly code.

Phase 0 of docs/plans/SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10.md.

What a replay does:

* points every database reader at `sara_replay` — a throwaway database
  rebuilt from the fixture by provision.py — so the live one is not merely
  "not written to", it is not opened;
* pins the clock to the wall-clock minute of the captured turn, because
  half of these failures are about what "today" and "now" meant;
* runs the actual context assembly the chat endpoint runs, and hands back
  the assembled text plus a per-section size account;
* builds the REAL final outgoing payload through
  `app.services.chat_assembly.assemble_local_provider_messages` — the same
  pure function the local chat lane calls in production, not a harness
  reimplementation of the prompt-cache-split shape (harness/thinking/
  personality plan, Phase 0: this used to hand-concatenate one system-message
  string and call `get_system_prompt`, the pre-"harness rebuild Phase 5"
  persona builder production text chat has not used since 2026-09-11);
* records every write anyone attempts — SQL DML and tool calls alike —
  instead of performing it.

What it is NOT: the whole `chat_stream` endpoint. That function is ~1,100
lines of inline assembly with an HTTP request, an auth dependency and a
streaming generator wrapped around it, and there is no seam to call it
through yet. The harness reassembles the same blocks in the same order
through the same functions (see `assemble`), ending in the same final
payload-boundary function `chat_stream` itself calls, and `SECTION_GAPS`
records exactly which of the endpoint's other inputs are not covered, so the
gap is written down rather than assumed away. Closing the remaining gap
(calling `chat_stream` itself, end to end) is separate work — that requires
extracting a single assembly function from the ~1,100-line handler, which
this change does not attempt.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

# SARA_REPLAY_FIXTURE picks which captured fixture to replay against — the
# original Sept 9/10 conversations, or a later one (e.g. "2026_09_16", the
# MTP repair plan's morning conversation). Defaults to the original so every
# existing invocation is unchanged.
FIXTURE_NAME = os.getenv("SARA_REPLAY_FIXTURE", "2026_09_09")
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / FIXTURE_NAME
REPLAY_DB_NAME = "sara_replay"
REPLAY_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

ET = timezone(timedelta(hours=-4))  # America/New_York in September 2026

# Blocks chat_stream appends after the ones `assemble` reproduces. They are
# listed, not silently omitted: a Phase 2 claim about "one budget over the
# final assembled context" has to account for these too.
SECTION_GAPS = (
    "inbox digest (P3, only on include_inbox turns)",
    "attention-item context (reply-to-a-proactive-item turns)",
    "content-inbox item body",
    "workspace context (desktop client only)",
    "re-entry / last-conversation digest",
    "repeat-question flag",
    "unacked-notification slice",
    "multi-turn conversation_history — every replay is a single isolated "
    "turn (empty conversation_history, one user message); a real multi-round "
    "thread's prior turns, and their effect on dialogue_state/token budget, "
    "are not modeled",
    "non-local provider path (assemble_non_local_provider_messages) — this "
    "harness only exercises the local (MTPLX) chat lane's assembly function",
)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def replay_database_url() -> str:
    """The URL a replay is allowed to use, or raise.

    This is the one guarantee the whole harness rests on: a replay cannot
    touch live data because it never holds a connection string that points
    at it. Checked here rather than trusted from the caller.
    """
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is unset; run through run_replay.sh")
    dbname = url.rsplit("/", 1)[-1].split("?")[0]
    if dbname != REPLAY_DB_NAME:
        raise RuntimeError(
            f"refusing to replay against database {dbname!r} — a replay runs "
            f"only against {REPLAY_DB_NAME!r} (run through run_replay.sh)"
        )
    return url


def replay_enabled() -> bool:
    try:
        replay_database_url()
    except RuntimeError:
        return False
    return True


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Turn:
    index: int
    conversation_id: str
    at_utc: datetime
    user_text: str
    observed_assistant_text: str
    user_episode_id: str

    @property
    def at_et(self) -> datetime:
        return self.at_utc.replace(tzinfo=timezone.utc).astimezone(ET)


def load_turns() -> list[Turn]:
    raw = json.loads((FIXTURE_DIR / "turns.json").read_text())
    return [
        Turn(
            index=t["index"],
            conversation_id=t["conversation_id"],
            # episode.created_at is naive UTC (gotcha_day_replay_timestamp_
            # conventions) — the fixture keeps it exactly as stored.
            at_utc=datetime.fromisoformat(t["at"]),
            user_text=t["user_text"],
            observed_assistant_text=t["observed_assistant_text"],
            user_episode_id=t["user_episode_id"],
        )
        for t in raw
    ]


def turn(index: int) -> Turn:
    return load_turns()[index]


def fixture_rows(table: str) -> list[dict]:
    rows = json.loads(gzip.decompress((FIXTURE_DIR / "rows.json.gz").read_bytes()).decode())
    return rows.get(table, [])


# ---------------------------------------------------------------------------
# Rewinding the world
# ---------------------------------------------------------------------------

_rewinding = False

REPLAY_REDIS_DB = "15"


def flush_replay_caches():
    """Empty the replay Redis database.

    Assembly is cached in Redis — the context snapshot for 20 seconds, the
    world brief for two minutes — and a replay moves between September 9th
    and 10th in milliseconds. Without this, the second turn replayed in a
    session is handed the first turn's world and every assertion after it is
    measuring the cache.

    Refuses to run against any Redis database but the replay one, since
    "flush the cache" against db 0 would drop live working memory.
    """
    url = os.getenv("REDIS_URL", "")
    if not url.rstrip("/").endswith("/" + REPLAY_REDIS_DB):
        raise RuntimeError(
            f"refusing to flush Redis at {url!r} — a replay uses db {REPLAY_REDIS_DB} "
            "(run through run_replay.sh)")
    from app.core.redis import get_redis_sync
    get_redis_sync().flushdb()


_fixture_briefs: Optional[Path] = None

# Six modules hardcode the same live path, and four of them WRITE to it.
# Miss one and a replay edits David's real narrative.
_BRIEF_MODULES = (
    "app.services.daily_brief.compiler",
    "app.services.daily_brief.stable_layer",
    "app.services.daily_brief.moment_layer",
    "app.services.daily_brief.day_layer",
    "app.services.daily_brief.context_layer",
    "app.services.daily_brief.status_tracker",
)
_BRIEF_SINGLETONS = (
    ("app.services.daily_brief.compiler", "brief_compiler"),
    ("app.services.daily_brief.stable_layer", "stable_layer"),
    ("app.services.daily_brief.moment_layer", "moment_layer"),
    ("app.services.daily_brief.day_layer", "day_layer"),
    ("app.services.daily_brief.context_layer", "context_layer"),
)


def install_fixture_briefs() -> Path:
    """Point the daily-brief layers at the fixture's copy, in a temp dir.

    The four layers Sara reads every turn — moment, day, context, stable —
    are markdown FILES under data/briefs/<user>/layers, not database rows,
    and the container mounts the same host directory the live assistant
    writes. A replay that leaves this alone reads today's narrative and
    calls it evidence; worse, the layer code calls mkdir on the way past.

    Copying to a temp directory keeps a replay from writing into the
    fixture as well as out of the live one.
    """
    global _fixture_briefs
    if _fixture_briefs is not None:
        return _fixture_briefs

    import importlib
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="sara-replay-briefs-"))
    source = FIXTURE_DIR / "briefs"
    if source.is_dir():
        shutil.copytree(source, root, dirs_exist_ok=True)
    for module_name in _BRIEF_MODULES:
        try:
            importlib.import_module(module_name).BRIEFS_DIR = root
        except Exception:
            pass
    for module_name, singleton in _BRIEF_SINGLETONS:
        try:
            getattr(importlib.import_module(module_name), singleton).briefs_dir = root
        except Exception:
            pass
    try:
        from app.services.daily_brief.brief_service import daily_brief_service
        daily_brief_service.compiler.briefs_dir = root
    except Exception:
        pass
    _fixture_briefs = root
    return root


def rewind_to(at: datetime) -> dict[str, int]:
    """Restore the replay database to the rows that existed at `at`.

    Freezing the clock is only half of "replay this turn": the fixture holds
    every row up to the last exchange, so without this the Wednesday
    afternoon turns are assembled against Thursday morning's sleep readings
    and the health slice reports a measurement taken "in 16h".

    Each rewindable table is refilled from its pristine copy in the `fixture`
    schema, which makes this idempotent and order-independent — turns can be
    replayed in any order, repeatedly.
    """
    from sqlalchemy import text
    from app.db.base import SessionLocal
    from tests.replay.provision import REWINDABLE

    at_et = at.astimezone(ET)
    bounds = {
        "aware": at_et.isoformat(),
        "utc": at_et.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" "),
        "et": at_et.replace(tzinfo=None).isoformat(sep=" "),
    }

    global _rewinding
    flush_replay_caches()
    restored: dict[str, int] = {}
    _rewinding = True
    db = SessionLocal()
    try:
        db.execute(text("SET session_replication_role = replica"))
        for table, (columns, convention) in REWINDABLE.items():
            db.execute(text(f'DELETE FROM public."{table}"'))
            predicate = " AND ".join(
                f'("{c}" IS NULL OR "{c}" <= :bound)' for c in columns)
            result = db.execute(text(
                f'INSERT INTO public."{table}" SELECT * FROM fixture."{table}" '
                f'WHERE {predicate}'
            ), {"bound": bounds[convention]})
            restored[table] = result.rowcount
        db.execute(text("SET session_replication_role = DEFAULT"))
        db.commit()
    finally:
        _rewinding = False
        db.close()
    return restored


# ---------------------------------------------------------------------------
# Frozen clock
# ---------------------------------------------------------------------------

_CLOCK_NAMES = ("now", "today", "now_utc", "naive_local_now", "naive_utc_now")


@contextmanager
def frozen_clock(at: datetime) -> Iterator[datetime]:
    """Pin `app.core.timezone`'s clock to `at` (an aware datetime).

    Modules bind these functions at import time (`from app.core.timezone
    import naive_local_now`), so patching the module attribute alone would
    miss every consumer already imported — hence the sys.modules sweep.

    `datetime.now()` and `date.today()` are frozen too, but only inside
    `app.*` modules, and only via a subclass so that isinstance checks,
    arithmetic and pickling keep working. Without this the freeze is a
    half-measure: `render_when` — the single function every timestamp in a
    prompt goes through — takes its reference time from a bare
    `datetime.now(USER_TIMEZONE)`, and a replay of the 6:54 AM greeting was
    rendering the 10 AM dentist appointment as "34m ago".
    """
    import app.core.timezone as tz

    at_et = at.astimezone(ET)
    frozen = {
        "now": lambda: at_et,
        "today": lambda: at_et.date(),
        "now_utc": lambda: at_et.astimezone(timezone.utc),
        "naive_local_now": lambda: at_et.replace(tzinfo=None),
        "naive_utc_now": lambda: at_et.astimezone(timezone.utc).replace(tzinfo=None),
    }
    originals = {name: getattr(tz, name) for name in _CLOCK_NAMES}

    # The metaclasses are load-bearing, not decoration: application code is
    # full of `isinstance(x, datetime)`, and a plain subclass would answer
    # False for the ordinary datetimes coming out of the database driver.
    # (Same approach freezegun takes.)
    class _FrozenDatetimeMeta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, datetime)

        def __subclasscheck__(cls, sub):
            return issubclass(sub, datetime)

    class _FrozenDateMeta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, date)

        def __subclasscheck__(cls, sub):
            return issubclass(sub, date)

    class FrozenDatetime(datetime, metaclass=_FrozenDatetimeMeta):
        @classmethod
        def now(cls, tz_=None):
            return at_et.astimezone(tz_) if tz_ is not None else at_et.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return at_et.astimezone(timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return at_et.replace(tzinfo=None)

    class FrozenDate(date, metaclass=_FrozenDateMeta):
        @classmethod
        def today(cls):
            return at_et.date()

    rebound: list[tuple[Any, str, Any]] = []
    # Held in locals: the sweep below rebinds module globals named `datetime`
    # and `date`, and this module has two of its own. Comparing against the
    # module global after that point compares against FrozenDatetime and
    # every later `is` check silently fails — which is exactly what happened
    # the first time this was written.
    real_datetime, real_date = datetime, date
    this_module = sys.modules[__name__]

    def rebind(module, name, replacement, original):
        rebound.append((module, name, original))
        setattr(module, name, replacement)

    for name in _CLOCK_NAMES:
        setattr(tz, name, frozen[name])
    for module in list(sys.modules.values()):
        if module is None or module is this_module:
            continue
        for name in _CLOCK_NAMES:
            if getattr(module, name, None) is originals[name]:
                rebind(module, name, frozen[name], originals[name])
        if (getattr(module, "__name__", "") or "").startswith("app."):
            if getattr(module, "datetime", None) is real_datetime:
                rebind(module, "datetime", FrozenDatetime, real_datetime)
            if getattr(module, "date", None) is real_date:
                rebind(module, "date", FrozenDate, real_date)
    try:
        yield at_et
    finally:
        for name, original in originals.items():
            setattr(tz, name, original)
        for module, name, original in rebound:
            setattr(module, name, original)


# ---------------------------------------------------------------------------
# Write interception
# ---------------------------------------------------------------------------

@dataclass
class WriteLedger:
    """Every mutating statement that reached a database during a replay.

    The replay database is disposable, so these writes are allowed to land —
    recording them is the point. "Zero consumed-food writes for a planned
    dinner" is a claim about this ledger.
    """
    statements: list[tuple[str, str]] = field(default_factory=list)  # (verb, sql)

    def record(self, sql: str):
        if _rewinding:
            return  # the harness rewinding the fixture is not Sara writing
        verb = sql.lstrip().split(" ", 1)[0].upper()
        if verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER", "CREATE"):
            self.statements.append((verb, " ".join(sql.split())[:400]))

    def touching(self, table: str) -> list[tuple[str, str]]:
        needle = table.lower()
        return [(v, s) for v, s in self.statements if needle in s.lower()]

    def __len__(self) -> int:
        return len(self.statements)


@contextmanager
def write_ledger() -> Iterator[WriteLedger]:
    from sqlalchemy import event
    from app.db.base import engine

    ledger = WriteLedger()

    def before(conn, cursor, statement, parameters, context, executemany):
        ledger.record(statement)

    listeners = [(engine.sync_engine if hasattr(engine, "sync_engine") else engine, before)]
    for target, fn in listeners:
        event.listen(target, "before_cursor_execute", fn)

    # The async engine is built lazily per event loop; attach to whatever
    # exists now and to anything created during the replay.
    from app.db import session as db_session
    original_factory = db_session.get_async_session_factory
    attached: set[int] = set()

    def factory_with_listener(*args, **kwargs):
        result = original_factory(*args, **kwargs)
        async_engine = getattr(db_session, "_async_engine", None)
        sync_engine = getattr(async_engine, "sync_engine", None)
        if sync_engine is not None and id(sync_engine) not in attached:
            event.listen(sync_engine, "before_cursor_execute", before)
            attached.add(id(sync_engine))
        return result

    db_session.get_async_session_factory = factory_with_listener
    try:
        yield ledger
    finally:
        db_session.get_async_session_factory = original_factory
        for target, fn in listeners:
            event.remove(target, "before_cursor_execute", fn)


# ---------------------------------------------------------------------------
# Tool interception
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    name: str
    arguments: dict
    executed: bool
    result: Any = None


@dataclass
class ToolLog:
    calls: list[ToolCall] = field(default_factory=list)

    def named(self, name: str) -> list[ToolCall]:
        return [c for c in self.calls if c.name == name]

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.calls]


# Tools that change the world. In a replay they are recorded and answered
# with a plausible success, never run: a replay of "dinner is going to be
# taco pasta salad" must be able to observe the model TRYING to log food
# without the attempt being what proves the fix.
MUTATING_TOOLS = {
    "food_search_and_log", "log_food", "delete_food_log",
    "create_reminder", "cancel_reminder", "update_reminder",
    "start_timer", "cancel_timer",
    "create_calendar_event", "update_calendar_event", "delete_calendar_event",
    "create_note", "edit_note", "delete_note",
    "send_notification", "send_message", "queue_for_sara",
    "log_workout_set", "start_workout", "end_workout",
    "create_standing_order", "cancel_standing_order",
}


@contextmanager
def intercepted_tools(
    canned: Optional[dict[str, Any]] = None,
    allow_reads: bool = True,
) -> Iterator[ToolLog]:
    """Record tool calls. Mutating tools never execute; read tools may.

    Read-through is on by default because the reads answer from the replay
    database, which is the whole point of having one — "did she consult the
    logged workout" is only a real question if she could have.
    """
    from app.tools.registry import tool_registry

    log = ToolLog()
    canned = canned or {}
    original = tool_registry.execute_tool

    async def execute(name, arguments, *args, **kwargs):
        if name in MUTATING_TOOLS or name in canned:
            result = canned.get(name, {
                "success": True,
                "replayed": True,
                "message": f"[replay] {name} was not executed",
            })
            log.calls.append(ToolCall(name, dict(arguments or {}), executed=False, result=result))
            return result
        if not allow_reads:
            result = {"success": False, "replayed": True, "message": "[replay] reads disabled"}
            log.calls.append(ToolCall(name, dict(arguments or {}), executed=False, result=result))
            return result
        result = await original(name, arguments, *args, **kwargs)
        log.calls.append(ToolCall(name, dict(arguments or {}), executed=True, result=result))
        return result

    tool_registry.execute_tool = execute
    try:
        yield log
    finally:
        tool_registry.execute_tool = original


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

@dataclass
class Assembled:
    """What the model would have been shown, and what it cost to build."""
    text: str
    sections: dict[str, str]
    seconds: float
    recall_traces: list[dict] = field(default_factory=list)
    tools_offered: list[str] = field(default_factory=list)
    tool_schemas: list[dict] = field(default_factory=list)
    model: str = ""
    # The actual outgoing payload, built by the SAME function
    # (`app.services.chat_assembly.assemble_local_provider_messages`) the
    # local-provider chat lane calls in production — not a harness
    # reimplementation of it. See `assemble()`.
    all_messages: list = field(default_factory=list)
    stable_system_prompt: str = ""
    stable_system_prompt_sha256: str = ""
    # Personal-conversation remediation plan, step 2.
    conversation_mode: str = ""
    suppress_ambient: bool = False

    @property
    def sizes(self) -> dict[str, int]:
        return {name: len(body or "") for name, body in self.sections.items()}

    @property
    def chars(self) -> int:
        return len(self.text)

    def section(self, name: str) -> str:
        return self.sections.get(name) or ""

    def account(self) -> str:
        lines = [f"{self.chars:>7,} chars total, assembled in {self.seconds:.2f}s"]
        for name, size in sorted(self.sizes.items(), key=lambda kv: -kv[1]):
            if size:
                lines.append(f"{size:>7,}  {name}")
        return "\n".join(lines)


async def assemble(
    message: str,
    at: datetime,
    *,
    user_id: str = REPLAY_USER_ID,
    session_id: Optional[str] = None,
    include_world_brief: bool = True,
    rewind: bool = True,
) -> Assembled:
    """Reassemble a turn's context through the real functions, ending in the
    REAL outgoing payload — not a harness reimplementation of it.

    Harness-plan Phase 0 correction: this used to build the persona half with
    `get_system_prompt`, the ~14,000-char pre-"harness rebuild Phase 5"
    function, and then hand-concatenate every section into one system-message
    string. Production's local chat lane has not built its payload that way
    since Phase 5 (persona) and the living-world-context plan (final
    payload): it calls `build_chat_system_prompt` for a cache-stable persona
    prefix, and `app.services.chat_assembly.assemble_local_provider_messages`
    — a pure, independently-tested function — for the actual
    `[stable system][live-context-wrapped last user turn]` message list. This
    now calls both of those, so a replay's payload is the same shape a real
    turn's payload is, not merely a same-length approximation of it.

    Mirrors chat_stream's build order: tool selection, stable persona prompt
    (now tool-name-aware, matching production), the singular-context block
    (snapshot + intent graph + extended signals + recall), the world brief,
    the per-turn slices (life facts, directives, scratchpad, interoception,
    recency floor), world_state_core, and a dialogue-state block built from
    this turn's own message (no multi-turn history is modeled by this
    fixture format — see the module docstring and `SECTION_GAPS`, which
    lists what chat_stream appends that this function still does not).
    """
    replay_database_url()

    from app.db.base import SessionLocal
    from app.db.session import get_async_session_factory

    install_fixture_briefs()
    if rewind:
        rewind_to(at)
    else:
        flush_replay_caches()

    sections: dict[str, str] = {}
    started = time.monotonic()

    with frozen_clock(at) as now_et:
        db = SessionLocal()
        try:
            import hashlib as _hashlib

            from app.main_simple import (
                ASSISTANT_NAME, load_soul_for_prompt, format_prompt_datetime_line,
                LIVE_CONTEXT_CHAR_BUDGET,
            )
            from app.prompts.chat_system_prompt import build_chat_system_prompt
            from app.services.tool_retrieval import tool_names as _names_of_tools
            from app.services.context_snapshot import (
                get_context_snapshot_cached, get_extended_signals,
                render_engaged_context, should_skip_recall,
            )
            from app.services.memory_recall import recall as memory_recall, ALL_KINDS
            from app.services.intent_graph_projection import get_intent_graph
            from app.services.world_state.chat_facts import render_world_state_core
            from app.services.dialogue_state import build_dialogue_state, render_dialogue_state_block
            from app.services.chat_assembly import assemble_local_provider_messages, WORLD_BRIEF_MARKER
            from app.schemas.chat import ChatMessage
            from app.services.context_router import (
                classify_conversation_mode, AMBIENT_SUPPRESS_MODES, has_active_urgent_alert,
            )

            # Personal-conversation remediation plan (2026-09-23), step 2 —
            # mirrors chat_stream's own conversation_mode gate so a replay
            # shows the same suppressed/unsuppressed payload production
            # would build, not the pre-fix unconditional one.
            conversation_mode = classify_conversation_mode(message)
            suppress_ambient = conversation_mode in AMBIENT_SUPPRESS_MODES
            if suppress_ambient and has_active_urgent_alert(db, user_id):
                suppress_ambient = False
            sections["conversation_mode"] = (
                f"[replay: conversation_mode={conversation_mode}, "
                f"suppress_ambient={suppress_ambient}]"
            )

            # `select_tools` classifies via `get_tool_intent_classifier()`, a
            # module-level singleton that remembers "sticky" categories per
            # session_id across calls (by design — a real conversation's
            # tool selection should drift, not reset every turn). Each
            # fixture Turn is an INDEPENDENT moment, not a continuation of
            # the previous Turn replayed in the same test run, so reusing
            # one constant session_id across `assemble()` calls (as an
            # earlier version of this function did implicitly, by never
            # calling select_tools at all before persona-prompt time) would
            # leak one turn's classified categories into the next one's tool
            # list and, downstream, into `build_chat_system_prompt`'s tool
            # names. Deriving a per-(message, at) id keeps a given turn
            # reproducible across repeated calls while never sharing state
            # with a different turn — verified via the sticky-category
            # regression this caused before the derivation was added.
            _session_id = session_id or f"replay-{_hashlib.sha1((message + at.isoformat()).encode()).hexdigest()[:16]}"
            tools = select_tools(message, _session_id)
            soul_content = load_soul_for_prompt(db)
            stable_system_prompt = build_chat_system_prompt(
                ASSISTANT_NAME, soul_content, _names_of_tools(tools),
            )
            sections["system_prompt"] = stable_system_prompt
            datetime_line = format_prompt_datetime_line(now_et)
            sections["datetime_line"] = datetime_line

            snapshot = await get_context_snapshot_cached(db, user_id)
            open_intents = get_intent_graph(db, user_id)["total"]
            extended = await get_extended_signals(db, user_id, message)

            traces: list[dict] = []
            if not should_skip_recall(message):
                recalled = await memory_recall(
                    user_id=user_id, query=message, k=5,
                    kinds=[k for k in ALL_KINDS if k != "fact"],
                )
                traces = recalled.get("traces") or []

            sections["engaged_context"] = render_engaged_context(
                snapshot, open_intents, traces, extended=extended,
                conversation_mode=conversation_mode if suppress_ambient else None,
            )

            world_brief = ""
            if include_world_brief and not suppress_ambient:
                try:
                    from app.services.world_brief import get_rendered_brief
                    factory = get_async_session_factory()
                    async with factory() as adb:
                        world_brief = await get_rendered_brief(adb, user_id) or ""
                except Exception as e:  # a missing brief is data, not a crash
                    world_brief = ""
                    sections["world_brief"] = f"[replay: world brief unavailable — {e}]"
            sections.setdefault("world_brief", world_brief)

            for name, loader in _PER_TURN_SLICES.items():
                try:
                    sections[name] = await loader(db, user_id) or ""
                except Exception as e:
                    sections[name] = f"[replay: {name} unavailable — {e}]"

            try:
                world_state_core = render_world_state_core(
                    db, user_id,
                    conversation_mode=conversation_mode if suppress_ambient else None,
                )
            except Exception as e:
                world_state_core = ""
                sections["world_state_core"] = f"[replay: world_state_core unavailable — {e}]"
            else:
                sections["world_state_core"] = world_state_core

            # No multi-turn history is modeled by this fixture format (see
            # the module docstring): dialogue_state is built from just this
            # turn's own message, same as it would be for the first turn of
            # a real conversation.
            dialogue_messages = [{"role": "user", "content": message}]
            dialogue_state = build_dialogue_state(dialogue_messages)
            dialogue_block = render_dialogue_state_block(dialogue_state)
            sections["dialogue_block"] = dialogue_block

            # Build `full_sys` the way chat_stream does: stable prompt, then
            # engaged context, then the world brief under its production
            # marker, then the remaining per-turn slices. The exact byte
            # order of the appended-after-persona sections does not change
            # the final payload — `assemble_local_provider_messages` locates
            # `stable_system_prompt` and the WORLD_BRIEF_MARKER-prefixed
            # brief as substrings and reallocates everything else through
            # `allocate_live_context_sections` regardless of where it sat.
            full_sys = stable_system_prompt + "\n\n" + sections["engaged_context"]
            if world_brief:
                full_sys += WORLD_BRIEF_MARKER + world_brief
            for name in ("life_facts", "directives", "scratchpad", "interoception", "recency_floor"):
                body = sections.get(name) or ""
                if body:
                    full_sys += "\n\n" + body

            conversation_history: list[ChatMessage] = []
            merged_request_messages = [ChatMessage(role="user", content=message)]

            result = assemble_local_provider_messages(
                full_sys=full_sys,
                stable_system_prompt=stable_system_prompt,
                conversation_history=conversation_history,
                merged_request_messages=merged_request_messages,
                dialogue_block=dialogue_block,
                world_state_core=world_state_core,
                world_brief=world_brief,
                datetime_line=datetime_line,
                live_context_char_budget=LIVE_CONTEXT_CHAR_BUDGET,
            )
        finally:
            db.close()

    text = "\n\n".join(body for body in sections.values() if body)
    return Assembled(
        text=text, sections=sections, seconds=time.monotonic() - started,
        recall_traces=traces,
        tools_offered=[t.get("function", {}).get("name") for t in tools],
        tool_schemas=tools,
        all_messages=result["all_messages"],
        stable_system_prompt=stable_system_prompt,
        stable_system_prompt_sha256=_hashlib.sha256(stable_system_prompt.encode()).hexdigest(),
        conversation_mode=conversation_mode,
        suppress_ambient=suppress_ambient,
    )


@dataclass
class Response:
    """A replayed turn, model and all."""
    text: str
    assembled: Assembled
    tools: ToolLog
    writes: WriteLedger
    seconds: float

    def called(self, name: str) -> bool:
        return bool(self.tools.named(name))


def select_tools(message: str, session_id: str = "replay") -> list[dict]:
    """The tool list chat_stream would offer for this message.

    Mirrors the non-work-mode path: intent classification, then the presence
    diet (core names + sticky categories) when PRESENCE_TOOL_DIET is on,
    then the background-dispatch policy.
    """
    from app.main_simple import (
        _PRESENCE_CORE_TOOL_NAMES, _apply_background_dispatch_policy,
        get_tool_intent_classifier,
    )
    from app.tools.registry import tool_registry
    from app.core.feature_flags import Flag, is_enabled

    _, categories = get_tool_intent_classifier().classify_with_context(message, session_id)
    if is_enabled(Flag.PRESENCE_TOOL_DIET):
        selected = tool_registry.get_tools_by_names(_PRESENCE_CORE_TOOL_NAMES)
        for category in sorted(categories or []):
            in_category = tool_registry.get_tools_by_categories([category])
            in_category.sort(key=lambda t: t.get("function", {}).get("name") or "")
            selected += in_category
    elif categories:
        selected = tool_registry.get_tools_by_categories(list(categories))
    else:
        selected = tool_registry.get_tools_by_categories(
            ["memory", "notes", "time", "devices", "vm_agents", "personal_knowledge", "inbox"])

    deduped, seen = [], set()
    for tool in selected:
        name = tool.get("function", {}).get("name")
        if name and name not in seen:
            seen.add(name)
            deduped.append(tool)
    return _apply_background_dispatch_policy(deduped, message)


async def respond(
    message: str,
    at: datetime,
    *,
    user_id: str = REPLAY_USER_ID,
    conversation_id: Optional[str] = None,
    canned_tools: Optional[dict[str, Any]] = None,
    model: Optional[str] = None,
) -> Response:
    """Assemble the turn and actually ask the model, with writes intercepted.

    This calls the live model lane — it is the only way to answer questions
    like "does she still log a planned dinner", which are questions about
    behaviour, not about rendering. Slow and stochastic; the tests that use
    it say so and repeat themselves.
    """
    replay_database_url()
    assembled = await assemble(message, at, user_id=user_id, session_id=conversation_id or "replay")

    started = time.monotonic()
    with frozen_clock(at):
        with write_ledger() as writes:
            with intercepted_tools(canned_tools) as tool_log:
                from app.main_simple import SimpleLLMClient
                client = SimpleLLMClient()
                # The exact payload `assemble()` built via
                # `assemble_local_provider_messages` — same function, same
                # shape production sends on the local chat lane.
                messages = assembled.all_messages
                # ephemeral=False on purpose: the episode/memory writes a real
                # turn performs are part of what a replay is meant to show,
                # and they land in the disposable replay database where the
                # ledger can count them.
                text = await client.chat_with_tools(
                    messages, assembled.tool_schemas, user_id,
                    conversation_id=conversation_id, model=model, ephemeral=False,
                )
    return Response(text=text or "", assembled=assembled, tools=tool_log,
                    writes=writes, seconds=time.monotonic() - started)


async def _life_facts(db, user_id: str) -> str:
    from app.services.life_facts import get_life_facts_summary
    return await get_life_facts_summary(user_id)


async def _directives(db, user_id: str) -> str:
    from app.services.directives import get_directives_for_context
    return await get_directives_for_context(user_id)


async def _scratchpad(db, user_id: str) -> str:
    from app.services.scratchpad import get_scratchpad_for_context
    return await get_scratchpad_for_context(user_id)


async def _interoception(db, user_id: str) -> str:
    from app.services.interoception import build_interoception_header
    return await build_interoception_header(user_id)


async def _recency_floor(db, user_id: str) -> str:
    from app.services.recency_buffer import build_recency_floor
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as adb:
        return await build_recency_floor(adb, user_id)


_PER_TURN_SLICES: dict[str, Callable] = {
    "life_facts": _life_facts,
    "directives": _directives,
    "scratchpad": _scratchpad,
    "interoception": _interoception,
    "recency_floor": _recency_floor,
}
