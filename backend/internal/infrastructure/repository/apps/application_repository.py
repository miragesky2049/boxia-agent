"""应用仓储：application + application_graph + tenant_instance。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


def _load_json_array(raw: Any) -> list[dict[str, Any]]:
    """JSONB 列 → list[dict]；兼容驱动返回字符串/None 的情况。"""
    value = _load_json_value(raw)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _load_json_value(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (list, dict, int, float, bool)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw
    return raw


class ApplicationRepository:
    """应用仓储，用原生 SQL 操作新表。"""

    def __init__(self, session: Session):
        self._session = session

    # ========== application CRUD ==========
    def create_application(
        self,
        name: str,
        owner_type: str,
        owner_id: UUID | None,
        description: str = "",
        created_by: UUID | None = None,
        flow_type: str = "workflow",
        visibility_template: str = "all",
        visibility_lock: bool = False,
        admin_scope_mode: str = "creator_only",
    ) -> UUID:
        app_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO application "
                "(id, owner_type, owner_id, name, description, created_by, flow_type, "
                "visibility_template, visibility_lock, admin_scope_mode) "
                "VALUES (:id, :owner_type, :owner_id, :name, :description, :created_by, :flow_type, "
                ":visibility_template, :visibility_lock, :admin_scope_mode)"
            ),
            {
                "id": app_id,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "name": name,
                "description": description,
                "created_by": created_by,
                "flow_type": flow_type,
                "visibility_template": visibility_template,
                "visibility_lock": visibility_lock,
                "admin_scope_mode": admin_scope_mode,
            },
        )
        return app_id

    def update_application(
        self,
        application_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        avatar_url: str | None = None,
        flow_type: str | None = None,
        visibility_template: str | None = None,
        visibility_lock: bool | None = None,
        admin_scope_mode: str | None = None,
    ) -> None:
        sets: list[str] = ["updated_at = NOW()"]
        params: dict[str, Any] = {"id": application_id}
        if name is not None:
            sets.append("name = :name")
            params["name"] = name
        if description is not None:
            sets.append("description = :description")
            params["description"] = description
        if avatar_url is not None:
            sets.append("avatar_url = :avatar_url")
            params["avatar_url"] = avatar_url
        if flow_type is not None:
            sets.append("flow_type = :flow_type")
            params["flow_type"] = flow_type
        if visibility_template is not None:
            sets.append("visibility_template = :visibility_template")
            params["visibility_template"] = visibility_template
        if visibility_lock is not None:
            sets.append("visibility_lock = :visibility_lock")
            params["visibility_lock"] = visibility_lock
        if admin_scope_mode is not None:
            sets.append("admin_scope_mode = :admin_scope_mode")
            params["admin_scope_mode"] = admin_scope_mode
        self._session.execute(
            text(f"UPDATE application SET {', '.join(sets)} WHERE id = :id"),
            params,
        )

    def set_listed_in_market(self, application_id: UUID, listed: bool) -> None:
        self._session.execute(
            text(
                "UPDATE application SET is_listed_in_market = :listed, updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"listed": listed, "id": application_id},
        )

    def set_enabled(self, application_id: UUID, enabled: bool) -> None:
        self._session.execute(
            text(
                "UPDATE application SET is_enabled = :enabled, updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"enabled": enabled, "id": application_id},
        )

    def get_application(self, application_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, owner_type, owner_id, name, avatar_url, description, is_enabled, "
                "is_listed_in_market, sale_mode, visibility_lock, visibility_template, "
                "admin_scope_mode, published_graph_version, "
                "flow_type, created_by, created_at, updated_at "
                "FROM application WHERE id = :aid"
            ),
            {"aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    # ========== v2 可见范围：app_visibility_scope + app_visibility_whitelist ==========
    def get_tenant_scope(self, application_id: UUID, tenant_id: UUID) -> dict | None:
        """读取某应用在某租户的可见范围配置（含白名单明细）。无记录返回 None。"""
        row = self._session.execute(
            text(
                """
                SELECT id, visibility, created_at, updated_at
                FROM app_visibility_scope
                WHERE application_id = :aid AND tenant_id = :tid
                """
            ),
            {"aid": str(application_id), "tid": str(tenant_id)},
        ).first()
        if row is None:
            return None
        scope_id = row._mapping["id"]
        wl_rows = self._session.execute(
            text(
                """
                SELECT subject_type, subject_id, include_subtree
                FROM app_visibility_whitelist
                WHERE scope_id = :sid
                ORDER BY created_at
                """
            ),
            {"sid": str(scope_id)},
        ).all()
        return {
            "id": str(scope_id),
            "visibility": row._mapping["visibility"],
            "whitelist": [
                {
                    "subject_type": r._mapping["subject_type"],
                    "subject_id": str(r._mapping["subject_id"]),
                    "include_subtree": r._mapping["include_subtree"],
                }
                for r in wl_rows
            ],
        }

    def upsert_tenant_scope(
        self,
        application_id: UUID,
        tenant_id: UUID,
        visibility: str,
        whitelist: list[dict],
    ) -> dict:
        """整体覆盖写入可见范围：upsert scope 行 + 清空并重写 whitelist。

        使用 ON CONFLICT 兜底并发：两个请求同时首次写入时，唯一约束
        (application_id, tenant_id) 让后到的请求走 DO UPDATE 分支，不会报 23505。
        """
        scope_pk = self._session.execute(
            text(
                """
                INSERT INTO app_visibility_scope (id, application_id, tenant_id, visibility)
                VALUES (:sid, :aid, :tid, :vis)
                ON CONFLICT (application_id, tenant_id)
                DO UPDATE SET visibility = EXCLUDED.visibility, updated_at = now()
                RETURNING id
                """
            ),
            {
                "sid": str(new_uuid()),
                "aid": str(application_id),
                "tid": str(tenant_id),
                "vis": visibility,
            },
        ).scalar_one()
        scope_id = str(scope_pk)

        self._session.execute(
            text("DELETE FROM app_visibility_whitelist WHERE scope_id = :sid"),
            {"sid": scope_id},
        )

        if visibility == "whitelist":
            for item in whitelist:
                self._session.execute(
                    text(
                        """
                        INSERT INTO app_visibility_whitelist
                            (id, scope_id, subject_type, subject_id, include_subtree)
                        VALUES
                            (:id, :sid, :stype, :sub_id, :sub)
                        """
                    ),
                    {
                        "id": str(new_uuid()),
                        "sid": scope_id,
                        "stype": item["subject_type"],
                        "sub_id": str(item["subject_id"]),
                        "sub": item.get("include_subtree", False),
                    },
                )

        # 回读走 get_tenant_scope，保证与 GET 接口返回结构一致（id/visibility/whitelist）
        return {
            "id": scope_id,
            "visibility": visibility,
            "whitelist": [
                {
                    "subject_type": item["subject_type"],
                    "subject_id": str(item["subject_id"]),
                    "include_subtree": bool(item.get("include_subtree", False)),
                }
                for item in (whitelist if visibility == "whitelist" else [])
            ],
        }

    def ensure_scope_on_subscribe(self, application_id: UUID, tenant_id: UUID) -> None:
        """租户订阅产品级应用时调用：无 scope 则按平台 visibility_template 初始化。

        一期策略：不依赖显式钩子，list_visible_for_user 对缺失 scope 已按模板惰性兜底；
        本方法保留供未来显式 hook（3 处订阅创建点 / 租户级应用创建）使用。
        """
        row = self._session.execute(
            text("SELECT visibility_template FROM application WHERE id = :aid"),
            {"aid": str(application_id)},
        ).first()
        template = row._mapping["visibility_template"] if row else "all"
        self._session.execute(
            text(
                """
                INSERT INTO app_visibility_scope (id, application_id, tenant_id, visibility)
                VALUES (:id, :aid, :tid, :vis)
                ON CONFLICT (application_id, tenant_id) DO NOTHING
                """
            ),
            {
                "id": str(new_uuid()),
                "aid": str(application_id),
                "tid": str(tenant_id),
                "vis": template,
            },
        )

    def list_subscribed_apps_for_admin(self, tenant_id: UUID) -> list[dict]:
        """列出当前租户已订阅（生效中）的产品级应用，供租户管理端配置可见范围。

        LEFT JOIN 本租户 scope：未配置时 configured=false，
        visibility 回退平台模板值，便于列表直接渲染当前生效范围标签。
        """
        rows = self._session.execute(
            text(
                """
                SELECT a.id, a.name, a.avatar_url, a.description,
                       a.visibility_lock, a.visibility_template,
                       a.admin_scope_mode, a.created_by,
                       s.id IS NOT NULL AS configured,
                       COALESCE(s.visibility, a.visibility_template) AS visibility,
                       COALESCE((
                           SELECT count(*) FROM app_visibility_whitelist w
                           WHERE w.scope_id = s.id
                       ), 0) AS whitelist_count
                FROM application a
                JOIN tenant_application_instance t ON t.application_id = a.id
                LEFT JOIN app_visibility_scope s
                    ON s.application_id = a.id AND s.tenant_id = :tid
                WHERE t.tenant_id = :tid
                  AND t.status = 'active'
                  AND (t.start_time IS NULL OR t.start_time <= now())
                  AND (t.expire_time IS NULL OR t.expire_time > now())
                  AND a.owner_type = 'platform'
                  AND a.is_enabled = true
                ORDER BY a.updated_at DESC
                """
            ),
            {"tid": str(tenant_id)},
        ).all()
        return [
            {
                "id": str(r._mapping["id"]),
                "name": r._mapping["name"],
                "avatar_url": r._mapping["avatar_url"] or "",
                "description": r._mapping["description"] or "",
                "visibility_lock": r._mapping["visibility_lock"],
                "visibility_template": r._mapping["visibility_template"],
                "admin_scope_mode": r._mapping["admin_scope_mode"],
                "created_by": (
                    str(r._mapping["created_by"]) if r._mapping["created_by"] else None
                ),
                "configured": r._mapping["configured"],
                "visibility": r._mapping["visibility"],
                "whitelist_count": int(r._mapping["whitelist_count"]),
            }
            for r in rows
        ]

    # ========== 变量体系 ==========
    def get_application_variables(self, application_id: UUID) -> list[dict[str, Any]]:
        """读取应用变量定义（name/type/default/scope）。"""
        row = self._session.execute(
            text("SELECT variables FROM application WHERE id = :aid"),
            {"aid": application_id},
        ).first()
        if row is None:
            return []
        return _load_json_array(row[0])

    def set_application_variables(
        self,
        application_id: UUID,
        variables: list[dict[str, Any]],
    ) -> None:
        self._session.execute(
            text(
                "UPDATE application SET variables = CAST(:variables AS JSONB), updated_at = NOW() "
                "WHERE id = :aid"
            ),
            {"aid": application_id, "variables": json.dumps(variables, ensure_ascii=False, default=str)},
        )

    def get_user_variables(self, application_id: UUID, user_id: UUID) -> dict[str, Any]:
        """读取用户变量实际取值；缺失的键由调用方回退到定义默认值。"""
        rows = self._session.execute(
            text(
                "SELECT variable_key, value FROM application_user_variable "
                "WHERE application_id = :aid AND user_id = :uid"
            ),
            {"aid": application_id, "uid": user_id},
        ).all()
        return {str(row[0]): _load_json_value(row[1]) for row in rows}

    def set_user_variables(
        self,
        application_id: UUID,
        user_id: UUID,
        values: dict[str, Any],
    ) -> None:
        """批量写入用户变量取值（UPSERT）。"""
        for key, value in values.items():
            self._session.execute(
                text(
                    "INSERT INTO application_user_variable "
                    "(id, application_id, user_id, variable_key, value) "
                    "VALUES (:id, :aid, :uid, :key, CAST(:value AS JSONB)) "
                    "ON CONFLICT (application_id, user_id, variable_key) "
                    "DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
                ),
                {
                    "id": new_uuid(),
                    "aid": application_id,
                    "uid": user_id,
                    "key": str(key),
                    "value": json.dumps(value, ensure_ascii=False, default=str),
                },
            )

    def delete_user_variable(
        self,
        application_id: UUID,
        user_id: UUID,
        key: str,
    ) -> None:
        self._session.execute(
            text(
                "DELETE FROM application_user_variable "
                "WHERE application_id = :aid AND user_id = :uid AND variable_key = :key"
            ),
            {"aid": application_id, "uid": user_id, "key": key},
        )

    def set_published_graph_version(self, application_id: UUID, version: int) -> None:
        """把 application.published_graph_version 指向指定版本号（NULL → 未发布，回退 latest）。"""
        self._session.execute(
            text(
                "UPDATE application SET published_graph_version = :ver, updated_at = NOW() "
                "WHERE id = :aid"
            ),
            {"aid": application_id, "ver": version},
        )

    def list_applications(
        self,
        owner_type: str | None = None,
        owner_id: UUID | None = None,
        include_marketplace_only: bool = False,
    ) -> list[dict]:
        sql = (
            "SELECT id, owner_type, owner_id, name, avatar_url, description, is_enabled, "
            "is_listed_in_market, flow_type, visibility_lock, visibility_template, "
            "admin_scope_mode, created_at, updated_at FROM application"
        )
        conditions: list[str] = []
        params: dict[str, Any] = {}
        if owner_type:
            conditions.append("owner_type = :owner_type")
            params["owner_type"] = owner_type
        if owner_id is not None:
            conditions.append("owner_id = :owner_id")
            params["owner_id"] = owner_id
        if include_marketplace_only:
            conditions.append("is_listed_in_market = true")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY updated_at DESC"
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]

    def list_marketplace(self) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, name, avatar_url, description FROM application "
                "WHERE owner_type = 'platform' AND is_enabled = true "
                "AND is_listed_in_market = true"
            )
        ).all()
        return [dict(r._mapping) for r in rows]

    def get_marketplace_application(self, application_id: UUID) -> dict | None:
        """市场详情页：只返回上架且启用的平台应用（含 sale_mode/support_trial/doc_url）。"""
        row = self._session.execute(
            text(
                "SELECT id, name, avatar_url, description, sale_mode, support_trial, doc_url "
                "FROM application "
                "WHERE id = :aid AND owner_type = 'platform' AND is_enabled = true "
                "AND is_listed_in_market = true"
            ),
            {"aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    # ========== graph（schema_json 列名对齐 coze Workflow.schema_json） ==========
    def create_graph(self, application_id: UUID, graph: dict) -> None:
        self._session.execute(
            text(
                "INSERT INTO application_graph (application_id, schema_json) "
                "VALUES (:aid, CAST(:graph AS JSONB))"
            ),
            {"aid": application_id, "graph": json.dumps(graph)},
        )

    def update_graph(self, application_id: UUID, graph: dict, runtime_mode: str = "dag") -> None:
        """覆盖写入 graph；不存在则插入。"""
        existing = self._session.execute(
            text("SELECT 1 FROM application_graph WHERE application_id = :aid"),
            {"aid": application_id},
        ).first()
        if existing:
            self._session.execute(
                text(
                    "UPDATE application_graph SET schema_json = CAST(:graph AS JSONB), "
                    "runtime_mode = :mode, updated_at = NOW() WHERE application_id = :aid"
                ),
                {"aid": application_id, "graph": json.dumps(graph), "mode": runtime_mode},
            )
        else:
            self._session.execute(
                text(
                    "INSERT INTO application_graph (application_id, schema_json, runtime_mode) "
                    "VALUES (:aid, CAST(:graph AS JSONB), :mode)"
                ),
                {"aid": application_id, "graph": json.dumps(graph), "mode": runtime_mode},
            )

    def get_graph(self, application_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT schema_json AS graph, runtime_mode, graph_schema_version "
                "FROM application_graph WHERE application_id = :aid"
            ),
            {"aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    # ========== tenant instance ==========
    def subscribe(self, tenant_id: UUID, application_id: UUID) -> UUID:
        instance_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO tenant_application_instance "
                "(id, tenant_id, application_id, status, source) "
                "VALUES (:id, :tid, :aid, 'active', 'marketplace')"
            ),
            {"id": instance_id, "tid": tenant_id, "aid": application_id},
        )
        return instance_id

    def get_instance(self, tenant_id: UUID, application_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT * FROM tenant_application_instance "
                "WHERE tenant_id = :tid AND application_id = :aid"
            ),
            {"tid": tenant_id, "aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    def get_active_instance(self, tenant_id: UUID, application_id: UUID) -> dict | None:
        """仅返回 status='active' 且未过期的实例。"""
        row = self._session.execute(
            text(
                "SELECT * FROM tenant_application_instance "
                "WHERE tenant_id = :tid AND application_id = :aid AND status = 'active' "
                "AND (expire_time IS NULL OR expire_time > now())"
            ),
            {"tid": tenant_id, "aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    def list_instances(self, tenant_id: UUID) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT i.*, a.name, a.description, a.avatar_url "
                "FROM tenant_application_instance i "
                "JOIN application a ON a.id = i.application_id "
                "WHERE i.tenant_id = :tid AND i.status = 'active'"
            ),
            {"tid": tenant_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    # ========== graph 整图版本（新 hot path） ==========
    def insert_graph_version(
        self,
        application_id: UUID,
        version: int,
        graph: dict,
        runtime_mode: str,
        changelog: str = "",
        created_by: UUID | None = None,
    ) -> UUID:
        vid = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO application_graph_version "
                "(id, application_id, version, schema_json, runtime_mode, changelog, created_by) "
                "VALUES (:id, :aid, :ver, CAST(:graph AS JSONB), :mode, :log, :by)"
            ),
            {
                "id": vid,
                "aid": application_id,
                "ver": version,
                "graph": json.dumps(graph),
                "mode": runtime_mode,
                "log": changelog,
                "by": created_by,
            },
        )
        return vid

    def get_latest_graph_version(self, application_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, application_id, version, schema_json AS graph, runtime_mode, changelog, created_at "
                "FROM application_graph_version "
                "WHERE application_id = :aid ORDER BY version DESC LIMIT 1"
            ),
            {"aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    def get_graph_version(self, application_id: UUID, version: int) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, application_id, version, schema_json AS graph, runtime_mode, changelog, created_at "
                "FROM application_graph_version "
                "WHERE application_id = :aid AND version = :ver"
            ),
            {"aid": application_id, "ver": version},
        ).first()
        return dict(row._mapping) if row else None

    def list_graph_versions(self, application_id: UUID, limit: int = 50) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, version, runtime_mode, changelog, created_by, created_at "
                "FROM application_graph_version "
                "WHERE application_id = :aid ORDER BY version DESC LIMIT :lim"
            ),
            {"aid": application_id, "lim": limit},
        ).all()
        return [dict(r._mapping) for r in rows]

    # ========== 租户级 config kv（新 hot path） ==========
    def list_tenant_config(self, tenant_id: UUID, application_id: UUID) -> dict[str, Any]:
        """一次性读出租户对某应用的所有 config 覆盖。"""
        rows = self._session.execute(
            text(
                "SELECT config_key, config_value FROM tenant_application_config "
                "WHERE tenant_id = :tid AND application_id = :aid"
            ),
            {"tid": tenant_id, "aid": application_id},
        ).all()
        return {r._mapping["config_key"]: r._mapping["config_value"] for r in rows}

    def upsert_tenant_config(
        self,
        tenant_id: UUID,
        application_id: UUID,
        config_key: str,
        config_value: Any,
    ) -> None:
        self._session.execute(
            text(
                "INSERT INTO tenant_application_config "
                "(id, tenant_id, application_id, config_key, config_value) "
                "VALUES (:id, :tid, :aid, :key, CAST(:val AS JSONB)) "
                "ON CONFLICT ON CONSTRAINT ux_tenant_app_config_key "
                "DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = NOW()"
            ),
            {
                "id": new_uuid(),
                "tid": tenant_id,
                "aid": application_id,
                "key": config_key,
                "val": json.dumps(config_value),
            },
        )

    def delete_tenant_config(
        self,
        tenant_id: UUID,
        application_id: UUID,
        config_key: str,
    ) -> None:
        self._session.execute(
            text(
                "DELETE FROM tenant_application_config "
                "WHERE tenant_id = :tid AND application_id = :aid AND config_key = :key"
            ),
            {"tid": tenant_id, "aid": application_id, "key": config_key},
        )

    def pin_graph_version(
        self,
        tenant_id: UUID,
        application_id: UUID,
        version: int | None,
    ) -> None:
        """租户锁定整图版本；version=None 表示回到 latest。"""
        self._session.execute(
            text(
                "UPDATE tenant_application_instance "
                "SET pinned_graph_version = :ver, updated_at = NOW() "
                "WHERE tenant_id = :tid AND application_id = :aid"
            ),
            {"tid": tenant_id, "aid": application_id, "ver": version},
        )

    # ========== marketplace cursor 分页 ==========
    def list_marketplace_paged(
        self,
        cursor_updated_at: datetime | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """cursor 分页：按 updated_at DESC，上一页最后一条的 updated_at 作 cursor。"""
        sql = (
            "SELECT id, name, avatar_url, description, updated_at FROM application "
            "WHERE owner_type = 'platform' AND is_enabled = true AND is_listed_in_market = true"
        )
        params: dict[str, Any] = {"lim": limit}
        if cursor_updated_at is not None:
            sql += " AND updated_at < :cursor"
            params["cursor"] = cursor_updated_at
        sql += " ORDER BY updated_at DESC LIMIT :lim"
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]

    # ========== user 端可见应用（v2：按 (应用, 租户) 隔离的可见范围） ==========
    def list_visible_for_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        """当前用户可见应用 = 本租户自建 + 已开通的产品级实例，叠加 v2 可见范围过滤。

        可见范围解析（0068）：
        - scope 有记录：visibility='all' 全员可见；'whitelist' 需命中部门/角色/用户白名单。
        - scope 无记录（订阅后未配置）：产品级应用按平台模板 visibility_template 兜底；
          租户级应用一期不做创建、兜底为不可见（未来创建时会显式写 scope）。
        孤儿数据兜底：subject_id 无外键，三条 JOIN 链路（departments /
        user_employments+users / user_roles）在主体被删后自然过滤，无需级联清理。
        """
        params: dict[str, Any] = {"tid": str(tenant_id), "uid": str(user_id)}
        kw_clause = ""
        if keyword:
            kw_clause = " AND a.name ILIKE :kw"
            params["kw"] = f"%{keyword}%"

        rows = self._session.execute(
            text(
                f"""
                SELECT a.id, a.name, a.avatar_url, a.description, a.is_enabled, a.flow_type
                FROM application a
                WHERE a.is_enabled = true
                  AND (
                    (a.owner_type = 'tenant' AND a.owner_id = :tid)
                    OR (
                      a.owner_type = 'platform'
                      AND EXISTS (
                        SELECT 1 FROM tenant_application_instance t
                        WHERE t.application_id = a.id
                          AND t.tenant_id = :tid
                          AND t.status = 'active'
                          AND (t.start_time IS NULL OR t.start_time <= now())
                          AND (t.expire_time IS NULL OR t.expire_time > now())
                      )
                    )
                  )
                  AND (
                    -- 分支 1：scope 已配置为 all
                    EXISTS (
                      SELECT 1 FROM app_visibility_scope s
                      WHERE s.application_id = a.id
                        AND s.tenant_id = :tid
                        AND s.visibility = 'all'
                    )
                    -- 分支 2：scope 已配置为 whitelist，命中部门/角色/用户白名单
                    OR EXISTS (
                      SELECT 1 FROM app_visibility_scope s
                      JOIN app_visibility_whitelist w ON w.scope_id = s.id
                      WHERE s.application_id = a.id
                        AND s.tenant_id = :tid
                        AND s.visibility = 'whitelist'
                        AND (
                          (w.subject_type = 'USER'
                            AND w.subject_id = :uid
                            AND EXISTS (
                              SELECT 1 FROM users us
                              WHERE us.id = :uid AND us.tenant_id = :tid AND us.is_active = true
                            ))
                          OR (
                            w.subject_type = 'ROLE'
                            AND w.subject_id IN (
                              SELECT role_id FROM user_roles
                              WHERE user_id = :uid AND tenant_id = :tid
                            )
                          )
                          OR (
                            w.subject_type = 'DEPARTMENT'
                            AND EXISTS (
                              SELECT 1
                              FROM user_employments ue
                              JOIN departments ud ON ud.id = ue.department_id AND ud.tenant_id = :tid
                              JOIN departments wd ON wd.id = w.subject_id
                              WHERE ue.user_id = :uid
                                AND ue.tenant_id = :tid
                                AND ue.is_current = true
                                AND (
                                  wd.id = ud.id
                                  OR (w.include_subtree = true AND ud.path LIKE wd.path || '%')
                                )
                            )
                          )
                        )
                    )
                    -- 分支 3：scope 不存在，按 owner_type 兜底
                    OR (
                      NOT EXISTS (
                        SELECT 1 FROM app_visibility_scope s
                        WHERE s.application_id = a.id AND s.tenant_id = :tid
                      )
                      AND (
                        -- 产品级应用：按平台模板兜底（模板为 whitelist 时等待租户配置，暂不可见）
                        (a.owner_type = 'platform' AND a.visibility_template = 'all')
                        -- 租户级应用：一期不做创建，兜底不可见；未来创建时显式写 scope
                        OR (a.owner_type = 'tenant' AND false)
                      )
                    )
                  )
                  {kw_clause}
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
                "flow_type": r._mapping["flow_type"] or "workflow",
            }
            for r in rows
        ]

    # ========== 复制应用（copy）专用 ==========
    def count_copies(self, source_name: str) -> int:
        """统计以「{source_name}的副本」或「{source_name}的副本N」命名的应用数。

        用 ILIKE 前缀匹配避免正则元字符注入；source_name 中的 %/_ 需转义。
        """
        escaped = source_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        prefix = f"{escaped}的副本%"
        rows = self._session.execute(
            text(
                "SELECT name FROM application "
                "WHERE owner_type = 'platform' AND name ILIKE :prefix ESCAPE '\\'"
            ),
            {"prefix": prefix},
        ).all()
        return len(rows)

    def get_full_application(self, application_id: UUID) -> dict | None:
        """读取 application 主行全部列（复制用）。"""
        row = self._session.execute(
            text(
                "SELECT id, owner_type, owner_id, name, avatar_url, description, "
                "is_enabled, is_listed_in_market, sale_mode, support_trial, doc_url, "
                "ext_json, visibility_lock, visibility_template, admin_scope_mode, "
                "published_graph_version, flow_type, "
                "variables, created_by, created_at, updated_at "
                "FROM application WHERE id = :aid"
            ),
            {"aid": application_id},
        ).first()
        if row is None:
            return None
        return dict(row._mapping)

    def insert_application_row(self, data: dict[str, Any]) -> UUID:
        """按显式字段集插入 application 行（复制路径专用）。"""
        app_id = new_uuid()
        variables_raw = data.get("variables")
        if isinstance(variables_raw, (dict, list)):
            variables_str = json.dumps(variables_raw, ensure_ascii=False, default=str)
        elif variables_raw is None:
            variables_str = "[]"
        else:
            variables_str = str(variables_raw)

        ext_json_raw = data.get("ext_json") or {}
        ext_json_str = (
            json.dumps(ext_json_raw, ensure_ascii=False, default=str)
            if isinstance(ext_json_raw, (dict, list))
            else str(ext_json_raw)
        )

        self._session.execute(
            text(
                "INSERT INTO application ("
                "id, owner_type, owner_id, name, avatar_url, description, "
                "is_enabled, is_listed_in_market, sale_mode, support_trial, doc_url, "
                "ext_json, visibility_lock, visibility_template, admin_scope_mode, "
                "published_graph_version, flow_type, "
                "variables, created_by"
                ") VALUES ("
                ":id, :owner_type, :owner_id, :name, :avatar_url, :description, "
                ":is_enabled, :is_listed_in_market, :sale_mode, :support_trial, :doc_url, "
                "CAST(:ext_json AS JSONB), :visibility_lock, :visibility_template, :admin_scope_mode, "
                ":published_graph_version, :flow_type, "
                "CAST(:variables AS JSONB), :created_by"
                ")"
            ),
            {
                "id": app_id,
                "owner_type": data.get("owner_type", "platform"),
                "owner_id": data.get("owner_id"),
                "name": data["name"],
                "avatar_url": data.get("avatar_url"),
                "description": data.get("description", ""),
                "is_enabled": bool(data.get("is_enabled", False)),
                "is_listed_in_market": bool(data.get("is_listed_in_market", False)),
                "sale_mode": int(data.get("sale_mode", 1)),
                "support_trial": bool(data.get("support_trial", False)),
                "doc_url": data.get("doc_url", ""),
                "ext_json": ext_json_str,
                "visibility_lock": bool(data.get("visibility_lock", False)),
                "visibility_template": data.get("visibility_template", "all"),
                "admin_scope_mode": data.get("admin_scope_mode", "all_admin"),
                "published_graph_version": data.get("published_graph_version"),
                "flow_type": data.get("flow_type", "workflow"),
                "variables": variables_str,
                "created_by": data.get("created_by"),
            },
        )
        return app_id

    def get_graph_row(self, application_id: UUID) -> dict | None:
        """读取 application_graph 当前整行（复制用）。"""
        row = self._session.execute(
            text(
                "SELECT application_id, schema_json AS graph, graph_schema_version, runtime_mode "
                "FROM application_graph WHERE application_id = :aid"
            ),
            {"aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    def insert_graph_row(self, application_id: UUID, graph: dict, runtime_mode: str) -> None:
        """向 application_graph 写入一行（复制路径专用，目标应用无残留行）。"""
        self._session.execute(
            text(
                "INSERT INTO application_graph "
                "(application_id, schema_json, runtime_mode) "
                "VALUES (:aid, CAST(:graph AS JSONB), :mode)"
            ),
            {
                "aid": application_id,
                "graph": json.dumps(graph, ensure_ascii=False, default=str),
                "mode": runtime_mode,
            },
        )

    def get_latest_graph_version_row(self, application_id: UUID) -> dict | None:
        """读取最新 graph 版本整行（复制用）。"""
        row = self._session.execute(
            text(
                "SELECT id, application_id, version, schema_json AS graph, runtime_mode, changelog "
                "FROM application_graph_version "
                "WHERE application_id = :aid ORDER BY version DESC LIMIT 1"
            ),
            {"aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

    def insert_graph_version_row(
        self,
        application_id: UUID,
        version: int,
        graph: dict,
        runtime_mode: str,
        changelog: str = "",
        created_by: UUID | None = None,
    ) -> UUID:
        """写入 graph 版本行（复制路径专用）。"""
        vid = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO application_graph_version "
                "(id, application_id, version, schema_json, runtime_mode, changelog, created_by) "
                "VALUES (:id, :aid, :ver, CAST(:graph AS JSONB), :mode, :log, :by)"
            ),
            {
                "id": vid,
                "aid": application_id,
                "ver": version,
                "graph": json.dumps(graph, ensure_ascii=False, default=str),
                "mode": runtime_mode,
                "log": changelog,
                "by": created_by,
            },
        )
        return vid

