"""MCP 观测端口（M4-b F17.6）：domain 定义 Protocol，Prometheus 适配器由观测模块注册。

对齐 LlmCallObserver 的端口模式：domain 不 import infrastructure；
未装配时走 no-op（纯脚本/单测），web 进程导入 metrics 模块时自动注册实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# 调用状态口径：正常返回 / 工具执行错误（isError）/ 传输层失败 / 治理拒绝（熔断、限流）
MCP_STATUS_OK = "ok"
MCP_STATUS_TOOL_ERROR = "tool_error"
MCP_STATUS_TRANSPORT_ERROR = "transport_error"
MCP_STATUS_REJECTED = "rejected"


@dataclass(frozen=True)
class McpCallRecord:
    """一次 MCP 工具调用的汇总（耗时口径为执行层端到端，含建连与治理检查）。"""

    tenant: str
    server: str
    tool: str
    status: str
    duration_seconds: float


class McpObserver(Protocol):
    """MCP 会话与调用观测端口；实现方不得抛出异常影响主链路。"""

    def on_handshake(self, server: str) -> None:
        """McpSession 完成一次协议握手（新建连接）时调用。"""

    def on_reuse(self, server: str) -> None:
        """会话池命中既有连接、省去一次握手时调用。"""

    def observe_call(self, record: McpCallRecord) -> None:
        """记录一次工具调用汇总。"""

    def set_pool_size(self, size: int) -> None:
        """上报会话池当前水位。"""


class NoopMcpObserver:
    """默认空实现：未装配观测时不记录任何指标。"""

    def on_handshake(self, server: str) -> None:
        return None

    def on_reuse(self, server: str) -> None:
        return None

    def observe_call(self, record: McpCallRecord) -> None:
        return None

    def set_pool_size(self, size: int) -> None:
        return None


_observer: McpObserver = NoopMcpObserver()


def configure_mcp_observer(observer: McpObserver) -> None:
    """注册全局 MCP 观测实现（由观测模块 / 组合根调用）。"""
    global _observer
    _observer = observer


def mcp_observer() -> McpObserver:
    """取当前生效的观测实现。"""
    return _observer
