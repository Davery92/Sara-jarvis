# Sara Personal Hub

A comprehensive personal AI assistant and knowledge management system with human-like memory, built for sara.avery.cloud.

## Features

- **Chat Interface**: Conversational AI with selective RAG retrieval
- **Memory System**: Human-like episodic memory with importance scoring and compaction
- **Notes Management**: Create, edit, and search notes with semantic understanding
- **Document Processing**: Upload and search through PDFs, DOCX, PPTX, and more
- **Reminders & Timers**: Schedule notifications and track time
- **Calendar Integration**: Manage events and appointments
- **Smart Retrieval**: Hybrid search combining similarity, recency, importance, and frequency

## Architecture

- **Frontend**: React + Vite + TypeScript + Tailwind CSS (Port 3000)
- **Backend**: FastAPI + SQLAlchemy + pgvector (Port 8000)
- **Database**: PostgreSQL 16 with pgvector extension (Port 5432)
- **Storage**: MinIO for document storage (Ports 9000/9001)
- **LLM**: Configurable OpenAI-compatible endpoint (currently: http://100.104.68.115:11434)

## Configuration

The system is configured for:
- **Model**: gpt-oss:120b
- **Embeddings**: bge-m3 via same endpoint
- **Domain**: sara.avery.cloud
- **Assistant Name**: Sara

## Quick Start

1. **Clone and setup**:
   ```bash
   git clone <this-repo>
   cd sara-hub
   cp .env.example .env
   # Edit .env if needed
   ```

2. **Start services**:
   ```bash
   docker-compose up -d
   ```

3. **Access the application**:
   - Frontend: http://10.185.1.180:3000
   - Backend API: http://10.185.1.180:8000
   - Database: 10.185.1.180:5432
   - MinIO Console: http://10.185.1.180:9001

4. **Point your domain**:
   Configure your nginx proxy manager to route sara.avery.cloud to 10.185.1.180:3000

## Environment Variables

Key configuration in `.env`:

```env
# LLM Configuration
OPENAI_BASE_URL=http://100.104.68.115:11434/v1
OPENAI_MODEL=gpt-oss:120b
EMBEDDING_BASE_URL=http://100.104.68.115:11434
EMBEDDING_MODEL=bge-m3

# Sara Branding
ASSISTANT_NAME=Sara
DOMAIN=sara.avery.cloud

# Security
JWT_SECRET=your-secret-key
COOKIE_DOMAIN=.sara.avery.cloud
```

## Memory System

Sara implements human-like memory with:

- **Episodes**: Everything flows through the AI is stored as episodes
- **Importance Scoring**: AI rates content importance (0-1)
- **Composite Retrieval**: Combines similarity, recency, importance, and frequency
- **Compaction**: Daily/weekly summaries compress old memories
- **Selective RAG**: Router decides when to retrieve context

## API Endpoints

- `POST /auth/login` - Authentication
- `POST /chat` - Chat with Sara
- `GET/POST /notes` - Notes management
- `POST /docs/upload` - Document upload
- `GET/POST /reminders` - Reminder management
- `GET/POST /events` - Calendar events
- `POST /memory/search` - Semantic search

## Development

To extend Sara:

1. **Add new tools**: Implement in `backend/app/tools/`
2. **Add routes**: Create in `backend/app/routes/`
3. **Add frontend pages**: Create in `frontend/src/pages/`
4. **Database changes**: Use Alembic migrations

## Deployment

The system is designed for nginx proxy manager deployment:

1. Start containers: `docker-compose up -d`
2. Configure proxy: sara.avery.cloud → 10.185.1.180:3000
3. Enable SSL termination in proxy manager
4. Set CORS origins in backend configuration

## Ports

- **Frontend**: 10.185.1.180:3000 (Point your domain here)
- **Backend API**: 10.185.1.180:8000
- **PostgreSQL**: 10.185.1.180:5432
- **MinIO**: 10.185.1.180:9000 (API), 10.185.1.180:9001 (Console)