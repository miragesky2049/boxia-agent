"""智能体配置面应用服务（0074 PRD F2，20261107）。

DDD 分层：本服务只做"类型闸门 + 表单校验 + 读写转译编排"，纯映射逻辑在
domain/canvas/agent_config，缺省解析在 domain/agent/memory；画布即唯一事实源，
版本快照、审计、缓存失效全部经 ApplicationService 既有端口，不新增存储表。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from internal.application.apps.application_service import FLOW_TYPE_AGENT, ApplicationService
from internal.application.errors import NotFoundError, ValidationError
from internal.domain.canvas.agent_config import (
    apply_form_to_node,
    find_agent_loop_node,
    node_config_to_form,
    validate_form,
)
from internal.domain.canvas.convert import find_agent_loop_config


class AgentConfigService:
    """智能体应用配置读写：GET 表单化读出、PUT 校验后写回画布 draft 版本。"""

    def __init__(
        self,
        app_service: ApplicationService,
        *,
        long_term_admin_available: bool = True,
    ) -> None:
        """app_service 由组合根注入（复用其画布事实源与 save_graph 版本链路）。

        long_term_admin_available：M4 PRD F16.6 隐私硬条件开关，组合根从 settings
        注入（用户端记忆管理面未部署的实例置 False，保存时拒绝开启长期记忆）。
        """
        self._app_service = app_service
        self._long_term_admin_available = long_term_admin_available

    def get_config(self, application_id: UUID) -> dict[str, Any]:
        """读取智能体配置表单；应用非 agent 型或画布缺 Agent 节点时抛业务异常。"""
        pack = self._load_agent_graph_pack(application_id)
        found = find_agent_loop_config(pack["graph"])
        if found is None:
            raise ValidationError("画布缺少 Agent 循环节点，无法读取智能体配置")
        return node_config_to_form(found[1])

    def save_config(
        self,
        application_id: UUID,
        form: dict[str, Any],
        *,
        actor_id: UUID | None = None,
        actor_username: str = "",
    ) -> dict[str, Any]:
        """保存智能体配置：校验表单 → 写回节点 → save_graph 产生新版本，回读归一化结果。"""
        pack = self._load_agent_graph_pack(application_id)
        # M4-c F14.1：传入当前应用 ID 以拒绝 subAgents 自引用
        issues = validate_form(
            form,
            long_term_admin_available=self._long_term_admin_available,
            self_application_id=str(application_id),
        )
        if issues:
            raise ValidationError("智能体配置不合法：" + "；".join(issues))
        node = find_agent_loop_node(pack["graph"])
        if node is None:
            raise ValidationError("画布缺少 Agent 循环节点，无法保存智能体配置")
        apply_form_to_node(node, form)
        self._app_service.save_graph(
            application_id,
            pack["graph"],
            changelog="智能体配置更新",
            actor_id=actor_id,
            actor_username=actor_username,
        )
        return self.get_config(application_id)

    def _load_agent_graph_pack(self, application_id: UUID) -> dict[str, Any]:
        """取最新画布快照并校验应用为智能体类型。"""
        pack = self._app_service.get_graph(application_id)
        if pack is None:
            raise NotFoundError("应用或画布不存在")
        if pack.get("flow_type") != FLOW_TYPE_AGENT:
            raise ValidationError("当前应用不是智能体类型，请使用对应配置接口")
        return pack
