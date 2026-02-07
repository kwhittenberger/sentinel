#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────
# backup-db.sh — PostgreSQL backup for Sentinel
#
# Usage:
#   ./scripts/backup-db.sh              # Daily backup
#   ./scripts/backup-db.sh --verify     # Backup + verify archive integrity
#   ./scripts/backup-db.sh --label pre-migration  # Named backup
# ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Defaults (overridable via .env or environment)
DB_BACKUP_HOST="${DB_BACKUP_HOST:-localhost}"
DB_BACKUP_PORT="${DB_BACKUP_PORT:-5433}"
DB_BACKUP_USER="${DB_BACKUP_USER:-sentinel}"
DB_BACKUP_NAME="${DB_BACKUP_NAME:-sentinel}"
BACKUP_RETAIN_DAILY="${BACKUP_RETAIN_DAILY:-7}"
BACKUP_RETAIN_WEEKLY="${BACKUP_RETAIN_WEEKLY:-4}"

BACKUP_DIR="$PROJECT_DIR/backups"
DAILY_DIR="$BACKUP_DIR/daily"
WEEKLY_DIR="$BACKUP_DIR/weekly"
LOG_DIR="$PROJECT_DIR/.logs"
LOG_FILE="$LOG_DIR/backup.log"

VERIFY=false
LABEL=""

# ── Parse arguments ──────────────────────────────────────────────────

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --verify        Validate archive after backup (pg_restore --list)
  --label NAME    Create a labeled backup (e.g., pre-migration)
  -h, --help      Show this help

Environment (via .env or shell):
  DB_BACKUP_HOST          Database host (default: localhost)
  DB_BACKUP_PORT          Database port (default: 5433)
  DB_BACKUP_USER          Database user (default: sentinel)
  DB_BACKUP_NAME          Database name (default: sentinel)
  BACKUP_RETAIN_DAILY     Daily backups to keep (default: 7)
  BACKUP_RETAIN_WEEKLY    Weekly backups to keep (default: 4)
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --verify)  VERIFY=true; shift ;;
        --label)   LABEL="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ── Load .env for POSTGRES_PASSWORD ──────────────────────────────────

if [[ -f "$PROJECT_DIR/.env" ]]; then
    # Source only POSTGRES_PASSWORD to avoid polluting the environment
    POSTGRES_PASSWORD=$(grep -E '^POSTGRES_PASSWORD=' "$PROJECT_DIR/.env" | head -1 | cut -d= -f2-)
fi

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
    echo "ERROR: POSTGRES_PASSWORD not set. Set it in .env or environment." >&2
    exit 1
fi

export PGPASSWORD="$POSTGRES_PASSWORD"

# ── Helpers ──────────────────────────────────────────────────────────

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

die() {
    log "ERROR: $*"
    exit 1
}

ensure_dirs() {
    mkdir -p "$DAILY_DIR" "$WEEKLY_DIR" "$LOG_DIR"
}

# ── Backup ───────────────────────────────────────────────────────────

do_backup() {
    local timestamp
    timestamp="$(date '+%Y%m%d_%H%M%S')"

    local filename
    if [[ -n "$LABEL" ]]; then
        filename="sentinel_${LABEL}_${timestamp}.dump"
    else
        filename="sentinel_${timestamp}.dump"
    fi

    local filepath="$DAILY_DIR/$filename"

    log "Starting backup: $filename"

    pg_dump \
        -h "$DB_BACKUP_HOST" \
        -p "$DB_BACKUP_PORT" \
        -U "$DB_BACKUP_USER" \
        -d "$DB_BACKUP_NAME" \
        -Fc \
        -f "$filepath"

    local size
    size=$(du -h "$filepath" | cut -f1)
    log "Backup complete: $filepath ($size)"

    # Verify if requested
    if [[ "$VERIFY" == true ]]; then
        verify_backup "$filepath"
    fi

    # Copy to weekly on Sundays
    local dow
    dow="$(date '+%u')"  # 7 = Sunday
    if [[ "$dow" == "7" && -z "$LABEL" ]]; then
        cp "$filepath" "$WEEKLY_DIR/$filename"
        log "Weekly copy: $WEEKLY_DIR/$filename"
    fi

    # Cleanup old backups
    cleanup_old "$DAILY_DIR" "$BACKUP_RETAIN_DAILY"
    cleanup_old "$WEEKLY_DIR" "$BACKUP_RETAIN_WEEKLY"

    echo "$filepath"
}

verify_backup() {
    local filepath="$1"
    log "Verifying archive: $filepath"

    if pg_restore --list "$filepath" > /dev/null 2>&1; then
        local toc_count
        toc_count=$(pg_restore --list "$filepath" 2>/dev/null | grep -c '^[0-9]' || true)
        log "Verification passed ($toc_count TOC entries)"
    else
        die "Verification FAILED for $filepath"
    fi
}

cleanup_old() {
    local dir="$1"
    local keep="$2"

    # Count .dump files
    local count
    count=$(find "$dir" -maxdepth 1 -name '*.dump' -type f | wc -l)

    if [[ "$count" -le "$keep" ]]; then
        return
    fi

    # Remove oldest files beyond retention count
    local to_remove=$((count - keep))
    find "$dir" -maxdepth 1 -name '*.dump' -type f -printf '%T+ %p\n' \
        | sort \
        | head -n "$to_remove" \
        | cut -d' ' -f2- \
        | while read -r f; do
            log "Removing old backup: $f"
            rm -f "$f"
        done
}

# ── Main ─────────────────────────────────────────────────────────────

ensure_dirs
do_backup
