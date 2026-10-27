"""Prompt 模板渲染：{{var}} 语法，与 dify SimplePromptTransform 风格一致。"""

from __future__ import annotations

import re
from typing import Any

_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_template(template: str, variables: dict[str, Any]) -> str:
    """把 {{var}} 占位符替换为变量值；未提供的变量替换为空串。"""

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = variables.get(name, "")
        if value is None:
            return ""
        return str(value)

    return _VAR_PATTERN.sub(_replace, template or "")


def extract_variables(template: str) -> set[str]:
    """提取模板中出现的全部变量名（用于校验必填变量）。"""
    return {match.group(1) for match in _VAR_PATTERN.finditer(template or "")}
