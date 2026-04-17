"""
Error Handling Middleware and Custom Exceptions

Provides centralized error handling for the Sara Hub API:
- Global exception handlers
- Custom exception classes
- Structured error responses
- Request/response logging
"""

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError
import logging
from typing import Union, Dict, Any
from datetime import datetime, timezone
import traceback

logger = logging.getLogger(__name__)


# ==========================================
# CUSTOM EXCEPTIONS
# ==========================================

class SaraHubException(Exception):
    """Base exception for all Sara Hub custom exceptions"""
    def __init__(self, message: str, status_code: int = 500, details: Dict[str, Any] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class MemoryServiceError(SaraHubException):
    """Memory service operation failed"""
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, status_code=500, details=details)


class AuthenticationError(SaraHubException):
    """Authentication failed"""
    def __init__(self, message: str = "Authentication failed", details: Dict[str, Any] = None):
        super().__init__(message, status_code=401, details=details)


class AuthorizationError(SaraHubException):
    """User not authorized to access resource"""
    def __init__(self, message: str = "Not authorized", details: Dict[str, Any] = None):
        super().__init__(message, status_code=403, details=details)


class ResourceNotFoundError(SaraHubException):
    """Requested resource not found"""
    def __init__(self, resource_type: str, resource_id: str, details: Dict[str, Any] = None):
        message = f"{resource_type} with id '{resource_id}' not found"
        super().__init__(message, status_code=404, details=details)


class ValidationError(SaraHubException):
    """Request data validation failed"""
    def __init__(self, message: str, field: str = None, details: Dict[str, Any] = None):
        details = details or {}
        if field:
            details["field"] = field
        super().__init__(message, status_code=422, details=details)


class ExternalServiceError(SaraHubException):
    """External service (LLM, embedding, etc.) unavailable"""
    def __init__(self, service_name: str, details: Dict[str, Any] = None):
        message = f"External service '{service_name}' unavailable"
        super().__init__(message, status_code=502, details=details)


class RateLimitError(SaraHubException):
    """Rate limit exceeded"""
    def __init__(self, retry_after: int = 60, details: Dict[str, Any] = None):
        message = f"Rate limit exceeded. Retry after {retry_after} seconds"
        details = details or {}
        details["retry_after"] = retry_after
        super().__init__(message, status_code=429, details=details)


# ==========================================
# ERROR RESPONSE FORMATTER
# ==========================================

def format_error_response(
    status_code: int,
    message: str,
    error_type: str = "error",
    details: Dict[str, Any] = None,
    request: Request = None
) -> Dict[str, Any]:
    """
    Format consistent error response structure

    Args:
        status_code: HTTP status code
        message: Error message
        error_type: Type of error (error, validation_error, etc.)
        details: Additional error details
        request: FastAPI request object

    Returns:
        Formatted error response dict
    """
    response = {
        "error": {
            "type": error_type,
            "message": message,
            "status_code": status_code,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    }

    if details:
        response["error"]["details"] = details

    if request:
        response["error"]["path"] = request.url.path
        response["error"]["method"] = request.method

    return response


# ==========================================
# GLOBAL EXCEPTION HANDLERS
# ==========================================

async def sara_hub_exception_handler(request: Request, exc: SaraHubException) -> JSONResponse:
    """Handler for custom SaraHub exceptions"""
    logger.error(
        f"SaraHub exception: {exc.message}",
        extra={
            "error_type": type(exc).__name__,
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method,
            "details": exc.details
        }
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=format_error_response(
            status_code=exc.status_code,
            message=exc.message,
            error_type=type(exc).__name__,
            details=exc.details,
            request=request
        )
    )


async def http_exception_handler(request: Request, exc: Union[HTTPException, StarletteHTTPException]) -> JSONResponse:
    """Handler for FastAPI HTTP exceptions"""
    logger.warning(
        f"HTTP exception: {exc.detail}",
        extra={
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method
        }
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=format_error_response(
            status_code=exc.status_code,
            message=str(exc.detail),
            error_type="HTTPException",
            request=request
        )
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handler for request validation errors"""
    # Extract validation errors
    validation_errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        validation_errors.append({
            "field": field,
            "message": error["msg"],
            "type": error["type"]
        })

    logger.warning(
        f"Validation error: {len(validation_errors)} fields failed",
        extra={
            "path": request.url.path,
            "method": request.method,
            "errors": validation_errors
        }
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=format_error_response(
            status_code=422,
            message="Request validation failed",
            error_type="ValidationError",
            details={"validation_errors": validation_errors},
            request=request
        )
    )


async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Handler for database errors"""
    logger.error(
        f"Database error: {str(exc)}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "error_type": type(exc).__name__
        },
        exc_info=True
    )

    # Don't leak database details to client
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=format_error_response(
            status_code=500,
            message="Database operation failed",
            error_type="DatabaseError",
            request=request
        )
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unexpected exceptions"""
    # Get stack trace
    tb = traceback.format_exc()

    logger.error(
        f"Unhandled exception: {str(exc)}",
        extra={
            "error_type": type(exc).__name__,
            "path": request.url.path,
            "method": request.method,
            "traceback": tb
        },
        exc_info=True
    )

    # In production, don't leak stack traces
    details = {"error_type": type(exc).__name__}

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=format_error_response(
            status_code=500,
            message="An unexpected error occurred",
            error_type="InternalServerError",
            details=details,
            request=request
        )
    )


# ==========================================
# MIDDLEWARE SETUP HELPER
# ==========================================

def setup_error_handlers(app):
    """
    Register all error handlers with FastAPI app

    Usage:
        from app.core.errors import setup_error_handlers

        app = FastAPI()
        setup_error_handlers(app)
    """
    # Custom exceptions
    app.add_exception_handler(SaraHubException, sara_hub_exception_handler)

    # HTTP exceptions
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # Validation errors
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    # Database errors
    app.add_exception_handler(SQLAlchemyError, database_exception_handler)

    # Catch-all
    app.add_exception_handler(Exception, general_exception_handler)

    logger.info("✅ Error handlers registered")


# ==========================================
# UTILITY FUNCTIONS
# ==========================================

def raise_not_found(resource_type: str, resource_id: str, details: Dict[str, Any] = None):
    """Convenience function to raise ResourceNotFoundError"""
    raise ResourceNotFoundError(resource_type, resource_id, details)


def raise_unauthorized(message: str = "Not authorized", details: Dict[str, Any] = None):
    """Convenience function to raise AuthorizationError"""
    raise AuthorizationError(message, details)


def raise_validation_error(message: str, field: str = None, details: Dict[str, Any] = None):
    """Convenience function to raise ValidationError"""
    raise ValidationError(message, field, details)
