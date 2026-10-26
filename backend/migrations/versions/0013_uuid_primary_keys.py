"""全量主键切换为应用层 UUID v7。

清理全部业务数据后，把主键与外键列从 bigint 改为 PostgreSQL 原生 uuid，
并重建权限目录、平台角色与角色权限种子。管理员账号不在迁移内重建，部署后
执行 scripts/create_admin.py。

Revision ID: 0013_uuid_primary_keys
Revises: 0012_agent_tenant_openings
Create Date: 2026-10-25
"""

import secrets
import time
import uuid
from collections.abc import Sequence

from alembic import op
from sqlalchemy import bindparam, text

revision: str = "0013_uuid_primary_keys"
down_revision: str | None = "0012_agent_tenant_openings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 每张表需要切换为 uuid 的列；除 resource_grants.resource_id 外均参与外键约束。
_ID_COLUMNS: dict[str, tuple[str, ...]] = {
    "tenants": ("id",),
    "admin_users": ("id", "role_id"),
    "roles": ("id", "tenant_id"),
    "users": ("id", "tenant_id", "role_id"),
    "user_roles": ("id", "user_id", "role_id", "tenant_id"),
    "admin_refresh_tokens": ("id", "user_id", "replaced_by_id"),
    "user_refresh_tokens": ("id", "user_id", "replaced_by_id"),
    "audit_logs": ("id", "tenant_id", "actor_id"),
    "agents": ("id", "tenant_id"),
    "agent_tenant_openings": ("id", "agent_id", "tenant_id", "opened_by"),
    "agent_tools": ("agent_id", "tool_id"),
    "agent_skills": ("agent_id", "skill_id"),
    "skills": ("id", "tenant_id", "agent_id"),
    "skill_files": ("id", "skill_id"),
    "tools": ("id", "tenant_id", "agent_id"),
    "components": ("id", "tenant_id", "agent_id"),
    "prompts": ("id", "tenant_id", "agent_id"),
    "resource_grants": ("id", "resource_id", "tenant_id", "role_id", "granted_by"),
    "permission_resources": ("id",),
    "role_permissions": ("id", "role_id", "permission_id", "granted_by"),
}
_TABLES = tuple(_ID_COLUMNS)

# 这些唯一索引以 COALESCE(tenant_id, 0) 区分产品级与租户级，tenant_id 改为 uuid 后
# 表达式必须重写，否则 ALTER COLUMN TYPE 会报 uuid 与 bigint 无法匹配。
_COALESCE_INDEXES: dict[str, str] = {
    "agents": "ux_agents_name_lower",
    "skills": "ux_skills_name_lower",
    "tools": "ux_tools_name_lower",
    "components": "ux_components_name_lower",
    "prompts": "ux_prompts_name_lower",
}
_PLATFORM_TENANT_SENTINEL = "00000000-0000-0000-0000-000000000000"


def _uuid7() -> uuid.UUID:
    """迁移内联的极简 UUID v7 生成器，不依赖应用代码以保证历史可重复执行。"""
    milliseconds = time.time_ns() // 1_000_000
    randomness = secrets.randbits(74)
    value = (milliseconds & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= (randomness >> 62) << 64
    value |= 0b10 << 62
    value |= randomness & ((1 << 62) - 1)
    return uuid.UUID(int=value)


def _snapshot_seed(conn) -> dict[str, list[dict]]:
    """TRUNCATE 前快照权限目录、平台角色与授权关系。"""
    permissions = conn.execute(
        text(
            "SELECT code, name, category, action, description, sort_order, is_active "
            "FROM permission_resources ORDER BY id"
        )
    ).mappings()
    roles = conn.execute(
        text(
            "SELECT code, name, description, is_system, is_active "
            "FROM roles WHERE tenant_id IS NULL ORDER BY id"
        )
    ).mappings()
    mappings = conn.execute(
        text(
            "SELECT r.code AS role_code, p.code AS permission_code "
            "FROM role_permissions rp "
            "JOIN roles r ON r.id = rp.role_id "
            "JOIN permission_resources p ON p.id = rp.permission_id "
            "WHERE r.tenant_id IS NULL"
        )
    ).mappings()
    seed = {
        "permissions": [dict(row) for row in permissions],
        "roles": [dict(row) for row in roles],
        "mappings": [dict(row) for row in mappings],
    }
    if not seed["permissions"] or not seed["roles"]:
        raise RuntimeError("权限目录或平台角色种子缺失，禁止清空数据")
    return seed


def _foreign_keys(conn) -> list[dict[str, str]]:
    """快照涉及这些表的外键定义，改列类型前必须先删除。"""
    statement = text(
        "SELECT c.conrelid::regclass::text AS table_name, "
        "       c.conname AS constraint_name, "
        "       pg_get_constraintdef(c.oid) AS definition "
        "FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid "
        "WHERE c.contype = 'f' AND t.relname IN :tables"
    ).bindparams(bindparam("tables", expanding=True))
    return [dict(row) for row in conn.execute(statement, {"tables": list(_TABLES)}).mappings()]


def _drop_foreign_keys(conn, constraints: list[dict[str, str]]) -> None:
    for item in constraints:
        op.execute(
            f'ALTER TABLE "{item["table_name"]}" DROP CONSTRAINT "{item["constraint_name"]}"'
        )


def _is_grant_actor_fk(item: dict[str, str]) -> bool:
    """granted_by 可能是平台管理员或租户账号，无法用单一外键约束。"""
    return item["table_name"] in {"role_permissions", "resource_grants"} and (
        "granted_by" in item["definition"]
    )


def _restore_foreign_keys(conn, constraints: list[dict[str, str]]) -> None:
    for item in constraints:
        if _is_grant_actor_fk(item):
            continue
        op.execute(
            f'ALTER TABLE "{item["table_name"]}" ADD CONSTRAINT '
            f'"{item["constraint_name"]}" {item["definition"]}'
        )


def _restore_grant_actor_foreign_keys() -> None:
    """回滚到 0012 的 schema 时恢复历史外键定义。"""
    for table in ("role_permissions", "resource_grants"):
        op.execute(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "{table}_granted_by_fkey" '
            "FOREIGN KEY (granted_by) REFERENCES admin_users(id) ON DELETE SET NULL"
        )


def _drop_coalesce_indexes() -> None:
    for index in _COALESCE_INDEXES.values():
        op.execute(f'DROP INDEX IF EXISTS "{index}"')


def _create_coalesce_indexes(sentinel: str) -> None:
    for table, index in _COALESCE_INDEXES.items():
        op.execute(
            f'CREATE UNIQUE INDEX "{index}" ON "{table}" '
            f"(COALESCE(tenant_id, {sentinel}), lower(name))"
        )


def _drop_sequences(conn) -> None:
    """移除已不再需要的自增默认值与序列。"""
    for table in _TABLES:
        if "id" not in _ID_COLUMNS[table]:
            continue
        sequence = conn.execute(
            text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table}
        ).scalar()
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN id DROP DEFAULT')
        if sequence:
            op.execute(f"DROP SEQUENCE IF EXISTS {sequence}")


def _restore_seed(conn, seed: dict[str, list[dict]], explicit_ids: bool) -> None:
    """重建权限目录、平台角色与角色权限关系。"""
    permission_ids: dict[str, uuid.UUID] = {}
    for row in seed["permissions"]:
        new_id = _uuid7() if explicit_ids else None
        if explicit_ids:
            conn.execute(
                text(
                    "INSERT INTO permission_resources "
                    "(id, code, name, category, action, description, sort_order, is_active) "
                    "VALUES (:id, :code, :name, :category, :action, :description, "
                    ":sort_order, :is_active)"
                ),
                {**row, "id": new_id},
            )
            permission_ids[row["code"]] = new_id
        else:
            conn.execute(
                text(
                    "INSERT INTO permission_resources "
                    "(code, name, category, action, description, sort_order, is_active) "
                    "VALUES (:code, :name, :category, :action, :description, "
                    ":sort_order, :is_active)"
                ),
                row,
            )

    role_ids: dict[str, uuid.UUID] = {}
    for row in seed["roles"]:
        new_id = _uuid7() if explicit_ids else None
        if explicit_ids:
            conn.execute(
                text(
                    "INSERT INTO roles "
                    "(id, tenant_id, code, name, description, is_system, is_active) "
                    "VALUES (:id, NULL, :code, :name, :description, :is_system, :is_active)"
                ),
                {**row, "id": new_id},
            )
            role_ids[row["code"]] = new_id
        else:
            conn.execute(
                text(
                    "INSERT INTO roles "
                    "(tenant_id, code, name, description, is_system, is_active) "
                    "VALUES (NULL, :code, :name, :description, :is_system, :is_active)"
                ),
                row,
            )

    if not explicit_ids:
        permission_ids = {
            code: pid
            for code, pid in conn.execute(
                text("SELECT code, id FROM permission_resources")
            ).all()
        }
        role_ids = {
            code: rid
            for code, rid in conn.execute(
                text("SELECT code, id FROM roles WHERE tenant_id IS NULL")
            ).all()
        }

    for row in seed["mappings"]:
        role_id = role_ids.get(row["role_code"])
        permission_id = permission_ids.get(row["permission_code"])
        if role_id is None or permission_id is None:
            continue
        if explicit_ids:
            conn.execute(
                text(
                    "INSERT INTO role_permissions (id, role_id, permission_id, granted_by) "
                    "VALUES (:id, :role_id, :permission_id, NULL)"
                ),
                {"id": _uuid7(), "role_id": role_id, "permission_id": permission_id},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_id, granted_by) "
                    "VALUES (:role_id, :permission_id, NULL)"
                ),
                {"role_id": role_id, "permission_id": permission_id},
            )


def upgrade() -> None:
    """清空业务数据，主键与外键切换为 uuid，并重建权限种子。"""
    conn = op.get_bind()
    seed = _snapshot_seed(conn)
    constraints = _foreign_keys(conn)

    op.execute(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
    _drop_foreign_keys(conn, constraints)
    _drop_sequences(conn)
    _drop_coalesce_indexes()

    for table, columns in _ID_COLUMNS.items():
        for column in columns:
            op.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE uuid USING NULL::uuid'
            )

    _create_coalesce_indexes(f"'{_PLATFORM_TENANT_SENTINEL}'::uuid")
    _restore_foreign_keys(conn, constraints)
    _restore_seed(conn, seed, explicit_ids=True)


def downgrade() -> None:
    """回滚为 bigint 自增主键并重建种子；upgrade 已清空业务数据，无法恢复。"""
    conn = op.get_bind()
    seed = _snapshot_seed(conn)
    constraints = _foreign_keys(conn)

    op.execute(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
    _drop_foreign_keys(conn, constraints)
    _drop_coalesce_indexes()

    for table, columns in _ID_COLUMNS.items():
        for column in columns:
            op.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE bigint USING NULL::bigint'
            )
        if "id" not in columns:
            continue
        sequence = f"{table}_id_seq"
        op.execute(f'CREATE SEQUENCE IF NOT EXISTS "{sequence}" OWNED BY "{table}".id')
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN id SET DEFAULT nextval(\'{sequence}\'::regclass)'
        )
        op.execute(f"SELECT setval('{sequence}', 1, false)")

    _create_coalesce_indexes("0")
    _restore_foreign_keys(conn, constraints)
    _restore_grant_actor_foreign_keys()
    _restore_seed(conn, seed, explicit_ids=False)
