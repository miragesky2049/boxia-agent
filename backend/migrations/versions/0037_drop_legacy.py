"""下线老 agent / workflow / skill / component / prompt 相关表与权限。

Revision ID: 0037_drop_legacy
Revises: 0036_rename_event_webhook
Create Date: 2026-10-29

设计要点：
- 老 v1-v3 agents/workflows/skills/components/prompts 已被新 apps 表与 RAG 链路替代，物理 DROP
- documents.agent_id 列不再使用，一并 DROP
- permission_resources 中老 code 全部删除，同步清理 role_permissions 引用
- 历史数据不保留
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0037_drop_legacy"
down_revision: str | None = "0036_rename_event_webhook"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 老表 DROP 顺序：先依赖表后主表
_DROP_TABLES = (
    "agent_skills",
    "agent_tools",
    "agent_tenant_openings",
    "agent_visibility_departments",
    "agent_visibility_users",
    "agents",
    "skill_files",
    "skills",
    "components",
    "prompts",
    "workflow_templates",
    "workflows",
)

# 老权限码：agent/skill/component/prompt 菜单/页面/按钮/资源 + workflow 菜单/页面
_LEGACY_PERMISSION_CODES = (
    "menu:agents",
    "page:agents",
    "menu:workflows",
    "page:workflows",
    "agent:create",
    "agent:read",
    "agent:update",
    "agent:delete",
    "button:agent:create",
    "button:agent:update",
    "button:agent:delete",
    "skill:create",
    "skill:read",
    "skill:update",
    "skill:delete",
    "button:skill:create",
    "button:skill:update",
    "button:skill:delete",
    "component:create",
    "component:read",
    "component:update",
    "component:delete",
    "button:component:create",
    "button:component:update",
    "button:component:delete",
    "prompt:create",
    "prompt:read",
    "prompt:update",
    "prompt:delete",
    "button:prompt:create",
    "button:prompt:update",
    "button:prompt:delete",
)


def upgrade() -> None:
    # 1. 清理老权限引用：先删 role_permissions，再删 permission_resources
    codes_literal = ", ".join(f"'{code}'" for code in _LEGACY_PERMISSION_CODES)
    op.execute(
        f"DELETE FROM role_permissions WHERE permission_id IN "
        f"(SELECT id FROM permission_resources WHERE code IN ({codes_literal}))"
    )
    op.execute(f"DELETE FROM permission_resources WHERE code IN ({codes_literal})")

    # 2. documents.agent_id 列不再使用
    op.drop_index("ix_documents_tenant_agent", table_name="documents", if_exists=True)
    op.drop_column("documents", "agent_id")

    # 3. DROP 老表
    for table in _DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    # 老表不做 downgrade：业务已下线，重新建表无意义
    raise NotImplementedError("老 agent/workflow/skill 表已下线，不支持回滚")
