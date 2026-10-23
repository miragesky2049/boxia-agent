#!/usr/bin/env bash
# 本地开发：按站点启动后端（热重载）+ Vite 开发服务器。
# 用法：./ops/dev.sh [admin|user|all]，缺省为 all。
# 前置：PostgreSQL 已运行，backend/.env 已配置 DATABASE_URL。
set -euo pipefail

SITE="${1:-all}"
case "$SITE" in
  all) SITES=(admin user) ;;
  admin | user) SITES=("$SITE") ;;
  *)
    echo "用法：$0 [admin|user|all]" >&2
    exit 1
    ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/backend"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 backend/.env，请确认 DATABASE_URL 与 JWT_SECRET"
fi
uv sync
uv run alembic upgrade head

PIDS=()
for site in "${SITES[@]}"; do
  case "$site" in
    admin) module=web.app_admin:app; port=8000 ;;
    user) module=web.app_user:app; port=8001 ;;
  esac
  uv run uvicorn "$module" --reload --host 127.0.0.1 --port "$port" &
  PIDS+=("$!")
  echo "已启动 ${site} 后端 http://127.0.0.1:${port}"
done
trap 'kill "${PIDS[@]}" 2>/dev/null || true' EXIT

cd "$ROOT/frontend"
for site in "${SITES[@]}"; do
  [ -d "$site/node_modules" ] || (cd "$site" && pnpm install --frozen-lockfile)
done
pnpm run dev -- "${SITES[@]}"
