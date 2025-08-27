# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Docker Container Management
```bash
# Start all data services (recommended for development)
docker compose up -d db neo4j minio redis

# Start complete application stack
docker compose up -d

# View logs for specific services
docker compose logs -f db          # Database logs
docker compose logs -f backend     # Backend API logs
docker compose logs -f frontend    # Frontend dev server logs

# Stop all services
docker compose down

# Rebuild containers after code changes
docker compose build --no-cache backend
docker compose build --no-cache frontend
```

### Frontend (React + Vite + TypeScript)
```bash
# Running in Docker (recommended for development)
# Frontend automatically starts in Docker container on port 3000
# Access at: http://10.185.1.180:3000

# Local development (alternative)
cd frontend
npm run dev        # Start development server on port 3000
npm run build      # Build for production (requires TypeScript fixes)
npm run lint       # Run ESLint
npm run preview    # Preview production build
```

### Backend (FastAPI + Python)
```bash
# Running locally (current setup)
cd backend
export DATABASE_URL="postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
export OPENAI_BASE_URL=http://100.104.68.115:11434/v1
export OPENAI_MODEL=gpt-oss:120b
export OPENAI_API_KEY=dummy
export EMBEDDING_BASE_URL=http://100.104.68.115:11434
export EMBEDDING_MODEL=bge-m3
export EMBEDDING_DIM=1024
export ASSISTANT_NAME=Sara
python3 app/main_simple.py

# Running in Docker (production)
docker compose up -d backend       # Requires fixing large dependencies
```

### Database Operations
```bash
# Connect to PostgreSQL
psql postgresql://sara:sara123@10.185.1.180:5432/sara_hub

# Run migration scripts
python3 backend/migrate_users.py        # Migrate from SQLite to PostgreSQL
python3 backend/add_folder_column.py    # Update database schema
python3 backend/add_note_connections.py # Add knowledge garden connections table
```

## Architecture Overview

### System Design
Sara is a personal AI hub with human-like memory built as a full-stack application:

- **Frontend**: React SPA using App-interactive.tsx (not App.tsx) as main entry point
- **Backend**: FastAPI server with main_simple.py as primary implementation
- **Database**: PostgreSQL 16 with pgvector extension for semantic search
- **Storage**: MinIO for document uploads
- **LLM**: OpenAI-compatible endpoint (gpt-oss:120b via http://100.104.68.115:11434)

### Docker Container Architecture

The application uses a hybrid containerized architecture optimized for development:

#### Current Running Containers
```bash
docker compose ps
# Shows:
# jarvis-db-1              - PostgreSQL 16 with pgvector (port 5432)
# jarvis-neo4j-1           - Neo4j graph database (ports 7474/7687)
# jarvis-redis-1           - Redis cache (port 6379)
# jarvis-frontend-dev-1    - Vite dev server (port 3000)
```

#### Container Details

**Data Layer (Containerized)**
- **PostgreSQL (`jarvis-db-1`)**: Primary database with pgvector extension
  - Image: `pgvector/pgvector:pg16`
  - Port: `10.185.1.180:5432`
  - Persistent volume: `postgres_data`
  
- **Neo4j (`jarvis-neo4j-1`)**: Knowledge graph database
  - Image: `neo4j:5.15-community`
  - Ports: `10.185.1.180:7474` (HTTP), `10.185.1.180:7687` (Bolt)
  - Persistent volumes: `neo4j_data`, `neo4j_logs`, `neo4j_import`, `neo4j_plugins`
  
- **Redis (`jarvis-redis-1`)**: Caching layer
  - Image: `redis:7-alpine`
  - Port: `0.0.0.0:6379`
  
- **MinIO (`jarvis-minio-1`)**: Object storage for documents
  - Image: `quay.io/minio/minio`
  - Ports: `10.185.1.180:9000` (API), `10.185.1.180:9001` (Console)
  - Persistent volume: `minio_data`

**Application Layer**
- **Frontend (`jarvis-frontend-dev-1`)**: React development server
  - Image: `node:20-alpine`
  - Port: `0.0.0.0:3000`
  - Volume mounted: Live code reloading
  - Command: Vite dev server with hot module replacement
  
- **Backend**: Currently runs locally for development
  - Connects to containerized databases
  - Access: `http://10.185.1.180:8000`
  - Environment: Full Python dependencies available locally

#### Container Networking
- All containers use the `jarvis_default` Docker network
- Services can communicate using container names (e.g., `db`, `neo4j`, `redis`)
- Host networking for external access (frontend, API, databases)

#### Development Workflow
1. **Data services** run in Docker containers for consistency
2. **Frontend** runs in Docker with live reloading for rapid development  
3. **Backend** runs locally for easier debugging and dependency management
4. **Hot reloading** enabled for both frontend and backend development

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

#### Notes System (Knowledge Garden)
- **Current UI**: Full Obsidian-style knowledge garden interface with multiple views:
  - **Notes View**: Three-panel layout (sidebar + editor + context panel)
  - **Graph View**: Interactive D3.js visualization of notes and connections
  - **Timeline View**: Chronological exploration of notes and memories
  - **Settings**: Memory management and knowledge garden configuration
- **Backend**: Supports hierarchical folders with parent_id relationships
- **Database**: Note model with folder_id + new note_connection table for bidirectional links
- **API**: Full CRUD endpoints for notes, folders, and connections
- **Knowledge Features**:
  - **Bidirectional Linking**: `[[Note Title]]` syntax with auto-detection
  - **Connection Types**: Reference (explicit links), Semantic (content similarity), Temporal
  - **Auto-Connection Detection**: Automatically creates connections when notes are saved
  - **Connection Suggestions**: Semantic similarity recommendations with manual approval
  - **Memory Context**: Shows related episodic memories for each note
  - **Backlinks & Related Notes**: Automatically detected relationships

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
- **NoteConnections**: Knowledge garden connections between notes
  - source_note_id, target_note_id, connection_type (reference/semantic/temporal)
  - strength (0-100), auto_generated flag, user_id for ownership
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

### Knowledge Garden Components

#### Frontend Components
- `frontend/src/components/NotesKnowledgeGarden.tsx`: Main knowledge garden interface
- `frontend/src/components/KnowledgeGraph.tsx`: D3.js interactive graph visualization
- `frontend/src/components/TimelineView.tsx`: Chronological memory/note timeline
- `frontend/src/components/MemoryManager.tsx`: Memory curation and management tools

#### Utilities & Services
- `frontend/src/utils/linkParser.ts`: Bidirectional link parsing and detection
- `frontend/src/utils/connectionDetector.ts`: Auto-connection detection and suggestions

#### Backend APIs
- `/notes/{id}/connections`: CRUD operations for note connections
- `/notes/graph-data`: Graph visualization data endpoint
- `/memory/episodes`: Memory management endpoints (list, update, delete)

#### Key Features Implemented
1. **Bidirectional Linking**: Auto-detects `[[Note Title]]` syntax and note title mentions
2. **Connection Types**: Reference (explicit), Semantic (similarity), Temporal (time-based)
3. **Auto-Detection**: Automatically creates connections when notes are saved
4. **Visual Graph**: Interactive D3.js visualization with physics simulation
5. **Timeline Exploration**: Chronological view of notes and memories
6. **Memory Context**: Shows related episodes for each note
7. **Connection Suggestions**: AI-powered similarity recommendations
8. **Manual Curation**: Edit/delete memories, adjust importance scores
9. **Search & Filter**: Full-text search across notes and memories
10. **Settings Panel**: Knowledge garden management and statistics

### File Structure Highlights
- `frontend/src/App-interactive.tsx`: Main application component
- `backend/app/main_simple.py`: Primary FastAPI server implementation
- `backend/app/tools/`: AI tool implementations
- `docker-compose.yml`: Complete service orchestration
- `frontend/src/config.ts`: Dynamic API URL configuration

### Vulnerability Watch System
New defensive security monitoring feature for vulnerability intelligence:

#### Features
- **Daily Reports**: Automated 5am generation of vulnerability intelligence reports
- **Multi-Source Intelligence**: MSRC, CISA KEV, NVD, Project Zero, Exploit-DB
- **Priority Scoring**: Known exploited (KEV) and critical vulnerabilities highlighted
- **NTFY Notifications**: Report ready alerts and critical vulnerability notifications
- **Knowledge Integration**: Reports processed into Sara's Neo4j knowledge graph
- **Mobile Responsive**: Clean UI with sidebar navigation and markdown rendering

#### Database Tables
- `vulnerability_report`: Daily reports with metadata and markdown content
- `notification_log`: NTFY notification tracking for debugging

#### API Endpoints
- `GET /api/vulnerability-reports`: List all reports
- `GET /api/vulnerability-reports/{id}`: Get specific report content
- `POST /api/vulnerability-reports/generate`: Manual report generation
- `POST /api/notifications/ntfy`: Send test notifications

#### Daily Automation
- **Cron Job**: `/home/david/jarvis/scripts/generate_daily_vulnerability_report.py`
- **Schedule**: Daily at 5:00 AM via crontab
- **Logs**: `/home/david/jarvis/logs/vulnerability_reports.log`

#### Frontend Components
- `frontend/src/components/VulnerabilityWatch.tsx`: Main vulnerability watch interface
- **Navigation**: "Vulns" button in sidebar with security icon
- **Layout**: Left sidebar (reports list) + right panel (markdown viewer)

### Environment Variables
Key variables for development:
- `DATABASE_URL`: PostgreSQL connection string
- `OPENAI_BASE_URL`: LLM endpoint (http://100.104.68.115:11434/v1)
- `OPENAI_MODEL`: Model name (gpt-oss:120b)
- `EMBEDDING_MODEL`: Embedding model (bge-m3)
- `ASSISTANT_NAME`: Branding (Sara)
- `DOMAIN`: Target domain (sara.avery.cloud)
- `NTFY_VULNERABILITY_TOPIC`: NTFY topic for vulnerability notifications

### Sara's Autonomous Personality System
Sara features a complete autonomous personality system with living sprite animations, contextual intelligence, and memory-enhanced insights. See detailed documentation:

- **[Sara Autonomous System Documentation](docs/SARA_AUTONOMOUS_SYSTEM.md)**: Complete technical documentation
- **[Sara User Guide](docs/SARA_USER_GUIDE.md)**: Quick reference for users

**Key Features:**
- **Living Sprite**: Breathing animations with 6 distinct personality modes
- **Contextual Intelligence**: Memory-enhanced insights from conversation patterns  
- **Smart Notifications**: Respectful, duplicate-free notifications
- **Activity Monitoring**: Idle detection triggers contextual assistance
- **User Controls**: Comprehensive settings and feedback mechanisms