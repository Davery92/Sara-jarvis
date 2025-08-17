# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Frontend (React + Vite + TypeScript)
```bash
cd frontend
npm run dev        # Start development server on port 3000
npm run build      # Build for production
npm run lint       # Run ESLint
npm run preview    # Preview production build
```

### Backend (FastAPI + Python)
```bash
cd backend

# Development (local)
export DATABASE_URL="postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
export OPENAI_BASE_URL=http://100.104.68.115:11434/v1
export OPENAI_MODEL=gpt-oss:120b
export OPENAI_API_KEY=dummy
export EMBEDDING_BASE_URL=http://100.104.68.115:11434
export EMBEDDING_MODEL=bge-m3
export EMBEDDING_DIM=1024
export ASSISTANT_NAME=Sara
python3 app/main_simple.py

# Production
docker-compose up -d        # Start all services
docker-compose logs -f      # View logs
docker-compose down         # Stop services
```

### Database Operations
```bash
# Connect to PostgreSQL
psql postgresql://sara:sara123@10.185.1.180:5432/sara_hub

# Run migration scripts
python3 backend/migrate_users.py        # Migrate from SQLite to PostgreSQL
python3 backend/add_folder_column.py    # Update database schema
```

## Architecture Overview

### System Design
Sara is a personal AI hub with human-like memory built as a full-stack application:

- **Frontend**: React SPA using App-interactive.tsx (not App.tsx) as main entry point
- **Backend**: FastAPI server with main_simple.py as primary implementation
- **Database**: PostgreSQL 16 with pgvector extension for semantic search
- **Storage**: MinIO for document uploads
- **LLM**: OpenAI-compatible endpoint (gpt-oss:120b via http://100.104.68.115:11434)

### Key Components

#### Frontend Architecture
- **Main App**: `App-interactive.tsx` is the actual app entry point (not App.tsx)
- **Routing**: View-based state management, not React Router
- **State**: Local React state with some TanStack Query for server state
- **Styling**: Tailwind CSS with dark theme
- **Features**: Chat, Notes (Obsidian-style), Documents, Timers, Reminders, Calendar

#### Backend Architecture
- **Main Server**: `main_simple.py` contains all endpoints in single file
- **Database**: SQLAlchemy ORM with PostgreSQL + pgvector
- **AI Tools**: Tool-based system in `app/tools/` with registry pattern
- **Memory System**: Episodic memory with importance scoring and compaction
- **Authentication**: JWT-based with HTTP-only cookies

### Critical Implementation Details

#### Notes System
- **Current UI**: Obsidian-style two-panel interface (sidebar + editor)
- **Backend**: Supports hierarchical folders with parent_id relationships
- **Database**: Note model has folder_id field for organization
- **API**: Full CRUD endpoints for notes and folders

#### Memory & RAG System
- **Episodes**: All interactions stored as episodes with importance scores
- **Retrieval**: Composite scoring (similarity + recency + importance + frequency)
- **Tools**: AI can use tools like memory search, note creation, timers, etc.
- **Selective RAG**: Router decides when to retrieve context vs direct response

#### Authentication Flow
- **Login**: POST /auth/login sets HTTP-only cookie
- **Session**: JWT token in secure cookie with domain .sara.avery.cloud
- **Protection**: All endpoints require authentication via get_current_user dependency

### Development Environment

#### Local Development
- Frontend dev server: http://10.185.1.180:3000
- Backend API: http://10.185.1.180:8000
- Database: 10.185.1.180:5432
- The frontend uses App-interactive.tsx for local development

#### Production Configuration
- Domain: sara.avery.cloud
- SSL termination via nginx proxy manager
- Docker Compose orchestration
- CORS configured for production domain

### Database Schema
- **Users**: Authentication and user data
- **Notes**: Content with optional folder organization
- **Folders**: Hierarchical structure with parent_id
- **Episodes**: Memory system with embeddings (vector column)
- **Documents**: File uploads with MinIO storage
- **Reminders/Timers**: Time-based features
- **Calendar Events**: Scheduling system

### AI Tool System
Tools are registered in `app/tools/registry.py`:
- **Memory**: Search episodic memory
- **Notes**: Create, search, edit notes
- **Reminders**: Create, list, cancel reminders  
- **Timers**: Start, check status, cancel timers
- **Calendar**: List events, create events

### Important Gotchas
1. **App Entry Point**: main.tsx imports App-interactive.tsx, not App.tsx
2. **API Base URL**: Uses dynamic configuration based on environment
3. **Database**: Requires PostgreSQL with pgvector extension enabled
4. **CORS**: Must include both development and production origins
5. **Embeddings**: Uses bge-m3 model via OpenAI-compatible endpoint
6. **Authentication**: Uses HTTP-only cookies, not localStorage tokens

### File Structure Highlights
- `frontend/src/App-interactive.tsx`: Main application component
- `backend/app/main_simple.py`: Primary FastAPI server implementation
- `backend/app/tools/`: AI tool implementations
- `docker-compose.yml`: Complete service orchestration
- `frontend/src/config.ts`: Dynamic API URL configuration

### Environment Variables
Key variables for development:
- `DATABASE_URL`: PostgreSQL connection string
- `OPENAI_BASE_URL`: LLM endpoint (http://100.104.68.115:11434/v1)
- `OPENAI_MODEL`: Model name (gpt-oss:120b)
- `EMBEDDING_MODEL`: Embedding model (bge-m3)
- `ASSISTANT_NAME`: Branding (Sara)
- `DOMAIN`: Target domain (sara.avery.cloud)