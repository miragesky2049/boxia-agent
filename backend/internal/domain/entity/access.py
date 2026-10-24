"""租户角色、最终用户与资源授权领域实体。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

# 租户初始化时自动生成的系统角色：(code, name, description)
SYSTEM_ROLE_SEEDS = (
    ("superadmin", "超级管理员", "租户最高权限，可管理本租户全部对象与授权"),
    ("admin", "管理员", "可读写本租户被授权的业务对象"),
    ("viewer", "只读成员", "只读访问被授权的业务对象"),
)

RESOURCE_TYPES = ("agent", "skill", "tool", "component", "prompt")

# 管理端基础权限：read=查看，write=业务对象读写，manage=角色/账号/授权管理
SYSTEM_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "superadmin": ("read", "write", "manage"),
    "admin": ("read", "write"),
    "viewer": ("read",),
}


@dataclass(frozen=True)
class Role:
    """租户自定义角色；system_role 决定管理端基础权限。"""

    id: int
    tenant_id: int
    code: str
    name: str
    description: str
    system_role: str
    is_system: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class User:
    """租户最终用户。"""

    id: int
    tenant_id: int
    username: str
    password_hash: str
    display_name: str
    is_active: bool
    role_id: int
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    token_version: int = 1
    failed_login_count: int = 0
    locked_until: datetime | None = None
    role_ids: tuple[int, ...] = ()

    def effective_role_ids(self) -> tuple[int, ...]:
        """返回完整角色集合；旧数据未写入关联表时退回主角色。"""
        return self.role_ids or (self.role_id,)


@dataclass(frozen=True)
class UserRefreshToken:
    """最终用户刷新令牌（仅存哈希）。"""

    id: int
    user_id: int
    token_hash: str
    family_id: UUID
    token_version: int
    issued_at: datetime
    expires_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    replaced_by_id: int | None = None
    ip: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class ResourceGrant:
    """资源授权：role_id 为空表示授予整个租户。"""

    id: int
    resource_type: str
    resource_id: int
    tenant_id: int
    role_id: int | None
    granted_by: int | None
    created_at: datetime


@dataclass(frozen=True)
class GrantSummary:
    """资源授权汇总：用于授权管理列表，避免逐条加载授权明细。"""

    resource_id: int
    grant_count: int
    tenant_count: int
    role_count: int


@dataclass(frozen=True)
class AccessScope:
    """仓储查询使用的作用域：租户 + 当前账号可用的角色集合。"""

    tenant_id: int | None
    role_ids: tuple[int, ...] = ()
    apply_role_filter: bool = True
    is_platform: bool = False

    @property
    def has_role_filter(self) -> bool:
        """是否需要按角色收敛可见范围。"""
        return self.apply_role_filter and bool(self.role_ids)

    @property
    def allowed_role_ids(self) -> set[int]:
        """便于集合运算的角色 ID 集合。"""
        return set(self.role_ids)
