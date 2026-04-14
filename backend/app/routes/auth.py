"""Authentication routes."""
import logging
from typing import Optional
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import UserCreate, UserLogin, UserResponse, UserUpdate
from app.core.auth import create_access_token, get_cookie_domain
from app.core.deps import get_current_user
from app.core.security import rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


async def check_auth_rate_limit(request: Request):
    """Rate limit auth endpoints: 5 attempts per 5 minutes per IP."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"auth:{client_ip}"
    if rate_limiter.is_rate_limited(key, max_requests=5, window_seconds=300):
        retry_after = rate_limiter.get_retry_after(key, window_seconds=300)
        logger.warning(f"Auth rate limit exceeded for {client_ip}")
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Retry after {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


def _get_username(db: Session, user_id: str) -> Optional[str]:
    """Fetch display username from user_settings.preferences if available."""
    try:
        from app.models.user_settings import UserSettings as UserSettingsModel

        settings = db.query(UserSettingsModel).filter(
            UserSettingsModel.user_id == user_id
        ).first()
        if not settings:
            return None
        prefs = settings.preferences or {}
        username = prefs.get("username")
        if isinstance(username, str) and username.strip():
            return username.strip()
        return None
    except Exception:
        # Keep auth endpoints resilient if user_settings table is unavailable.
        return None


def _set_username(db: Session, user_id: str, username: Optional[str]) -> None:
    """Persist display username to user_settings.preferences."""
    from app.models.user_settings import UserSettings as UserSettingsModel

    settings = db.query(UserSettingsModel).filter(
        UserSettingsModel.user_id == user_id
    ).first()

    if not settings:
        settings = UserSettingsModel(user_id=user_id, preferences={})
        db.add(settings)

    prefs = dict(settings.preferences or {})
    if username and username.strip():
        prefs["username"] = username.strip()
    else:
        prefs.pop("username", None)
    settings.preferences = prefs


@router.post("/signup", response_model=UserResponse)
async def signup(
    user_data: UserCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _rate_limit=Depends(check_auth_rate_limit),
):
    """Register a new user account."""
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Hash password
    hashed_password = bcrypt.hashpw(
        user_data.password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    user = User(email=user_data.email, password_hash=hashed_password)
    db.add(user)
    db.commit()
    db.refresh(user)

    # Auto-login after signup
    access_token = create_access_token(data={"sub": user.id})
    cookie_domain = get_cookie_domain(request)

    # Detect if request is HTTPS
    is_secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    cookie_kwargs = {
        "key": "access_token",
        "value": access_token,
        "secure": is_secure,
        "httponly": True,
        "samesite": "lax",
        "max_age": 24 * 7 * 3600
    }
    if cookie_domain:
        cookie_kwargs["domain"] = cookie_domain
    response.set_cookie(**cookie_kwargs)

    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at.isoformat(),
        username=_get_username(db, user.id),
    )


@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """Alias for signup to support frontend client."""
    return await signup(user_data, request, response, db)


@router.post("/login", response_model=UserResponse)
async def login(
    user_data: UserLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _rate_limit=Depends(check_auth_rate_limit),
):
    """Authenticate user and return access token."""
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    # Verify password
    try:
        password_valid = bcrypt.checkpw(
            user_data.password.encode('utf-8'),
            user.password_hash.encode('utf-8')
        )
    except (ValueError, Exception):
        password_valid = False

    if not password_valid:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    access_token = create_access_token(data={"sub": user.id})
    cookie_domain = get_cookie_domain(request)

    # Detect if request is HTTPS
    is_secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    cookie_kwargs = {
        "key": "access_token",
        "value": access_token,
        "secure": is_secure,
        "httponly": True,
        "samesite": "lax",
        "max_age": 24 * 7 * 3600
    }
    if cookie_domain:
        cookie_kwargs["domain"] = cookie_domain
    response.set_cookie(**cookie_kwargs)

    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at.isoformat(),
        username=_get_username(db, user.id),
        access_token=access_token
    )


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Log out the current user by clearing the access token cookie."""
    cookie_domain = get_cookie_domain(request)
    if cookie_domain:
        response.delete_cookie(key="access_token", domain=cookie_domain)
    else:
        response.delete_cookie(key="access_token")
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the current authenticated user's information."""
    username = _get_username(db, current_user.id)

    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at.isoformat(),
        username=username,
    )


@router.put("/me", response_model=UserResponse)
async def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current user profile fields used by clients."""
    changed = False

    if payload.email is not None and payload.email != current_user.email:
        existing = db.query(User).filter(
            User.email == payload.email,
            User.id != current_user.id,
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        current_user.email = payload.email
        changed = True

    if payload.username is not None:
        try:
            _set_username(db, current_user.id, payload.username)
            changed = True
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to update username: {exc}")

    if changed:
        try:
            db.commit()
            db.refresh(current_user)
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to update user: {exc}")

    username = _get_username(db, current_user.id)
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at.isoformat(),
        username=username,
    )


@router.get("/token")
async def get_token(request: Request, current_user: User = Depends(get_current_user)):
    """Get the current access token (for sidecar configuration)."""
    token = request.cookies.get("access_token")
    if not token:
        # Check Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=401, detail="No token found")

    return {"access_token": token, "user_id": current_user.id}
