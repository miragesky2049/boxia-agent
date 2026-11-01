"""节点元数据 API：给前端节点库动态渲染用。

GET /api/v1/admin/node-meta
  返回全部已登记节点类型，含端口、配置表单字段 schema。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends

from internal.domain.canvas.node_meta import list_node_metas
from web.deps.auth import require_admin

router = APIRouter(prefix="/node-meta", tags=["node-meta"], dependencies=[Depends(require_admin)])


@router.get("")
def list_node_meta() -> dict[str, Any]:
    """返回全部节点元数据，按 category 分组。"""
    metas = [asdict(meta) for meta in list_node_metas()]
    categories: dict[str, list[dict]] = {}
    for meta in metas:
        cat = meta.get("category", "other")
        categories.setdefault(cat, []).append(meta)
    return {
        "items": metas,
        "categories": categories,
    }
