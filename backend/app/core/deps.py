from typing import Optional
from fastapi import Depends, HTTPException, status, Cookie, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.auth import verify_token
from app.db.session import get_db
from app.models.user import User


async def get_current_user(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
) -> User:
    """Get the current authenticated user from JWT cookie, Authorization header, or device token"""

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Try cookie first
    token = access_token

    # If no cookie, try Authorization header (for mobile apps)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix

    # If we have a JWT token, validate it
    if token:
        payload = verify_token(token)
        if payload is None:
            raise credentials_exception

        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception

        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise credentials_exception

        return user

    # Try device token as fallback (for iOS app)
    device_token = request.headers.get("X-Device-Token")
    if device_token:
        result = db.execute(text("""
            SELECT user_id FROM device_registration
            WHERE device_token = :token
        """), {"token": device_token}).fetchone()

        if result:
            # Update last_seen
            db.execute(text("""
                UPDATE device_registration SET last_seen = NOW()
                WHERE device_token = :token
            """), {"token": device_token})
            db.commit()

            user = db.query(User).filter(User.id == result[0]).first()
            if user:
                return user

    raise credentials_exception


async def get_streaming_user(
    request: Request,
    access_token: Optional[str] = Cookie(None),
) -> User:
    """Authenticate for a long-lived SSE/streaming endpoint WITHOUT holding a DB
    session open for the stream's lifetime.

    FastAPI keeps ``yield`` dependencies (get_db) alive until the response
    finishes; on an SSE stream that can be hours, and the auth SELECT's
    transaction sits idle until Postgres kills it ("idle-in-transaction
    timeout"). This opens its own short-lived session, resolves + detaches the
    user, and closes the session before the stream begins.
    """
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        user = await get_current_user(request=request, access_token=access_token, db=db)
        # Touch commonly-used attributes so they're loaded before we detach,
        # preventing a lazy-load from reopening a transaction mid-stream.
        _ = user.id
        _ = getattr(user, "email", None)
        try:
            db.expunge(user)
        except Exception:
            pass
        return user
    finally:
        db.close()


async def get_current_user_optional(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get the current user if authenticated, otherwise None"""
    try:
        return await get_current_user(request, access_token, db)
    except HTTPException:
        return None