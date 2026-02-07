#!/bin/bash
# Start all Sentinel services for local development.
#
# Usage:
#   ./start-dev.sh          Start all services (db, redis, backend, workers, beat, frontend)
#   ./start-dev.sh stop     Stop all non-Docker processes (workers, beat, backend)
#   ./start-dev.sh status   Show what's running
#
# Prerequisites: Docker containers for db + redis must be running.
# Run `docker-compose up -d db redis` first if they aren't.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

LOGDIR="$PROJECT_DIR/.logs"
mkdir -p "$LOGDIR"

# --- helpers ---

source_env() {
  source .venv/bin/activate
  set -a
  source .env
  set +a
  export USE_DATABASE=true
  export USE_CELERY=true
}

pid_alive() {
  kill -0 "$1" 2>/dev/null
}

status() {
  echo "=== Sentinel Dev Services ==="
  echo ""

  # Docker
  for svc in sentinel_db sentinel_redis; do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${svc}$"; then
      echo "  [UP]   $svc (docker)"
    else
      echo "  [DOWN] $svc (docker)"
    fi
  done

  # Backend
  if ss -tlnp 2>/dev/null | grep -q ':8000 '; then
    echo "  [UP]   backend (port 8000)"
  else
    echo "  [DOWN] backend"
  fi

  # Celery workers + beat
  for name in "worker-default@" "worker-extraction@" "worker-fetch@" "celery.*beat"; do
    pid=$(pgrep -f "$name" 2>/dev/null | head -1 || true)
    label=$(echo "$name" | sed 's/@$//' | sed 's/\.\*//')
    if [ -n "$pid" ]; then
      echo "  [UP]   $label (pid $pid)"
    else
      echo "  [DOWN] $label"
    fi
  done

  # Frontend
  pid=$(pgrep -f 'node.*vite' 2>/dev/null | head -1 || true)
  if [ -n "$pid" ]; then
    echo "  [UP]   frontend (pid $pid)"
  else
    echo "  [DOWN] frontend"
  fi

  echo ""
}

stop() {
  echo "Stopping Sentinel dev services..."
  pkill -f 'celery -A backend.celery_app' 2>/dev/null && echo "  Celery workers + beat stopped" || echo "  Celery not running"
  # Kill uvicorn by port — catches both parent and reload child
  local uvicorn_pid
  uvicorn_pid=$(ss -tlnp 2>/dev/null | grep ':8000 ' | grep -oP 'pid=\K[0-9]+' || true)
  if [ -n "$uvicorn_pid" ]; then
    kill "$uvicorn_pid" 2>/dev/null
    sleep 1
    kill -9 "$uvicorn_pid" 2>/dev/null  # force if still alive
    echo "  Backend stopped"
  else
    echo "  Backend not running"
  fi
  echo "  (Docker services left running — use 'docker-compose down' to stop db/redis)"
  echo "  (Frontend left running — stop manually if needed)"
}

start() {
  echo "=== Starting Sentinel Dev Services ==="
  echo ""

  # 1. Docker: db + redis
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^sentinel_db$'; then
    echo "[1/6] Starting db + redis via docker-compose..."
    docker-compose up -d db redis
  else
    echo "[1/6] db + redis already running"
  fi

  source_env

  # 2. Backend (uvicorn)
  if ss -tlnp 2>/dev/null | grep -q ':8000 '; then
    echo "[2/6] Backend already running (port 8000 in use)"
  else
    echo "[2/6] Starting backend (uvicorn)..."
    cd "$PROJECT_DIR/backend"
    nohup uvicorn main:app --host 127.0.0.1 --port 8000 --reload \
      > "$LOGDIR/backend.log" 2>&1 &
    echo "       PID: $! — log: .logs/backend.log"
    cd "$PROJECT_DIR"
  fi

  # 3. Celery worker: default + enrichment
  if pgrep -f 'worker-default@' >/dev/null 2>&1; then
    echo "[3/6] Worker (default+enrichment) already running"
  else
    echo "[3/6] Starting worker: default + enrichment..."
    nohup celery -A backend.celery_app worker \
      --loglevel=info --queues=default,enrichment --concurrency=2 \
      -n worker-default@%h \
      > "$LOGDIR/worker-default.log" 2>&1 &
    echo "       PID: $!"
  fi

  # 4. Celery worker: extraction
  if pgrep -f 'worker-extraction@' >/dev/null 2>&1; then
    echo "[4/6] Worker (extraction) already running"
  else
    echo "[4/6] Starting worker: extraction..."
    nohup celery -A backend.celery_app worker \
      --loglevel=info --queues=extraction --concurrency=1 \
      -n worker-extraction@%h \
      > "$LOGDIR/worker-extraction.log" 2>&1 &
    echo "       PID: $!"
  fi

  # 5. Celery worker: fetch
  if pgrep -f 'worker-fetch@' >/dev/null 2>&1; then
    echo "[5/6] Worker (fetch) already running"
  else
    echo "[5/6] Starting worker: fetch..."
    nohup celery -A backend.celery_app worker \
      --loglevel=info --queues=fetch --concurrency=2 \
      -n worker-fetch@%h \
      > "$LOGDIR/worker-fetch.log" 2>&1 &
    echo "       PID: $!"
  fi

  # 6. Celery beat
  if pgrep -f 'celery.*beat' >/dev/null 2>&1; then
    echo "[6/6] Celery beat already running"
  else
    echo "[6/6] Starting Celery beat..."
    nohup celery -A backend.celery_app beat --loglevel=info \
      > "$LOGDIR/celery-beat.log" 2>&1 &
    echo "       PID: $!"
  fi

  echo ""
  echo "All services started. Logs in .logs/"
  echo "  Backend:    http://localhost:8000"
  echo "  Frontend:   cd frontend && npm run dev"
  echo ""
  echo "Run '$0 status' to check services."
  echo "Run '$0 stop' to stop non-Docker services."
}

# --- main ---
case "${1:-start}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *)      echo "Usage: $0 {start|stop|status}" ;;
esac
