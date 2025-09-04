from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.config import settings
from app.db.session import engine, create_tables
from app.routes import (
    auth, chat, notes, reminders, calendar, docs, memory, fitness, 
    folders, knowledge_graph, dashboard, conversations,
    episodes, insights, today, documents, analytics, frontend_api
)
from app.routes import settings as settings_routes
from app.routes import search as search_routes
from app.routes import timers
from app.services.scheduler import scheduler_service


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting {settings.assistant_name} Hub API")
    logger.info(f"CORS allow_origins: {settings.cors_origins}")
    logger.info(f"Cookie config -> domain: {settings.cookie_domain}, secure: {settings.cookie_secure}, samesite: {settings.cookie_samesite}")
    await create_tables()
    scheduler_service.start()
    yield
    # Shutdown
    scheduler_service.shutdown()
    logger.info("Shutting down API")


app = FastAPI(
    title=f"{settings.assistant_name} Personal Hub API",
    description=f"Personal AI assistant and knowledge management system for {settings.domain}",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware - specific origins for credentials support
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(notes.router, prefix="/notes", tags=["notes"])
app.include_router(reminders.router, prefix="/reminders", tags=["reminders"])
app.include_router(calendar.router, prefix="/events", tags=["calendar"])
app.include_router(docs.router, prefix="/docs", tags=["documents"])
app.include_router(memory.router, prefix="/memory", tags=["memory"])
app.include_router(fitness.router, prefix="/fitness", tags=["fitness"])
app.include_router(folders.router, prefix="/folders", tags=["folders"])
app.include_router(knowledge_graph.router, prefix="/knowledge-graph", tags=["knowledge-graph"])
app.include_router(settings_routes.router, prefix="/settings", tags=["settings"])
app.include_router(timers.router, prefix="/timers", tags=["timers"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
app.include_router(episodes.router, prefix="/episodes", tags=["episodes"])
app.include_router(insights.router, prefix="/insights", tags=["insights"])
app.include_router(today.router, prefix="/today", tags=["today"])
app.include_router(documents.router, prefix="/documents", tags=["documents-alias"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
# Frontend compatibility routes (no prefix)
app.include_router(frontend_api.router, tags=["frontend-compat"])
app.include_router(search_routes.router)


@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.assistant_name} Personal Hub API",
        "version": "1.0.0",
        "domain": settings.domain
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "assistant": settings.assistant_name}
