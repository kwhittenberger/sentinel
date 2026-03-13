#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────
# deploy-dev-server.sh — Deploy Sentinel to dev-server (production)
#
# Usage:
#   ./scripts/deploy-dev-server.sh              # Full deploy
#   ./scripts/deploy-dev-server.sh --restore    # Deploy + restore DB from dump
#   ./scripts/deploy-dev-server.sh --build-only # Build images only
#   ./scripts/deploy-dev-server.sh --status     # Show service status
#   ./scripts/deploy-dev-server.sh --stop       # Stop all services
# ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.prod.yml"
ENV_FILE="$PROJECT_DIR/.env.prod"
SECRETS_ENC="$PROJECT_DIR/secrets/secrets.prod.enc.env"

RESTORE=false
BUILD_ONLY=false
STATUS=false
STOP=false
DUMP_FILE=""

# ── Parse arguments ──────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --restore)    RESTORE=true; shift ;;
        --dump)       DUMP_FILE="$2"; shift 2 ;;
        --build-only) BUILD_ONLY=true; shift ;;
        --status)     STATUS=true; shift ;;
        --stop)       STOP=true; shift ;;
        -h|--help)
            echo "Usage: $(basename "$0") [--restore] [--dump FILE] [--build-only] [--status] [--stop]"
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*"; }
die() { log "ERROR: $*"; exit 1; }

wait_healthy() {
    local service="$1"
    local max_wait="${2:-60}"
    local elapsed=0

    log "Waiting for $service to be healthy..."
    while [[ $elapsed -lt $max_wait ]]; do
        local health
        health=$($COMPOSE --env-file "$ENV_FILE" ps "$service" --format json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Health',''))" 2>/dev/null || echo "")
        if [[ "$health" == "healthy" ]]; then
            log "$service is healthy"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    die "$service did not become healthy within ${max_wait}s"
}

# ── Status / Stop ────────────────────────────────────────────────────

if [[ "$STATUS" == true ]]; then
    $COMPOSE --env-file "$ENV_FILE" ps
    exit 0
fi

if [[ "$STOP" == true ]]; then
    log "Stopping all services..."
    $COMPOSE --env-file "$ENV_FILE" down
    exit 0
fi

# ── Decrypt secrets ──────────────────────────────────────────────────

if [[ ! -f "$SECRETS_ENC" ]]; then
    die "Encrypted secrets not found: $SECRETS_ENC"
fi

log "Decrypting secrets..."
sops -d "$SECRETS_ENC" > "$ENV_FILE"
log "Secrets decrypted to $ENV_FILE"

# ── Build ────────────────────────────────────────────────────────────

log "Building images..."
$COMPOSE --env-file "$ENV_FILE" build

if [[ "$BUILD_ONLY" == true ]]; then
    log "Build complete (--build-only). Exiting."
    rm -f "$ENV_FILE"
    exit 0
fi

# ── Start infrastructure ─────────────────────────────────────────────

log "Starting database and Redis..."
$COMPOSE --env-file "$ENV_FILE" up -d sentinel-db sentinel-redis

wait_healthy sentinel-db 60
wait_healthy sentinel-redis 30

# ── Optional: Restore database dump ──────────────────────────────────

if [[ "$RESTORE" == true ]]; then
    if [[ -z "$DUMP_FILE" ]]; then
        # Look for migration dump
        DUMP_FILE=$(find "$PROJECT_DIR" -maxdepth 2 -name '*.dump' -type f -printf '%T+ %p\n' 2>/dev/null \
            | sort -r | head -1 | cut -d' ' -f2-)
    fi

    if [[ -z "$DUMP_FILE" || ! -f "$DUMP_FILE" ]]; then
        die "No dump file found. Use --dump FILE to specify."
    fi

    log "Restoring database from: $DUMP_FILE"

    # Get the prod postgres password from env file
    PROD_PG_PASS=$(grep '^POSTGRES_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)

    docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" exec -T sentinel-db \
        pg_restore \
        -U sentinel \
        -d sentinel \
        --clean \
        --if-exists \
        --no-owner \
        --no-privileges \
        < "$DUMP_FILE" 2>&1 || true

    log "Database restore complete"

    # Verify
    docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" exec sentinel-db \
        psql -U sentinel -d sentinel -c "SELECT count(*) AS incidents FROM incidents;"
fi

# ── Start all services ────────────────────────────────────────────────

log "Starting all services..."
$COMPOSE --env-file "$ENV_FILE" up -d

# ── Verify ────────────────────────────────────────────────────────────

log "Waiting for backend to start..."
sleep 5

log "Health check..."
if curl -sf http://localhost:8580/api/health > /dev/null 2>&1; then
    HEALTH=$(curl -s http://localhost:8580/api/health)
    log "Backend healthy: $HEALTH"
else
    log "WARNING: Health check failed — backend may still be starting"
fi

log ""
log "════════════════════════════════════════════════════════════"
log "  Sentinel deployed successfully!"
log "  Local:  http://localhost:8580"
log "  Public: https://sentinel.appliedaccountability.com"
log "          (after Cloudflare tunnel hostname is configured)"
log "════════════════════════════════════════════════════════════"

$COMPOSE --env-file "$ENV_FILE" ps
