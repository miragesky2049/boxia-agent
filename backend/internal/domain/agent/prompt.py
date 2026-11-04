"""Prompt 模板渲染：{{var}} 与 {{node_id.field}} 点号语法。

- ``{{var}}``：从全局 variables 字典取值（保留旧行为，兼容现有 Prompt 模板）。
- ``{{node_id.field}}``：从上游节点输出 ``ctx.node_outputs[node_id][field]`` 取值。

设计约束：用正则替换，不引入 eval / jinja2，避免模板注入风险。
"""

from __future__ import annotations

import json
import re
from typing import Any

# 匹配 {{name}} 或 {{node_id.field}}；name / node_id / field 都必须是合法标识符。
_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\s*\}\}")


def render_template(
    template: str,
    variables: dict[str, Any],
    node_outputs: dict[str, dict[str, Any]] | None = None,
) -> str:
    """渲染模板；未提供的占位符替换为空串。"""

    def _replace(match: re.Match[str]) -> str:
        expr = match.group(1)
        if "." in expr:
            if node_outputs is None:
                return ""
            node_id, field = expr.split(".", 1)
            node_output = node_outputs.get(node_id) or {}
            value = node_output.get(field, "")
        else:
            value = variables.get(expr, "")
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return _VAR_PATTERN.sub(_replace, template or "")


def extract_variables(template: str) -> set[str]:
    """提取模板中出现的全部占位符表达式（用于校验必填变量）。"""
    return {match.group(1) for match in _VAR_PATTERN.finditer(template or "")}
