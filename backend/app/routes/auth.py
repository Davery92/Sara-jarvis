"""Authentication routes."""
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import UserCreate, UserLogin, UserResponse
from app.core.auth import create_access_token, get_cookie_domain
from app.core.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup", response_model=UserResponse)
async def signup(
    user_data: UserCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
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
        created_at=user.created_at.isoformat()
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
    db: Session = Depends(get_db)
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
async def get_me(current_user: User = Depends(get_current_user)):
    """Get the current authenticated user's information."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at.isoformat()
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
