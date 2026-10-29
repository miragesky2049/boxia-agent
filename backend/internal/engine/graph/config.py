"""配置合并：字段级版本 + 租户 pin + overrides。"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


def get_effective_config(
    base_config: dict[str, Any],
    field_versions: dict[str, list[dict]],
    tenant_pins: dict[str, int],
    tenant_overrides: dict[str, Any],
) -> dict[str, Any]:
    """计算有效配置：base + 字段版本 + 租户 pin + overrides。

    优先级：tenant_overrides > tenant_pins > field_versions.latest > base_config
    """
    result = _deep_copy(base_config)

    # 应用字段版本
    for field_path, versions in field_versions.items():
        if not versions:
            continue
        pinned_version = tenant_pins.get(field_path)
        if pinned_version:
            version = next((v for v in versions if v["version"] == pinned_version), None)
        else:
            version = versions[-1]  # 最新

        if version:
            _set_by_path(result, field_path, version["value"])

    # 应用租户 overrides
    for field_path, override_data in tenant_overrides.items():
        if isinstance(override_data, dict) and "value" in override_data:
            if not override_data.get("frozen", False):
                _set_by_path(result, field_path, override_data["value"])
        else:
            _set_by_path(result, field_path, override_data)

    return result


def _set_by_path(config: dict, path: str, value: Any) -> None:
    """按点分路径设置 dict 值，支持 graph.nodes.{node_id}.config.xxx 形式。"""
    parts = path.split(".")
    current = config
    for i, part in enumerate(parts[:-1]):
        if part.isdigit():
            part = int(part)
        if isinstance(current, list):
            current = current[part]
        else:
            current = current.setdefault(part, {})
    last = parts[-1]
    if last.isdigit():
        last = int(last)
    if isinstance(current, list):
        current[last] = value
    else:
        current[last] = value


def _deep_copy(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(v) for v in obj]
    return obj
