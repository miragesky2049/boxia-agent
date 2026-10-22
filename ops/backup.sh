#!/usr/bin/env bash
# PostgreSQL 逻辑备份：custom 格式，保留 14 天。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
FILE="$BACKUP_DIR/boxia-$(date +%Y%m%d-%H%M%S).dump"

if ! docker compose -f "$COMPOSE_FILE" ps --status running db >/dev/null 2>&1; then
  echo "数据库容器未运行，无法备份" >&2
  exit 1
fi

echo "备份数据库到 $FILE"
docker compose -f "$COMPOSE_FILE" exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$FILE"

find "$BACKUP_DIR" -name 'boxia-*.dump' -type f -mtime +"$RETENTION_DAYS" -print -delete
echo "备份完成：$FILE"
