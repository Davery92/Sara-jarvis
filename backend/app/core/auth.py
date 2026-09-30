import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt
from passlib.context import CryptContext
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)

# R11 (Sara repair plan 2026-09-25, evidence A05_LOGOUT_DOES_NOT_REVOKE_TOKEN,
# and the 2026-09-25 review remediation of the first version of this fix):
# this app's JWTs are stateless (signature + exp only) — logout only ever
# cleared the cookie, so a bearer token captured before logout (the `/auth/
# token` endpoint hands the raw token to mobile/API clients on purpose)
# stayed valid for its full week-long lifetime regardless. Every token now
# carries a per-issuance `jti`; logging out (`revoke_token`) records that
# jti in the DURABLE `revoked_token` Postgres table (moved off the first
# version's Redis-only, fail-open design — see that table's module
# docstring for why). This revokes THIS ONE SESSION's token, not every
# device's — a separate "log out everywhere" is not implemented (not
# evidenced, would be a new feature, not this defect's repair).


class RevokeResult:
    """Truthful outcome of a revoke_token() call — logout() reports this
    to the caller instead of a blanket 'Successfully logged out' regardless
    of whether anything was actually revoked."""
    __slots__ = ("revoked", "reason")

    def __init__(self, revoked: bool, reason: str):
        self.revoked = revoked
        self.reason = reason  # "revoked" | "no_jti_legacy_token" | "already_expired" | "invalid_token" | "store_unavailable"


def _own_db_session():
    from app.db.session import get_db
    gen = get_db()
    return next(gen), gen


def revoke_token(token: str, db: Optional[Session] = None) -> RevokeResult:
    """Revoke one issued token so `verify_token` refuses it from now on.

    `db` is optional — callers that already have a session open (routes
    with `db: Session = Depends(get_db)`) should pass it to avoid opening a
    second one; callers without one get a short-lived session opened and
    closed internally.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:
        return RevokeResult(False, "invalid_token")

    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti or not exp:
        logger.info("Logout: token has no jti — issued before session revocation existed; cannot be individually revoked, will expire naturally")
        return RevokeResult(False, "no_jti_legacy_token")

    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return RevokeResult(False, "already_expired")  # nothing to revoke

    owns_session = db is None
    try:
        # Opening the session itself can fail (e.g. Postgres genuinely
        # unreachable) — this must land in the SAME except below as a
        # query failure, not raise uncaught past this function. An
        # earlier version of this fix opened the session BEFORE the
        # try/except and let exactly this case propagate unhandled.
        if owns_session:
            db, _ = _own_db_session()
        db.execute(text("""
            INSERT INTO revoked_token (jti, user_id, expires_at)
            VALUES (:jti, :user_id, :expires_at)
            ON CONFLICT (jti) DO NOTHING
        """), {"jti": jti, "user_id": payload.get("sub"), "expires_at": expires_at})
        db.commit()
        return RevokeResult(True, "revoked")
    except Exception as e:
        # Durable store unavailable (Postgres down) — this is a hard
        # dependency failure, not a soft "Redis cache miss": the whole app
        # is already unusable in this condition (every authenticated
        # request needs Postgres for the User lookup too), so there is no
        # "fail open silently" trade-off being made here, only an honest
        # report that revocation could not be recorded.
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
        logger.error(f"Failed to record token revocation (Postgres unavailable?): {e}")
        return RevokeResult(False, "store_unavailable")
    finally:
        if owns_session and db is not None:
            db.close()


def _is_revoked(jti: Optional[str], db: Optional[Session] = None) -> bool:
    if not jti:
        return False
    owns_session = db is None
    try:
        # See revoke_token's matching comment: opening the session itself
        # must be inside this try, not before it.
        if owns_session:
            db, _ = _own_db_session()
        row = db.execute(text("""
            SELECT 1 FROM revoked_token WHERE jti = :jti AND expires_at > NOW()
        """), {"jti": jti}).fetchone()
        return row is not None
    except Exception as e:
        # A revocation check that cannot run must fail CLOSED, not open —
        # this is the corrected behavior from the review remediation. It
        # is safe to fail closed here because Postgres being unreachable
        # already means every OTHER authenticated request is failing too
        # (get_current_user's own User lookup needs the same database) —
        # unlike the first version's Redis-only design, this introduces no
        # new single point of failure the rest of the app didn't already have.
        logger.error(f"Revocation check failed (Postgres unavailable?) — failing closed: {e}")
        return True
    finally:
        if owns_session and db is not None:
            db.close()


def get_cookie_domain(request: Request) -> Optional[str]:
    """Determine the appropriate cookie domain based on the request host."""
    host = request.headers.get("host", "")
    # Check if host is avery.cloud or any subdomain
    if host.endswith("avery.cloud") or "avery.cloud:" in host:
        return ".avery.cloud"
    else:
        # For local development, don't set a domain (defaults to current host)
        return None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)

    # R11: a per-issuance id, so this ONE token (and only this one) can
    # later be individually revoked at logout without needing a stateful
    # session table for every request's hot path.
    to_encode.update({"exp": expire, "jti": str(uuid.uuid4())})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded_jwt


def verify_token(token: str, db: Optional[Session] = None) -> Optional[dict]:
    """Verify a JWT token and return payload.

    `db` is optional, same contract as `revoke_token` — pass an existing
    session when the caller already has one open (e.g. `get_current_user`),
    to avoid a second connection on every authenticated request.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:
        return None
    # R11 (evidence A05_LOGOUT_DOES_NOT_REVOKE_TOKEN): a signature- and
    # exp-valid token that was explicitly logged out must still be refused.
    if _is_revoked(payload.get("jti"), db=db):
        return None
    return payload


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)
