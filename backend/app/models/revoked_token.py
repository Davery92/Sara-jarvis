"""R11 review remediation (Sara repair plan 2026-09-25): durable session
revocation.

The first version of this fix stored revocations in Redis only, and
`_is_revoked` failed OPEN on any Redis error — meaning a revoked token
could keep authenticating for the duration of a Redis outage or restart
(this app's Redis has no guaranteed persistence config asserted anywhere
in this repo, so a restart is a real, not hypothetical, loss scenario).
That is not an acceptable outage/restart behavior for a security control.

Moved to Postgres — already a HARD dependency for every authenticated
request (`get_current_user` already queries the `User` row from it on
every call), so making revocation durable here introduces no NEW single
point of failure: if Postgres is unreachable, authentication was already
completely down regardless of this table.
"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.sql import func

from app.db.base import Base


class RevokedToken(Base):
    __tablename__ = "revoked_token"

    # Primary key IS the token's jti — a revoke of the same jti twice
    # (e.g. a double-submitted logout) is a natural no-op via
    # INSERT ... ON CONFLICT DO NOTHING, not a second row.
    jti = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    revoked_at = Column(DateTime(timezone=True), server_default=func.now())
    # Mirrors the JWT's own `exp` — a cheap, periodic
    # `DELETE FROM revoked_token WHERE expires_at < NOW()` (not scheduled
    # here; this table stays tiny in practice since revocation is only a
    # deliberate logout, not a per-request event) keeps this from growing
    # unbounded without ever needing a row to individually self-expire the
    # way the Redis TTL used to provide for free.
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
