"""Agent 运行期上下文：贯穿 LLM 调用、工具执行与日志追踪。"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True)
class AgentRunContext:
    """一次 agent 调用的上下文。

    对齐 boxia-agent 的 BoxiaContext：把租户、用户、智能体、会话等
    追踪字段打包，供 LLM header、工具调用 header、审计日志统一使用。
    """

    agent_id: UUID
    tenant_id: UUID | None
    user_id: UUID | None
    # 调用方传入的会话 ID：同一对话保持一致，便于后续做历史记忆
    conversation_id: str
    user_name: str = ""
    tenant_code: str = ""
    # 单次运行的追踪 ID：用于串联一轮内的 LLM/tool 调用日志
    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex[:24]}")

    def llm_headers(self) -> dict[str, str]:
        """LLM 出站请求附加 header（当前为本地调试直连网关，预留租户路由）。"""
        headers: dict[str, str] = {}
        if self.tenant_id is not None:
            headers["X-PAAS-Tenant-ID"] = str(self.tenant_id)
        if self.user_id is not None:
            headers["X-PAAS-User-ID"] = str(self.user_id)
        headers["X-PAAS-Run-Id"] = self.run_id
        return headers
