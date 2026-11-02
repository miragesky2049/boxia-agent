"""LLM 调用观测端口：domain 定义 Protocol，Prometheus 等具体实现由观测模块注册。

client 不再直接 import infrastructure.observability，依赖方向反转；
未注册时走 no-op（如纯脚本场景），web 应用导入 metrics 模块时自动装配。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LlmCallRecord:
    """一次 LLM 调用（非流式或流式整轮）的汇总。

    prompt_tokens / completion_tokens 为 None 表示该次调用没有可用 usage
    （失败路径），实现方不应记录 0 值 token 序列；成功时原样传递（允许 0）。
    """

    tenant: str
    model: str
    status: str
    duration_seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LlmCallObserver(Protocol):
    """LLM 调用观测端口。"""

    def observe(self, record: LlmCallRecord) -> None:
        """记录一次调用汇总；实现方不得抛出异常影响主链路。"""


class NoopLlmCallObserver:
    """默认空实现：未装配观测时不记录任何指标。"""

    def observe(self, record: LlmCallRecord) -> None:
        return None


_observer: LlmCallObserver = NoopLlmCallObserver()


def configure_llm_observer(observer: LlmCallObserver) -> None:
    """注册全局 LLM 观测实现（由观测模块 / 组合根调用）。"""
    global _observer
    _observer = observer


def llm_call_observer() -> LlmCallObserver:
    """取当前生效的观测实现。"""
    return _observer
