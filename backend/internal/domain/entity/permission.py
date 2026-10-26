"""RBAC 权限资源目录与内置角色权限集合。

权限资源是全局目录，随版本迁移预置；角色与权限资源通过 role_permissions 关联。
"""

from dataclasses import dataclass
from uuid import UUID

PERMISSION_CATEGORIES = (
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
PERMISSION_ACTIONS = ("view", "access", "create", "read", "update", "delete", "manage")

# 关键系统权限：管理端登录入口与全量数据范围
CONSOLE_ACCESS = "system:console:access"
DATA_ALL = "system:data:all"


@dataclass(frozen=True)
class PermissionDefinition:
    """权限资源定义：编码在全局唯一，category/action 用于分组展示与校验。"""

    code: str
    name: str
    category: str
    action: str
    sort_order: int
    description: str = ""


@dataclass(frozen=True)
class PermissionResource:
    """持久化的权限资源目录项。"""

    id: UUID
    code: str
    name: str
    category: str
    action: str
    description: str
    sort_order: int
    is_active: bool


def _perm(
    code: str,
    name: str,
    category: str,
    action: str,
    sort_order: int,
    description: str = "",
) -> PermissionDefinition:
    return PermissionDefinition(code, name, category, action, sort_order, description)


PERMISSION_CATALOG: tuple[PermissionDefinition, ...] = (
    _perm(CONSOLE_ACCESS, "管理端访问", "system", "access", 5, "登录管理后台的入口权限"),
    _perm(DATA_ALL, "全量数据权限", "system", "manage", 6, "跳过数据权限过滤，可访问全部资源"),
    _perm("menu:agents", "智能体管理", "menu", "view", 10),
    _perm("menu:grants", "用户授权", "menu", "view", 20),
    _perm("menu:roles", "角色管理", "menu", "view", 30),
    _perm("menu:users", "用户管理", "menu", "view", 40),
    _perm("menu:departments", "部门管理", "menu", "view", 45),
    _perm("menu:employments", "任职管理", "menu", "view", 46),
    _perm("menu:admin-users", "管理员账号", "menu", "view", 50),
    _perm("menu:tenants", "租户管理", "menu", "view", 60),
    _perm("menu:audit", "审计日志", "menu", "view", 70),
    _perm("page:agents", "智能体管理页面", "page", "view", 110),
    _perm("page:grants", "用户授权页面", "page", "view", 120),
    _perm("page:roles", "角色管理页面", "page", "view", 130),
    _perm("page:users", "用户管理页面", "page", "view", 140),
    _perm("page:departments", "部门管理页面", "page", "view", 145),
    _perm("page:employments", "任职管理页面", "page", "view", 146),
    _perm("page:admin-users", "管理员账号页面", "page", "view", 150),
    _perm("page:tenants", "租户管理页面", "page", "view", 160),
    _perm("page:audit", "审计日志页面", "page", "view", 170),
    _perm("button:agent:create", "智能体-新建", "button", "create", 210),
    _perm("button:agent:update", "智能体-编辑", "button", "update", 211),
    _perm("button:agent:delete", "智能体-删除", "button", "delete", 212),
    _perm("button:skill:create", "技能-新建/导入/克隆", "button", "create", 220),
    _perm("button:skill:update", "技能-编辑/文件维护", "button", "update", 221),
    _perm("button:skill:delete", "技能-删除", "button", "delete", 222),
    _perm("button:tool:create", "工具-新建/克隆", "button", "create", 230),
    _perm("button:tool:update", "工具-编辑", "button", "update", 231),
    _perm("button:tool:delete", "工具-删除", "button", "delete", 232),
    _perm("button:component:create", "组件-新建/克隆", "button", "create", 240),
    _perm("button:component:update", "组件-编辑", "button", "update", 241),
    _perm("button:component:delete", "组件-删除", "button", "delete", 242),
    _perm("button:prompt:create", "提示词-新建/克隆", "button", "create", 250),
    _perm("button:prompt:update", "提示词-编辑", "button", "update", 251),
    _perm("button:prompt:delete", "提示词-删除", "button", "delete", 252),
    _perm("button:role:create", "角色-新建", "button", "create", 260),
    _perm("button:role:update", "角色-编辑", "button", "update", 261),
    _perm("button:role:delete", "角色-删除", "button", "delete", 262),
    _perm("button:role:copy", "角色-复制", "button", "create", 263),
    _perm("button:role:grant", "角色-授权", "button", "manage", 264),
    _perm("button:admin-user:create", "管理员账号-新建", "button", "create", 270),
    _perm("button:admin-user:update", "管理员账号-编辑", "button", "update", 271),
    _perm("button:admin-user:delete", "管理员账号-删除", "button", "delete", 272),
    _perm("button:admin-user:reset-password", "管理员账号-重置密码", "button", "manage", 273),
    _perm("button:tenant:create", "租户-新建", "button", "create", 280),
    _perm("button:tenant:update", "租户-编辑", "button", "update", 281),
    _perm("button:user:create", "用户-新建", "button", "create", 290),
    _perm("button:user:update", "用户-编辑", "button", "update", 291),
    _perm("button:user:delete", "用户-删除", "button", "delete", 292),
    _perm("button:grant:manage", "用户授权-维护", "button", "manage", 300),
    _perm("agent:create", "智能体-创建", "agent", "create", 310),
    _perm("agent:read", "智能体-查看", "agent", "read", 311),
    _perm("agent:update", "智能体-修改", "agent", "update", 312),
    _perm("agent:delete", "智能体-删除", "agent", "delete", 313),
    _perm("skill:create", "技能-创建", "skill", "create", 320),
    _perm("skill:read", "技能-查看", "skill", "read", 321),
    _perm("skill:update", "技能-修改", "skill", "update", 322),
    _perm("skill:delete", "技能-删除", "skill", "delete", 323),
    _perm("tool:create", "工具-创建", "tool", "create", 330),
    _perm("tool:read", "工具-查看", "tool", "read", 331),
    _perm("tool:update", "工具-修改", "tool", "update", 332),
    _perm("tool:delete", "工具-删除", "tool", "delete", 333),
    _perm("component:create", "组件-创建", "component", "create", 340),
    _perm("component:read", "组件-查看", "component", "read", 341),
    _perm("component:update", "组件-修改", "component", "update", 342),
    _perm("component:delete", "组件-删除", "component", "delete", 343),
    _perm("prompt:create", "提示词-创建", "prompt", "create", 350),
    _perm("prompt:read", "提示词-查看", "prompt", "read", 351),
    _perm("prompt:update", "提示词-修改", "prompt", "update", 352),
    _perm("prompt:delete", "提示词-删除", "prompt", "delete", 353),
    _perm("button:department:create", "部门-新建", "button", "create", 360),
    _perm("button:department:update", "部门-编辑", "button", "update", 361),
    _perm("button:department:delete", "部门-删除", "button", "delete", 362),
    _perm("button:employment:create", "任职-新建", "button", "create", 370),
    _perm("button:employment:update", "任职-编辑/调岗/结束任职", "button", "update", 371),
    _perm("button:employment:delete", "任职-删除", "button", "delete", 372),
)

PERMISSION_CODES: tuple[str, ...] = tuple(item.code for item in PERMISSION_CATALOG)
PERMISSION_BY_CODE: dict[str, PermissionDefinition] = {
    item.code: item for item in PERMISSION_CATALOG
}

# 租户作用域不包含平台级租户管理权限
PLATFORM_ONLY_CODES: frozenset[str] = frozenset(
    {
        "menu:tenants",
        "page:tenants",
        "button:tenant:create",
        "button:tenant:update",
    }
)
# 平台作用域不展示租户用户、用户授权与组织架构菜单：平台授权入口在资源/角色详情内
TENANT_ONLY_CODES: frozenset[str] = frozenset(
    {
        "menu:grants",
        "menu:users",
        "menu:departments",
        "menu:employments",
        "page:users",
        "page:departments",
        "page:employments",
        "button:user:create",
        "button:user:update",
        "button:user:delete",
        "button:department:create",
        "button:department:update",
        "button:department:delete",
        "button:employment:create",
        "button:employment:update",
        "button:employment:delete",
    }
)

# 组织架构：只读菜单/页面 与 部门/任职写操作按钮
_ORG_READ_CODES = frozenset(
    {
        "menu:departments",
        "menu:employments",
        "page:departments",
        "page:employments",
    }
)
_ORG_WRITE_CODES = frozenset(
    {
        "button:department:create",
        "button:department:update",
        "button:department:delete",
        "button:employment:create",
        "button:employment:update",
        "button:employment:delete",
    }
)
TENANT_SCOPED_CODES: frozenset[str] = frozenset(PERMISSION_CODES) - PLATFORM_ONLY_CODES
PLATFORM_SCOPED_CODES: frozenset[str] = frozenset(PERMISSION_CODES) - TENANT_ONLY_CODES

_READ_CODES = frozenset(
    {
        "agent:read",
        "skill:read",
        "tool:read",
        "component:read",
        "prompt:read",
    }
)
_RESOURCE_WRITE_CODES = frozenset(
    {
        f"{resource}:{action}"
        for resource in ("agent", "skill", "tool", "component", "prompt")
        for action in ("create", "update", "delete")
    }
)
_RESOURCE_BUTTON_CODES = frozenset(
    {
        f"button:{resource}:{action}"
        for resource in ("agent", "skill", "tool", "component", "prompt")
        for action in ("create", "update", "delete")
    }
)
_CONSOLE_CODES = frozenset(
    {
        CONSOLE_ACCESS,
        "menu:agents",
        "page:agents",
    }
)

# 平台内置角色：与迁移中的种子数据保持一致
PLATFORM_SUPERADMIN_CODES: frozenset[str] = PLATFORM_SCOPED_CODES
PLATFORM_ADMIN_CODES: frozenset[str] = (
    _CONSOLE_CODES | _READ_CODES | _RESOURCE_WRITE_CODES | _RESOURCE_BUTTON_CODES
)
PLATFORM_VIEWER_CODES: frozenset[str] = _CONSOLE_CODES | _READ_CODES

# 租户内置角色：仅包含租户作用域权限，并并入组织架构相关权限
TENANT_SUPERADMIN_CODES: frozenset[str] = TENANT_SCOPED_CODES
TENANT_ADMIN_CODES: frozenset[str] = (
    PLATFORM_ADMIN_CODES & TENANT_SCOPED_CODES
) | _ORG_READ_CODES | _ORG_WRITE_CODES
TENANT_VIEWER_CODES: frozenset[str] = (
    PLATFORM_VIEWER_CODES & TENANT_SCOPED_CODES
) | _ORG_READ_CODES

# 角色复制时按作用域保留的默认权限集合
DEFAULT_ROLE_PERMISSION_CODES: dict[str, dict[str, frozenset[str]]] = {
    "platform": {
        "superadmin": PLATFORM_SUPERADMIN_CODES,
        "admin": PLATFORM_ADMIN_CODES,
        "viewer": PLATFORM_VIEWER_CODES,
    },
    "tenant": {
        "superadmin": TENANT_SUPERADMIN_CODES,
        "admin": TENANT_ADMIN_CODES,
        "viewer": TENANT_VIEWER_CODES,
    },
}
