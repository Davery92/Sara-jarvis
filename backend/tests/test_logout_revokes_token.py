"""Logout token revocation (Sara repair plan R11, evidence
A05_LOGOUT_DOES_NOT_REVOKE_TOKEN, and the 2026-09-25 review remediation of
the first version of this fix).

Confirmed mechanism: these JWTs are stateless (signature + exp only,
verified in `app.core.auth.verify_token`) and `/auth/logout` only ever
cleared the cookie — a bearer token captured before logout (returned raw to
mobile/API clients by `/auth/token` on purpose) stayed valid for its full
week-long lifetime regardless of logout.

The review flagged three problems with the first version of this fix,
covered here:
  1. Revocation was Redis-only and failed OPEN on any Redis error/outage —
     a revoked token could keep authenticating. Now backed by Postgres
     (`revoked_token`, a table this codebase already has a hard dependency
     on for every authenticated request), and fails CLOSED on a genuine
     store failure.
  2. Logout revoked BOTH the cookie token and the bearer token if both
     happened to be present on the request, contradicting its own
     documented "cookie-first precedence." Now revokes exactly the one
     token `get_current_user` would have resolved for this same request.
  3. Logout always returned "Successfully logged out" regardless of
     whether anything was actually revoked. Now reports truthfully:
     `revoked: bool` plus a specific `reason`.

`revoked_token` is a NEW table (alembic revision 156_revoked_token, not
applied to any running database as part of this repair session) —
self-provisioned here against the real disposable Postgres.
"""
import uuid

import pytest
from fastapi import Response

from app.core.auth import create_access_token, revoke_token, verify_token


@pytest.fixture(scope="module", autouse=True)
def _provision_table():
    from app.db.base import engine
    from app.models.revoked_token import RevokedToken
    RevokedToken.__table__.create(engine, checkfirst=True)
    yield


@pytest.fixture()
def db_session():
    from app.db.base import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def user_id(db_session):
    """A real app_user row — revoked_token.user_id has an FK to it."""
    from sqlalchemy import text
    uid = str(uuid.uuid4())
    db_session.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :email, 'x', NOW())
    """), {"id": uid, "email": f"{uid}@test.local"})
    db_session.commit()
    yield uid
    db_session.execute(text("DELETE FROM revoked_token WHERE user_id = :id"), {"id": uid})
    db_session.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": uid})
    db_session.commit()


class _FakeRequest:
    """Duck-typed stand-in for fastapi.Request — the real `logout()` route
    only ever calls `.cookies.get(...)` and `.headers.get(...)` on it."""

    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}


class TestTokenRevocation:
    def test_a_token_works_before_logout(self, user_id):
        token = create_access_token(data={"sub": user_id})
        assert verify_token(token) is not None

    def test_revoking_a_token_makes_it_fail_verification(self, user_id):
        token = create_access_token(data={"sub": user_id})
        assert verify_token(token) is not None

        result = revoke_token(token)
        assert result.revoked is True
        assert result.reason == "revoked"
        assert verify_token(token) is None

    def test_a_different_tokens_session_is_unaffected(self, user_id):
        """Revoking one token must not invalidate a DIFFERENT token for the
        same (or another) user — each issuance gets its own jti."""
        token_a = create_access_token(data={"sub": user_id})
        token_b = create_access_token(data={"sub": user_id})

        revoke_token(token_a)

        assert verify_token(token_a) is None
        assert verify_token(token_b) is not None

    def test_an_invalid_token_cannot_be_revoked_and_reports_so(self):
        result = revoke_token("not-a-real-jwt")
        assert result.revoked is False
        assert result.reason == "invalid_token"

    def test_every_issued_token_carries_a_distinct_jti(self, user_id):
        from jose import jwt as _jwt
        from app.core.config import settings

        t1 = create_access_token(data={"sub": user_id})
        t2 = create_access_token(data={"sub": user_id})
        p1 = _jwt.decode(t1, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        p2 = _jwt.decode(t2, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert p1["jti"] and p2["jti"]
        assert p1["jti"] != p2["jti"]

    def test_revocation_survives_a_fresh_db_session(self, user_id):
        """Durability check: revocation must be readable from a BRAND NEW
        session/connection, not just whatever session happened to write
        it — proves this isn't process-local or connection-local state."""
        token = create_access_token(data={"sub": user_id})
        revoke_token(token)

        from app.db.base import SessionLocal
        fresh_session = SessionLocal()
        try:
            assert verify_token(token, db=fresh_session) is None
        finally:
            fresh_session.close()

    def test_a_double_logout_of_the_same_token_does_not_error(self, user_id):
        """ON CONFLICT DO NOTHING — a double-submitted logout must not
        raise, and the token stays revoked either way."""
        token = create_access_token(data={"sub": user_id})
        first = revoke_token(token)
        second = revoke_token(token)
        assert first.revoked is True
        assert second.revoked is True  # idempotent — not an error, still reports revoked
        assert verify_token(token) is None

    def test_revocation_check_fails_closed_on_a_store_error(self, monkeypatch, user_id):
        """The corrected behavior from the review: a revocation check that
        cannot run must refuse the token, not silently let it through —
        unlike the first version's Redis fail-open design."""
        import app.core.auth as auth_mod

        token = create_access_token(data={"sub": user_id})
        assert verify_token(token) is not None  # sanity: works before the simulated outage

        def _broken_own_db_session():
            raise RuntimeError("simulated Postgres outage")

        monkeypatch.setattr(auth_mod, "_own_db_session", _broken_own_db_session)
        assert verify_token(token) is None  # fails closed, not open


class TestLogoutRouteRevokesTheActualTokenInUse:
    @pytest.mark.asyncio
    async def test_logout_with_a_cookie_token_revokes_it_and_reports_truthfully(self, db_session, user_id):
        from app.routes.auth import logout

        token = create_access_token(data={"sub": user_id})
        assert verify_token(token) is not None

        request = _FakeRequest(cookies={"access_token": token}, headers={"host": "localhost"})
        response = Response()

        result = await logout(request, response, db=db_session)

        assert result["revoked"] is True
        assert result["reason"] == "revoked"
        assert verify_token(token) is None

    @pytest.mark.asyncio
    async def test_logout_with_a_bearer_token_revokes_it(self, db_session, user_id):
        """A mobile/API client authenticating via Authorization: Bearer
        (no cookie at all) must have ITS token revoked too — this is the
        exact A05 shape (token replayed after logout)."""
        from app.routes.auth import logout

        token = create_access_token(data={"sub": user_id})

        request = _FakeRequest(
            cookies={},
            headers={"host": "localhost", "Authorization": f"Bearer {token}"},
        )
        response = Response()

        result = await logout(request, response, db=db_session)
        assert result["revoked"] is True
        assert verify_token(token) is None

    @pytest.mark.asyncio
    async def test_logout_does_not_affect_an_unrelated_sessions_token(self, db_session, user_id):
        from app.routes.auth import logout

        this_session_token = create_access_token(data={"sub": user_id})
        other_session_token = create_access_token(data={"sub": user_id})

        request = _FakeRequest(cookies={"access_token": this_session_token}, headers={"host": "localhost"})
        response = Response()
        await logout(request, response, db=db_session)

        assert verify_token(this_session_token) is None
        assert verify_token(other_session_token) is not None

    @pytest.mark.asyncio
    async def test_when_both_cookie_and_bearer_are_present_only_the_cookie_precedence_token_is_revoked(
        self, db_session, user_id,
    ):
        """Review finding: the first version revoked BOTH tokens whenever
        both were present, contradicting its own documented cookie-first
        precedence — a mobile client's unrelated bearer token riding
        alongside a stale/different browser cookie could get invalidated
        by a request that was never actually authenticating with it.
        `get_current_user` resolves the COOKIE when both are present; this
        must revoke exactly that one and leave the OTHER, different token
        (the bearer one) untouched."""
        from app.routes.auth import logout

        cookie_token = create_access_token(data={"sub": user_id})
        different_bearer_token = create_access_token(data={"sub": user_id})

        request = _FakeRequest(
            cookies={"access_token": cookie_token},
            headers={"host": "localhost", "Authorization": f"Bearer {different_bearer_token}"},
        )
        response = Response()
        result = await logout(request, response, db=db_session)

        assert result["revoked"] is True
        assert verify_token(cookie_token) is None  # the one get_current_user would have used
        assert verify_token(different_bearer_token) is not None  # untouched — was never the active session here

    @pytest.mark.asyncio
    async def test_no_token_at_all_is_reported_truthfully_not_as_a_fake_success(self, db_session):
        from app.routes.auth import logout

        request = _FakeRequest(cookies={}, headers={"host": "localhost"})
        response = Response()
        result = await logout(request, response, db=db_session)

        assert result["revoked"] is False
        assert result["reason"] == "no_token_presented"

    @pytest.mark.asyncio
    async def test_a_legacy_token_with_no_jti_is_reported_truthfully(self, db_session, user_id):
        """A token issued before this fix existed (no jti claim) cannot be
        individually revoked — logout must say so, not claim success."""
        from jose import jwt as _jwt
        from datetime import datetime, timedelta, timezone as _tz
        from app.core.config import settings
        from app.routes.auth import logout

        legacy_token = _jwt.encode(
            {"sub": user_id, "exp": datetime.now(_tz.utc) + timedelta(hours=1)},
            settings.jwt_secret, algorithm=settings.jwt_algorithm,
        )

        request = _FakeRequest(cookies={"access_token": legacy_token}, headers={"host": "localhost"})
        response = Response()
        result = await logout(request, response, db=db_session)

        assert result["revoked"] is False
        assert result["reason"] == "no_jti_legacy_token"
