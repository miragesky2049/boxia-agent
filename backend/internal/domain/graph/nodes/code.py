"""Code 节点（coze type=5）：执行用户 Python 代码。

config 约定：
- inputs: 静态输入变量（list[{key,value}] 或 dict），合并进 sandbox.run 的 args
- code: 用户 Python 源码（必须定义 main(args: dict) -> dict）
- timeoutMs: 超时（毫秒，默认 10000）

依赖服务：
- sandbox: PythonSandbox 实例（未注入时走 stub）
"""

from __future__ import annotations

import logging
from typing import Any

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, NodeHandler, NodeResult
from internal.domain.graph.nodes import register_node_handler

logger = logging.getLogger(__name__)


def _parse_config_inputs(raw: Any) -> dict:
    """把 config['inputs'] 规范化为 dict。支持 list[{key,value}] 和 dict。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items()}
    if isinstance(raw, list):
        result = {}
        for item in raw:
            if isinstance(item, dict):
                key = item.get("key") or item.get("name")
                if key:
                    result[str(key)] = item.get("value")
        return result
    return {}


class CodeNodeHandler(NodeHandler):
    type_name = NodeType.CODE.value

    async def run(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        code = str(config.get("code") or "")
        timeout_ms = int(config.get("timeoutMs") or 10_000)

        if not code:
            return NodeResult(outputs={"error": "code 节点缺少 code 配置"})

        # 合并静态输入变量 + 上游动态 inputs（上游覆盖静态同名 key）
        args = _parse_config_inputs(config.get("inputs"))
        args.update(ctx.inputs or {})

        if not ctx.services.has("sandbox"):
            return NodeResult(outputs={
                "stub": f"[Code stub] input={str(args)[:80]}",
            })

        sandbox = ctx.services.get("sandbox")
        # 用 config 级 timeout 覆盖默认值
        result = await sandbox.run(code=code, args=args)

        if result.timed_out:
            raise RuntimeError(f"代码节点执行超时: {timeout_ms}ms")
        if result.exit_code != 0:
            raise RuntimeError(f"代码节点执行失败: {result.stderr[:500]}")

        outputs = dict(result.outputs)
        if "__error__" in outputs:
            raise RuntimeError(f"代码运行时错误: {outputs['__error__'][:500]}")

        return NodeResult(outputs=outputs)


register_node_handler(CodeNodeHandler())
