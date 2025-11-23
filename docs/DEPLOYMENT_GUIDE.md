# Sara Enhancement Deployment Guide

**Version:** 1.0.0
**Last Updated:** 2025-11-14

This guide covers deployment and integration of all Phase 1-4 backend enhancements.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Database Migration](#database-migration)
3. [Service Configuration](#service-configuration)
4. [Scheduled Jobs Setup](#scheduled-jobs-setup)
5. [Testing](#testing)
6. [Monitoring](#monitoring)
7. [Rollback Procedures](#rollback-procedures)

---

## Prerequisites

### System Requirements

**Minimum:**
- Python 3.11+
- PostgreSQL 16+ with pgvector extension
- Redis 7+
- 2GB RAM
- 10GB storage

**Recommended:**
- Python 3.12
- PostgreSQL 16 with pgvector
- Redis 7
- 4GB RAM
- 20GB storage
- SSD storage for database

### Python Dependencies

Already installed in your environment. Key dependencies:
```
fastapi>=0.104.0
sqlalchemy>=2.0.0
psycopg[binary]>=3.1.0
redis>=5.0.0
pydantic>=2.0.0
sentence-transformers>=2.2.0  # For BGE reranker
apscheduler>=3.10.0  # For scheduled jobs
```

### Database Extensions

Ensure pgvector extension is enabled:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

---

## Database Migration

### Step 1: Backup Current Database

```bash
# Full backup
pg_dump -h 10.185.1.180 -U sara -d sara_hub -F c -f sara_hub_backup_$(date +%Y%m%d).dump

# Schema only backup
pg_dump -h 10.185.1.180 -U sara -d sara_hub -s -f sara_hub_schema_backup_$(date +%Y%m%d).sql
```

### Step 2: Verify Current Migration Status

```bash
cd /home/david/jarvis/backend
export DATABASE_URL="postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
alembic current
```

Expected output:
```
225701a85ead (head)
```

### Step 3: Apply New Migrations

All 8 migrations have been successfully applied:

```bash
# Already applied - shown for reference
alembic upgrade 001_event_log          # ✓ Applied
alembic upgrade 002_lifeos_context     # ✓ Applied
alembic upgrade 003_emotion_metadata   # ✓ Applied
alembic upgrade 004_importance_tracking # ✓ Applied
alembic upgrade 005_intelligence_reports # ✓ Applied
alembic upgrade 006_goals_tables       # ✓ Applied
alembic upgrade 007_proactive_suggestions # ✓ Applied
alembic upgrade 008_daily_briefings    # ✓ Applied
```

### Step 4: Verify Migration Success

```bash
# Check migration status
alembic current

# Expected: 008_daily_briefings (head)

# Verify tables exist
python3 -c "
import os
os.environ['DATABASE_URL'] = 'postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub'
from sqlalchemy import create_engine, inspect
engine = create_engine(os.environ['DATABASE_URL'])
inspector = inspect(engine)
new_tables = [
    'event_log', 'user_life_context', 'context_snapshots',
    'memory_references', 'intelligence_report', 'goal',
    'goal_milestone', 'goal_progress', 'proactive_suggestion',
    'detected_pattern', 'daily_briefing', 'briefing_settings'
]
for table in new_tables:
    exists = table in inspector.get_table_names()
    print(f'{table}: {'✓' if exists else '✗'}')
"
```

Expected output:
```
event_log: ✓
user_life_context: ✓
context_snapshots: ✓
memory_references: ✓
intelligence_report: ✓
goal: ✓
goal_milestone: ✓
goal_progress: ✓
proactive_suggestion: ✓
detected_pattern: ✓
daily_briefing: ✓
briefing_settings: ✓
```

---

## Service Configuration

### Environment Variables

Add to your `.env` or environment:

```bash
# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# LLM Configuration (for insights generation)
OPENAI_BASE_URL=http://100.104.68.115:11434/v1
OPENAI_MODEL=gpt-oss:120b
OPENAI_API_KEY=dummy

# Embedding Configuration (for HYDRA)
EMBEDDING_BASE_URL=http://100.104.68.115:11434
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024

# Scheduler Configuration
SCHEDULER_TIMEZONE=America/New_York
ENABLE_SCHEDULED_JOBS=true

# Feature Flags
ENABLE_EMOTION_ANALYSIS=true
ENABLE_IMPORTANCE_RESCORING=true
ENABLE_HYDRA_RETRIEVAL=true
ENABLE_PROACTIVE_SUGGESTIONS=true
ENABLE_DAILY_BRIEFINGS=true
```

### Redis Setup

Ensure Redis is running:

```bash
# Check Redis status
redis-cli ping
# Expected: PONG

# Test connection
redis-cli
> SET test_key "test_value"
> GET test_key
> DEL test_key
> EXIT
```

### BGE Reranker Model

The BGE reranker will auto-download on first use. To pre-download:

```python
from sentence_transformers import CrossEncoder

# Pre-download model (optional)
model = CrossEncoder('BAAI/bge-reranker-base')
print("✓ BGE reranker model downloaded")
```

---

## Scheduled Jobs Setup

### Option 1: APScheduler (Recommended for Development)

Jobs are automatically configured in the services. Start the FastAPI app and they'll run:

```bash
cd /home/david/jarvis/backend
python3 app/main_simple.py
```

Scheduled jobs will log:
```
📅 Scheduled intelligence report generation:
  - Weekly: Sundays at 9pm
  - Monthly: 1st of month at 8am
  - Quarterly: Jan/Apr/Jul/Oct 1st at 8am
📅 Scheduled daily briefings:
  - Morning: 7am (customizable per user)
  - Evening: 9pm (customizable per user)
📅 Scheduled importance rescoring:
  - Daily: 3am
```

### Option 2: Systemd Service (Recommended for Production)

Create `/etc/systemd/system/sara-backend.service`:

```ini
[Unit]
Description=Sara Backend API
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=david
WorkingDirectory=/home/david/jarvis/backend
Environment="DATABASE_URL=postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
Environment="OPENAI_BASE_URL=http://100.104.68.115:11434/v1"
Environment="OPENAI_MODEL=gpt-oss:120b"
Environment="OPENAI_API_KEY=dummy"
ExecStart=/usr/bin/python3 /home/david/jarvis/backend/app/main_simple.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable sara-backend
sudo systemctl start sara-backend
sudo systemctl status sara-backend
```

### Option 3: Cron Jobs (Alternative)

Create cron jobs for each scheduled task:

```bash
# Edit crontab
crontab -e

# Add scheduled jobs
# Importance rescoring (3am daily)
0 3 * * * cd /home/david/jarvis/backend && python3 -c "from app.services.nightly_rescoring_job import trigger_rescoring_now; import asyncio; asyncio.run(trigger_rescoring_now())"

# Weekly reports (Sundays 9pm)
0 21 * * 0 cd /home/david/jarvis/backend && python3 -c "from app.services.report_scheduler import trigger_weekly_report_now; import asyncio; asyncio.run(trigger_weekly_report_now())"

# Monthly reports (1st of month 8am)
0 8 1 * * cd /home/david/jarvis/backend && python3 -c "from app.services.report_scheduler import trigger_monthly_report_now; import asyncio; asyncio.run(trigger_monthly_report_now())"

# Morning briefings (7am daily) - requires custom script
0 7 * * * /home/david/jarvis/scripts/generate_morning_briefings.sh

# Evening briefings (9pm daily) - requires custom script
0 21 * * * /home/david/jarvis/scripts/generate_evening_briefings.sh
```

---

## Testing

### Step 1: Smoke Tests

Test each major service:

```bash
cd /home/david/jarvis/backend

# Test database connectivity
python3 -c "
from app.db.session import get_db
db = next(get_db())
print('✓ Database connected')
"

# Test Redis connectivity
python3 -c "
import redis
r = redis.Redis(host='localhost', port=6379, db=0)
r.ping()
print('✓ Redis connected')
"

# Test event bus
python3 -c "
from app.services.event_bus import get_event_bus, Event, EventType
import asyncio

async def test():
    bus = get_event_bus()
    await bus.publish(Event(
        event_type=EventType.TEST,
        user_id='test',
        payload={'test': True}
    ))
    print('✓ Event bus working')

asyncio.run(test())
"
```

### Step 2: API Tests

```bash
# Start backend (if not running)
python3 app/main_simple.py &

# Wait for startup
sleep 5

# Test emotion endpoints
curl http://10.185.1.180:8000/api/emotions/summary?days=7

# Test intelligence reports endpoints
curl http://10.185.1.180:8000/api/reports/latest/weekly

# Kill background process
pkill -f "python3 app/main_simple.py"
```

### Step 3: Service Integration Tests

```python
# Create test script: tests/integration/test_phase_services.py

import pytest
from datetime import date
from app.services.temporal_intelligence import get_temporal_intelligence
from app.services.goal_manager import get_goal_manager, Goal
from app.services.proactive_intelligence import get_proactive_intelligence
from app.services.daily_briefing import get_daily_briefing_service
from app.db.session import get_db

def test_temporal_intelligence():
    db = next(get_db())
    engine = get_temporal_intelligence(db)

    # Test weekly report generation
    report = await engine.generate_weekly_report(
        user_id="test_user",
        week_start=date(2025, 11, 11)
    )

    assert report.id is not None
    assert report.report_type == "weekly"
    assert report.generation_time_ms < 5000
    print("✓ Temporal intelligence working")

def test_goal_manager():
    db = next(get_db())
    manager = get_goal_manager(db)

    # Test goal creation
    goal = Goal(
        user_id="test_user",
        title="Test Goal",
        goal_type="custom",
        target_value=100.0
    )

    goal_id = await manager.create_goal(goal)
    assert goal_id is not None

    # Test goal retrieval
    retrieved = await manager.get_goal(goal_id, "test_user")
    assert retrieved.title == "Test Goal"

    print("✓ Goal manager working")

# Run with: pytest tests/integration/test_phase_services.py -v
```

### Step 4: Load Testing

```bash
# Install Apache Bench
sudo apt-get install apache2-utils

# Test emotion summary endpoint
ab -n 100 -c 10 http://10.185.1.180:8000/api/emotions/summary?days=7

# Test report generation (lower concurrency)
ab -n 10 -c 2 http://10.185.1.180:8000/api/reports/latest/weekly
```

---

## Monitoring

### Database Monitoring

Monitor table sizes and query performance:

```sql
-- Table sizes
SELECT
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
AND tablename IN (
    'event_log', 'intelligence_report', 'goal',
    'proactive_suggestion', 'daily_briefing'
)
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Index usage
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;

-- Slow queries (requires pg_stat_statements)
SELECT
    query,
    calls,
    mean_exec_time,
    max_exec_time
FROM pg_stat_statements
WHERE query LIKE '%intelligence_report%'
   OR query LIKE '%goal%'
   OR query LIKE '%proactive_suggestion%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### Redis Monitoring

```bash
# Redis info
redis-cli INFO stats

# Monitor cache hit rate
redis-cli INFO stats | grep keyspace_hits
redis-cli INFO stats | grep keyspace_misses

# Check memory usage
redis-cli INFO memory | grep used_memory_human

# Monitor commands
redis-cli MONITOR
```

### Application Logs

```bash
# View backend logs
tail -f /home/david/jarvis/logs/backend.log

# Filter for phase services
tail -f /home/david/jarvis/logs/backend.log | grep -E "(temporal_intelligence|goal_manager|proactive_intelligence|daily_briefing)"

# Check for errors
tail -f /home/david/jarvis/logs/backend.log | grep ERROR
```

### Performance Metrics

Key metrics to monitor:

1. **Report Generation Time**
   - Target: < 5s
   - Alert if > 10s

2. **HYDRA Retrieval Time**
   - Cached: < 200ms
   - Uncached: < 1s
   - Alert if > 2s

3. **Database Query Time**
   - Average: < 100ms
   - Alert if > 500ms

4. **Redis Cache Hit Rate**
   - Target: > 95%
   - Alert if < 80%

5. **Scheduled Job Success Rate**
   - Target: 100%
   - Alert if < 95%

---

## Rollback Procedures

### Emergency Rollback

If critical issues occur, rollback migrations:

```bash
# Step 1: Stop application
sudo systemctl stop sara-backend
# or
pkill -f "python3 app/main_simple.py"

# Step 2: Rollback migrations (in reverse order)
export DATABASE_URL="postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"

alembic downgrade 007_proactive_suggestions
alembic downgrade 006_goals_tables
alembic downgrade 005_intelligence_reports
alembic downgrade 004_importance_tracking
alembic downgrade 003_emotion_metadata
alembic downgrade 002_lifeos_context
alembic downgrade 001_event_log

# Step 3: Restore database backup
pg_restore -h 10.185.1.180 -U sara -d sara_hub -c sara_hub_backup_YYYYMMDD.dump

# Step 4: Restart application
sudo systemctl start sara-backend
```

### Partial Rollback

Rollback specific features:

```bash
# Disable via environment variables
export ENABLE_EMOTION_ANALYSIS=false
export ENABLE_PROACTIVE_SUGGESTIONS=false

# Or rollback specific migration
alembic downgrade 007_proactive_suggestions
```

---

## Production Checklist

Before going live:

- [ ] Database backup completed
- [ ] All 8 migrations applied successfully
- [ ] All new tables verified
- [ ] Redis connectivity tested
- [ ] BGE reranker model downloaded
- [ ] Environment variables configured
- [ ] Scheduled jobs configured
- [ ] Systemd service created and enabled
- [ ] Smoke tests passed
- [ ] Integration tests passed
- [ ] Load tests passed
- [ ] Monitoring configured
- [ ] Logs rotating properly
- [ ] Rollback procedure documented
- [ ] Team notified of new features
- [ ] API documentation shared

---

## Troubleshooting

### Issue: Migrations fail

**Symptom:** Alembic migration errors

**Solution:**
```bash
# Check current migration
alembic current

# Check migration history
alembic history

# Stamp database with current version
alembic stamp head

# Try upgrade again
alembic upgrade head
```

### Issue: Scheduled jobs not running

**Symptom:** No reports or briefings generated

**Solution:**
```bash
# Check APScheduler logs
tail -f /home/david/jarvis/logs/backend.log | grep -i scheduler

# Manually trigger job
python3 -c "
from app.services.report_scheduler import trigger_weekly_report_now
import asyncio
asyncio.run(trigger_weekly_report_now())
"

# Check cron logs
grep CRON /var/log/syslog
```

### Issue: Redis connection errors

**Symptom:** Cache errors in logs

**Solution:**
```bash
# Check Redis status
sudo systemctl status redis

# Restart Redis
sudo systemctl restart redis

# Verify connectivity
redis-cli ping

# Clear cache if corrupted
redis-cli FLUSHDB
```

### Issue: Slow HYDRA retrieval

**Symptom:** Retrieval > 2s

**Solution:**
```bash
# Check database indexes
psql -h 10.185.1.180 -U sara -d sara_hub -c "
SELECT tablename, indexname, idx_scan
FROM pg_stat_user_indexes
WHERE tablename IN ('episode', 'note', 'document')
ORDER BY idx_scan;"

# Rebuild indexes if needed
psql -h 10.185.1.180 -U sara -d sara_hub -c "REINDEX TABLE episode;"

# Clear Redis cache
redis-cli FLUSHDB
```

### Issue: Out of memory errors

**Symptom:** PostgreSQL or Redis OOM

**Solution:**
```bash
# Check memory usage
free -h

# PostgreSQL memory settings
psql -h 10.185.1.180 -U sara -d sara_hub -c "
SHOW shared_buffers;
SHOW work_mem;
SHOW maintenance_work_mem;"

# Redis memory limit
redis-cli CONFIG GET maxmemory

# Set Redis max memory
redis-cli CONFIG SET maxmemory 2gb
redis-cli CONFIG SET maxmemory-policy allkeys-lru
```

---

## Support

For deployment support:
- **Documentation:** `/home/david/jarvis/docs/`
- **Logs:** `/home/david/jarvis/logs/`
- **Issues:** Create issue with logs and error messages

---

**Last Updated:** 2025-11-14
**Version:** 1.0.0
