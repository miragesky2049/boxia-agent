"""等待数据库可用（容器启动编排使用）。"""

import os
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Docker 重启后 PostgreSQL 要先做一遍 data directory fsync + WAL 崩溃恢复，
# 本机实测约 190 秒，60 秒会误判超时，故默认放宽到 300 秒
DEFAULT_TIMEOUT = 300


def main() -> int:
    """轮询 SELECT 1，直到成功或超时。"""
    from internal.infrastructure.config.settings import get_settings

    url = os.environ.get("DATABASE_URL") or get_settings().database_url
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    timeout = int(os.environ.get("DB_WAIT_TIMEOUT", DEFAULT_TIMEOUT))
    deadline = time.monotonic() + timeout
    engine = create_engine(url, pool_pre_ping=True)
    try:
        while time.monotonic() < deadline:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                print("database is ready")
                return 0
            except Exception as exc:  # 启动阶段需要重试所有连接错误
                print(f"database not ready: {exc}", file=sys.stderr)
                time.sleep(2)
    finally:
        engine.dispose()
    print("database wait timeout", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
