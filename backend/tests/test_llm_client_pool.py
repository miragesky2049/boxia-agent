"""共享 httpx client 池的事件循环绑定回归测试（20261107 worker 冒烟发现）。"""

from __future__ import annotations

import asyncio

import httpx

from internal.domain.llm.client import _client_pool, _get_shared_client

_TIMEOUT = httpx.Timeout(5.0)
_BASE_URL = "http://llm-pool-test.local"


def setup_function() -> None:
    _client_pool.clear()


def test_reuses_client_within_same_loop() -> None:
    """同一事件循环内多次取用应命中同一 client（连接池复用是本池的存在意义）。"""

    async def probe() -> tuple[object, object]:
        return _get_shared_client(_BASE_URL, _TIMEOUT), _get_shared_client(_BASE_URL, _TIMEOUT)

    a, b = asyncio.run(probe())
    assert a is b


def test_recreates_client_when_loop_switched() -> None:
    """asyncio.run 结束后旧 loop 关闭，新 loop 必须拿到新 client。

    复现 Celery solo worker 同进程连续任务的场景：若继续返回绑定旧 loop 的
    client，后续请求会抛 "Event loop is closed"。
    """

    async def probe() -> object:
        return _get_shared_client(_BASE_URL, _TIMEOUT)

    first = asyncio.run(probe())
    second = asyncio.run(probe())
    assert second is not first
