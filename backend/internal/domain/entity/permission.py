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
    is_active: bool
    sort_order: int


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
    _perm("menu:apps", "应用管理", "menu", "view", 10),
    _perm("menu:marketplace", "应用市场", "menu", "view", 12),
    _perm("menu:resources", "资源管理", "menu", "view", 14),
    _perm("menu:grants", "用户授权", "menu", "view", 20),
    _perm("menu:roles", "角色管理", "menu", "view", 30),
    _perm("menu:users", "用户管理", "menu", "view", 40),
    _perm("menu:departments", "部门管理", "menu", "view", 45),
    _perm("menu:employments", "任职管理", "menu", "view", 46),
    _perm("menu:mgmt-units", "管理单元", "menu", "view", 47),
    _perm("menu:admin-users", "管理员账号", "menu", "view", 50),
    _perm("menu:tenants", "租户管理", "menu", "view", 60),
    _perm("menu:audit", "审计日志", "menu", "view", 70),
    _perm("page:apps", "应用管理页面", "page", "view", 110),
    _perm("page:marketplace", "应用市场页面", "page", "view", 112),
    _perm("page:resources", "资源管理页面", "page", "view", 114),
    _perm("page:grants", "用户授权页面", "page", "view", 120),
    _perm("page:roles", "角色管理页面", "page", "view", 130),
    _perm("page:users", "用户管理页面", "page", "view", 140),
    _perm("page:departments", "部门管理页面", "page", "view", 145),
    _perm("page:employments", "任职管理页面", "page", "view", 146),
    _perm("page:mgmt-units", "管理单元页面", "page", "view", 147),
    _perm("page:admin-users", "管理员账号页面", "page", "view", 150),
    _perm("page:tenants", "租户管理页面", "page", "view", 160),
    _perm("page:audit", "审计日志页面", "page", "view", 170),
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
    _perm("button:tenant:delete", "租户-删除", "button", "delete", 282),
    _perm("button:user:create", "用户-新建", "button", "create", 290),
    _perm("button:user:update", "用户-编辑", "button", "update", 291),
    _perm("button:user:delete", "用户-删除", "button", "delete", 292),
    _perm("button:grant:manage", "用户授权-维护", "button", "manage", 300),
    _perm("button:department:create", "部门-新建", "button", "create", 360),
    _perm("button:department:update", "部门-编辑", "button", "update", 361),
    _perm("button:department:delete", "部门-删除", "button", "delete", 362),
    _perm("button:employment:create", "任职-新建", "button", "create", 370),
    _perm("button:employment:update", "任职-编辑/调岗/结束任职", "button", "update", 371),
    _perm("button:employment:delete", "任职-删除", "button", "delete", 372),
    _perm("button:mgmt-unit:create", "管理单元-新建", "button", "create", 380),
    _perm("button:mgmt-unit:update", "管理单元-编辑", "button", "update", 381),
    _perm("button:mgmt-unit:delete", "管理单元-删除", "button", "delete", 382),
    _perm("button:mgmt-unit:grant", "管理单元-授权用户", "button", "manage", 384),
    _perm("button:audit:clear", "审计日志-清空", "button", "delete", 390),
    _perm("button:app:create", "应用-新建", "button", "create", 400),
    _perm("button:app:update", "应用-编辑", "button", "update", 401),
    _perm("button:app:delete", "应用-删除", "button", "delete", 402),
    _perm("menu:entitlements", "租户开通", "menu", "view", 15),
    _perm("page:entitlements", "租户开通页面", "page", "view", 115),
    _perm("button:entitlement:manage", "租户开通-维护", "button", "manage", 405),
    _perm("button:resource:review", "资源-审核", "button", "manage", 406),
    _perm("button:resource:create", "资源-新建", "button", "create", 302),
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
        "button:tenant:delete",
        "menu:entitlements",
        "page:entitlements",
        "button:entitlement:manage",
        "button:resource:review",
        "button:app:delete",
    }
)
# 平台作用域不展示租户用户、用户授权与组织架构菜单：平台授权入口在资源/角色详情内
TENANT_ONLY_CODES: frozenset[str] = frozenset(
    {
        "menu:grants",
        "menu:users",
        "menu:departments",
        "menu:employments",
        "menu:mgmt-units",
        "page:users",
        "page:departments",
        "page:employments",
        "page:mgmt-units",
        "button:user:create",
        "button:user:update",
        "button:user:delete",
        "button:department:create",
        "button:department:update",
        "button:department:delete",
        "button:employment:create",
        "button:employment:update",
        "button:employment:delete",
        "button:mgmt-unit:create",
        "button:mgmt-unit:update",
        "button:mgmt-unit:delete",
        "button:mgmt-unit:grant",
        "button:resource:create",
    }
)

# 组织与管理单元：只读菜单/页面 与 部门/任职/管理单元/数据范围写操作按钮
_ORG_READ_CODES = frozenset(
    {
        "menu:departments",
        "menu:employments",
        "menu:mgmt-units",
        "page:departments",
        "page:employments",
        "page:mgmt-units",
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
        "button:mgmt-unit:create",
        "button:mgmt-unit:update",
        "button:mgmt-unit:delete",
        "button:mgmt-unit:grant",
    }
)
TENANT_SCOPED_CODES: frozenset[str] = frozenset(PERMISSION_CODES) - PLATFORM_ONLY_CODES
PLATFORM_SCOPED_CODES: frozenset[str] = frozenset(PERMISSION_CODES) - TENANT_ONLY_CODES

_CONSOLE_CODES = frozenset(
    {
        CONSOLE_ACCESS,
        "menu:apps",
        "page:apps",
        "menu:marketplace",
        "page:marketplace",
        "menu:resources",
        "page:resources",
    }
)

# 平台内置角色新增：租户开通 + 资源审核（viewer 不授予）
_ENTITLEMENT_CODES = frozenset(
    {
        "menu:entitlements",
        "page:entitlements",
        "button:entitlement:manage",
        "button:resource:review",
    }
)
# 租户内置角色新增：资源新建（viewer 不授予）；
# 0073 起角色授权页并入角色详情，role-access 三码下线
_TENANT_RESOURCE_CODES = frozenset(
    {
        "button:resource:create",
    }
)

# 平台内置角色：与迁移中的种子数据保持一致
PLATFORM_SUPERADMIN_CODES: frozenset[str] = PLATFORM_SCOPED_CODES
PLATFORM_ADMIN_CODES: frozenset[str] = _CONSOLE_CODES | _ENTITLEMENT_CODES
PLATFORM_VIEWER_CODES: frozenset[str] = _CONSOLE_CODES

# 租户内置角色：仅包含租户作用域权限，并并入组织架构相关权限
TENANT_SUPERADMIN_CODES: frozenset[str] = TENANT_SCOPED_CODES
TENANT_ADMIN_CODES: frozenset[str] = (
    (PLATFORM_ADMIN_CODES & TENANT_SCOPED_CODES)
    | _ORG_READ_CODES
    | _ORG_WRITE_CODES
    | _TENANT_RESOURCE_CODES
)
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
