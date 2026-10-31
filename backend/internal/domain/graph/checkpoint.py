"""AsyncPostgresSaver 单例：checkpoint 持久化到 PostgreSQL。

从旧版 runner.py 搬过来，独立成模块。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_CHECKPOINTER: Any | None = None
_CHECKPOINTER_LOCK: asyncio.Lock | None = None


async def get_checkpointer() -> Any:
    """全局单例 AsyncPostgresSaver。异步懒加载。"""
    global _CHECKPOINTER, _CHECKPOINTER_LOCK
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    if _CHECKPOINTER_LOCK is None:
        _CHECKPOINTER_LOCK = asyncio.Lock()

    async with _CHECKPOINTER_LOCK:
        if _CHECKPOINTER is not None:
            return _CHECKPOINTER

        from internal.infrastructure.config.settings import get_settings

        settings = get_settings()
        db_url = settings.database_url.replace("+psycopg", "")

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        cm = AsyncPostgresSaver.from_conn_string(db_url)
        saver = await cm.__aenter__()
        await saver.setup()
        saver._cm = cm  # type: ignore[attr-defined]
        _CHECKPOINTER = saver
        logger.info("AsyncPostgresSaver 已初始化")
        return saver
