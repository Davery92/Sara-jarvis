"""
Structured Logging Configuration

Provides JSON-formatted logging for production environments:
- Structured JSON output
- Correlation IDs for request tracing
- Performance metrics
- Log aggregation ready (ELK, Loki, etc.)
- Configurable log levels per module
"""

import logging
import json
import sys
import time
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from contextvars import ContextVar
from fastapi import Request
import uuid

# Context variable for correlation ID (request tracing)
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


# ==========================================
# JSON FORMATTER
# ==========================================

class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging
    """

    def __init__(
        self,
        service_name: str = "sara-hub",
        environment: str = "development",
        include_traceback: bool = True
    ):
        super().__init__()
        self.service_name = service_name
        self.environment = environment
        self.include_traceback = include_traceback

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
            "environment": self.environment
        }

        # Add correlation ID for request tracing
        correlation_id = correlation_id_var.get()
        if correlation_id:
            log_data["correlation_id"] = correlation_id

        # Add code location
        log_data["location"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName
        }

        # Add extra fields from logger.info(..., extra={...})
        if hasattr(record, 'extra_fields'):
            log_data.update(record.extra_fields)

        # Add exception info if present
        if record.exc_info and self.include_traceback:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info)
            }

        # Add performance metrics if available
        if hasattr(record, 'duration_ms'):
            log_data["duration_ms"] = record.duration_ms

        if hasattr(record, 'status_code'):
            log_data["status_code"] = record.status_code

        return json.dumps(log_data)


# ==========================================
# STRUCTURED LOGGER ADAPTER
# ==========================================

class StructuredLogger(logging.LoggerAdapter):
    """
    Logger adapter that adds structured fields to log records
    """

    def process(self, msg, kwargs):
        """Add extra fields to log record"""
        # Extract extra fields
        extra = kwargs.get('extra', {})

        # Add correlation ID if available
        correlation_id = correlation_id_var.get()
        if correlation_id:
            extra['correlation_id'] = correlation_id

        # Store extra fields for JSON formatter
        if 'extra_fields' not in extra:
            extra['extra_fields'] = {}

        # Move all extra fields to extra_fields dict
        for key, value in list(extra.items()):
            if key != 'extra_fields':
                extra['extra_fields'][key] = value

        kwargs['extra'] = extra
        return msg, kwargs


# ==========================================
# LOGGING CONFIGURATION
# ==========================================

def setup_logging(
    service_name: str = "sara-hub",
    environment: str = "development",
    log_level: str = "INFO",
    json_output: bool = False
) -> None:
    """
    Configure application logging

    Args:
        service_name: Name of the service
        environment: Environment (development, staging, production)
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: Use JSON formatting (True for production)
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    root_logger.handlers = []

    # Create handler
    handler = logging.StreamHandler(sys.stdout)

    # Set formatter
    if json_output:
        formatter = JSONFormatter(
            service_name=service_name,
            environment=environment,
            include_traceback=True
        )
    else:
        # Human-readable format for development
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Interoception: buffer WARNING+ records to redis for the system_event ring
    # buffer (drained into the DB by a Celery beat task). Best-effort.
    try:
        from app.core.diagnostics_logging import install as _install_diag_logging
        _install_diag_logging(service_name=service_name or "backend")
    except Exception:
        pass

    # Set specific log levels for noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info(
        f"✅ Logging configured",
        extra={
            "service": service_name,
            "environment": environment,
            "log_level": log_level,
            "json_output": json_output
        }
    )


# ==========================================
# REQUEST LOGGING MIDDLEWARE
# ==========================================

class RequestLoggingMiddleware:
    """
    Middleware to log all HTTP requests with performance metrics
    """

    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger("sara.request")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Generate correlation ID
        request_id = str(uuid.uuid4())
        correlation_id_var.set(request_id)

        # Extract request info
        request = Request(scope, receive)
        start_time = time.time()

        # Track response
        status_code = 500
        response_body_size = 0

        async def send_wrapper(message):
            nonlocal status_code, response_body_size
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body":
                response_body_size += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            self.logger.error(
                f"Request failed: {request.method} {request.url.path}",
                extra={
                    "correlation_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error": str(exc)
                },
                exc_info=True
            )
            raise
        finally:
            # Log request completion
            duration_ms = (time.time() - start_time) * 1000

            # Determine log level based on status code
            if status_code >= 500:
                log_level = logging.ERROR
            elif status_code >= 400:
                log_level = logging.WARNING
            else:
                log_level = logging.INFO

            self.logger.log(
                log_level,
                f"{request.method} {request.url.path} - {status_code}",
                extra={
                    "correlation_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query_params": str(request.query_params),
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                    "response_size_bytes": response_body_size,
                    "user_agent": request.headers.get("user-agent"),
                    "client_ip": request.client.host if request.client else None
                }
            )

            # Clear correlation ID
            correlation_id_var.set(None)


# ==========================================
# PERFORMANCE LOGGER
# ==========================================

class PerformanceLogger:
    """
    Context manager for logging operation performance
    """

    def __init__(self, operation_name: str, logger: logging.Logger = None):
        self.operation_name = operation_name
        self.logger = logger or logging.getLogger(__name__)
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self.start_time) * 1000

        if exc_type:
            self.logger.error(
                f"{self.operation_name} failed",
                extra={
                    "operation": self.operation_name,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(exc_val)
                },
                exc_info=True
            )
        else:
            self.logger.info(
                f"{self.operation_name} completed",
                extra={
                    "operation": self.operation_name,
                    "duration_ms": round(duration_ms, 2)
                }
            )


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_correlation_id() -> Optional[str]:
    """Get current request correlation ID"""
    return correlation_id_var.get()


def get_logger(name: str) -> StructuredLogger:
    """
    Get a structured logger instance

    Usage:
        logger = get_logger(__name__)
        logger.info("User login", extra={"user_id": "123", "email": "user@example.com"})
    """
    base_logger = logging.getLogger(name)
    return StructuredLogger(base_logger, {})


def log_performance(operation_name: str, logger: logging.Logger = None):
    """
    Decorator or context manager for performance logging

    Usage as decorator:
        @log_performance("fetch_user_data")
        async def fetch_user(user_id: str):
            ...

    Usage as context manager:
        with log_performance("database_query"):
            results = db.query(...)
    """
    return PerformanceLogger(operation_name, logger)


# ==========================================
# EXAMPLE USAGE
# ==========================================

if __name__ == "__main__":
    # Setup logging
    setup_logging(
        service_name="sara-hub",
        environment="development",
        log_level="INFO",
        json_output=True
    )

    # Get logger
    logger = get_logger(__name__)

    # Basic logging
    logger.info("Application started")

    # Structured logging with extra fields
    logger.info(
        "User authenticated",
        extra={
            "user_id": "123",
            "email": "user@example.com",
            "auth_method": "jwt"
        }
    )

    # Performance logging
    with log_performance("sample_operation", logger):
        time.sleep(0.1)  # Simulate work

    # Error logging
    try:
        raise ValueError("Something went wrong")
    except Exception as e:
        logger.error("Operation failed", exc_info=True, extra={"error_code": "ERR_001"})
