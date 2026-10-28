#!/usr/bin/env bash
# 杀掉监听指定 TCP 端口的进程（跨平台：Windows netstat/taskkill *nix lsof/kill）。
# 用法：kill-port.sh <port>
set -euo pipefail

PORT="${1:-}"
if [ -z "$PORT" ]; then
  echo "用法：$0 <port>" >&2
  exit 1
fi

if command -v netstat >/dev/null 2>&1 && (netstat -ano 2>/dev/null | grep -qE "LISTENING") ; then
  # Windows (Git Bash)
  PIDS=$(netstat -ano \
    | awk "\$1 ~ /^TCP/ && \$2 ~ /[:.]${PORT}[[:space:]]/ && \$0 ~ /LISTENING/ {print \$NF}" \
    | sort -u)
  for pid in $PIDS; do
    [ "$pid" = "0" ] && continue
    echo "kill-port.sh: 终止 Windows PID=$pid（端口 $PORT）"
    taskkill //PID "$pid" //T //F >/dev/null 2>&1 || true
  done
else
  # *nix
  PIDS=$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true)
  for pid in $PIDS; do
    echo "kill-port.sh: 终止 PID=$pid（端口 $PORT）"
    kill "$pid" 2>/dev/null || true
  done
fi
