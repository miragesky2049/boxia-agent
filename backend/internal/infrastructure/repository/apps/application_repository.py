"""应用仓储：application + application_graph + tenant_instance。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


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
    ) -> UUID:
        app_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO application (id, owner_type, owner_id, name, description, created_by) "
                "VALUES (:id, :owner_type, :owner_id, :name, :description, :created_by)"
            ),
            {
                "id": app_id,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "name": name,
                "description": description,
                "created_by": created_by,
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

    # ========== visibility（数据可见范围） ==========
    def get_application_visibility(self, application_id: UUID) -> dict:
        """读取应用可见范围：mode + 部门白名单（含子树开关）+ 用户白名单。"""
        mode_row = self._session.execute(
            text("SELECT visibility_mode FROM application WHERE id = :aid"),
            {"aid": application_id},
        ).first()
        mode = mode_row._mapping["visibility_mode"] if mode_row else "all"

        dept_rows = self._session.execute(
            text(
                "SELECT department_id, include_subtree FROM application_visibility_departments "
                "WHERE application_id = :aid ORDER BY created_at"
            ),
            {"aid": application_id},
        ).all()
        user_rows = self._session.execute(
            text(
                "SELECT user_id FROM application_visibility_users "
                "WHERE application_id = :aid ORDER BY created_at"
            ),
            {"aid": application_id},
        ).all()
        return {
            "mode": mode,
            "departments": [
                {"department_id": str(r._mapping["department_id"]), "include_subtree": r._mapping["include_subtree"]}
                for r in dept_rows
            ],
            "users": [str(r._mapping["user_id"]) for r in user_rows],
        }

    def replace_application_visibility(
        self,
        application_id: UUID,
        mode: str,
        departments: list[dict],
        users: list[UUID],
    ) -> None:
        """整体覆盖可见范围：先清空两张关联表，再按入参写入；同时更新 visibility_mode。"""
        self._session.execute(
            text(
                "UPDATE application SET visibility_mode = :mode, updated_at = NOW() WHERE id = :aid"
            ),
            {"mode": mode, "aid": application_id},
        )
        self._session.execute(
            text("DELETE FROM application_visibility_departments WHERE application_id = :aid"),
            {"aid": application_id},
        )
        self._session.execute(
            text("DELETE FROM application_visibility_users WHERE application_id = :aid"),
            {"aid": application_id},
        )
        if mode == "custom":
            for dept in departments:
                self._session.execute(
                    text(
                        "INSERT INTO application_visibility_departments "
                        "(application_id, department_id, include_subtree) "
                        "VALUES (:aid, :did, :sub)"
                    ),
                    {
                        "aid": application_id,
                        "did": dept["department_id"],
                        "sub": dept.get("include_subtree", True),
                    },
                )
            for uid in users:
                self._session.execute(
                    text(
                        "INSERT INTO application_visibility_users (application_id, user_id) "
                        "VALUES (:aid, :uid)"
                    ),
                    {"aid": application_id, "uid": uid},
                )

    def get_application(self, application_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, owner_type, owner_id, name, avatar_url, description, is_enabled, "
                "is_listed_in_market, visibility_mode, published_graph_version, "
                "created_by, created_at, updated_at "
                "FROM application WHERE id = :aid"
            ),
            {"aid": application_id},
        ).first()
        return dict(row._mapping) if row else None

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
            "is_listed_in_market, created_at, updated_at FROM application"
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
