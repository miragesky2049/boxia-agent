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


@dataclass(frozen=True)
class Role:
    """角色；tenant_id 为空表示平台自有角色，功能权限由 role_permissions 决定。"""

    id: UUID
    tenant_id: UUID | None
    code: str
    name: str
    description: str
    is_system: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class User:
    """租户最终用户。"""

    id: UUID
    tenant_id: UUID
    username: str
    password_hash: str
    display_name: str
    is_active: bool
    role_id: UUID
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    token_version: int = 1
    failed_login_count: int = 0
    locked_until: datetime | None = None
    must_change_password: bool = False
    password_changed_at: datetime | None = None
    role_ids: tuple[UUID, ...] = ()
    # 当前任职部门展示字段，由用户列表仓储按当前任职批量回填
    current_department_id: UUID | None = None
    current_department_name: str | None = None

    def effective_role_ids(self) -> tuple[UUID, ...]:
        """返回完整角色集合；旧数据未写入关联表时退回主角色。"""
        return self.role_ids or (self.role_id,)


@dataclass(frozen=True)
class UserRefreshToken:
    """最终用户刷新令牌（仅存哈希）。"""

    id: UUID
    user_id: UUID
    token_hash: str
    family_id: UUID
    token_version: int
    issued_at: datetime
    expires_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    replaced_by_id: UUID | None = None
    ip: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class ResourceGrant:
    """资源授权：role_id 为空表示授予整个租户。"""

    id: UUID
    resource_type: str
    resource_id: UUID
    tenant_id: UUID | None
    role_id: UUID | None
    granted_by: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class AgentTenantOpening:
    """平台智能体对租户的开通关系；不代表角色级可见性。"""

    id: UUID
    agent_id: UUID
    tenant_id: UUID
    opened_by: UUID | None
    opened_at: datetime


@dataclass(frozen=True)
class GrantSummary:
    """资源授权汇总：用于授权管理列表，避免逐条加载授权明细。"""

    resource_id: UUID
    grant_count: int
    tenant_count: int
    role_count: int


@dataclass(frozen=True)
class AccessScope:
    """仓储查询使用的作用域：租户 + 当前账号可用的角色集合。"""

    tenant_id: UUID | None
    role_ids: tuple[UUID, ...] = ()
    apply_role_filter: bool = True
    is_platform: bool = False

    @property
    def has_role_filter(self) -> bool:
        """是否需要按角色收敛可见范围。"""
        return self.apply_role_filter and bool(self.role_ids)

    @property
    def allowed_role_ids(self) -> set[UUID]:
        """便于集合运算的角色 ID 集合。"""
        return set(self.role_ids)
