"""用户端 agent 运行接口：同步调用，返回最终文本与工具调用轨迹。"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter

from internal.application.agent_run_service import AgentRunService
from web.deps.auth import UserAuthDep
from web.deps.services import AgentRunServiceDep
from web.user.schemas.agent_run import (
    AgentRunRequest,
    AgentRunResponse,
    ToolCallTraceOut,
)

router = APIRouter(prefix="/agents", tags=["user-agent-run"])


@router.post("/{agent_id}/run", response_model=AgentRunResponse)
async def run_agent(
    agent_id: UUID,
    body: AgentRunRequest,
    service: AgentRunServiceDep,
    principal: UserAuthDep,
) -> AgentRunResponse:
    """运行一次 agent：LLM 循环 + 工具调用，返回最终文本。"""
    conversation_id = body.conversation_id or f"conv_{uuid4().hex[:16]}"
    result = await service.run(
        agent_id=agent_id,
        query=body.query,
        conversation_id=conversation_id,
        user_id=principal.user_id,
        user_name=principal.display_name or principal.username,
        history=[item.model_dump() for item in body.history],
    )
    return AgentRunResponse(
        agent_id=agent_id,
        run_id=result.run_id,
        conversation_id=result.conversation_id or conversation_id,
        content=result.content,
        tool_traces=[ToolCallTraceOut(**trace.__dict__) for trace in result.tool_traces],
        iterations=result.iterations,
        usage=result.usage,
        finish_reason=result.finish_reason,
    )


# 类型导出：便于在测试中显式引用
__all__ = ["AgentRunService"]
