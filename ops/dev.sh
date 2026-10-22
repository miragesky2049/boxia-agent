#!/usr/bin/env bash
# 本地开发：启动后端（热重载）+ 管理端 Vite 开发服务器。
# 前置：PostgreSQL 已运行，backend/.env 已配置 DATABASE_URL。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/backend"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 backend/.env，请确认 DATABASE_URL 与 JWT_SECRET"
fi
uv sync
uv run alembic upgrade head

uv run uvicorn web.app:app --reload --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT

cd "$ROOT/frontend/admin"
[ -d node_modules ] || npm ci
npm run dev
