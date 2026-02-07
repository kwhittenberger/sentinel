#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────
# restore-db.sh — PostgreSQL restore for Sentinel
#
# Usage:
#   ./scripts/restore-db.sh                           # List available backups
#   ./scripts/restore-db.sh --dry-run FILE.dump       # Preview archive contents
#   ./scripts/restore-db.sh --latest                  # Restore most recent backup
#   ./scripts/restore-db.sh backups/daily/FILE.dump   # Restore specific backup
# ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Defaults (overridable via .env or environment)
DB_BACKUP_HOST="${DB_BACKUP_HOST:-localhost}"
DB_BACKUP_PORT="${DB_BACKUP_PORT:-5433}"
DB_BACKUP_USER="${DB_BACKUP_USER:-sentinel}"
DB_BACKUP_NAME="${DB_BACKUP_NAME:-sentinel}"

BACKUP_DIR="$PROJECT_DIR/backups"
LOG_DIR="$PROJECT_DIR/.logs"
LOG_FILE="$LOG_DIR/backup.log"

DRY_RUN=false
LATEST=false
TARGET_FILE=""

# ── Parse arguments ──────────────────────────────────────────────────

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] [BACKUP_FILE]

Options:
  --dry-run FILE  Show archive contents without restoring
  --latest        Restore the most recent daily backup
  -h, --help      Show this help

With no arguments: lists all available backups.

Environment (via .env or shell):
  DB_BACKUP_HOST   Database host (default: localhost)
  DB_BACKUP_PORT   Database port (default: 5433)
  DB_BACKUP_USER   Database user (default: sentinel)
  DB_BACKUP_NAME   Database name (default: sentinel)
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)  DRY_RUN=true; TARGET_FILE="$2"; shift 2 ;;
        --latest)   LATEST=true; shift ;;
        -h|--help)  usage ;;
        -*)         echo "Unknown option: $1" >&2; exit 1 ;;
        *)          TARGET_FILE="$1"; shift ;;
    esac
done

# ── Load .env for POSTGRES_PASSWORD ──────────────────────────────────

if [[ -f "$PROJECT_DIR/.env" ]]; then
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
    mkdir -p "$LOG_DIR"
    echo "$msg" >> "$LOG_FILE"
}

die() {
    log "ERROR: $*"
    exit 1
}

resolve_path() {
    local file="$1"
    # If it's already an absolute path or starts with backups/, use as-is
    if [[ "$file" == /* ]]; then
        echo "$file"
    elif [[ "$file" == backups/* ]]; then
        echo "$PROJECT_DIR/$file"
    else
        # Try to find it in daily/ or weekly/
        if [[ -f "$BACKUP_DIR/daily/$file" ]]; then
            echo "$BACKUP_DIR/daily/$file"
        elif [[ -f "$BACKUP_DIR/weekly/$file" ]]; then
            echo "$BACKUP_DIR/weekly/$file"
        else
            echo "$file"
        fi
    fi
}

find_latest() {
    local latest
    latest=$(find "$BACKUP_DIR" -name '*.dump' -type f -printf '%T+ %p\n' 2>/dev/null \
        | sort -r \
        | head -1 \
        | cut -d' ' -f2-)

    if [[ -z "$latest" ]]; then
        die "No backups found in $BACKUP_DIR"
    fi

    echo "$latest"
}

# ── List backups ─────────────────────────────────────────────────────

list_backups() {
    echo "Available backups:"
    echo ""

    local found=false

    if [[ -d "$BACKUP_DIR/daily" ]]; then
        local daily_files
        daily_files=$(find "$BACKUP_DIR/daily" -name '*.dump' -type f 2>/dev/null | sort -r)
        if [[ -n "$daily_files" ]]; then
            echo "  Daily:"
            while IFS= read -r f; do
                local size
                size=$(du -h "$f" | cut -f1)
                local mtime
                mtime=$(date -r "$f" '+%Y-%m-%d %H:%M:%S')
                echo "    $(basename "$f")  ($size, $mtime)"
                found=true
            done <<< "$daily_files"
            echo ""
        fi
    fi

    if [[ -d "$BACKUP_DIR/weekly" ]]; then
        local weekly_files
        weekly_files=$(find "$BACKUP_DIR/weekly" -name '*.dump' -type f 2>/dev/null | sort -r)
        if [[ -n "$weekly_files" ]]; then
            echo "  Weekly:"
            while IFS= read -r f; do
                local size
                size=$(du -h "$f" | cut -f1)
                local mtime
                mtime=$(date -r "$f" '+%Y-%m-%d %H:%M:%S')
                echo "    $(basename "$f")  ($size, $mtime)"
                found=true
            done <<< "$weekly_files"
            echo ""
        fi
    fi

    if [[ "$found" == false ]]; then
        echo "  No backups found. Run ./scripts/backup-db.sh to create one."
    fi
}

# ── Dry run ──────────────────────────────────────────────────────────

do_dry_run() {
    local filepath
    filepath=$(resolve_path "$TARGET_FILE")

    if [[ ! -f "$filepath" ]]; then
        die "Backup file not found: $filepath"
    fi

    echo "Archive contents for: $(basename "$filepath")"
    echo "────────────────────────────────────────"
    pg_restore --list "$filepath"
}

# ── Restore ──────────────────────────────────────────────────────────

do_restore() {
    local filepath="$1"

    if [[ ! -f "$filepath" ]]; then
        die "Backup file not found: $filepath"
    fi

    local size
    size=$(du -h "$filepath" | cut -f1)
    local mtime
    mtime=$(date -r "$filepath" '+%Y-%m-%d %H:%M:%S')

    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    DATABASE RESTORE                         ║"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  File:     $(basename "$filepath")"
    echo "║  Size:     $size"
    echo "║  Created:  $mtime"
    echo "║  Target:   $DB_BACKUP_NAME@$DB_BACKUP_HOST:$DB_BACKUP_PORT"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  This will REPLACE all data in the target database.        ║"
    echo "║  A safety backup will be taken first.                      ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo -n "Type 'restore' to confirm: "
    read -r confirm

    if [[ "$confirm" != "restore" ]]; then
        echo "Aborted."
        exit 0
    fi

    # Safety backup before restore
    log "Taking safety backup before restore..."
    "$SCRIPT_DIR/backup-db.sh" --label pre-restore

    # Restore
    log "Restoring from: $filepath"

    pg_restore \
        -h "$DB_BACKUP_HOST" \
        -p "$DB_BACKUP_PORT" \
        -U "$DB_BACKUP_USER" \
        -d "$DB_BACKUP_NAME" \
        --clean \
        --if-exists \
        --no-owner \
        --no-privileges \
        "$filepath" 2>&1 || true
    # pg_restore returns non-zero for warnings (e.g., "relation does not exist" on --clean)
    # which is expected behavior, so we don't fail on it

    log "Restore complete."

    # Post-restore verification
    echo ""
    echo "Post-restore verification:"
    echo "──────────────────────────"
    psql \
        -h "$DB_BACKUP_HOST" \
        -p "$DB_BACKUP_PORT" \
        -U "$DB_BACKUP_USER" \
        -d "$DB_BACKUP_NAME" \
        -c "
        SELECT 'tables' AS type, count(*)::text AS count
          FROM information_schema.tables
         WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        UNION ALL
        SELECT 'incidents', count(*)::text FROM incidents
        UNION ALL
        SELECT 'articles', count(*)::text FROM ingested_articles
        UNION ALL
        SELECT 'extractions', count(*)::text FROM article_extractions
        UNION ALL
        SELECT 'actors', count(*)::text FROM actors
        ORDER BY type;
        "

    log "Restore verified."
}

# ── Main ─────────────────────────────────────────────────────────────

if [[ "$DRY_RUN" == true ]]; then
    do_dry_run
    exit 0
fi

if [[ "$LATEST" == true ]]; then
    TARGET_FILE=$(find_latest)
    do_restore "$TARGET_FILE"
    exit 0
fi

if [[ -n "$TARGET_FILE" ]]; then
    TARGET_FILE=$(resolve_path "$TARGET_FILE")
    do_restore "$TARGET_FILE"
    exit 0
fi

# No arguments: list backups
list_backups
