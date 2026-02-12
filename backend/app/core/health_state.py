"""Shared startup health state for the application."""

STARTUP_HEALTH = {
    "database": {"status": "unknown", "message": None},
    "embedding_service": {"status": "unknown", "message": None, "dimension": None},
    "llm_service": {"status": "unknown", "message": None},
    "neo4j": {"status": "unknown", "message": None},
    "startup_time": None,
    "critical_failures": []
}
