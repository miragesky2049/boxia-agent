"""仓储与工作单元协议：应用层只依赖接口，不感知数据库实现。"""

from datetime import datetime
from typing import Any, Protocol, TypeVar
from uuid import UUID

from internal.domain.entity.access import (
    GrantSummary,
    ResourceGrant,
    Role,
    User,
    UserRefreshToken,
)
from internal.domain.entity.admin_user import AdminUser
from internal.domain.entity.audit_log import AuditLog
from internal.domain.entity.refresh_token import RefreshToken
from internal.domain.entity.resource import Agent, Component, Prompt, Skill, SkillFile, Tool
from internal.domain.entity.tenant import Tenant

TResource = TypeVar("TResource")


class TenantRepository(Protocol):
    """租户仓储。"""

    def get_by_code(self, code: str) -> Tenant | None:
        """按租户编码（子域名）查询。"""

    def get_by_id(self, tenant_id: int) -> Tenant | None:
        """按主键查询。"""

    def list_all(self) -> list[Tenant]:
        """查询全部租户。"""

    def list_active(self) -> list[Tenant]:
        """查询启用中的租户。"""

    def search(self, keyword: str | None) -> list[Tenant]:
        """按关键字查询租户。"""

    def create(self, values: dict[str, Any]) -> Tenant:
        """创建租户。"""

    def update(self, tenant_id: int, values: dict[str, Any]) -> Tenant | None:
        """更新租户。"""

    def code_exists(self, code: str) -> bool:
        """租户编码是否已存在。"""

    def name_exists(self, name: str) -> bool:
        """租户名称是否已存在。"""


class AdminUserRepository(Protocol):
    """管理员账号仓储。"""

    def get_by_username(self, username: str) -> AdminUser | None:
        """按用户名查询产品级平台账号。"""

    def get_by_username_for_update(self, username: str) -> AdminUser | None:
        """按用户名加行锁查询，用于登录失败计数。"""

    def get_by_id(self, user_id: int) -> AdminUser | None:
        """按主键查询。"""

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
    ) -> tuple[list[AdminUser], int]:
        """分页查询产品级平台账号。"""

    def create(self, values: dict[str, Any]) -> AdminUser:
        """创建管理员。"""

    def update(self, user_id: int, values: dict[str, Any]) -> AdminUser | None:
        """更新管理员基础字段。"""

    def mark_login_success(self, user_id: int) -> None:
        """登录成功：清零失败次数并记录时间。"""

    def record_failed_login(
        self, user_id: int, max_attempts: int, lock_minutes: int
    ) -> datetime | None:
        """累计失败次数，返回新的锁定截止时间（未锁定返回 None）。"""

    def update_password(
        self,
        user_id: int,
        password_hash: str,
        must_change_password: bool,
        changed_at: datetime,
    ) -> None:
        """更新密码并递增令牌版本。"""

    def bump_token_version(self, user_id: int) -> int:
        """递增令牌版本，使已签发令牌失效。"""

    def delete(self, admin_user_id: int) -> bool:
        """删除管理员账号。"""


class RefreshTokenRepository(Protocol):
    """刷新令牌仓储。"""

    def create(self, values: dict[str, Any]) -> RefreshToken:
        """写入刷新令牌（哈希）。"""

    def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        """按哈希加行锁查询。"""

    def rotate(self, old_id: int, replaced_by_id: int) -> None:
        """标记旧令牌已轮换。"""

    def revoke_family(self, family_id: UUID) -> int:
        """撤销同一会话族全部令牌。"""

    def revoke_all_for_user(self, user_id: int) -> int:
        """撤销用户全部令牌。"""

    def is_family_active(self, family_id: UUID) -> bool:
        """会话族是否仍有有效令牌。"""

    def delete_expired(self, before: datetime) -> int:
        """清理过期令牌。"""


class AuditLogRepository(Protocol):
    """审计日志仓储。"""

    def record(self, values: dict[str, Any]) -> None:
        """写入审计记录。"""

    def list_page(
        self,
        page: int,
        page_size: int,
        action: str | None,
        actor_id: int | None,
        tenant_id: int | None = None,
    ) -> tuple[list[AuditLog], int]:
        """分页查询审计记录；tenant_id 为 None 时查询全部（产品级）。"""


class ResourceRepository(Protocol[TResource]):
    """通用资源仓储（技能/工具/组件/提示词）。"""

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        agent_id: int | None = None,
        manageable_only: bool = False,
        grant_state: str | None = None,
        grant_tenant_id: int | None = None,
    ) -> tuple[list[TResource], int]:
        """分页查询；manageable_only 仅返回当前作用域可授权的资源。"""

    def get(self, resource_id: int) -> TResource | None:
        """按主键查询。"""

    def create(self, values: dict) -> TResource:
        """创建。"""

    def update(self, resource_id: int, values: dict) -> TResource | None:
        """全量更新。"""

    def delete(self, resource_id: int) -> bool:
        """删除。"""

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        """名称是否已存在。"""

    def list_for_agent(
        self, agent_id: int, is_enabled: bool | None = None
    ) -> list[TResource]:
        """读取归属于指定智能体的可见资源。"""

    def ids_exist(self, ids: list[int], agent_id: int | None = None) -> set[int]:
        """返回给定 id 中真实存在的部分。"""

    def ids_owned(self, ids: list[int]) -> set[int]:
        """返回给定 id 中归属于当前作用域的部分（授权写操作校验）。"""

    def get_by_name(self, name: str) -> TResource | None:
        """按名称在当前归属范围内精确查询（忽略大小写）。"""

    def list_grantable(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        ids: list[int] | None = None,
    ) -> tuple[list[TResource], int]:
        """分页查询可向本租户角色授权的资源：租户自有 + 平台资源。"""

    def ids_grantable(self, ids: list[int]) -> set[int]:
        """返回给定 id 中可向本租户角色授权的部分。"""


class SkillFileRepository(Protocol):
    """技能包文件仓储，调用前必须由应用层完成所属技能的作用域校验。"""

    def list_by_skill(
        self, skill_id: int, prefix: str | None = None, include_content: bool = False
    ) -> list[SkillFile]:
        """按路径排序列出技能包文件；默认不加载正文。"""

    def get(self, skill_id: int, path: str) -> SkillFile | None:
        """按相对路径查询文件。"""

    def upsert(self, skill_id: int, path: str, content: str) -> SkillFile:
        """新增或覆盖文件，自动维护哈希、大小与媒体类型。"""

    def delete(self, skill_id: int, path: str) -> bool:
        """删除文件。"""

    def replace_all(self, skill_id: int, files: list[tuple[str, str]]) -> list[SkillFile]:
        """事务内全量替换技能包文件。"""

    def stats(self, skill_id: int) -> tuple[int, int]:
        """返回文件数与总字节数。"""


class AgentRepository(Protocol):
    """智能体仓储。"""

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        authorized: bool = False,
        manageable_only: bool = False,
        grant_state: str | None = None,
        grant_tenant_id: int | None = None,
    ) -> tuple[list[Agent], int]:
        """分页查询；manageable_only 仅返回当前作用域可授权的智能体。"""

    def get(self, agent_id: int) -> Agent | None:
        """查询详情（含工具/技能关联）。"""

    def create(self, values: dict) -> Agent:
        """创建智能体并写入关联。"""

    def update(self, agent_id: int, values: dict) -> Agent | None:
        """全量更新并替换关联。"""

    def delete(self, agent_id: int) -> bool:
        """删除。"""

    def ids_owned(self, ids: list[int]) -> set[int]:
        """返回给定 id 中归属于当前作用域的部分（授权写操作校验）。"""

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        """名称是否已存在。"""

    def list_grantable(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        ids: list[int] | None = None,
    ) -> tuple[list[Agent], int]:
        """分页查询可向本租户角色授权的智能体：租户自有 + 平台资源。"""

    def ids_grantable(self, ids: list[int]) -> set[int]:
        """返回给定 id 中可向本租户角色授权的部分。"""


class RoleRepository(Protocol):
    """租户角色仓储。"""

    def get_by_id(self, role_id: int) -> Role | None:
        """按主键查询。"""

    def get_by_code(self, tenant_id: int, code: str) -> Role | None:
        """按租户与编码查询。"""

    def list_by_tenant(self, tenant_id: int, include_inactive: bool = False) -> list[Role]:
        """查询租户角色列表。"""

    def create(self, values: dict[str, Any]) -> Role:
        """创建角色。"""

    def update(self, role_id: int, values: dict[str, Any]) -> Role | None:
        """更新角色。"""

    def delete(self, role_id: int) -> bool:
        """删除角色。"""

    def code_exists(self, tenant_id: int, code: str, exclude_id: int | None = None) -> bool:
        """租户内编码是否已存在。"""

    def name_exists(self, tenant_id: int, name: str, exclude_id: int | None = None) -> bool:
        """租户内名称是否已存在。"""

    def count_references(self, role_id: int) -> int:
        """统计管理员账号与最终用户的引用数。"""


class UserRepository(Protocol):
    """最终用户仓储。"""

    def get_by_username(self, username: str, tenant_id: int) -> User | None:
        """按用户名与租户查询。"""

    def get_by_username_for_update(self, username: str, tenant_id: int) -> User | None:
        """登录失败计数使用的加锁查询。"""

    def get_by_id(self, user_id: int) -> User | None:
        """按主键查询。"""

    def list_page(
        self, page: int, page_size: int, keyword: str | None, tenant_id: int
    ) -> tuple[list[User], int]:
        """分页查询租户最终用户。"""

    def create(self, values: dict[str, Any]) -> User:
        """创建最终用户。"""

    def update(self, user_id: int, values: dict[str, Any]) -> User | None:
        """更新最终用户。"""

    def delete(self, user_id: int) -> bool:
        """删除最终用户。"""

    def username_exists(self, tenant_id: int, username: str, exclude_id: int | None = None) -> bool:
        """租户内用户名是否已存在。"""

    def mark_login_success(self, user_id: int) -> None:
        """登录成功：清零失败次数并记录时间。"""

    def record_failed_login(
        self, user_id: int, max_attempts: int, lock_minutes: int
    ) -> datetime | None:
        """累计失败次数，达到阈值后锁定。"""

    def update_password(self, user_id: int, password_hash: str) -> None:
        """更新密码并递增令牌版本。"""

    def bump_token_version(self, user_id: int) -> int:
        """递增令牌版本。"""

    def list_role_ids(self, user_id: int) -> tuple[int, ...]:
        """读取用户的全部角色 ID。"""

    def list_role_ids_for_users(self, user_ids: list[int]) -> dict[int, tuple[int, ...]]:
        """批量读取多个用户的角色 ID，避免列表 N+1。"""

    def replace_roles(self, user_id: int, tenant_id: int, role_ids: list[int]) -> None:
        """整体替换用户角色，并把首个角色设为主角色。"""

    def add_roles_for_users(
        self, user_ids: list[int], tenant_id: int, role_ids: list[int]
    ) -> int:
        """批量追加角色授权，已存在的关联自动跳过，返回新增关联数。"""

    def ids_existing(self, tenant_id: int, user_ids: list[int]) -> set[int]:
        """返回给定 id 中属于当前租户的用户 ID。"""

    def list_admin_page(
        self,
        tenant_id: int,
        page: int,
        page_size: int,
        keyword: str | None,
        admin_system_roles: tuple[str, ...],
    ) -> tuple[list[User], int]:
        """分页查询拥有管理类角色的租户用户。"""

    def has_role_system(
        self, user_id: int, tenant_id: int, system_roles: tuple[str, ...]
    ) -> bool:
        """判断用户是否拥有指定系统角色之一。"""


class UserRefreshTokenRepository(Protocol):
    """最终用户刷新令牌仓储。"""

    def create(self, values: dict[str, Any]) -> UserRefreshToken:
        """写入刷新令牌（哈希）。"""

    def get_by_hash_for_update(self, token_hash: str) -> UserRefreshToken | None:
        """按哈希加行锁查询。"""

    def rotate(self, old_id: int, replaced_by_id: int) -> None:
        """标记旧令牌已轮换。"""

    def revoke_family(self, family_id: UUID) -> int:
        """撤销同一会话族全部令牌。"""

    def revoke_all_for_user(self, user_id: int) -> int:
        """撤销用户全部令牌。"""

    def is_family_active(self, family_id: UUID) -> bool:
        """会话族是否仍有有效令牌。"""


class ResourceGrantRepository(Protocol):
    """资源授权仓储。"""

    def list_for_resource(
        self, resource_type: str, resource_id: int, tenant_id: int | None = None
    ) -> list[ResourceGrant]:
        """读取资源授权；指定租户时只返回该租户的授权。"""

    def list_for_resources(
        self,
        resource_type: str,
        resource_ids: list[int],
        tenant_id: int | None = None,
    ) -> list[ResourceGrant]:
        """批量读取多个资源的授权（避免列表 N+1）；可限定租户。"""

    def summary_for_resources(
        self,
        resource_type: str,
        resource_ids: list[int],
        tenant_id: int | None = None,
    ) -> dict[int, GrantSummary]:
        """批量统计资源授权数量，不加载授权明细。"""

    def lock_resources(self, resource_type: str, resource_ids: list[int]) -> None:
        """按排序后的资源顺序获取事务级仲裁锁，串行化批量写入。"""

    def replace_for_resource(
        self,
        resource_type: str,
        resource_id: int,
        grants: list[tuple[int, int | None]],
        granted_by: int | None,
    ) -> None:
        """整体替换资源授权。"""

    def replace_for_tenant(
        self,
        resource_type: str,
        resource_id: int,
        tenant_id: int,
        role_ids: list[int] | None,
        granted_by: int | None,
    ) -> None:
        """整体替换某租户对资源的授权；role_ids 为 None 表示整个租户。"""

    def delete_for_resources(self, resource_type: str, resource_ids: list[int]) -> None:
        """批量删除多个资源的全部授权。"""

    def delete_for_resource(self, resource_type: str, resource_id: int) -> None:
        """删除资源全部授权。"""

    def count_for_role(self, role_id: int) -> int:
        """统计角色被授权次数。"""

    def list_granted_resource_ids(self, role_id: int, resource_type: str) -> set[int]:
        """读取角色在某类资源上已获授权的资源 ID。"""

    def list_for_role(
        self, role_id: int, resource_type: str
    ) -> list[ResourceGrant]:
        """读取角色在某类资源上的全部授权明细。"""

    def replace_for_role(
        self,
        role_id: int,
        tenant_id: int,
        resource_type: str,
        resource_ids: list[int],
        granted_by: int | None,
    ) -> None:
        """整体替换角色在某类资源上的授权。"""

    def add_for_role(
        self,
        role_id: int,
        tenant_id: int,
        resource_type: str,
        resource_ids: list[int],
        granted_by: int | None,
    ) -> int:
        """追加角色授权，重复授权自动跳过，返回新增数量。"""

    def remove_for_role(self, role_id: int, resource_type: str, resource_id: int) -> bool:
        """删除角色对单个资源的授权。"""


class UnitOfWork(Protocol):
    """请求级工作单元，负责事务提交与仓储访问。"""

    tenant_id: int | None
    tenants: TenantRepository
    admin_users: AdminUserRepository
    refresh_tokens: RefreshTokenRepository
    audit_logs: AuditLogRepository
    roles: RoleRepository
    users: UserRepository
    user_refresh_tokens: UserRefreshTokenRepository
    resource_grants: ResourceGrantRepository
    agents: AgentRepository
    skills: ResourceRepository[Skill]
    skill_files: SkillFileRepository
    tools: ResourceRepository[Tool]
    components: ResourceRepository[Component]
    prompts: ResourceRepository[Prompt]

    def apply_scope(
        self, role_ids: tuple[int, ...] = (), apply_role_filter: bool = True
    ) -> None:
        """按当前账号角色重建资源与智能体仓储。"""

    def commit(self) -> None:
        """提交事务。"""

    def rollback(self) -> None:
        """回滚事务。"""

    def close(self) -> None:
        """释放会话。"""


# 便于在类型注解中直接引用具体资源仓储
SkillRepository = ResourceRepository[Skill]
ToolRepository = ResourceRepository[Tool]
ComponentRepository = ResourceRepository[Component]
PromptRepository = ResourceRepository[Prompt]
