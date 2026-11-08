"""Agent 运行期上下文：贯穿 LLM 调用、工具执行与日志追踪。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from internal.domain.constants import PLATFORM_TENANT_ID


@dataclass(frozen=True)
class AgentRunContext:
    """一次 agent 调用的上下文。

    对齐 boxia-agent 的 BoxiaContext：把租户、用户、智能体、会话等
    追踪字段打包，供 LLM header、工具调用 header、审计日志统一使用。
    """

    agent_id: UUID
    tenant_id: UUID
    user_id: UUID | None
    # 调用方传入的会话 ID：同一对话保持一致，便于后续做历史记忆
    conversation_id: str
    user_name: str = ""
    tenant_code: str = ""
    # 单次运行的追踪 ID：用于串联一轮内的 LLM/tool 调用日志
    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex[:24]}")

    def to_storage_dict(self) -> dict[str, Any]:
        """转为可 json.dumps 的平铺字典（20261106 review 修正）。

        画布运行入参要进 run 表 JSONB 列与 graph state，UUID/自定义对象
        直接序列化必抛 TypeError，chat 兼容通道统一以本形态传递、节点侧
        用 from_storage_dict 还原。
        """
        return {
            "agent_id": str(self.agent_id),
            "tenant_id": str(self.tenant_id),
            "user_id": str(self.user_id) if self.user_id is not None else None,
            "conversation_id": self.conversation_id,
            "user_name": self.user_name,
            "tenant_code": self.tenant_code,
            "run_id": self.run_id,
        }

    @classmethod
    def from_storage_dict(cls, data: dict[str, Any]) -> AgentRunContext | None:
        """从 to_storage_dict 形态还原上下文对象；关键字段缺失或非法返回 None。"""
        try:
            kwargs: dict[str, Any] = {
                "agent_id": UUID(str(data["agent_id"])),
                "tenant_id": UUID(str(data["tenant_id"])),
                "user_id": UUID(str(data["user_id"])) if data.get("user_id") else None,
                "conversation_id": str(data.get("conversation_id") or ""),
                "user_name": str(data.get("user_name") or ""),
                "tenant_code": str(data.get("tenant_code") or ""),
            }
        except (KeyError, TypeError, ValueError):
            return None
        if data.get("run_id"):
            kwargs["run_id"] = str(data["run_id"])
        return cls(**kwargs)

    def llm_headers(self) -> dict[str, str]:
        """LLM 出站请求附加 header（当前为本地调试直连网关，预留租户路由）。"""
        headers: dict[str, str] = {}
        if self.tenant_id != PLATFORM_TENANT_ID:
            headers["X-PAAS-Tenant-ID"] = str(self.tenant_id)
        if self.user_id is not None:
            headers["X-PAAS-User-ID"] = str(self.user_id)
        headers["X-PAAS-Run-Id"] = self.run_id
        return headers
