#!/usr/bin/env bash
# 本地质量门禁：与 CI 保持一致。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> 后端：ruff / mypy / pytest"
cd "$ROOT/backend"
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy internal web
uv run pytest --cov=internal --cov=web --cov-fail-under=80

echo "==> 前端：typecheck / lint / format / test / build"
cd "$ROOT/frontend/admin"
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run lint
pnpm run format:check
pnpm run test:coverage
pnpm run build

echo "全部检查通过"
