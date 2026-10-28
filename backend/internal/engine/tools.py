"""工具适配层：把数据库里的 Tool 实体统一封装为可被 agent runner 调用的形态。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from internal.domain.entity.resource import Tool as ToolEntity
from internal.engine.context import AgentRunContext
from internal.engine.llm import LLMToolSpec
from internal.engine.tool_gateway import (
    GatewayConfig,
    ToolExecutionError,
    get_tool_gateway,
)

logger = logging.getLogger(__name__)


class Tool(ABC):
    """运行期工具抽象。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名：必须与 LLM function 调用的 name 一致。"""

    @abstractmethod
    def spec(self) -> LLMToolSpec:
        """向 LLM 暴露的 JSON Schema。"""

    @abstractmethod
    async def invoke(self, arguments: dict[str, Any], context: AgentRunContext) -> str:
        """执行工具并返回文本结果；失败抛 ToolExecutionError。"""


class EchoTool(Tool):
    """内置 echo 工具：原样回显参数，便于联调与冒烟测试。"""

    def __init__(self, name: str = "echo", description: str = "原样回显输入文本，用于调试") -> None:
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    def spec(self) -> LLMToolSpec:
        return LLMToolSpec(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要回显的文本"},
                },
                "required": ["text"],
            },
        )

    async def invoke(self, arguments: dict[str, Any], context: AgentRunContext) -> str:
        text = str(arguments.get("text") or "")
        return f"echo: {text}"


class HttpTool(Tool):
    """HTTP 工具：按 ToolEntity.config 中声明的 url/method/headers 调用外部接口。"""

    def __init__(self, entity: ToolEntity) -> None:
        self._entity = entity
        config = entity.config or {}
        self._url_template: str = config.get("url") or ""
        self._method: str = (config.get("method") or "GET").upper()
        self._headers: dict[str, str] = config.get("headers") or {}
        self._parameters: dict[str, Any] = config.get("parameters") or {
            "type": "object",
            "properties": {},
        }
        self._timeout: float = float(config.get("timeout_seconds") or 30.0)

    @property
    def name(self) -> str:
        return self._entity.name

    def spec(self) -> LLMToolSpec:
        return LLMToolSpec(
            name=self._entity.name,
            description=self._entity.description or self._entity.name,
            parameters=self._parameters,
        )

    async def invoke(self, arguments: dict[str, Any], context: AgentRunContext) -> str:
        if not self._url_template:
            raise ToolExecutionError(f"工具 {self._entity.name} 未配置 url")
        from internal.engine.prompt import render_template

        url = render_template(self._url_template, {**arguments, "tenant_id": str(context.tenant_id or "")})
        method = self._method
        request_headers: dict[str, str] = {
            "Content-Type": "application/json",
            **{k: str(v) for k, v in self._headers.items()},
        }
        gateway_cfg = GatewayConfig.from_config(
            (self._entity.config or {}).get("gateway")
        )
        gateway = get_tool_gateway()
        return await gateway.invoke_http(
            method=method,
            url=url,
            headers=request_headers,
            json_body=arguments if method != "GET" else None,
            params=arguments if method == "GET" else None,
            context=context,
            tool_name=self._entity.name,
            cfg=gateway_cfg,
        )


class McpTool(Tool):
    """MCP 工具：通过 MCP 协议调用外部 boxia-mcp-server。"""

    def __init__(self, entity: ToolEntity) -> None:
        self._entity = entity
        config = entity.config or {}
        self._server_url: str = config.get("server_url") or ""
        self._tool_name: str = config.get("tool_name") or entity.name
        self._parameters: dict[str, Any] = config.get("input_schema") or {
            "type": "object",
            "properties": {},
        }

    @property
    def name(self) -> str:
        return self._entity.name

    def spec(self) -> LLMToolSpec:
        return LLMToolSpec(
            name=self._entity.name,
            description=self._entity.description or self._entity.name,
            parameters=self._parameters,
        )

    async def invoke(self, arguments: dict[str, Any], context: AgentRunContext) -> str:
        if not self._server_url:
            raise ToolExecutionError(f"工具 {self._entity.name} 未配置 server_url")
        from internal.engine.mcp_client import call_tool

        try:
            return await call_tool(self._server_url, self._tool_name, arguments)
        except Exception as exc:  # noqa: BLE001 - McpClientError 已包装
            raise ToolExecutionError(str(exc)) from exc


def build_tools(entities: list[ToolEntity]) -> list[Tool]:
    """根据 Tool 实体列表构造运行期工具集合；未知类型回退为 HTTP 工具。"""
    tools: list[Tool] = []
    for entity in entities:
        if not entity.is_enabled:
            continue
        tool_type = (entity.type or "http").lower()
        if tool_type == "echo":
            tools.append(EchoTool(name=entity.name, description=entity.description))
        elif tool_type == "mcp":
            tools.append(McpTool(entity))
        else:
            tools.append(HttpTool(entity))
    return tools


@dataclass(frozen=True)
class SkillManifest:
    """运行期技能清单：用于渐进式披露。"""

    name: str
    description: str
    content: str


class LoadSkillTool(Tool):
    """内置工具：按需加载某个 skill 的完整执行规则。

    渐进式披露（Progressive Disclosure）：
      - system prompt 里只暴露 skill 清单（name + description）
      - LLM 判断该用哪个 skill 后，通过本工具拿到完整规则
      - 避免把所有 skill 全量塞进 system prompt 导致 token 膨胀
    """

    def __init__(self, skills: list[SkillManifest]) -> None:
        self._skills = {s.name: s for s in skills}

    @property
    def name(self) -> str:
        return "load_skill"

    def spec(self) -> LLMToolSpec:
        return LLMToolSpec(
            name=self.name,
            description=(
                "按名称加载某个已安装技能的完整执行规则。"
                "当你决定使用某个技能时，必须先调用本工具拿到完整规则，"
                "再按规则执行任务。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "要加载的技能名称（来自 system prompt 的技能清单）",
                        "enum": list(self._skills.keys()),
                    }
                },
                "required": ["skill_name"],
            },
        )

    async def invoke(self, arguments: dict[str, Any], context: AgentRunContext) -> str:
        skill_name = str(arguments.get("skill_name") or "").strip()
        skill = self._skills.get(skill_name)
        if skill is None:
            available = "、".join(self._skills.keys()) or "（无可用技能）"
            raise ToolExecutionError(
                f"未找到技能 `{skill_name}`。可用技能：{available}"
            )
        return (
            f"# 技能：{skill.name}\n"
            f"## 简介\n{skill.description}\n\n"
            f"## 完整执行规则\n{skill.content}"
        )
