# IMPORTANT DEVELOPMENT NOTES

## Backend Deployment - READ THIS EVERY TIME!

### ⚠️ CRITICAL: ALWAYS USE DOCKER COMPOSE ⚠️

**NEVER start the backend with python3 directly!**

**ALWAYS use the Docker Compose development stack:**

```bash
# This is the ONLY way to run the backend:
docker compose -f docker-compose.dev.yml up -d backend

# Or to rebuild:
docker compose -f docker-compose.dev.yml build backend
docker compose -f docker-compose.dev.yml up -d backend

# To view logs:
docker compose -f docker-compose.dev.yml logs -f backend
```

### Why Docker Compose?

- The backend MUST run in Docker
- All services (db, neo4j, redis, minio) are containerized
- The docker-compose.dev.yml orchestrates everything correctly
- Running python3 directly breaks the deployment architecture

### DO NOT:
- ❌ Run `python3 app/main_simple.py`
- ❌ Start backend with manual environment variables
- ❌ Use pkill to stop the backend and restart manually

### DO:
- ✅ Use `docker compose -f docker-compose.dev.yml restart backend`
- ✅ Use `docker compose -f docker-compose.dev.yml logs -f backend`
- ✅ Use `docker compose -f docker-compose.dev.yml build backend` after code changes

---

**This note was created because I kept making this mistake. READ IT EVERY TIME!**
