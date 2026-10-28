"""v4 应用服务：应用市场浏览、自助开通、我的应用列表、平台管理、字段级版本。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from internal.application.errors import NotFoundError, ValidationError
from internal.engine.v4.compiler import infer_runtime_mode
from internal.infrastructure.repository.v4.application_repository import V4ApplicationRepository


def flatten_config(graph: dict[str, Any]) -> dict[str, Any]:
    """把 graph 中每个节点的 config 展平为 {field_path: value}。

    field_path 约定：graph.nodes.{node_id}.config.{field}
    复杂对象（数组/嵌套对象）整体作为一个 value，不深入展开。
    """
    result: dict[str, Any] = {}
    for node in graph.get("nodes", []) or []:
        node_id = node.get("id")
        if not node_id:
            continue
        config = node.get("config") or {}
        if not isinstance(config, dict):
            continue
        for field, value in config.items():
            path = f"graph.nodes.{node_id}.config.{field}"
            result[path] = value
    return result


def values_equal(a: Any, b: Any) -> bool:
    """JSON 规范化比较：dict/list 序列化后比对，避免键序差异误判。"""
    try:
        return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
            b, sort_keys=True, ensure_ascii=False
        )
    except TypeError:
        return a == b


class V4ApplicationService:
    def __init__(self, session: Session):
        self._repo = V4ApplicationRepository(session)

    # ========== 市场浏览（租户端） ==========
    def list_marketplace(self) -> list[dict]:
        """列出应用市场中所有产品级应用。"""
        return self._repo.list_marketplace()

    def subscribe(self, tenant_id: UUID, application_id: UUID) -> dict:
        """租户自助开通一个产品级应用。"""
        existing = self._repo.get_instance(tenant_id, application_id)
        if existing:
            raise ValidationError("该应用已开通")

        app = self._repo.get_application(application_id)
        if not app:
            raise NotFoundError("应用不存在")
        if app["owner_type"] != "platform":
            raise ValidationError("只能开通产品级应用")
        if not app["is_listed_in_market"]:
            raise ValidationError("该应用未上架市场")
        if not app["is_enabled"]:
            raise ValidationError("该应用已被禁用")

        instance_id = self._repo.subscribe(tenant_id, application_id)
        return {"instance_id": instance_id, "application_id": application_id}

    def list_my_apps(self, tenant_id: UUID) -> list[dict]:
        """租户查看自己已开通的应用列表。"""
        return self._repo.list_instances(tenant_id)

    # ========== graph 读取 ==========
    def get_graph(self, application_id: UUID) -> dict | None:
        """获取应用的 graph 定义。"""
        return self._repo.get_graph(application_id)

    # ========== 平台管理端 ==========
    def create_platform_application(
        self,
        *,
        name: str,
        description: str = "",
        created_by: UUID | None = None,
    ) -> UUID:
        """平台管理员创建新应用（未上架）。"""
        if not name.strip():
            raise ValidationError("应用名称不能为空")
        return self._repo.create_application(
            name=name.strip(),
            owner_type="platform",
            owner_id=None,
            description=description,
            created_by=created_by,
        )

    def update_application(
        self,
        application_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        self._repo.update_application(
            application_id, name=name, description=description, avatar_url=avatar_url
        )

    def set_listed_in_market(self, application_id: UUID, listed: bool) -> None:
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        if app["owner_type"] != "platform":
            raise ValidationError("只能上架产品级应用")
        if listed and not app["is_enabled"]:
            raise ValidationError("应用已被禁用，无法上架")
        self._repo.set_listed_in_market(application_id, listed)

    def set_enabled(self, application_id: UUID, enabled: bool) -> None:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        self._repo.set_enabled(application_id, enabled)

    def save_graph(self, application_id: UUID, graph: dict[str, Any]) -> dict[str, Any]:
        """保存 graph 定义，自动推断 runtime_mode，并对变化的 config 字段写入新版本。

        Returns:
            {"runtime_mode": str, "versioned_fields": [{path, old, new, version}]}
        """
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        if not graph.get("nodes"):
            raise ValidationError("graph 至少需要一个节点")
        runtime_mode = infer_runtime_mode(graph)

        old_record = self._repo.get_graph(application_id)
        old_graph: dict[str, Any] = {}
        if old_record and old_record.get("graph"):
            raw = old_record["graph"]
            if isinstance(raw, str):
                old_graph = json.loads(raw)
            else:
                old_graph = raw

        self._repo.update_graph(application_id, graph, runtime_mode)

        versioned = self._snapshot_changed_fields(application_id, old_graph, graph)
        return {"runtime_mode": runtime_mode, "versioned_fields": versioned}

    def _snapshot_changed_fields(
        self,
        application_id: UUID,
        old_graph: dict[str, Any],
        new_graph: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """diff 新旧 graph 的 config 字段，把变化字段写入 application_field_version。"""
        old_flat = flatten_config(old_graph)
        new_flat = flatten_config(new_graph)
        latest = self._repo.get_latest_field_versions(application_id)

        changed: list[dict[str, Any]] = []
        # 新增 / 修改的字段
        for path, new_value in new_flat.items():
            old_value = old_flat.get(path)
            if values_equal(old_value, new_value):
                continue
            current = latest.get(path)
            next_version = (current["version"] if current else 0) + 1
            self._repo.insert_field_version(
                application_id=application_id,
                field_path=path,
                version=next_version,
                value=new_value,
                changelog=self._describe_change(old_value, new_value),
            )
            changed.append(
                {
                    "path": path,
                    "old": old_value,
                    "new": new_value,
                    "version": next_version,
                }
            )
        # 删除的字段：也记录一个 null 版本，保留历史可追溯
        for path, old_value in old_flat.items():
            if path not in new_flat:
                current = latest.get(path)
                next_version = (current["version"] if current else 0) + 1
                self._repo.insert_field_version(
                    application_id=application_id,
                    field_path=path,
                    version=next_version,
                    value=None,
                    changelog=f"字段被删除（旧值：{self._short(old_value)}）",
                )
                changed.append(
                    {
                        "path": path,
                        "old": old_value,
                        "new": None,
                        "version": next_version,
                    }
                )
        return changed

    @staticmethod
    def _describe_change(old: Any, new: Any) -> str:
        if old is None:
            return f"新增字段，初值：{V4ApplicationService._short(new)}"
        return f"{V4ApplicationService._short(old)} -> {V4ApplicationService._short(new)}"

    @staticmethod
    def _short(value: Any, limit: int = 80) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            text = str(value)
        return text if len(text) <= limit else text[: limit - 1] + "…"

    # ========== 字段版本查询 ==========
    def list_field_versions(
        self,
        application_id: UUID,
        field_path: str | None = None,
    ) -> list[dict]:
        """列出某应用（或某字段）的版本历史。"""
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        return self._repo.list_field_versions(application_id, field_path)

    # ========== 租户字段 pin ==========
    def pin_field(
        self,
        tenant_id: UUID,
        application_id: UUID,
        field_path: str,
        version: int,
    ) -> None:
        """租户把某字段锁定在指定版本。"""
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        record = self._repo.get_field_version(application_id, field_path, version)
        if record is None:
            raise NotFoundError("指定字段版本不存在")
        self._repo.upsert_pin(tenant_id, application_id, field_path, version)

    def unpin_field(
        self,
        tenant_id: UUID,
        application_id: UUID,
        field_path: str,
    ) -> None:
        """租户取消 pin，回到 latest。"""
        self._repo.delete_pin(tenant_id, application_id, field_path)

    def list_pins(self, tenant_id: UUID, application_id: UUID) -> list[dict]:
        return self._repo.list_pins(tenant_id, application_id)

    def get_effective_config(
        self,
        application_id: UUID,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """计算某个租户视角下的生效 config。

        - 无 tenant_id：返回 latest 版本
        - 有 tenant_id：pin 字段用 pinned 版本，其余用 latest
        """
        latest = self._repo.get_latest_field_versions(application_id)
        pins_by_path: dict[str, int] = {}
        if tenant_id is not None:
            for p in self._repo.list_pins(tenant_id, application_id):
                pins_by_path[p["field_path"]] = p["pinned_version"]

        effective: dict[str, Any] = {}
        for path, current in latest.items():
            pinned_version = pins_by_path.get(path)
            if pinned_version is not None and pinned_version != current["version"]:
                pinned_record = self._repo.get_field_version(
                    application_id, path, pinned_version
                )
                effective[path] = {
                    "version": pinned_version,
                    "value": pinned_record["value"] if pinned_record else current["value"],
                    "pinned": True,
                }
            else:
                effective[path] = {
                    "version": current["version"],
                    "value": current["value"],
                    "pinned": False,
                }
        return effective

    def build_effective_graph(
        self,
        application_id: UUID,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """加载 graph 并按 tenant 的 pin 字段覆盖 config，返回可直接编译的 graph。

        不 mutate 原 graph；只对 pin 字段（pinned=True 且 version != latest）做覆盖。
        """
        record = self._repo.get_graph(application_id)
        if record is None:
            raise NotFoundError("graph 不存在")
        raw = record["graph"]
        graph: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else raw

        effective = self.get_effective_config(application_id, tenant_id)
        if not effective:
            return graph

        # 深拷贝 nodes，只覆盖被 pin 的字段
        nodes_copy: list[dict[str, Any]] = []
        for node in graph.get("nodes", []):
            node_copy = {**node, "config": {**(node.get("config") or {})}}
            nodes_copy.append(node_copy)

        for path, info in effective.items():
            if not info.get("pinned"):
                continue
            # field_path 形如 graph.nodes.{node_id}.config.{field}
            parts = path.split(".")
            if len(parts) < 5 or parts[0] != "graph" or parts[1] != "nodes" or parts[3] != "config":
                continue
            node_id = parts[2]
            field = ".".join(parts[4:])
            for node in nodes_copy:
                if node.get("id") == node_id:
                    node["config"][field] = info["value"]
                    break

        return {**graph, "nodes": nodes_copy}

    def list_applications(
        self,
        owner_type: str | None = None,
        include_marketplace_only: bool = False,
    ) -> list[dict]:
        """平台管理端列表。"""
        return self._repo.list_applications(
            owner_type=owner_type,
            include_marketplace_only=include_marketplace_only,
        )
