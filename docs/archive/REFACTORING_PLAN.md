# Sara Hub Refactoring Plan - Phase 1 & 2

## Overview
This document outlines the systematic refactoring of the Sara Hub backend from a monolithic `main_simple.py` (8,609 lines) to a modular, maintainable architecture.

## ✅ Phase 1 Completed

### MemoryService Implementation
- **Status**: ✅ Complete
- **File**: `backend/app/services/memory_service.py`
- **Lines of Code**: 624 (was 39 stubbed lines)
- **What Changed**:
  - Implemented `store_trace()` with Redis + Postgres + auto-salience
  - Implemented `recall()` with 3-tiered retrieval (Redis → HNSW → Edges)
  - Implemented `consolidate_day()` with temporal edge creation
  - Implemented `forget()` with cascading cleanup
  - Added comprehensive error handling and logging

### Benefits
1. **Performance**: Redis working set dramatically speeds up recent memory queries
2. **Reliability**: Graceful fallbacks when services unavailable
3. **Scalability**: HNSW indexing for fast vector search at scale
4. **Observability**: Rich logging throughout memory operations

---

## 🚧 Phase 2: Modular Architecture (In Progress)

### Strategy: Incremental Migration
Given that `main_simple.py` is in production, we'll use an incremental migration strategy:

1. **Extract services** (completed/in-progress)
   - ✅ MemoryService
   - ⏳ DreamConsolidationService
   - ⏳ ErrorHandlingMiddleware
   - ⏳ StructuredLogger

2. **Create router modules** (partially done)
   - Existing routers work but aren't connected to main_simple.py
   - Need to gradually migrate endpoints from main_simple.py to routers

3. **Hybrid approach** (recommended for safety)
   - Keep main_simple.py running
   - Mount new routers alongside existing endpoints
   - Gradually migrate endpoints one-by-one
   - Test each migration in production

### Architecture Target

```
backend/
├── app/
│   ├── main.py              # New modular entry point
│   ├── main_simple.py       # Legacy (gradually phase out)
│   ├── core/
│   │   ├── config.py        # ✅ Settings management
│   │   ├── auth.py          # ✅ JWT authentication
│   │   ├── deps.py          # ✅ Dependency injection
│   │   ├── llm.py           # ✅ LLM client
│   │   ├── logging.py       # 🆕 Structured logging
│   │   └── errors.py        # 🆕 Error handlers
│   ├── models/              # ✅ SQLAlchemy models (separate files)
│   ├── routes/              # ⚠️ Exist but not used
│   │   ├── auth.py
│   │   ├── chat.py
│   │   ├── notes.py
│   │   ├── habits.py        # 🆕 Extract from main_simple
│   │   ├── autonomous.py    # 🆕 Extract from main_simple
│   │   ├── vulnerabilities.py # 🆕 Extract from main_simple
│   │   └── ...
│   ├── services/            # Business logic layer
│   │   ├── memory_service.py         # ✅ Complete
│   │   ├── dream_consolidation.py    # ⏳ Phase 2
│   │   ├── autonomous_sweep_service.py # ✅ Complete
│   │   ├── vulnerability_service.py   # ✅ Complete
│   │   └── ...
│   └── tools/               # ✅ AI tool registry
```

---

## 📋 Remaining Phase 1 Tasks

### 1. Dream Consolidation Service (Priority 1)
**File**: `backend/app/services/dream_consolidation.py`
**Current**: Stubbed placeholder
**Needed**:
- Implement nightly LLM-based memory summarization
- Cluster related memories by topic/emotion
- Extract patterns and generate insights
- Store as DreamInsight records
- Schedule via cron (2 AM daily)

**Approach**:
```python
class DreamConsolidationService:
    async def consolidate_day(user_id, day):
        # 1. Fetch day's memory traces
        # 2. Use LLM to generate intelligent summary
        # 3. Cluster by semantic similarity
        # 4. Extract temporal/causal edges
        # 5. Generate insights (patterns, forgotten gems)
        # 6. Store in dream_insight table
        pass
```

### 2. Error Handling Middleware (Priority 2)
**File**: `backend/app/core/errors.py`
**Purpose**: Centralized error handling

```python
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

async def global_error_handler(request: Request, exc: Exception):
    """Global error handler with structured logging"""
    logger.error(
        "Unhandled exception",
        extra={
            "path": request.url.path,
            "method": request.method,
            "error": str(exc),
            "type": type(exc).__name__
        }
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )
```

### 3. Structured Logging (Priority 2)
**File**: `backend/app/core/logging.py`
**Purpose**: JSON-structured logs for production

```python
import logging
import json
from datetime import datetime

class StructuredLogger(logging.Handler):
    def emit(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName
        }
        print(json.dumps(log_entry))
```

### 4. Unit Tests (Priority 3)
**Directory**: `backend/tests/`

```
tests/
├── conftest.py              # Pytest fixtures
├── test_memory_service.py   # Memory service tests
├── test_auth.py             # Auth tests
├── test_dream_consolidation.py
└── ...
```

**Example Test**:
```python
import pytest
from app.services.memory_service import MemoryService

@pytest.mark.asyncio
async def test_store_and_recall_trace(db_session, redis_client):
    service = MemoryService(redis_client, db_session)

    # Store
    trace_id = await service.store_trace(
        user_id="test-user",
        content="Test memory content",
        role="user"
    )

    assert trace_id is not None

    # Recall
    results = await service.recall(
        user_id="test-user",
        q="Test memory",
        k=5
    )

    assert len(results) > 0
    assert any(r["trace_id"] == trace_id for r in results)
```

---

## 📋 Phase 2 Tasks

### 1. Frontend State Management (Priority 1)
**Tool**: Zustand
**Files**:
- `frontend/src/stores/chatStore.ts`
- `frontend/src/stores/notesStore.ts`
- `frontend/src/stores/habitsStore.ts`
- `frontend/src/stores/authStore.ts`

**Example**:
```typescript
// frontend/src/stores/chatStore.ts
import create from 'zustand'

interface ChatStore {
  messages: Message[]
  loading: boolean
  addMessage: (msg: Message) => void
  clearMessages: () => void
}

export const useChatStore = create<ChatStore>((set) => ({
  messages: [],
  loading: false,
  addMessage: (msg) => set((state) => ({
    messages: [...state.messages, msg]
  })),
  clearMessages: () => set({ messages: [] })
}))
```

### 2. Pagination & Caching (Priority 2)
**Backend**: Add pagination params to all list endpoints
**Frontend**: Implement infinite scroll with React Query

```python
# Backend example
@app.get("/notes")
async def list_notes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user=Depends(get_current_user)
):
    notes = db.query(Note).filter(
        Note.user_id == current_user.id
    ).offset(skip).limit(limit).all()

    total = db.query(Note).filter(
        Note.user_id == current_user.id
    ).count()

    return {
        "items": notes,
        "total": total,
        "skip": skip,
        "limit": limit
    }
```

### 3. Security Hardening (Priority 3)
**Tasks**:
- [ ] Add rate limiting (slowapi)
- [ ] Implement CSRF tokens for state-changing ops
- [ ] Add request validation middleware
- [ ] Audit and rotate secrets
- [ ] Add SQL injection protection (already using ORM)
- [ ] Add XSS protection headers

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/chat")
@limiter.limit("30/minute")  # 30 requests per minute
async def chat(request: Request, ...):
    pass
```

---

## Migration Strategy

### Option A: Gradual Migration (Recommended)
1. Keep `main_simple.py` as primary app
2. Extract one feature domain at a time to routers
3. Mount new routers with prefix `/v2/...`
4. Update frontend to call v2 endpoints
5. Monitor and validate
6. Remove old endpoints
7. Repeat for next domain

**Example**:
```python
# main_simple.py
from app.routes import habits_v2

# Mount new habits router
app.include_router(habits_v2.router, prefix="/v2/habits")

# Keep old habits endpoints for backward compatibility
# ... (existing @app.get("/habits") etc)
```

### Option B: Big Bang (Risky)
1. Create complete new `main.py` with all routers
2. Test thoroughly in staging
3. Switch Dockerfile CMD in one deployment
4. Rollback if issues

**Not recommended** due to production risk.

---

## Metrics & Success Criteria

### Code Quality Metrics
- [ ] Reduce `main_simple.py` from 8,609 to <500 lines (orchestration only)
- [ ] Achieve >80% test coverage on critical services
- [ ] All endpoints have proper error handling
- [ ] All services have structured logging
- [ ] No NotImplementedError exceptions remaining

### Performance Metrics
- [ ] Memory recall latency <200ms (p95)
- [ ] Redis hit rate >60% for recent memories
- [ ] API response times <500ms (p95)
- [ ] Vector search <100ms (p95)

### Reliability Metrics
- [ ] Zero crashes from missing error handlers
- [ ] Graceful degradation when Redis/Neo4j unavailable
- [ ] All database operations use transactions
- [ ] Proper cleanup in finally blocks

---

## Next Steps

### Immediate (This Session)
1. ✅ Complete MemoryService implementation
2. ⏳ Implement DreamConsolidationService
3. ⏳ Add structured logging
4. ⏳ Create error handling middleware

### Short-term (Next Session)
1. Write unit tests for MemoryService
2. Extract habits endpoints to router
3. Extract autonomous endpoints to router
4. Add frontend Zustand stores

### Medium-term (Next Week)
1. Complete router migration
2. Add pagination to all list endpoints
3. Implement rate limiting
4. Security audit

### Long-term (Next Month)
1. Remove main_simple.py entirely
2. Achieve 80% test coverage
3. Performance optimization pass
4. Production monitoring setup

---

## Resources

### Documentation
- FastAPI Routers: https://fastapi.tiangolo.com/tutorial/bigger-applications/
- Zustand: https://github.com/pmndrs/zustand
- Pytest-asyncio: https://pytest-asyncio.readthedocs.io/

### Tools
- **Black**: Code formatting
- **Ruff**: Fast linting
- **Pytest**: Testing framework
- **Locust**: Load testing

---

## Questions & Decisions

### Decision Log
1. **Q**: Keep main_simple.py or start fresh?
   **A**: Keep it, migrate gradually (safer for production)

2. **Q**: Which routers to migrate first?
   **A**: Start with habits (self-contained, well-defined)

3. **Q**: How to handle backward compatibility?
   **A**: Mount new routers with `/v2/` prefix, deprecate old endpoints gradually

4. **Q**: Testing strategy?
   **A**: Write integration tests first (higher ROI), then unit tests

---

## Conclusion

**Phase 1 Status**: 25% complete (MemoryService ✅)
**Phase 2 Status**: 0% complete (not started)

**Estimated Completion**:
- Phase 1: 2-3 sessions (6-9 hours)
- Phase 2: 3-4 sessions (9-12 hours)
- Total: 15-21 hours of focused development

**Risk Assessment**: Low (incremental approach minimizes production risk)

**Recommendation**: Continue with dream consolidation next, then add testing infrastructure before major refactoring.
