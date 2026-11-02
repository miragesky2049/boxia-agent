"""AsyncPostgresSaver 单例：checkpoint 持久化到 PostgreSQL。

从旧版 runner.py 搬过来，独立成模块。

DDD 五期决策：本模块对 infrastructure.config.settings 的 lazy import 记为
"已接受的基础设施对 domain 的用法"——checkpointer 是进程级连接单例，
database_url 若改为注入需穿透所有 GraphRuntime 构造点（含 resume/fork 路径），
改动风险大于收益，且不构成 domain→infra 的编译期依赖（函数内延迟解析）。
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

    # uvicorn 在 Windows 单进程（不带 --reload）时强制 ProactorEventLoop，
    # psycopg async 在该循环上无法建连，这里提前给出可操作的报错
    loop = asyncio.get_running_loop()
    if type(loop).__name__ == "ProactorEventLoop":
        raise RuntimeError(
            "psycopg async 不支持 ProactorEventLoop：Windows 本地请用 "
            "`python web/app_admin.py` 或 uvicorn --reload 启动后端"
        )

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
