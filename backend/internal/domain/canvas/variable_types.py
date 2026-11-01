"""A8：类型化变量池类型强制转换。

支持的类型：string / number / boolean / object / array。
未注册的类型或转换失败时返回原始值（宽容模式，不阻塞主流程）。
"""

from __future__ import annotations

import json
from typing import Any


def coerce(value: Any, type_name: str) -> Any:
    """按声明类型把值强制转换；转换失败返回 None 并记 warning。"""
    if value is None:
        return None

    type_name = (type_name or "string").lower()

    if type_name == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)

    if type_name == "number":
        if isinstance(value, (int, float)):
            return value
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    if type_name == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "是")
        return bool(value)

    if type_name == "object":
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {"value": parsed}
            except (json.JSONDecodeError, ValueError):
                return {"value": value}
        return {"value": value}

    if type_name == "array":
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else [parsed]
            except (json.JSONDecodeError, ValueError):
                return [value]
        return [value]

    return value
