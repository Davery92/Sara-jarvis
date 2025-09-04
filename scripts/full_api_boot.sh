#!/usr/bin/env bash
set -euo pipefail

# Full API setup + migrate + start script
# - Uses Postgres only (no SQLite)
# - Reads .env if present for DATABASE_URL

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/venv"

echo "🚀 Full API bootstrap starting..."

# Load .env if present
if [[ -f "$ROOT_DIR/.env" ]]; then
  echo "🔧 Loading environment from .env"
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

DATABASE_URL_SA="${DATABASE_URL:-}"
if [[ -z "$DATABASE_URL_SA" ]]; then
  # Fallback to a sensible local default (update to your env as needed)
  DATABASE_URL_SA="postgresql+psycopg://sara:sara123@localhost:5432/sara_hub"
  echo "ℹ️  DATABASE_URL not set; using default: $DATABASE_URL_SA"
fi

# If user supplied a docker-compose style URL pointing to host 'db', rewrite to localhost for host execution
if [[ "$DATABASE_URL_SA" == *"@db:"* ]]; then
  echo "🔁 Rewriting DATABASE_URL host 'db' → 'localhost' for host execution"
  DATABASE_URL_SA="${DATABASE_URL_SA/@db:/@localhost:}"
fi

# Export for Alembic and app
export DATABASE_URL="$DATABASE_URL_SA"

# Convert SQLAlchemy URL to psql-compatible URL for extension creation
PSQL_URL="${DATABASE_URL_SA/postgresql+psycopg/postgresql}"

# Ensure Python venv exists
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "🐍 Creating Python virtualenv at $VENV_DIR"
  if ! python3 -m venv "$VENV_DIR" 2>/dev/null; then
    echo "❌ Could not create venv. On Debian/Ubuntu: sudo apt install -y python3-venv"
    exit 1
  fi
fi

# Ensure pip inside venv (Debian may ship venv without pip)
if [[ ! -x "$VENV_DIR/bin/pip" ]]; then
  echo "🧰 Bootstrapping pip in venv"
  if ! "$VENV_DIR/bin/python" -m ensurepip --upgrade 2>/dev/null; then
    echo "❌ pip is not available in this Python. Install: sudo apt install -y python3-venv python3-pip"
    echo "   Then re-run: $0"
    exit 1
  fi
fi

echo "📦 Installing backend dependencies"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt"

# Ensure Postgres extensions (best effort)
if command -v psql >/dev/null 2>&1; then
  if [[ "$PSQL_URL" == postgresql* ]]; then
    echo "🧩 Ensuring Postgres extensions (uuid-ossp, vector)"
    set +e
    psql "$PSQL_URL" -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";' >/dev/null 2>&1
    psql "$PSQL_URL" -c 'CREATE EXTENSION IF NOT EXISTS vector;' >/dev/null 2>&1
    set -e
  fi
else
  echo "⚠️  psql not found; skipping extension creation"
fi

echo "🗄️  Running Alembic migrations"
pushd "$BACKEND_DIR" >/dev/null
# Wait for Postgres to be ready
echo "⏳ Waiting for database to be ready..."
PY_DSN="${DATABASE_URL/postgresql+psycopg/postgresql}"
for i in {1..30}; do
  DSN="$PY_DSN" "$VENV_DIR/bin/python" - <<'PY'
import os, sys
import psycopg
dsn = os.environ.get('DSN')
try:
    with psycopg.connect(dsn, connect_timeout=2) as conn:
        pass
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
  if [[ $? -eq 0 ]]; then
    echo "✅ Database is reachable"
    break
  fi
  sleep 2
  if [[ $i -eq 30 ]]; then
    echo "❌ Could not connect to database at $PY_DSN"
    exit 1
  fi
done

"$VENV_DIR/bin/python" -m alembic upgrade heads
popd >/dev/null

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
RELOAD_FLAG="${RELOAD:-1}"

echo "📡 Starting FastAPI (app.main) on $HOST:$PORT"
# Run from backend so Python can import the `app` package
cd "$BACKEND_DIR"
export PYTHONPATH="$BACKEND_DIR:${PYTHONPATH:-}"
if [[ "$RELOAD_FLAG" == "1" ]]; then
  exec "$VENV_DIR/bin/python" -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
else
  exec "$VENV_DIR/bin/python" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
fi
