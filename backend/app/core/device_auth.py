"""Device-token auth — used by the Pi dashboard and notes-search fallback.

Pi dashboard devices send ``X-Device-Token`` instead of a login cookie.
This helper resolves the token to a user id, updating ``last_seen`` on
every hit so device inactivity shows up in the registration table.
"""

from typing import Optional

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db


async def get_device_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[str]:
    """Return the user_id attached to the ``X-Device-Token`` header, or None.

    Touching ``last_seen`` inline means any Pi that talks to us stays
    counted as alive; a silent Pi goes stale naturally in the admin view.
    """
    device_token = request.headers.get("X-Device-Token")
    if not device_token:
        return None

    result = db.execute(
        text(
            """
            SELECT user_id FROM device_registration
            WHERE device_token = :token
            """
        ),
        {"token": device_token},
    ).fetchone()
    if not result:
        return None

    db.execute(
        text(
            """
            UPDATE device_registration SET last_seen = NOW()
            WHERE device_token = :token
            """
        ),
        {"token": device_token},
    )
    db.commit()
    return result.user_id
