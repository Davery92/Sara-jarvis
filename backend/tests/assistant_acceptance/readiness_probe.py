"""Four-capability readiness probe for a (source snapshot, schema) pair.

A restart is only safe against a combination that actually serves requests. On
2026-09-27 production was a pair that could not: the on-disk tree needs
migrations 155-158 and the live schema was 154, so `auth._is_revoked` failed
closed (every request 401), `Reminder` queries raised UndefinedColumn, and
`claim_operation` failed closed (every chat write refused). `/health` returned
200 throughout — which is why this probe exists and why a health check is not a
substitute for it.

Run inside the api/backend container. Exit 0 only if all four checks pass, so it
works both as a recovery gate and as a post-deploy smoke test.

  python tests/assistant_acceptance/readiness_probe.py [<user_email>] [--keep] [-v]

IT WRITES TO THE DATABASE. Checks 3 and 4 create a note (and, if no user with
the probe email exists, one user row), then delete exactly what they created and
verify zero residue. Every write is reported in the DISCLOSURE block at the end,
whether or not it was cleaned up. `--keep` skips cleanup (for debugging) and says
so loudly. Nothing pre-existing is ever modified or deleted.

Corrections made 2026-09-27 after review of an earlier version of this file:
  * Check 1 was labelled "BOOTS". It does not boot anything — it verifies schema
    objects and ORM queryability against an already-running process. Renamed.
  * Check 3 passed on ZERO search hits while reporting "excerpt-shaped", which
    proved nothing: with no rows, the shape assertion never ran. It now seeds a
    uniquely-marked note, requires that notes_search actually finds it, and only
    then asserts the excerpt shape.
  * The earlier version created a user row and never removed it, so running it
    against production — which the deployment procedure asks for — would have
    left that row behind silently. It is now tracked, removed, and disclosed.
"""
import logging
import sys
import traceback
import urllib.error
import urllib.request
import uuid
from datetime import timedelta

logging.disable(logging.ERROR)

RESULTS = []
# Every row this probe creates, as (table, human description, cleaned_up?).
WRITES = []
KEEP = "--keep" in sys.argv
VERBOSE = "-v" in sys.argv
EMAIL = next((a for a in sys.argv[1:] if "@" in a), "readiness.probe@validation.invalid")
STATE = {}


def check(name):
    def deco(fn):
        try:
            RESULTS.append((name, True, fn()))
        except Exception as exc:
            RESULTS.append((name, False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:170]}"))
            if VERBOSE:
                traceback.print_exc()
        return fn
    return deco


@check("1. SCHEMA — required objects present and ORM models queryable")
def _schema():
    from sqlalchemy import text
    from app.db.session import engine
    with engine.connect() as c:
        rev = c.execute(text("select version_num from alembic_version")).scalar()
        missing = []
        for obj, q in (
            ("revoked_token", "select to_regclass('public.revoked_token')"),
            ("chat_pending_proposal", "select to_regclass('public.chat_pending_proposal')"),
            ("uq_action_receipt_idempotency_key",
             "select indexname from pg_indexes where indexname='uq_action_receipt_idempotency_key'"),
            ("reminder.notified_at",
             "select column_name from information_schema.columns "
             "where table_name='reminder' and column_name='notified_at'"),
        ):
            if c.execute(text(q)).scalar() is None:
                missing.append(obj)
    if missing:
        raise AssertionError(f"schema {rev} is missing: {', '.join(missing)}")
    from app.db.base import SessionLocal
    from app.models.reminder import Reminder, Timer
    db = SessionLocal()
    try:
        db.query(Reminder).limit(1).all()
        db.query(Timer).limit(1).all()
    finally:
        db.close()
    return f"alembic {rev}; all 4 required objects present; Reminder/Timer queryable"


@check("2. AUTHENTICATES — a real token validates end to end over HTTP")
def _auth():
    from app.core.auth import create_access_token, verify_token, _is_revoked
    from app.db.base import SessionLocal
    from app.models.user import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == EMAIL).first()
        if u:
            STATE["created_user"] = False
        else:
            u = User(id=str(uuid.uuid4()), email=EMAIL, password_hash="x" * 20)
            db.add(u)
            db.commit()
            db.refresh(u)
            STATE["created_user"] = True
            WRITES.append(["app_user", f"user {EMAIL}", False])
        STATE["user_id"] = str(u.id)
    finally:
        db.close()
    # The exact 2026-09-27 failure: a never-revoked jti reported as revoked.
    if _is_revoked(str(uuid.uuid4())) is not False:
        raise AssertionError("_is_revoked fails CLOSED — every request would 401")
    token = create_access_token({"sub": STATE["user_id"]}, expires_delta=timedelta(hours=2))
    if verify_token(token) is None:
        raise AssertionError("a freshly minted token does not validate")
    STATE["token"] = token
    req = urllib.request.Request(
        "http://localhost:8000/notes", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise AssertionError(f"GET /notes returned {r.status}")
    try:
        urllib.request.urlopen(urllib.request.Request(
            "http://localhost:8000/notes", headers={"Authorization": "Bearer bogus"}), timeout=30)
        raise AssertionError("a bogus token was ACCEPTED")
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403):
            raise AssertionError(f"bogus token gave {e.code}, expected 401/403")
    reused = "reused existing user" if not STATE["created_user"] else "created a probe user"
    return f"token mints, validates, authorizes GET /notes; bogus token refused ({reused})"


@check("3. WRITES A NOTE — and it is really in the database")
def _writes():
    import asyncio
    from sqlalchemy import text
    from app.db.session import engine
    from app.tools.notes import NotesCreateTool
    marker = f"readiness-probe-{uuid.uuid4().hex[:8]}"
    STATE["marker"] = marker
    res = asyncio.new_event_loop().run_until_complete(NotesCreateTool().execute(
        user_id=STATE["user_id"], title=f"Readiness probe {marker}",
        content=f"Written by readiness_probe.py. Marker: {marker}"))
    if not res.success:
        raise AssertionError(f"notes_create failed: {res.message}")
    WRITES.append(["note", f"note marked {marker}", False])
    with engine.connect() as c:
        found = c.execute(text("select count(*) from note where content like :m"),
                          {"m": f"%{marker}%"}).scalar()
    if found != 1:
        raise AssertionError(f"note not in the database after a successful write (found {found})")
    return f"notes_create wrote a row, confirmed by direct SELECT (marker {marker})"


@check("4. READS NOTES — search actually finds the note just written")
def _reads():
    """Non-vacuous by construction: it searches for the marker seeded by check 3,
    so a zero-hit result is a FAILURE rather than a silent pass."""
    import asyncio
    from app.tools.notes import NotesSearchTool
    marker = STATE.get("marker")
    if not marker:
        raise AssertionError("check 3 did not write a note, so retrieval cannot be verified")
    res = asyncio.new_event_loop().run_until_complete(
        NotesSearchTool().execute(user_id=STATE["user_id"], query=marker))
    if not res.success:
        raise AssertionError(f"notes_search failed: {res.message}")
    notes = (res.data or {}).get("notes", [])
    hit = next((n for n in notes if marker in (n.get("snippet") or "")), None)
    if hit is None:
        raise AssertionError(
            f"notes_search did not return the note it was pointed at "
            f"({len(notes)} hit(s), none containing the marker)")
    if "content" in hit:
        raise AssertionError("notes_search returned a full 'content' field, not an excerpt")
    if "snippet" not in hit:
        raise AssertionError("notes_search hit has no 'snippet' field")
    return f"notes_search found the seeded note among {len(notes)} hit(s), excerpt-shaped"


def cleanup():
    """Remove exactly what this probe created — nothing else."""
    if KEEP:
        return
    from sqlalchemy import text
    from app.db.session import engine
    marker = STATE.get("marker")
    with engine.connect() as c:
        if marker:
            c.execute(text("delete from note where content like :m"), {"m": f"%{marker}%"})
            for w in WRITES:
                if w[0] == "note":
                    w[2] = True
        if STATE.get("created_user") and STATE.get("user_id"):
            # Only the user THIS run created, and only once its note is gone.
            c.execute(text("delete from app_user where id = :i and email = :e"),
                      {"i": STATE["user_id"], "e": EMAIL})
            for w in WRITES:
                if w[0] == "app_user":
                    w[2] = True
        c.commit()
        residue = 0
        if marker:
            residue = c.execute(text("select count(*) from note where content like :m"),
                                {"m": f"%{marker}%"}).scalar()
    STATE["residue"] = residue


try:
    cleanup()
except Exception as exc:  # cleanup failure must be loud, not swallowed
    STATE["cleanup_error"] = f"{type(exc).__name__}: {exc}"

print("\nReadiness probe — (source snapshot, schema) pair")
print("=" * 74)
ok = True
for name, passed, detail in RESULTS:
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}\n         {detail}")
    ok &= passed
print("-" * 74)
print("  DISCLOSURE — database writes made by this probe:")
if not WRITES:
    print("         none")
for table, desc, cleaned in WRITES:
    print(f"         {table:14s} {desc}  ->  {'removed' if cleaned else 'STILL PRESENT'}")
if KEEP:
    print("         --keep was passed: NOTHING WAS CLEANED UP.")
if STATE.get("cleanup_error"):
    print(f"         CLEANUP FAILED: {STATE['cleanup_error']}")
elif not KEEP and STATE.get("residue") not in (None, 0):
    print(f"         WARNING: {STATE['residue']} probe note(s) still present")
print("=" * 74)
print("VERDICT:", "READY — this pair serves requests"
      if ok else "NOT READY — do not deploy or restart onto this pair")
sys.exit(0 if ok else 1)
