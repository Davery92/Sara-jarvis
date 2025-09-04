#!/usr/bin/env bash
set -euo pipefail

echo "[backend] Waiting for database to be ready..."
python - <<'PY'
import time, os, sys
import psycopg

url = os.environ.get('DATABASE_URL') or ''
# Convert SQLAlchemy style to libpq if needed
if url.startswith('postgresql+psycopg://'):
    url = 'postgresql://' + url.split('postgresql+psycopg://', 1)[1]
elif url.startswith('postgresql+psycopg2://'):
    url = 'postgresql://' + url.split('postgresql+psycopg2://', 1)[1]

last_err = None
for i in range(120):  # wait up to 120s
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT 1')
                cur.fetchone()
        print('DB is reachable')
        sys.exit(0)
    except Exception as e:
        last_err = e
        time.sleep(1)
print('DB was not reachable in time:', last_err, file=sys.stderr)
sys.exit(1)
PY

echo "[backend] Running Alembic migrations..."
alembic upgrade head

echo "[backend] Starting API (app.main:app)"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
