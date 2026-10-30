"""应用服务：应用市场、自助开通、graph 整图版本、租户 config 覆盖、运行时 graph 解析。

性能设计（对齐 coze / dify）：
- graph 运行时读取走 Redis 缓存（key=`graph:{application_id}:v{version}`）
- save_graph 写新版本后主动失效缓存 + 发布 Pub/Sub 广播
- 租户 config 一次性 mget，不再 N+1
- marketplace cursor 分页，走部分覆盖索引
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from internal.application.errors import NotFoundError, ValidationError
from internal.domain.cache.base import KvCache
from internal.domain.canvas.validate import validate_raw_graph
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.cache.factory import get_kv_cache
from internal.infrastructure.repository.apps.application_repository import ApplicationRepository
from internal.infrastructure.repository.postgres_audit_log_repository import PostgresAuditLogRepository
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _infer_runtime_mode(graph: dict[str, Any]) -> str:
    """根据 coze 画布 JSON 推断运行模式：dag / agent_loop。

    首版简化：含 LLM 节点（coze type=3）即视为 agent_loop，其余 dag。
    """
    for node in graph.get("nodes", []) or []:
        if str(node.get("type")) == "3":
            return "agent_loop"
    return "dag"

GRAPH_CACHE_TTL_SECONDS = 300
GRAPH_INVALIDATE_CHANNEL = "graph:invalidate"
# graph JSONB 超过该阈值时只存 URI（对象存储留给后续接入）
GRAPH_INLINE_SIZE_THRESHOLD = 1024 * 1024  # 1MB


def flatten_config(graph: dict[str, Any]) -> dict[str, Any]:
    """把 graph 中每个节点的 config 展平为 {field_path: value}。"""
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
    try:
        return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
            b, sort_keys=True, ensure_ascii=False
        )
    except TypeError:
        return a == b


def _parse_graph(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


class ApplicationService:
    def __init__(self, uow: UnitOfWork, cache: KvCache | None = None):
        self._uow = uow
        self._repo = ApplicationRepository(uow.session)
        self._cache = cache or get_kv_cache()

    # ========== 缓存 key ==========
    @staticmethod
    def _graph_cache_key(application_id: UUID, version: int | None = None) -> str:
        suffix = f":v{version}" if version is not None else ":latest"
        return f"graph:{application_id}{suffix}"

    # ========== 市场浏览（租户端） ==========
    def list_marketplace(
        self,
        cursor_updated_at: datetime | None = None,
        limit: int = 20,
    ) -> dict:
        """cursor 分页返回市场应用。下一页用最后一条的 updated_at 作 cursor。"""
        rows = self._repo.list_marketplace_paged(cursor_updated_at, limit)
        next_cursor = rows[-1]["updated_at"].isoformat() if rows and len(rows) == limit else None
        return {"items": rows, "next_cursor": next_cursor}

    def subscribe(self, tenant_id: UUID, application_id: UUID) -> dict:
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
        self._uow.commit()
        return {"instance_id": instance_id, "application_id": application_id}

    def list_my_apps(self, tenant_id: UUID) -> list[dict]:
        return self._repo.list_instances(tenant_id)

    def list_applications(
        self,
        owner_type: str | None = None,
        include_marketplace_only: bool = False,
    ) -> list[dict]:
        return self._repo.list_applications(
            owner_type=owner_type,
            include_marketplace_only=include_marketplace_only,
        )

    # ========== 平台管理端 ==========
    def create_platform_application(
        self,
        *,
        name: str,
        description: str = "",
        created_by: UUID | None = None,
    ) -> UUID:
        if not name.strip():
            raise ValidationError("应用名称不能为空")
        app_id = self._repo.create_application(
            name=name.strip(),
            owner_type="platform",
            owner_id=None,
            description=description,
            created_by=created_by,
        )
        self._uow.commit()
        return app_id

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
        self._uow.commit()

    def set_listed_in_market(self, application_id: UUID, listed: bool) -> None:
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        if app["owner_type"] != "platform":
            raise ValidationError("只能上架产品级应用")
        if listed and not app["is_enabled"]:
            raise ValidationError("应用已被禁用，无法上架")
        self._repo.set_listed_in_market(application_id, listed)
        self._uow.commit()

    def set_enabled(self, application_id: UUID, enabled: bool) -> None:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        self._repo.set_enabled(application_id, enabled)
        self._uow.commit()

    # ========== 数据可见范围（保持原逻辑） ==========
    def get_visibility(self, application_id: UUID) -> dict:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        return self._repo.get_application_visibility(application_id)

    def replace_visibility(
        self,
        application_id: UUID,
        *,
        mode: str,
        departments: list[dict] | None = None,
        users: list[UUID] | None = None,
    ) -> dict:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        if mode not in ("all", "custom"):
            raise ValidationError("visibility_mode 只能是 all 或 custom")

        depts = departments or []
        uids = users or []
        if mode == "custom" and not depts and not uids:
            raise ValidationError("自定义可见范围至少需要指定一个部门或用户")

        norm_depts: list[dict] = []
        for d in depts:
            did = d.get("department_id")
            if isinstance(did, str):
                did = UUID(did)
            norm_depts.append(
                {"department_id": did, "include_subtree": bool(d.get("include_subtree", True))}
            )

        norm_uids: list[UUID] = []
        for u in uids:
            norm_uids.append(UUID(u) if isinstance(u, str) else u)

        self._repo.replace_application_visibility(application_id, mode, norm_depts, norm_uids)
        self._uow.commit()
        return self._repo.get_application_visibility(application_id)

    # ========== graph 整图版本（新 hot path） ==========
    def save_graph(
        self,
        application_id: UUID,
        graph: dict[str, Any],
        changelog: str = "",
        actor_id: UUID | None = None,
        actor_username: str = "",
    ) -> dict:
        """保存 graph：写入新版本（整图快照），写审计，失效缓存，发布广播。"""
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        if not graph.get("nodes"):
            raise ValidationError("graph 至少需要一个节点")

        # A11: 保存前结构校验，error 级问题阻塞保存
        issues = validate_raw_graph(graph)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            detail = "; ".join(i.message for i in errors)
            raise ValidationError(f"画布校验不通过：{detail}")

        runtime_mode = _infer_runtime_mode(graph)
        latest = self._repo.get_latest_graph_version(application_id)
        previous_version = latest["version"] if latest else 0
        next_version = previous_version + 1

        # P2-8: 大 graph 预留对象存储 URI 接口（当前先内联写 JSONB）
        graph_size = len(json.dumps(graph, ensure_ascii=False))
        if graph_size > GRAPH_INLINE_SIZE_THRESHOLD:
            logger.info(
                "graph 超过内联阈值 %d bytes，预留对象存储 URI: app=%s size=%d",
                GRAPH_INLINE_SIZE_THRESHOLD, application_id, graph_size,
            )

        self._repo.insert_graph_version(
            application_id=application_id,
            version=next_version,
            graph=graph,
            runtime_mode=runtime_mode,
            changelog=changelog,
            created_by=actor_id,
        )
        # 同步更新 application_graph（兼容旧读取）
        self._repo.update_graph(application_id, graph, runtime_mode)

        # P2-7: 写审计日志（平台级操作使用 PLATFORM_TENANT_ID，audit_logs.tenant_id 不允许 NULL）
        audit_repo = PostgresAuditLogRepository(self._uow.session)
        audit_repo.record({
            "actor_id": actor_id,
            "actor_username": actor_username,
            "action": "GRAPH_SAVE",
            "resource_type": "application",
            "resource_id": str(application_id),
            "tenant_id": PLATFORM_TENANT_ID,
            "detail": {
                "previous_version": previous_version,
                "new_version": next_version,
                "runtime_mode": runtime_mode,
                "changelog": changelog,
                "node_count": len(graph.get("nodes", [])),
                "size_bytes": graph_size,
            },
        })

        self._uow.commit()

        # 失效缓存 + 广播
        self._invalidate_graph_cache(application_id)
        return {"runtime_mode": runtime_mode, "version": next_version}

    def get_graph(self, application_id: UUID) -> dict | None:
        """读取最新版本的 graph 整图快照；没有则返回 None。"""
        latest = self._repo.get_latest_graph_version(application_id)
        if latest is None:
            return None
        graph = _parse_graph(latest["graph"])
        return {
            "graph": graph,
            "runtime_mode": latest.get("runtime_mode", "dag"),
            "graph_schema_version": latest.get("version", 1),
        }

    def list_graph_versions(self, application_id: UUID, limit: int = 50) -> list[dict]:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        return self._repo.list_graph_versions(application_id, limit)

    def rollback_graph(self, application_id: UUID, version: int) -> dict:
        """回滚到指定历史版本：把该版本 graph 作为新版本再写一次。"""
        record = self._repo.get_graph_version(application_id, version)
        if record is None:
            raise NotFoundError("指定 graph 版本不存在")
        graph = _parse_graph(record["graph"])
        return self.save_graph(application_id, graph, changelog=f"回滚到版本 {version}")

    # ========== 运行时 graph（缓存 hot path） ==========
    async def get_runtime_graph(
        self,
        application_id: UUID,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """运行时 graph：Redis 缓存命中即返回；miss 回 DB，应用租户 config 覆盖。"""
        # 1. 读 latest version
        latest = self._repo.get_latest_graph_version(application_id)
        if latest is None:
            raise NotFoundError("graph 不存在")
        latest_version = latest["version"]

        # 2. 解析租户是否 pin 了版本
        pinned_version = latest_version
        if tenant_id is not None:
            inst = self._repo.get_instance(tenant_id, application_id)
            if inst and inst.get("pinned_graph_version"):
                pinned_version = int(inst["pinned_graph_version"])

        # 3. 查缓存（key 含 version，天然按版本隔离）
        cache_key = self._graph_cache_key(application_id, pinned_version)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            graph = cached.get("graph") or {}
        else:
            version_record = self._repo.get_graph_version(application_id, pinned_version)
            if version_record is None:
                raise NotFoundError(f"graph 版本 {pinned_version} 不存在")
            graph = _parse_graph(version_record["graph"])
            await self._cache.set(
                cache_key,
                {"graph": graph, "runtime_mode": version_record["runtime_mode"]},
                ttl_seconds=GRAPH_CACHE_TTL_SECONDS,
            )

        # 4. 应用租户 config 覆盖（一次性读，不再 N+1）
        if tenant_id is not None:
            tenant_config = self._repo.list_tenant_config(tenant_id, application_id)
            graph = self._apply_config_overrides(graph, tenant_config)

        return graph

    def build_effective_graph_sync(
        self,
        application_id: UUID,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """同步版本：HTTP router 里没有 async context 时用。

        直接走 DB，跳过缓存（运行时 hot path 一般是异步 router 调用）。
        """
        latest = self._repo.get_latest_graph_version(application_id)
        if latest is None:
            raise NotFoundError("graph 不存在")
        pinned_version = latest["version"]
        if tenant_id is not None:
            inst = self._repo.get_instance(tenant_id, application_id)
            if inst and inst.get("pinned_graph_version"):
                pinned_version = int(inst["pinned_graph_version"])

        version_record = self._repo.get_graph_version(application_id, pinned_version)
        if version_record is None:
            raise NotFoundError(f"graph 版本 {pinned_version} 不存在")
        graph = _parse_graph(version_record["graph"])

        if tenant_id is not None:
            tenant_config = self._repo.list_tenant_config(tenant_id, application_id)
            graph = self._apply_config_overrides(graph, tenant_config)
        return graph

    @staticmethod
    def _apply_config_overrides(graph: dict[str, Any], tenant_config: dict[str, Any]) -> dict[str, Any]:
        """把 tenant_config 里的 key 形如 graph.nodes.{node_id}.config.{field} 覆盖到 graph 上。"""
        if not tenant_config:
            return graph
        nodes_copy: list[dict[str, Any]] = []
        for node in graph.get("nodes", []):
            nodes_copy.append({**node, "config": {**(node.get("config") or {})}})

        for path, value in tenant_config.items():
            parts = path.split(".")
            if len(parts) < 5 or parts[0] != "graph" or parts[1] != "nodes" or parts[3] != "config":
                continue
            node_id = parts[2]
            field = ".".join(parts[4:])
            for node in nodes_copy:
                if node.get("id") == node_id:
                    node["config"][field] = value
                    break
        return {**graph, "nodes": nodes_copy}

    # ========== 租户 config 覆盖（替代旧 pin_field） ==========
    def set_tenant_config(
        self,
        tenant_id: UUID,
        application_id: UUID,
        config_key: str,
        config_value: Any,
    ) -> None:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        self._repo.upsert_tenant_config(tenant_id, application_id, config_key, config_value)
        self._uow.commit()
        self._invalidate_graph_cache(application_id)

    def delete_tenant_config(
        self,
        tenant_id: UUID,
        application_id: UUID,
        config_key: str,
    ) -> None:
        self._repo.delete_tenant_config(tenant_id, application_id, config_key)
        self._uow.commit()
        self._invalidate_graph_cache(application_id)

    def pin_graph_version(
        self,
        tenant_id: UUID,
        application_id: UUID,
        version: int | None,
    ) -> None:
        """租户锁定整图版本；version=None 回到 latest。"""
        if version is not None:
            record = self._repo.get_graph_version(application_id, version)
            if record is None:
                raise NotFoundError(f"graph 版本 {version} 不存在")
        self._repo.pin_graph_version(tenant_id, application_id, version)
        self._uow.commit()
        self._invalidate_graph_cache(application_id)

    # ========== user 端可见性 ==========
    def list_visible_apps_for_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        keyword: str | None = None,
    ) -> list[dict]:
        """当前用户可见应用 = 本租户自建 + 已开通的产品级实例，叠加 visibility 白名单/部门过滤。"""
        params: dict[str, Any] = {"tid": str(tenant_id), "uid": str(user_id)}
        kw_clause = ""
        if keyword:
            kw_clause = " AND a.name ILIKE :kw"
            params["kw"] = f"%{keyword}%"

        rows = self._uow.session.execute(
            text(
                f"""
                SELECT a.id, a.name, a.avatar_url, a.description, a.is_enabled
                FROM application a
                WHERE a.is_enabled = true
                  AND (
                    a.owner_type = 'tenant' AND a.owner_id = :tid
                    OR a.id IN (
                        SELECT application_id FROM tenant_application_instance
                        WHERE tenant_id = :tid AND status = 'active'
                    )
                  )
                  AND (
                    a.visibility_mode = 'all'
                    OR a.id IN (
                        SELECT application_id FROM application_visibility_users
                        WHERE user_id = :uid
                    )
                    OR a.id IN (
                        SELECT avd.application_id
                        FROM application_visibility_departments avd
                        JOIN user_employments ue ON ue.tenant_id = :tid
                        JOIN departments d ON d.id = ue.department_id AND d.tenant_id = :tid
                        WHERE ue.user_id = :uid
                          AND ue.is_current = true
                          AND avd.department_id = ue.department_id
                        UNION
                        SELECT avd.application_id
                        FROM application_visibility_departments avd
                        JOIN departments target_d ON target_d.id = avd.department_id
                        JOIN user_employments ue ON ue.tenant_id = :tid
                        JOIN departments d ON d.id = ue.department_id AND d.tenant_id = :tid
                        WHERE ue.user_id = :uid
                          AND ue.is_current = true
                          AND avd.include_subtree = true
                          AND d.path LIKE '/' || target_d.id::text || '/%'
                    )
                  )
                  {kw_clause}
                GROUP BY a.id, a.name, a.avatar_url, a.description, a.is_enabled, a.updated_at
                ORDER BY a.updated_at DESC
                """
            ),
            params,
        ).all()
        return [
            {
                "id": str(r._mapping["id"]),
                "name": r._mapping["name"],
                "avatar_url": r._mapping["avatar_url"] or "",
                "description": r._mapping["description"] or "",
                "is_enabled": r._mapping["is_enabled"],
            }
            for r in rows
        ]

    def get_visible_app_for_user(
        self,
        application_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> dict | None:
        """单个应用：用户是否可见。返回卡片 dict 或 None。"""
        items = self.list_visible_apps_for_user(tenant_id, user_id)
        return next((it for it in items if it["id"] == str(application_id)), None)

    def assert_user_can_view(
        self,
        application_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> dict:
        """用户访问应用前的鉴权闸门：不可见抛 NotFoundError。"""
        app = self.get_visible_app_for_user(application_id, tenant_id, user_id)
        if app is None:
            raise NotFoundError("应用不存在或未开通")
        return app

    # ========== 缓存失效 + 广播 ==========
    def _invalidate_graph_cache(self, application_id: UUID) -> None:
        """失效本地 + 广播其它节点。同步上下文里 fire-and-forget，吞掉异常不阻塞主流程。"""
        import asyncio
        import logging

        async def _run() -> None:
            # 清 latest 和所有已缓存 version
            await self._cache.delete(self._graph_cache_key(application_id, None))
            await self._cache.publish(GRAPH_INVALIDATE_CHANNEL, str(application_id))

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # threadpool 线程里没有 running loop：fire-and-forget，不阻塞
            try:
                asyncio.run(_run())
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning("graph cache invalidate failed: %s", exc)
            return
        loop.create_task(_run())


def build_effective_graph_compat(uow: UnitOfWork, application_id: UUID, tenant_id: UUID | None) -> dict[str, Any]:
    """兼容旧调用点（router 里同步调用）：走 build_effective_graph_sync。"""
    return ApplicationService(uow).build_effective_graph_sync(application_id, tenant_id)
