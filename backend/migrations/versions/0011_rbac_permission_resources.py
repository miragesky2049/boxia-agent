"""RBAC 权限资源目录与角色权限关系；移除基础权限字段

Revision ID: 0011_rbac_permission_resources
Revises: 0010_platform_roles
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_rbac_permission_resources"
down_revision: str | None = "0010_platform_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, name, category, action, sort_order, description)
_PERMISSIONS: tuple[tuple[str, str, str, str, int, str], ...] = (
    ("system:console:access", "管理端访问", "system", "access", 5, "登录管理后台的入口权限"),
    ("system:data:all", "全量数据权限", "system", "manage", 6, "跳过数据权限过滤，可访问全部资源"),
    ("menu:agents", "智能体管理", "menu", "view", 10, ""),
    ("menu:grants", "用户授权", "menu", "view", 20, ""),
    ("menu:roles", "角色管理", "menu", "view", 30, ""),
    ("menu:users", "用户管理", "menu", "view", 40, ""),
    ("menu:admin-users", "管理员账号", "menu", "view", 50, ""),
    ("menu:tenants", "租户管理", "menu", "view", 60, ""),
    ("menu:audit", "审计日志", "menu", "view", 70, ""),
    ("page:agents", "智能体管理页面", "page", "view", 110, ""),
    ("page:grants", "用户授权页面", "page", "view", 120, ""),
    ("page:roles", "角色管理页面", "page", "view", 130, ""),
    ("page:users", "用户管理页面", "page", "view", 140, ""),
    ("page:admin-users", "管理员账号页面", "page", "view", 150, ""),
    ("page:tenants", "租户管理页面", "page", "view", 160, ""),
    ("page:audit", "审计日志页面", "page", "view", 170, ""),
    ("button:agent:create", "智能体-新建", "button", "create", 210, ""),
    ("button:agent:update", "智能体-编辑", "button", "update", 211, ""),
    ("button:agent:delete", "智能体-删除", "button", "delete", 212, ""),
    ("button:skill:create", "技能-新建/导入/克隆", "button", "create", 220, ""),
    ("button:skill:update", "技能-编辑/文件维护", "button", "update", 221, ""),
    ("button:skill:delete", "技能-删除", "button", "delete", 222, ""),
    ("button:tool:create", "工具-新建/克隆", "button", "create", 230, ""),
    ("button:tool:update", "工具-编辑", "button", "update", 231, ""),
    ("button:tool:delete", "工具-删除", "button", "delete", 232, ""),
    ("button:component:create", "组件-新建/克隆", "button", "create", 240, ""),
    ("button:component:update", "组件-编辑", "button", "update", 241, ""),
    ("button:component:delete", "组件-删除", "button", "delete", 242, ""),
    ("button:prompt:create", "提示词-新建/克隆", "button", "create", 250, ""),
    ("button:prompt:update", "提示词-编辑", "button", "update", 251, ""),
    ("button:prompt:delete", "提示词-删除", "button", "delete", 252, ""),
    ("button:role:create", "角色-新建", "button", "create", 260, ""),
    ("button:role:update", "角色-编辑", "button", "update", 261, ""),
    ("button:role:delete", "角色-删除", "button", "delete", 262, ""),
    ("button:role:copy", "角色-复制", "button", "create", 263, ""),
    ("button:role:grant", "角色-授权", "button", "manage", 264, ""),
    ("button:admin-user:create", "管理员账号-新建", "button", "create", 270, ""),
    ("button:admin-user:update", "管理员账号-编辑", "button", "update", 271, ""),
    ("button:admin-user:delete", "管理员账号-删除", "button", "delete", 272, ""),
    ("button:admin-user:reset-password", "管理员账号-重置密码", "button", "manage", 273, ""),
    ("button:tenant:create", "租户-新建", "button", "create", 280, ""),
    ("button:tenant:update", "租户-编辑", "button", "update", 281, ""),
    ("button:user:create", "用户-新建", "button", "create", 290, ""),
    ("button:user:update", "用户-编辑", "button", "update", 291, ""),
    ("button:user:delete", "用户-删除", "button", "delete", 292, ""),
    ("button:grant:manage", "用户授权-维护", "button", "manage", 300, ""),
    ("agent:create", "智能体-创建", "agent", "create", 310, ""),
    ("agent:read", "智能体-查看", "agent", "read", 311, ""),
    ("agent:update", "智能体-修改", "agent", "update", 312, ""),
    ("agent:delete", "智能体-删除", "agent", "delete", 313, ""),
    ("skill:create", "技能-创建", "skill", "create", 320, ""),
    ("skill:read", "技能-查看", "skill", "read", 321, ""),
    ("skill:update", "技能-修改", "skill", "update", 322, ""),
    ("skill:delete", "技能-删除", "skill", "delete", 323, ""),
    ("tool:create", "工具-创建", "tool", "create", 330, ""),
    ("tool:read", "工具-查看", "tool", "read", 331, ""),
    ("tool:update", "工具-修改", "tool", "update", 332, ""),
    ("tool:delete", "工具-删除", "tool", "delete", 333, ""),
    ("component:create", "组件-创建", "component", "create", 340, ""),
    ("component:read", "组件-查看", "component", "read", 341, ""),
    ("component:update", "组件-修改", "component", "update", 342, ""),
    ("component:delete", "组件-删除", "component", "delete", 343, ""),
    ("prompt:create", "提示词-创建", "prompt", "create", 350, ""),
    ("prompt:read", "提示词-查看", "prompt", "read", 351, ""),
    ("prompt:update", "提示词-修改", "prompt", "update", 352, ""),
    ("prompt:delete", "提示词-删除", "prompt", "delete", 353, ""),
)

_SYSTEM_CATEGORIES = (
    "system",
    "menu",
    "page",
    "button",
    "agent",
    "skill",
    "tool",
    "component",
    "prompt",
)
_ACTIONS = ("view", "access", "create", "read", "update", "delete", "manage")

_PLATFORM_ONLY = (
    "menu:tenants",
    "page:tenants",
    "button:tenant:create",
    "button:tenant:update",
)

# 平台作用域不展示租户用户与用户授权菜单
_TENANT_ONLY = (
    "menu:grants",
    "menu:users",
    "page:users",
    "button:user:create",
    "button:user:update",
    "button:user:delete",
)

_RESOURCE_TABLES = ("agent", "skill", "tool", "component", "prompt")

# 平台内置角色的权限集合：升级前 system_role 为 admin 的自定义角色也按此回填
_PLATFORM_ADMIN_CODES = (
    "system:console:access",
    "menu:agents",
    "page:agents",
    *(f"button:{resource}:{action}" for resource in _RESOURCE_TABLES for action in ("create", "update", "delete")),
    *(f"{resource}:{action}" for resource in _RESOURCE_TABLES for action in ("create", "read", "update", "delete")),
)
_PLATFORM_VIEWER_CODES = (
    "system:console:access",
    "menu:agents",
    "page:agents",
    *(f"{resource}:read" for resource in _RESOURCE_TABLES),
)

_UPGRADE = [
    f"""
    CREATE TABLE permission_resources (
        id           BIGSERIAL    PRIMARY KEY,
        code         VARCHAR(128) NOT NULL,
        name         VARCHAR(64)  NOT NULL,
        category     VARCHAR(16)  NOT NULL,
        action       VARCHAR(16)  NOT NULL,
        description  TEXT         NOT NULL DEFAULT '',
        sort_order   INTEGER      NOT NULL DEFAULT 0,
        is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ux_permission_resources_code UNIQUE (code),
        CONSTRAINT ck_permission_resources_category
            CHECK (category IN ({', '.join(f"'{item}'" for item in _SYSTEM_CATEGORIES)})),
        CONSTRAINT ck_permission_resources_action
            CHECK (action IN ({', '.join(f"'{item}'" for item in _ACTIONS)}))
    )
    """,
    "CREATE INDEX ix_permission_resources_category "
    "ON permission_resources (category, sort_order)",
    """
    CREATE TRIGGER trg_permission_resources_updated_at BEFORE UPDATE ON permission_resources
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    CREATE TABLE role_permissions (
        id             BIGSERIAL   PRIMARY KEY,
        role_id        BIGINT      NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
        permission_id  BIGINT      NOT NULL REFERENCES permission_resources(id) ON DELETE CASCADE,
        granted_by     BIGINT      REFERENCES admin_users(id) ON DELETE SET NULL,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ux_role_permissions_role_permission UNIQUE (role_id, permission_id)
    )
    """,
    "CREATE INDEX ix_role_permissions_role ON role_permissions (role_id)",
    "CREATE INDEX ix_role_permissions_permission ON role_permissions (permission_id)",
]

_permission_values = ",\n        ".join(
    "('{code}', '{name}', '{category}', '{action}', {sort_order}, '{description}')".format(
        code=code,
        name=name,
        category=category,
        action=action,
        sort_order=sort_order,
        description=description.replace("'", "''"),
    )
    for code, name, category, action, sort_order, description in _PERMISSIONS
)
_UPGRADE.append(
    f"""
    INSERT INTO permission_resources (code, name, category, action, sort_order, description)
    VALUES
        {_permission_values}
    ON CONFLICT (code) DO NOTHING
    """
)

# 按升级前的 system_role 回填权限，保证存量账号升级后能力不下降
_UPGRADE += [
    f"""
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
      FROM roles r
     CROSS JOIN permission_resources p
     WHERE r.tenant_id IS NULL
       AND r.system_role = 'superadmin'
       AND p.code NOT IN ({', '.join(f"'{item}'" for item in _TENANT_ONLY)})
    ON CONFLICT DO NOTHING
    """,
    f"""
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
      FROM roles r
     CROSS JOIN permission_resources p
     WHERE r.tenant_id IS NULL
       AND r.system_role = 'admin'
       AND p.code IN ({', '.join(f"'{item}'" for item in _PLATFORM_ADMIN_CODES)})
    ON CONFLICT DO NOTHING
    """,
    f"""
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
      FROM roles r
     CROSS JOIN permission_resources p
     WHERE r.tenant_id IS NULL
       AND r.system_role = 'viewer'
       AND p.code IN ({', '.join(f"'{item}'" for item in _PLATFORM_VIEWER_CODES)})
    ON CONFLICT DO NOTHING
    """,
    f"""
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
      FROM roles r
     CROSS JOIN permission_resources p
     WHERE r.tenant_id IS NOT NULL
       AND r.system_role = 'superadmin'
       AND p.code NOT IN ({', '.join(f"'{item}'" for item in _PLATFORM_ONLY)})
    ON CONFLICT DO NOTHING
    """,
    f"""
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
      FROM roles r
     CROSS JOIN permission_resources p
     WHERE r.tenant_id IS NOT NULL
       AND r.system_role = 'admin'
       AND p.code IN ({', '.join(f"'{item}'" for item in _PLATFORM_ADMIN_CODES)})
    ON CONFLICT DO NOTHING
    """,
    f"""
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
      FROM roles r
     CROSS JOIN permission_resources p
     WHERE r.tenant_id IS NOT NULL
       AND r.system_role = 'viewer'
       AND p.code IN ({', '.join(f"'{item}'" for item in _PLATFORM_VIEWER_CODES)})
    ON CONFLICT DO NOTHING
    """,
    # 平台账号必须有角色；历史空角色账号回退到只读角色，避免升级后无法登录
    """
    UPDATE admin_users
       SET role_id = (
            SELECT id FROM roles
             WHERE tenant_id IS NULL AND code = 'viewer'
             ORDER BY id
             LIMIT 1
           )
     WHERE role_id IS NULL
    """,
    "ALTER TABLE admin_users DROP CONSTRAINT IF EXISTS ck_admin_users_role",
    "ALTER TABLE admin_users ALTER COLUMN role_id SET NOT NULL",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS role",
    "ALTER TABLE roles DROP CONSTRAINT IF EXISTS ck_roles_system_role",
    "ALTER TABLE roles DROP COLUMN IF EXISTS system_role",
]

_DOWNGRADE = [
    "ALTER TABLE roles ADD COLUMN IF NOT EXISTS system_role VARCHAR(16) NOT NULL DEFAULT 'viewer'",
    """
    UPDATE roles
       SET system_role = CASE
            WHEN code IN ('superadmin', 'admin', 'viewer') THEN code
            ELSE 'viewer'
       END
    """,
    """
    ALTER TABLE roles ADD CONSTRAINT ck_roles_system_role
        CHECK (system_role IN ('superadmin', 'admin', 'viewer'))
    """,
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'admin'",
    """
    UPDATE admin_users au
       SET role = CASE
            WHEN r.code IN ('superadmin', 'admin', 'viewer') THEN r.code
            ELSE 'admin'
       END
      FROM roles r
     WHERE r.id = au.role_id
    """,
    """
    ALTER TABLE admin_users ADD CONSTRAINT ck_admin_users_role
        CHECK (role IN ('superadmin', 'admin', 'viewer'))
    """,
    "ALTER TABLE admin_users ALTER COLUMN role_id DROP NOT NULL",
    "DROP TABLE IF EXISTS role_permissions",
    "DROP TRIGGER IF EXISTS trg_permission_resources_updated_at ON permission_resources",
    "DROP TABLE IF EXISTS permission_resources",
]


def upgrade() -> None:
    """创建权限目录与角色权限关系，并把基础权限映射为显式权限授权。"""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """恢复基础权限字段；角色权限关系不可逆，回滚前请备份 role_permissions。"""
    for statement in _DOWNGRADE:
        op.execute(statement)
