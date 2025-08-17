from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from app.core.auth import create_access_token, verify_password, get_password_hash
from app.core.deps import get_current_user, get_current_user_optional
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

router = APIRouter()
security = HTTPBearer()


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: str


@router.post("/signup", response_model=UserResponse)
async def signup(user_data: UserCreate, db: Session = Depends(get_db)):
    """Create a new user account"""
    
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user
    hashed_password = get_password_hash(user_data.password)
    user = User(
        email=user_data.email,
        password_hash=hashed_password
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return UserResponse(
        id=str(user.id),
        email=user.email,
        created_at=user.created_at.isoformat()
    )


@router.post("/login", response_model=UserResponse)
async def login(user_data: UserLogin, response: Response, db: Session = Depends(get_db)):
    """Authenticate user and set JWT cookie"""
    
    # Find user
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    # Create access token
    access_token = create_access_token(data={"sub": str(user.id)})
    
    # Set secure HTTP-only cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
        max_age=settings.jwt_expire_hours * 3600  # Convert hours to seconds
    )
    
    return UserResponse(
        id=str(user.id),
        email=user.email,
        created_at=user.created_at.isoformat()
    )


@router.post("/logout")
async def logout(response: Response):
    """Logout user by clearing JWT cookie"""
    
    response.delete_cookie(
        key="access_token",
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite
    )
    
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        created_at=current_user.created_at.isoformat()
    )


@router.get("/check")
async def check_auth(current_user: User = Depends(get_current_user_optional)):
    """Check if user is authenticated"""
    
    if current_user:
        return {
            "authenticated": True,
            "user": {
                "id": str(current_user.id),
                "email": current_user.email
            }
        }
    else:
        return {"authenticated": False}