#!/usr/bin/env bash
# 本地开发一键启动：
#   - 自动拉起 PostgreSQL / Redis（docker compose）
#   - 清理上次残留的 Vite / Uvicorn 端口占用
#   - uv sync + alembic 迁移
#   - 后台启动后端（热重载）+ Celery RAG worker + beat 定时调度器
#   - 前台启动 Vite 开发服务器
# 用法：./ops/dev.sh [admin|user|all]，缺省为 all。
# 注意：仍需先执行一次 `uv run python -m scripts.create_admin` 创建管理员。
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
BACKEND_PIDS=()
CELERY_PID=""
CELERY_BEAT_PID=""

cleanup() {
  echo
  echo "正在停止本次启动的进程..."
  [ -n "$CELERY_PID" ] && kill "$CELERY_PID" 2>/dev/null || true
  [ -n "$CELERY_BEAT_PID" ] && kill "$CELERY_BEAT_PID" 2>/dev/null || true
  for pid in "${BACKEND_PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  # 顺手清理 Vite（dev-all.mjs 已在 SIGINT 时处理，这里兜底）
  (cd "$ROOT/frontend" && node scripts/stop-all.mjs "${SITES[@]}" >/dev/null 2>&1 || true)
}
trap cleanup EXIT INT TERM

# ---------- 1. 拉起基础设施（PostgreSQL + Redis） ----------
echo "==> 启动 PostgreSQL / Redis（docker compose）"
docker compose -f "$ROOT/backend/docker/postgresql/docker-compose.yml" up -d
docker compose -f "$ROOT/backend/docker/redis/docker-compose.yml" up -d

# ---------- 2. 清理残留端口占用 ----------
echo "==> 清理残留 Vite 端口（5173 / 5174）"
(cd "$ROOT/frontend" && node scripts/stop-all.mjs "${SITES[@]}" >/dev/null 2>&1 || true)

echo "==> 清理残留后端端口（8000 / 8001）"
"$ROOT/ops/kill-port.sh" 8000
"$ROOT/ops/kill-port.sh" 8001

# ---------- 3. 后端依赖 + 迁移 ----------
cd "$ROOT/backend"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 backend/.env，请确认 DATABASE_URL / JWT_SECRET / LLM_API_KEY / EMBEDDING_API_KEY"
fi
uv sync
# 容器 up -d 后 PostgreSQL 可能仍在崩溃恢复（the database system is starting up），
# 直接跑 alembic 会连不上，必须先等数据库真正可连
uv run python scripts/wait_for_db.py
uv run alembic upgrade head

# ---------- 4. 后台启动后端 ----------
# --reload 不可去掉：Windows 上 uvicorn 单进程模式会强制 ProactorEventLoop，
# psycopg async（LangGraph AsyncPostgresSaver）在该循环上无法建连，试运行会直接报错；
# 带 --reload 时服务跑在子进程的 SelectorEventLoop 上才可用（Linux 无此问题）
for site in "${SITES[@]}"; do
  case "$site" in
    admin) module=web.app_admin:app; port=8000 ;;
    user)  module=web.app_user:app;  port=8001 ;;
  esac
  uv run uvicorn "$module" --reload --host 127.0.0.1 --port "$port" &
  BACKEND_PIDS+=("$!")
  echo "已启动 ${site} 后端 http://127.0.0.1:${port}"
done

# ---------- 5. 后台启动 Celery RAG worker + beat ----------
# Windows（Git Bash / MSYS）下 prefork 池会因 billiard 子进程权限/信号问题崩溃，
# 改用 solo 池（单进程，调试友好）；*nix 仍用默认 prefork。
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    CELERY_POOL="--pool=solo"
    ;;
  *)
    CELERY_POOL=""
    ;;
esac
echo "==> 启动 Celery RAG worker（队列 rag，pool=${CELERY_POOL:-prefork}）"
# shellcheck disable=SC2086
uv run celery -A internal.infrastructure.celery_app worker --loglevel=info -Q rag $CELERY_POOL &
CELERY_PID=$!
echo "已启动 Celery worker PID=${CELERY_PID}"

# beat 只投递定时任务（权益生效/到期流转、到期提醒、宽限期回收、每日对账），不使用执行池，
# 全环境统一命令即可；必须保证只启动一个实例，多实例会重复投递
echo "==> 启动 Celery beat 定时调度器（单实例）"
uv run celery -A internal.infrastructure.celery_app beat --loglevel=info &
CELERY_BEAT_PID=$!
echo "已启动 Celery beat PID=${CELERY_BEAT_PID}"

# ---------- 6. 前台启动 Vite ----------
cd "$ROOT/frontend"
for site in "${SITES[@]}"; do
  [ -d "$site/node_modules" ] || (cd "$site" && pnpm install --frozen-lockfile)
done
pnpm run dev -- "${SITES[@]}"
