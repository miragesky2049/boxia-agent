"""0043 下线字段级版本表：数据迁移 + drop application_field_version / tenant_field_pin。

Revision ID: 0043_drop_legacy_field_version
Revises: 0042_graph_version
Create Date: 2026-10-30

替代关系：
- application_field_version -> application_graph_version（整图快照）
- tenant_field_pin -> tenant_application_config + tenant_application_instance.pinned_graph_version

升级时：
1. 把每个应用的最新字段版本覆盖回 application_graph 当前 graph，写一行整图版本
2. 把字段级 pin 展开为 tenant_application_config kv
3. drop 旧表
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0043_drop_legacy_field_version"
down_revision: str | None = "0042_graph_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ========== 1. 数据迁移：旧字段版本 → 整图版本快照 ==========
    conn = op.get_bind()

    apps = conn.execute(sa.text("""
        SELECT DISTINCT fv.application_id
        FROM application_field_version fv
        LEFT JOIN application_graph_version gv
          ON gv.application_id = fv.application_id
        WHERE gv.application_id IS NULL
    """)).all()

    for (app_id,) in apps:
        graph_row = conn.execute(sa.text("""
            SELECT graph, runtime_mode FROM application_graph WHERE application_id = :aid
        """), {"aid": app_id}).first()
        if graph_row is None:
            continue

        raw_graph = graph_row._mapping["graph"]
        graph = json.loads(raw_graph) if isinstance(raw_graph, str) else (raw_graph or {})
        runtime_mode = graph_row._mapping["runtime_mode"] or "dag"

        latest_rows = conn.execute(sa.text("""
            SELECT DISTINCT ON (field_path) field_path, value
            FROM application_field_version
            WHERE application_id = :aid
            ORDER BY field_path, version DESC
        """), {"aid": app_id}).all()

        nodes_by_id = {n.get("id"): n for n in graph.get("nodes", [])}
        for row in latest_rows:
            path = row._mapping["field_path"]
            value = row._mapping["value"]
            parts = path.split(".")
            if len(parts) < 5 or parts[0] != "graph" or parts[1] != "nodes" or parts[3] != "config":
                continue
            node_id = parts[2]
            field = ".".join(parts[4:])
            node = nodes_by_id.get(node_id)
            if node is None:
                continue
            config = node.get("config") or {}
            config[field] = value
            node["config"] = config

        conn.execute(sa.text("""
            INSERT INTO application_graph_version
                (id, application_id, version, graph, runtime_mode, changelog)
            VALUES (:id, :aid, 1, CAST(:graph AS JSONB), :mode, :log)
        """), {
            "id": str(uuid4()),
            "aid": app_id,
            "graph": json.dumps(graph, ensure_ascii=False),
            "mode": runtime_mode,
            "log": "迁移自字段级版本",
        })

        # 字段级 pin → tenant_application_config
        pin_rows = conn.execute(sa.text("""
            SELECT t.tenant_id, f.field_path, f.value
            FROM tenant_field_pin t
            JOIN application_field_version f
              ON f.application_id = t.application_id
             AND f.field_path = t.field_path
             AND f.version = t.pinned_version
            WHERE t.application_id = :aid
        """), {"aid": app_id}).all()

        for pin in pin_rows:
            conn.execute(sa.text("""
                INSERT INTO tenant_application_config
                    (id, tenant_id, application_id, config_key, config_value)
                VALUES (:id, :tid, :aid, :key, CAST(:val AS JSONB))
                ON CONFLICT ON CONSTRAINT ux_tenant_app_config_key DO UPDATE
                SET config_value = EXCLUDED.config_value, updated_at = NOW()
            """), {
                "id": str(uuid4()),
                "tid": pin._mapping["tenant_id"],
                "aid": app_id,
                "key": pin._mapping["field_path"],
                "val": json.dumps(pin._mapping["value"], ensure_ascii=False),
            })

        tenant_ids = {pin._mapping["tenant_id"] for pin in pin_rows}
        for tid in tenant_ids:
            conn.execute(sa.text("""
                UPDATE tenant_application_instance
                SET pinned_graph_version = 1, updated_at = NOW()
                WHERE tenant_id = :tid AND application_id = :aid
            """), {"tid": tid, "aid": app_id})

    # ========== 2. drop 旧表 ==========
    op.drop_index("ix_field_pin_tenant", table_name="tenant_field_pin", if_exists=True)
    op.drop_table("tenant_field_pin", if_exists=True)
    op.drop_index("ix_field_version_app", table_name="application_field_version", if_exists=True)
    op.drop_table("application_field_version", if_exists=True)


def downgrade() -> None:
    # 回滚不重建：旧表已被新整图版本表替代，重建会导致语义冲突
    # 如需恢复，请从 0030_v4_field_version.py 提取原 DDL
    pass
