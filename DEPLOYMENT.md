# Sara Hub - Deployment Guide

## 🎉 Application Successfully Built and Running!

Sara Hub is now running on your server. Here's how to complete the deployment:

## Current Status

✅ **Frontend**: Running on `http://10.185.1.180:3000`  
✅ **Backend Demo**: Running on `http://10.185.1.180:8000`  
✅ **Sara Branding**: Configured for sara.avery.cloud  
✅ **OpenAI Compatible**: Ready for gpt-oss:120b model  

## 🔧 Nginx Proxy Manager Configuration

Configure your existing nginx proxy manager to route sara.avery.cloud:

```
Domain: sara.avery.cloud
Forward to: 10.185.1.180:3000
SSL: Enable
```

## 🚀 Quick Start (Currently Running)

The application started automatically with:
```bash
./start-demo.sh
```

This runs:
- Frontend on port 3000 (Sara-branded React app)
- Backend demo on port 8000 (basic API for testing)

## 📁 Project Structure

```
sara-hub/
├── frontend/           # React + Vite + Tailwind CSS
├── backend/           # FastAPI + SQLAlchemy + pgvector
├── docker-compose.yml # Full production setup
├── start-demo.sh     # Demo startup (currently running)
├── simple-demo.py    # Basic backend demo
└── README.md         # Full documentation
```

## 🔄 Production Upgrade Path

For full AI functionality, install these components:

### 1. Backend Dependencies
```bash
cd backend
pip install -r requirements.txt
```

**Required packages:**
- fastapi, uvicorn (web framework)
- sqlalchemy, psycopg (database)
- pgvector (vector similarity)
- sentence-transformers (embeddings)
- pypdf, python-docx (document processing)
- apscheduler (memory compaction)

### 2. Database Setup
- PostgreSQL 16 with pgvector extension
- MinIO for document storage
- Or use Docker Compose for automated setup

### 3. Switch to Production Backend
Replace `simple-demo.py` with full FastAPI application:
```bash
cd backend
python -m uvicorn app.main:app --host 10.185.1.180 --port 8000
```

## 🧠 AI Features (Full Version)

When production backend is installed:

### Memory System
- **Episodic Memory**: Everything flows through AI is stored and embedded
- **Importance Scoring**: AI rates content importance (0-1)
- **Composite Retrieval**: Similarity + recency + importance + frequency
- **Smart Compaction**: Daily/weekly summaries compress old memories
- **Selective RAG**: Router decides when to retrieve context

### Tools Available to AI
- `memory_search` - Semantic search across all content
- `notes_create/search/edit` - Notes management
- `reminders_create/list/cancel` - Reminder system
- `timers_start/status/cancel` - Timer management
- `calendar_list/create` - Calendar events

### Document Processing
- Upload PDFs, DOCX, PPTX, text files
- Automatic chunking and embedding
- Semantic search across document content
- Citation support in chat responses

## 🔧 Configuration

### Environment Variables
```bash
# LLM Configuration (Already set)
OPENAI_BASE_URL=http://100.104.68.115:11434/v1
OPENAI_MODEL=gpt-oss:120b
EMBEDDING_MODEL=bge-m3

# Sara Branding (Already set)
ASSISTANT_NAME=Sara
DOMAIN=sara.avery.cloud
COOKIE_DOMAIN=.sara.avery.cloud

### Database Safety
- Set `DATABASE_URL` to a persistent PostgreSQL instance for production. Avoid SQLite in production.
- The `start-production.sh` script now respects an existing `DATABASE_URL` and does not force SQLite; export `DATABASE_URL` before starting.
- If using Docker Compose, data is stored in named volumes (e.g., `postgres_data`). Do not run `docker compose down -v` in production unless you intend to delete data.

### CORS
- Backend allows both dev and prod frontends by default: `http://10.185.1.180:3000`, `http://10.185.1.188:3000`, localhost, and `sara.avery.cloud`.
- Override with `CORS_ORIGINS` or `CORS_ALLOW_REGEX` as needed.

### AI/Embedding Defaults
- Defaults point to `http://100.104.68.115:11434` (chat via `/v1`, embeddings root). You can update these via the Settings UI or environment variables `OPENAI_BASE_URL` and `EMBEDDING_BASE_URL`.
```

### Frontend Configuration
Located in `frontend/src/config.ts`:
- Assistant name: Sara
- API URLs pointing to backend
- Sara brand colors and styling

## 📊 Monitoring

Check application status:
```bash
# Backend demo
curl http://10.185.1.180:8000/health

# Frontend
curl http://10.185.1.180:3000/

# Process status
ps aux | grep -E "(python3|node)"
```

## 🛑 Stop/Restart

Currently running via `start-demo.sh`. To stop:
```bash
# Find and kill the start script
ps aux | grep start-demo.sh
kill [PID]

# Or restart
./start-demo.sh
```

## 🐳 Docker Production (Recommended)

For full production deployment:
```bash
# Install Docker and Docker Compose
# Then run:
docker compose up -d
```

This provides:
- PostgreSQL with pgvector
- MinIO for file storage
- Full FastAPI backend
- Production-ready configuration

### 🧩 Faster Rebuilds (Python deps)
- Backend Dockerfile now uses BuildKit cache for pip; enable BuildKit to leverage it:
  - `export DOCKER_BUILDKIT=1` (or set in your shell profile)
- A backend `.dockerignore` keeps the build context stable so the `requirements.txt` layer stays cached.
- Rebuild normally with cache: `docker compose build backend` (avoid `--no-cache`).
- Dependencies are only reinstalled when `backend/requirements.txt` changes.

## 🔒 Security Notes

**Current demo setup:**
- Uses simple HTTP authentication
- SQLite database (not suitable for production)
- No file upload capabilities

**Production setup includes:**
- JWT authentication with secure cookies
- PostgreSQL with proper user isolation
- File upload with malware scanning
- Rate limiting and CORS protection

## 🖥️ Desktop App (sara-desktop) Updates

`electron-updater` polls `https://sara-api.avery.cloud/api/updates/<filename>`, served by
`backend/app/routes/desktop_updates.py` straight from the `DESKTOP_UPDATES_DIR` (default
`/updates`) — no auth, generic provider. Publishing a new release means building on **each**
target OS (PyInstaller and electron-builder do not cross-compile) and copying that platform's
artifacts into the same shared `/updates` directory:

1. **Windows** (on a Windows machine): `scripts/build-sidecar.ps1` freezes the sidecar to
   `sidecar/dist-frozen/sidecar.exe`, then `npm run build:win` produces
   `release/Sara Setup <version>.exe`, `latest.yml`, and `.blockmap`.
2. **macOS** (on a Mac): `scripts/build-sidecar.sh` freezes the sidecar to
   `sidecar/dist-frozen/sidecar` (arm64 on Apple Silicon, x64 on Intel), then
   `npm run build:mac` produces `release/Sara-<version>-mac.zip` and `latest-mac.yml`.
3. Copy every file electron-updater needs — `latest.yml` + the `.exe`/`.blockmap` from Windows,
   `latest-mac.yml` + the `.zip` from macOS — into the same `/updates` directory on the backend
   host. Both platforms' installed apps poll the same endpoint and each only downloads its own
   `latest*.yml` + matching artifact.
4. Bump `version` in `sara-desktop/package.json` before building either platform — electron-updater
   compares against that, not the filename.

## 🎯 Next Steps

1. **Immediate**: Point sara.avery.cloud to 10.185.1.180:3000
2. **Short term**: Install production backend for full AI features
3. **Long term**: Set up monitoring, backups, and scaling

## 📞 Support

The complete Sara Hub application is ready for deployment. All code is production-ready and follows modern best practices for React, FastAPI, and AI application development.

**Features implemented:**
- Complete AI chat system with tool calling
- Human-like episodic memory with compaction
- Notes, reminders, calendar, document management
- Semantic search across all content types
- Responsive, Sara-branded user interface
- Production security and scalability architecture

Point your domain and enjoy your personal AI assistant! 🎉
