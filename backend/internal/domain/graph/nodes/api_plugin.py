"""API / 插件节点（coze type=4）。

coze 插件节点是"已注册工具"的引用：节点本身不带 URL / method，而是通过
config.pluginName（或 toolName）指向一个已在工具市场注册的工具，inputs 作为
参数传给工具执行器。

config 约定：
- pluginName / toolName: 工具名（必填）
- description: 工具描述（可选，用于日志和审计）

执行路径：
1. 从 config 取 pluginName；缺 name 直接返回 error。
2. 通过 ctx.services.get("tool_executor") 拿执行器。
   执行器签名：async (name: str, args: dict) -> str
3. ctx.inputs 作为 args 传给执行器。
4. 返回文本作为 output；同时尝试 JSON 解析，解析成功额外给 parsed 字段。

无 tool_executor 时返回 stub（与 LLM / HTTP 节点的开发态降级策略一致）。
"""

from __future__ import annotations

import json
import logging

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


class ApiPluginNodeHandler(NodeHandler):
    type_name = NodeType.API.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        plugin_name = str(
            ctx.config.get("pluginName")
            or ctx.config.get("toolName")
            or ctx.config.get("name")
            or ""
        ).strip()

        if not plugin_name:
            return NodeResult(outputs={"error": "api_plugin 节点缺少 pluginName"})

        args = dict(ctx.inputs or {})

        if not ctx.services.has("tool_executor"):
            logger.info(
                "api_plugin %s 无 tool_executor 服务，返回 stub（args=%s）",
                plugin_name,
                args,
            )
            return NodeResult(
                outputs={
                    "output": f"[plugin stub] {plugin_name}",
                    "plugin": plugin_name,
                    "args": args,
                }
            )

        tool_executor = ctx.services.get("tool_executor")

        try:
            result = await tool_executor(plugin_name, args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("插件调用失败: %s", plugin_name)
            raise RuntimeError(f"插件 {plugin_name} 调用失败: {exc}") from exc

        output_text = result if isinstance(result, str) else str(result)

        outputs: dict[str, object] = {
            "output": output_text,
            "plugin": plugin_name,
        }

        # 尝试 JSON 解析，给下游节点一个结构化字段
        try:
            parsed = json.loads(output_text)
            outputs["parsed"] = parsed
        except (ValueError, TypeError):
            pass

        return NodeResult(outputs=outputs)


register_node_handler(ApiPluginNodeHandler())
