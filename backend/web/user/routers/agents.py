"""用户端应用列表：当前用户可见的应用（按数据可见范围收敛）。"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from internal.application.apps.application_service import ApplicationService
from internal.application.errors import NotFoundError
from internal.domain.agent.react import build_tool_specs
from internal.domain.canvas.convert import find_agent_loop_config
from web.deps.apps_services import make_application_service
from web.deps.auth import UserAuthDep
from web.deps.db import UowDep

router = APIRouter(prefix="/agents", tags=["user-agents"])

# 应用详情卡片里 maxToolRounds 缺省值（与 chat_service 保持一致）
DEFAULT_MAX_TOOL_ROUNDS = 10


def _to_int(value: Any) -> int | None:
    """把画布 config 里的数值字段安全转 int，非法值或非正数返回 None。

    20261106 review 修正：语义与 chat_service._to_int 逐字节一致，
    保证详情卡片展示的 maxToolRounds 与实际执行取到同一个值。
    """
    try:
        result = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return result if result is not None and result > 0 else None


def get_app_service(uow: UowDep) -> ApplicationService:
    return make_application_service(uow)


AppServiceDep = Annotated[ApplicationService, Depends(get_app_service)]


@router.get("")
def list_agents(
    principal: UserAuthDep,
    service: AppServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=64),
) -> dict:
    """分页返回当前用户可见的应用卡片列表。"""
    items = service.list_visible_apps_for_user(
        principal.tenant_id, principal.user_id, keyword
    )
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{agent_id}")
async def get_agent(
    agent_id: UUID,
    principal: UserAuthDep,
    service: AppServiceDep,
) -> dict:
    """返回单个应用详情（用户端运行前拉取元信息）。"""
    target = service.get_visible_app_for_user(agent_id, principal.tenant_id, principal.user_id)
    if target is None:
        raise NotFoundError("应用不存在或未开通")

    # 从运行时 graph 中提取 agent_loop 节点配置填充前端期望的字段
    config: dict[str, Any] = {}
    prompts: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    try:
        graph = await service.get_runtime_graph(agent_id, principal.tenant_id)
        # 20261106 冒烟修正：画布持久化为 coze 数字形态（type "100" + data.inputs），
        # 统一走 find_agent_loop_config（与运行时节点 handler 同一份 convert 口径）
        loop_config = find_agent_loop_config(graph)
        if loop_config is not None:
            node_cfg = loop_config[1]
            # 20260731 双轨合并：coze 画布键（systemPrompt/modleName/maxToolRounds）优先，
            # 旧 snake_case 键兼容读取；对外响应结构保持不变
            system_prompt = node_cfg.get("systemPrompt") or node_cfg.get("system_prompt") or ""
            model_id = (
                node_cfg.get("modleName") or node_cfg.get("modelName")
                or node_cfg.get("model_id") or ""
            )
            # 与 chat_service._build_chat_run_plan 同构：camel 非法继续看 snake，
            # 两者都非法（含 0/负数）才落默认值，避免两条链路解析出不同轮数
            max_tool_rounds = (
                _to_int(node_cfg.get("maxToolRounds"))
                or _to_int(node_cfg.get("max_tool_rounds"))
                or DEFAULT_MAX_TOOL_ROUNDS
            )
            config = {
                "system_prompt": system_prompt,
                "model_id": model_id,
                "max_tool_rounds": max_tool_rounds,
            }
            if system_prompt:
                prompts.append(
                    {
                        "content": system_prompt,
                        "category": "system",
                        "variables": node_cfg.get("prompt_variables") or {},
                    }
                )
            # 20261106 review 修正：复用运行时同一个 build_tool_specs 解析
            # （含 OpenAI 嵌套 {function:{name}} 形态），卡片展示与真实暴露的工具集一致
            for tool_spec in build_tool_specs(node_cfg.get("tools")):
                tools.append({
                    "type": "tool",
                    "name": tool_spec.name,
                    "description": tool_spec.description or "",
                })
            for rid in node_cfg.get("tool_resource_ids") or []:
                tools.append({"type": "tool", "resource_id": str(rid)})
    except Exception:  # noqa: BLE001
        # graph 未配置或加载失败时保持空壳兜底，不影响应用详情返回
        pass

    return {
        **target,
        "config": config,
        "skills": [],
        "tools": tools,
        "components": [],
        "prompts": prompts,
    }
