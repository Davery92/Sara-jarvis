"""
Security Utilities

Provides security features:
- Rate limiting
- CSRF protection
- Request validation
- Security headers
"""

from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from typing import Optional, Dict, Callable
import time
from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import secrets
import logging

logger = logging.getLogger(__name__)

# ==========================================
# RATE LIMITING
# ==========================================

class RateLimiter:
    """
    Simple in-memory rate limiter
    For production, use Redis-based rate limiting
    """

    def __init__(self):
        self.requests: Dict[str, list] = defaultdict(list)
        self.cleanup_interval = 60  # Cleanup old entries every 60 seconds
        self.last_cleanup = time.time()

    def _cleanup(self):
        """Remove old entries"""
        if time.time() - self.last_cleanup > self.cleanup_interval:
            current_time = time.time()
            for key in list(self.requests.keys()):
                self.requests[key] = [
                    req_time for req_time in self.requests[key]
                    if current_time - req_time < 3600  # Keep last hour
                ]
                if not self.requests[key]:
                    del self.requests[key]
            self.last_cleanup = current_time

    def is_rate_limited(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> bool:
        """
        Check if rate limit exceeded

        Args:
            key: Unique identifier (IP, user_id, etc.)
            max_requests: Maximum requests allowed
            window_seconds: Time window in seconds

        Returns:
            True if rate limited, False otherwise
        """
        self._cleanup()

        current_time = time.time()
        window_start = current_time - window_seconds

        # Filter requests within window
        recent_requests = [
            req_time for req_time in self.requests[key]
            if req_time > window_start
        ]

        if len(recent_requests) >= max_requests:
            return True

        # Add current request
        self.requests[key].append(current_time)
        return False

    def get_retry_after(self, key: str, window_seconds: int) -> int:
        """Get seconds until rate limit resets"""
        if not self.requests[key]:
            return 0

        oldest_request = min(self.requests[key])
        reset_time = oldest_request + window_seconds
        return max(0, int(reset_time - time.time()))


# Global rate limiter instance
rate_limiter = RateLimiter()


def rate_limit(max_requests: int = 60, window_seconds: int = 60):
    """
    Decorator for rate limiting endpoints

    Usage:
        @app.post("/chat")
        @rate_limit(max_requests=30, window_seconds=60)
        async def chat(request: Request, ...):
            ...
    """
    def decorator(func: Callable):
        async def wrapper(request: Request, *args, **kwargs):
            # Use IP address as key (can customize per endpoint)
            client_ip = request.client.host if request.client else "unknown"
            key = f"rate_limit:{client_ip}:{request.url.path}"

            if rate_limiter.is_rate_limited(key, max_requests, window_seconds):
                retry_after = rate_limiter.get_retry_after(key, window_seconds)

                logger.warning(
                    f"Rate limit exceeded",
                    extra={
                        "client_ip": client_ip,
                        "path": request.url.path,
                        "retry_after": retry_after
                    }
                )

                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Retry after {retry_after} seconds",
                    headers={"Retry-After": str(retry_after)}
                )

            return await func(request, *args, **kwargs)

        return wrapper
    return decorator


# ==========================================
# SECURITY HEADERS MIDDLEWARE
# ==========================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # CSP header (adjust for your needs)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'"
        )

        return response


# ==========================================
# CSRF PROTECTION
# ==========================================

class CSRFProtection:
    """
    CSRF token generation and validation
    For state-changing operations (POST, PUT, DELETE)
    """

    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    def generate_token(self, session_id: str) -> str:
        """Generate CSRF token for session"""
        # Create token: hash(session_id + secret + timestamp)
        timestamp = str(int(time.time()))
        data = f"{session_id}{self.secret_key}{timestamp}"
        token_hash = hashlib.sha256(data.encode()).hexdigest()
        return f"{timestamp}.{token_hash}"

    def validate_token(
        self,
        token: str,
        session_id: str,
        max_age_seconds: int = 3600
    ) -> bool:
        """Validate CSRF token"""
        try:
            timestamp_str, token_hash = token.split(".")
            timestamp = int(timestamp_str)

            # Check if token expired
            if time.time() - timestamp > max_age_seconds:
                return False

            # Recreate token and compare
            data = f"{session_id}{self.secret_key}{timestamp_str}"
            expected_hash = hashlib.sha256(data.encode()).hexdigest()

            return secrets.compare_digest(expected_hash, token_hash)

        except (ValueError, AttributeError):
            return False


# CSRF instance (initialize with secret from config)
csrf_protection = None


def get_csrf_protection():
    """Get CSRF protection instance"""
    global csrf_protection
    if csrf_protection is None:
        from app.core.config import settings
        csrf_protection = CSRFProtection(settings.jwt_secret)
    return csrf_protection


def require_csrf_token(request: Request):
    """Dependency to require CSRF token for state-changing operations"""
    # Skip for GET, HEAD, OPTIONS
    if request.method in ["GET", "HEAD", "OPTIONS"]:
        return

    # Get token from header
    csrf_token = request.headers.get("X-CSRF-Token")
    if not csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing"
        )

    # Get session ID from cookie/header
    session_id = request.cookies.get("session_id") or "default"

    # Validate token
    csrf = get_csrf_protection()
    if not csrf.validate_token(csrf_token, session_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token"
        )


# ==========================================
# REQUEST VALIDATION
# ==========================================

class RequestValidator:
    """Validate common request patterns"""

    @staticmethod
    def validate_content_type(request: Request, expected: str = "application/json"):
        """Validate request content type"""
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith(expected):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Expected content-type: {expected}"
            )

    @staticmethod
    def validate_content_length(request: Request, max_bytes: int = 10_000_000):
        """Validate request content length (10MB default)"""
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Request too large. Max: {max_bytes} bytes"
            )

    @staticmethod
    def sanitize_string(text: str, max_length: int = 10000) -> str:
        """Sanitize user input string"""
        # Remove null bytes
        text = text.replace("\x00", "")

        # Trim to max length
        if len(text) > max_length:
            text = text[:max_length]

        return text.strip()


# ==========================================
# IP-BASED ACCESS CONTROL
# ==========================================

class IPWhitelist:
    """Simple IP whitelist/blacklist"""

    def __init__(self):
        self.whitelist: set = set()
        self.blacklist: set = set()

    def add_to_whitelist(self, ip: str):
        """Add IP to whitelist"""
        self.whitelist.add(ip)

    def add_to_blacklist(self, ip: str):
        """Add IP to blacklist"""
        self.blacklist.add(ip)

    def is_allowed(self, ip: str) -> bool:
        """Check if IP is allowed"""
        # Blacklist takes precedence
        if ip in self.blacklist:
            return False

        # If whitelist is empty, allow all (except blacklisted)
        if not self.whitelist:
            return True

        # Check whitelist
        return ip in self.whitelist


# Global IP whitelist instance
ip_whitelist = IPWhitelist()


def require_whitelisted_ip(request: Request):
    """Dependency to require whitelisted IP"""
    client_ip = request.client.host if request.client else "unknown"

    if not ip_whitelist.is_allowed(client_ip):
        logger.warning(f"Blocked request from non-whitelisted IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )


# ==========================================
# EXAMPLE USAGE
# ==========================================

"""
from app.core.security import (
    rate_limit,
    require_csrf_token,
    SecurityHeadersMiddleware
)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Rate limited endpoint
@app.post("/chat")
@rate_limit(max_requests=30, window_seconds=60)
async def chat(request: Request, ...):
    ...

# CSRF protected endpoint
@app.post("/notes")
async def create_note(
    request: Request,
    csrf_check=Depends(require_csrf_token),
    ...
):
    ...

# Generate CSRF token for session
@app.get("/csrf-token")
async def get_csrf_token(request: Request):
    session_id = request.cookies.get("session_id", "default")
    csrf = get_csrf_protection()
    token = csrf.generate_token(session_id)
    return {"csrf_token": token}
"""
