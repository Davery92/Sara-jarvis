from typing import Optional
from fastapi import Depends, HTTPException, status, Cookie
from sqlalchemy.orm import Session
from app.core.auth import verify_token
from app.db.session import get_db
from app.models.user import User


async def get_current_user(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
) -> User:
    """Get the current authenticated user from JWT cookie"""
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not access_token:
        raise credentials_exception
    
    payload = verify_token(access_token)
    if payload is None:
        raise credentials_exception
    
    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    
    return user


async def get_current_user_optional(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get the current user if authenticated, otherwise None"""
    try:
        return await get_current_user(access_token, db)
    except HTTPException:
        return None