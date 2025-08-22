from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.config import settings
from app.db.session import engine, create_tables
from app.routes import auth, chat, notes, reminders, calendar, docs, memory
from app.routes import search as search_routes
from app.services.scheduler import scheduler_service


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting {settings.assistant_name} Hub API")
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

# CORS middleware
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
