# Development Setup Guide

This project now has **two Docker Compose configurations**:

## Production Mode (Current)
```bash
docker compose up -d
```
- Uses `docker-compose.yml`
- Code baked into images
- Requires rebuild for changes
- Matches production environment exactly

## Development Mode (Fast Iteration) 🚀
```bash
docker compose -f docker-compose.dev.yml up -d
```
- Uses `docker-compose.dev.yml`
- Code mounted as volumes
- **Instant hot-reload** on file changes
- No rebuilds needed for code changes

## Quick Start: Development Mode

### 1. First Time Setup
Build the development images:
```bash
docker compose -f docker-compose.dev.yml build
```

### 2. Start Development Containers
```bash
docker compose -f docker-compose.dev.yml up -d
```

### 3. View Logs (Optional)
```bash
# All services
docker compose -f docker-compose.dev.yml logs -f

# Just backend
docker compose -f docker-compose.dev.yml logs -f backend

# Just frontend
docker compose -f docker-compose.dev.yml logs -f frontend
```

### 4. Make Code Changes
Just edit files normally! Changes will:
- **Backend**: Auto-reload via Uvicorn (1-2 second restart)
- **Frontend**: Hot Module Replacement (instant)

### 5. Stop Development Containers
```bash
docker compose -f docker-compose.dev.yml down
```

## Key Differences

| Feature | Production Mode | Development Mode |
|---------|----------------|------------------|
| File Changes | Rebuild required | Instant |
| Startup Time | ~10s | ~10s (first time only) |
| Backend Reload | Manual restart | Auto (--reload) |
| Frontend | Preview mode | Dev server (HMR) |
| Volume Mounts | None | Source code |
| Best For | Deployment | Active development |

## When to Rebuild (Dev Mode)

You only need to rebuild when:
- ✅ Adding new Python packages to `requirements.txt`
- ✅ Adding new npm packages to `package.json`
- ✅ Changing Dockerfile configuration

You **don't** need to rebuild for:
- ❌ Editing Python code (.py files)
- ❌ Editing React code (.tsx/.ts/.jsx/.js)
- ❌ Editing CSS/styles
- ❌ Changing environment variables (just restart)

## Troubleshooting

### Backend not reloading?
Check if the volume mount is working:
```bash
docker compose -f docker-compose.dev.yml exec backend ls -la /app/app/tools
```

### Frontend not hot-reloading?
Restart the frontend container:
```bash
docker compose -f docker-compose.dev.yml restart frontend
```

### Want to switch back to production mode?
```bash
# Stop dev containers
docker compose -f docker-compose.dev.yml down

# Start production containers
docker compose up -d
```

## Recommended Development Workflow

1. **Morning**: Start dev containers
   ```bash
   docker compose -f docker-compose.dev.yml up -d
   ```

2. **During the day**: Edit code freely
   - Changes appear automatically
   - No manual rebuilds

3. **Need new dependencies?**
   ```bash
   # Add to requirements.txt or package.json, then:
   docker compose -f docker-compose.dev.yml build backend  # or frontend
   docker compose -f docker-compose.dev.yml up -d
   ```

4. **End of day**: Leave running or stop
   ```bash
   docker compose -f docker-compose.dev.yml down
   ```

## Helper Aliases (Optional)

Add to your `~/.bashrc` or `~/.zshrc`:
```bash
alias dcdev='docker compose -f docker-compose.dev.yml'
alias dcprod='docker compose'

# Usage:
dcdev up -d
dcdev logs -f backend
dcdev down
```
