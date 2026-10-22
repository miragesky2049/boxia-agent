#!/usr/bin/env bash
# 从 custom 格式备份恢复数据库，会覆盖现有数据，必须二次确认。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"

if [ $# -ne 1 ]; then
  echo "用法: $0 <backup.dump>" >&2
  exit 1
fi

FILE="$1"
if [ ! -f "$FILE" ]; then
  echo "备份文件不存在: $FILE" >&2
  exit 1
fi

echo "警告：恢复将覆盖当前数据库全部数据。"
read -r -p "输入 RESTORE 确认执行: " answer
if [ "$answer" != "RESTORE" ]; then
  echo "已取消"
  exit 1
fi

docker compose -f "$COMPOSE_FILE" stop backend
docker compose -f "$COMPOSE_FILE" exec -T db \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' <"$FILE"
docker compose -f "$COMPOSE_FILE" start backend

echo "恢复完成，请检查 /health/ready 与业务日志"
