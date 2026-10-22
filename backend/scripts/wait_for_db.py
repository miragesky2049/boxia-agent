"""等待数据库可用（容器启动编排使用）。"""

import os
import sys
import time

from sqlalchemy import create_engine, text

DEFAULT_TIMEOUT = 60


def main() -> int:
    """轮询 SELECT 1，直到成功或超时。"""
    url = os.environ.get("DATABASE_URL", "")
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
