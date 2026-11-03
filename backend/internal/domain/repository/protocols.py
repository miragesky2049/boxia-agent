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
from internal.domain.entity.department import Department
from internal.domain.entity.employment import Employment
from internal.domain.entity.hr_dictionary import HrDictionary
from internal.domain.entity.mgmt_unit import (
    ManagementUnit,
    MgmtUnitDepartment,
    MgmtUnitUser,
)
from internal.domain.entity.permission import PermissionResource
from internal.domain.entity.refresh_token import RefreshToken
from internal.domain.entity.resource import Tool
from internal.domain.entity.tenant import Tenant
from internal.domain.entity.user_mgmt_unit_grant import UserMgmtUnitGrant

TResource = TypeVar("TResource")


class TenantRepository(Protocol):
    """租户仓储。"""

    def get_by_code(self, code: str) -> Tenant | None:
        """按租户编码（子域名）查询。"""

    def get_by_id(self, tenant_id: UUID) -> Tenant | None:
        """按主键查询。"""

    def list_all(self) -> list[Tenant]:
        """查询全部租户。"""

    def list_active(self) -> list[Tenant]:
        """查询启用中的租户。"""

    def search(self, keyword: str | None) -> list[Tenant]:
        """按关键字查询租户。"""

    def create(self, values: dict[str, Any]) -> Tenant:
        """创建租户。"""

    def update(self, tenant_id: UUID, values: dict[str, Any]) -> Tenant | None:
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

    def get_by_id(self, user_id: UUID) -> AdminUser | None:
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

    def update(self, user_id: UUID, values: dict[str, Any]) -> AdminUser | None:
        """更新管理员基础字段。"""

    def mark_login_success(self, user_id: UUID) -> None:
        """登录成功：清零失败次数并记录时间。"""

    def record_failed_login(
        self, user_id: UUID, max_attempts: int, lock_minutes: int
    ) -> datetime | None:
        """累计失败次数，返回新的锁定截止时间（未锁定返回 None）。"""

    def update_password(
        self,
        user_id: UUID,
        password_hash: str,
        must_change_password: bool,
        changed_at: datetime,
    ) -> None:
        """更新密码并递增令牌版本。"""

    def bump_token_version(self, user_id: UUID) -> int:
        """递增令牌版本，使已签发令牌失效。"""

    def delete(self, admin_user_id: UUID) -> bool:
        """删除管理员账号。"""


class RefreshTokenRepository(Protocol):
    """刷新令牌仓储。"""

    def create(self, values: dict[str, Any]) -> RefreshToken:
        """写入刷新令牌（哈希）。"""

    def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        """按哈希加行锁查询。"""

    def rotate(self, old_id: UUID, replaced_by_id: UUID) -> None:
        """标记旧令牌已轮换。"""

    def revoke_family(self, family_id: UUID) -> int:
        """撤销同一会话族全部令牌。"""

    def revoke_all_for_user(self, user_id: UUID) -> int:
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
        actor_id: UUID | None,
        tenant_id: UUID | None = None,
    ) -> tuple[list[AuditLog], int]:
        """分页查询审计记录；tenant_id 为 None 时查询全部（产品级）。"""


class ResourceRepository(Protocol[TResource]):
    """通用资源仓储（工具）。"""

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        manageable_only: bool = False,
        grant_state: str | None = None,
        grant_tenant_id: UUID | None = None,
    ) -> tuple[list[TResource], int]:
        """分页查询；manageable_only 仅返回当前作用域可授权的资源。"""

    def get(self, resource_id: UUID) -> TResource | None:
        """按主键查询。"""

    def create(self, values: dict) -> TResource:
        """创建。"""

    def update(self, resource_id: UUID, values: dict) -> TResource | None:
        """全量更新。"""

    def delete(self, resource_id: UUID) -> bool:
        """删除。"""

    def name_exists(self, name: str, exclude_id: UUID | None = None) -> bool:
        """名称是否已存在。"""

    def ids_exist(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中真实存在的部分。"""

    def ids_owned(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中归属于当前作用域的部分（授权写操作校验）。"""

    def get_by_name(self, name: str) -> TResource | None:
        """按名称在当前归属范围内精确查询（忽略大小写）。"""

    def list_grantable(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        ids: list[UUID] | None = None,
    ) -> tuple[list[TResource], int]:
        """分页查询可向本租户角色授权的资源：租户自有 + 已对本租户可见的平台资源。"""

    def ids_grantable(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中可向本租户角色授权的部分。"""


class RoleRepository(Protocol):
    """角色仓储：tenant_id 为空表示平台角色。"""

    def get_by_id(self, role_id: UUID) -> Role | None:
        """按主键查询。"""

    def get_by_code(self, tenant_id: UUID | None, code: str) -> Role | None:
        """按作用域与编码查询。"""

    def list_by_tenant(self, tenant_id: UUID | None, include_inactive: bool = False) -> list[Role]:
        """查询作用域内角色列表。"""

    def create(self, values: dict[str, Any]) -> Role:
        """创建角色。"""

    def update(self, role_id: UUID, values: dict[str, Any]) -> Role | None:
        """更新角色。"""

    def delete(self, role_id: UUID) -> bool:
        """删除角色。"""

    def code_exists(
        self, tenant_id: UUID | None, code: str, exclude_id: UUID | None = None
    ) -> bool:
        """作用域内编码是否已存在。"""

    def name_exists(
        self, tenant_id: UUID | None, name: str, exclude_id: UUID | None = None
    ) -> bool:
        """作用域内名称是否已存在。"""

    def count_references(self, role_id: UUID) -> int:
        """统计管理员账号与最终用户的引用数。"""


class PermissionResourceRepository(Protocol):
    """权限资源目录仓储（全局只读目录）。"""

    def list_all(self, include_inactive: bool = False) -> list[PermissionResource]:
        """按分类与排序读取权限目录。"""

    def list_by_codes(self, codes: set[str] | frozenset[str]) -> list[PermissionResource]:
        """按编码批量读取权限资源。"""

    def list_ids_by_codes(self, codes: set[str] | frozenset[str]) -> dict[str, UUID]:
        """返回编码到主键的映射，用于写入角色授权。"""

    def existing_codes(self, codes: set[str] | frozenset[str]) -> set[str]:
        """返回给定编码中真实存在且启用的部分。"""


class RolePermissionRepository(Protocol):
    """角色权限关系仓储。"""

    def lock_role(self, role_id: UUID) -> bool:
        """锁定角色行，串行化同一角色的并发授权写入。"""

    def list_codes_for_role(self, role_id: UUID) -> set[str]:
        """读取角色已授予的权限编码。"""

    def list_codes_for_roles(self, role_ids: tuple[UUID, ...]) -> set[str]:
        """合并读取多个角色的权限编码（多角色用户取并集）。"""

    def list_role_ids_with_code(self, tenant_id: UUID | None, code: str) -> set[UUID]:
        """读取作用域内拥有指定权限的角色 ID。"""

    def replace_for_role(
        self, role_id: UUID, codes: set[str] | frozenset[str], granted_by: UUID | None
    ) -> None:
        """整体替换角色权限；未在目录中的编码被忽略。"""

    def add_for_role(
        self, role_id: UUID, codes: set[str] | frozenset[str], granted_by: UUID | None
    ) -> int:
        """追加角色权限，重复授权自动跳过，返回新增数量。"""

    def remove_for_role(self, role_id: UUID, code: str) -> bool:
        """移除角色对单个权限的授权。"""

    def count_for_role(self, role_id: UUID) -> int:
        """统计角色权限数量。"""


class UserRepository(Protocol):
    """最终用户仓储。"""

    def get_by_username(self, username: str, tenant_id: UUID) -> User | None:
        """按用户名与租户查询。"""

    def get_by_username_for_update(self, username: str, tenant_id: UUID) -> User | None:
        """登录失败计数使用的加锁查询。"""

    def get_by_id(self, user_id: UUID) -> User | None:
        """按主键查询。"""

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        tenant_id: UUID,
        user_ids: list[UUID] | None = None,
    ) -> tuple[list[User], int]:
        """分页查询租户最终用户；user_ids 非空时仅返回其中用户（部门子树筛选用）。"""

    def create(self, values: dict[str, Any]) -> User:
        """创建最终用户。"""

    def update(self, user_id: UUID, values: dict[str, Any]) -> User | None:
        """更新最终用户。"""

    def delete(self, user_id: UUID) -> bool:
        """删除最终用户。"""

    def username_exists(
        self, tenant_id: UUID, username: str, exclude_id: UUID | None = None
    ) -> bool:
        """租户内用户名是否已存在。"""

    def mark_login_success(self, user_id: UUID) -> None:
        """登录成功：清零失败次数并记录时间。"""

    def record_failed_login(
        self, user_id: UUID, max_attempts: int, lock_minutes: int
    ) -> datetime | None:
        """累计失败次数，达到阈值后锁定。"""

    def update_password(
        self,
        user_id: UUID,
        password_hash: str,
        must_change_password: bool,
        changed_at: datetime,
    ) -> None:
        """更新密码、改密标记与时间，并递增令牌版本。"""

    def bump_token_version(self, user_id: UUID) -> int:
        """递增令牌版本。"""

    def list_role_ids(self, user_id: UUID) -> tuple[UUID, ...]:
        """读取用户的全部角色 ID。"""

    def list_role_ids_for_users(self, user_ids: list[UUID]) -> dict[UUID, tuple[UUID, ...]]:
        """批量读取多个用户的角色 ID，避免列表 N+1。"""

    def replace_roles(self, user_id: UUID, tenant_id: UUID, role_ids: list[UUID]) -> None:
        """整体替换用户角色，并把首个角色设为主角色。"""

    def add_roles_for_users(
        self, user_ids: list[UUID], tenant_id: UUID, role_ids: list[UUID]
    ) -> int:
        """批量追加角色授权，已存在的关联自动跳过，返回新增关联数。"""

    def ids_existing(self, tenant_id: UUID, user_ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中属于当前租户的用户 ID。"""

    def list_admin_page(
        self,
        tenant_id: UUID,
        page: int,
        page_size: int,
        keyword: str | None,
        permission_code: str,
    ) -> tuple[list[User], int]:
        """分页查询拥有指定管理权限的租户用户。"""

    def has_permission(self, user_id: UUID, tenant_id: UUID, permission_code: str) -> bool:
        """判断用户是否通过任一角色获得指定权限。"""


class UserRefreshTokenRepository(Protocol):
    """最终用户刷新令牌仓储。"""

    def create(self, values: dict[str, Any]) -> UserRefreshToken:
        """写入刷新令牌（哈希）。"""

    def get_by_hash_for_update(self, token_hash: str) -> UserRefreshToken | None:
        """按哈希加行锁查询。"""

    def rotate(self, old_id: UUID, replaced_by_id: UUID) -> None:
        """标记旧令牌已轮换。"""

    def revoke_family(self, family_id: UUID) -> int:
        """撤销同一会话族全部令牌。"""

    def revoke_all_for_user(self, user_id: UUID) -> int:
        """撤销用户全部令牌。"""

    def is_family_active(self, family_id: UUID) -> bool:
        """会话族是否仍有有效令牌。"""


class ResourceGrantRepository(Protocol):
    """资源授权仓储。"""

    def list_for_resource(
        self, resource_type: str, resource_id: UUID, tenant_id: UUID | None = None
    ) -> list[ResourceGrant]:
        """读取资源授权；指定租户时只返回该租户的授权。"""

    def list_for_resources(
        self,
        resource_type: str,
        resource_ids: list[UUID],
        tenant_id: UUID | None = None,
    ) -> list[ResourceGrant]:
        """批量读取多个资源的授权（避免列表 N+1）；可限定租户。"""

    def summary_for_resources(
        self,
        resource_type: str,
        resource_ids: list[UUID],
        tenant_id: UUID | None = None,
    ) -> dict[UUID, GrantSummary]:
        """批量统计资源授权数量，不加载授权明细。"""

    def lock_resources(self, resource_type: str, resource_ids: list[UUID]) -> None:
        """按排序后的资源顺序获取事务级仲裁锁，串行化批量写入。"""

    def replace_for_resource(
        self,
        resource_type: str,
        resource_id: UUID,
        grants: list[tuple[UUID, UUID | None]],
        granted_by: UUID | None,
    ) -> None:
        """整体替换资源授权。"""

    def replace_for_tenant(
        self,
        resource_type: str,
        resource_id: UUID,
        tenant_id: UUID,
        role_ids: list[UUID] | None,
        granted_by: UUID | None,
    ) -> None:
        """整体替换某租户对资源的授权；role_ids 为 None 表示整个租户。"""

    def delete_for_resources(self, resource_type: str, resource_ids: list[UUID]) -> None:
        """批量删除多个资源的全部授权。"""

    def delete_for_tenant_resources(
        self, resource_type: str, resource_ids: list[UUID], tenant_id: UUID
    ) -> None:
        """批量删除某租户对多个资源的授权，不影响其他租户。"""

    def delete_for_resource(self, resource_type: str, resource_id: UUID) -> None:
        """删除资源全部授权。"""

    def count_for_role(self, role_id: UUID) -> int:
        """统计角色被授权次数。"""

    def list_granted_resource_ids(self, role_id: UUID, resource_type: str) -> set[UUID]:
        """读取角色在某类资源上已获授权的资源 ID。"""

    def list_effective_granted_resource_ids(
        self, role_id: UUID, tenant_id: UUID, resource_type: str
    ) -> set[UUID]:
        """读取角色的有效授权资源 ID：本角色显式授权或整租户授权。"""

    def count_effective_granted(self, role_id: UUID, tenant_id: UUID, resource_type: str) -> int:
        """统计角色在某类资源上的有效授权数量。"""

    def list_tenant_wide_resource_ids(self, tenant_id: UUID, resource_type: str) -> set[UUID]:
        """读取某租户整租户授权的资源 ID。"""

    def has_tenant_wide(self, resource_type: str, resource_id: UUID, tenant_id: UUID) -> bool:
        """资源是否存在对指定租户的整租户授权。"""

    def list_for_role(self, role_id: UUID, resource_type: str) -> list[ResourceGrant]:
        """读取角色在某类资源上的全部授权明细。"""

    def replace_for_role(
        self,
        role_id: UUID,
        tenant_id: UUID,
        resource_type: str,
        resource_ids: list[UUID],
        granted_by: UUID | None,
    ) -> None:
        """整体替换角色在某类资源上的授权。"""

    def add_for_role(
        self,
        role_id: UUID,
        tenant_id: UUID,
        resource_type: str,
        resource_ids: list[UUID],
        granted_by: UUID | None,
    ) -> int:
        """追加角色授权，重复授权自动跳过，返回新增数量。"""

    def remove_for_role(self, role_id: UUID, resource_type: str, resource_id: UUID) -> bool:
        """删除角色对单个资源的授权。"""

    def list_platform_granted_resource_ids(self, role_id: UUID, resource_type: str) -> set[UUID]:
        """读取平台角色在某类平台资源上已获授权的资源 ID。"""

    def count_platform_granted(self, role_id: UUID, resource_type: str) -> int:
        """统计平台角色在某类平台资源上的授权数量。"""

    def replace_for_platform_role(
        self,
        role_id: UUID,
        resource_type: str,
        resource_ids: list[UUID],
        granted_by: UUID | None,
    ) -> None:
        """整体替换平台角色在某类平台资源上的授权。"""

    def add_for_platform_role(
        self,
        role_id: UUID,
        resource_type: str,
        resource_ids: list[UUID],
        granted_by: UUID | None,
    ) -> int:
        """追加平台角色授权，重复授权自动跳过，返回新增数量。"""

    def remove_for_platform_role(
        self, role_id: UUID, resource_type: str, resource_id: UUID
    ) -> bool:
        """删除平台角色对单个平台资源的授权。"""


class DepartmentRepository(Protocol):
    """部门仓储：物化路径树，所有调用均在单一租户作用域内。"""

    def get(self, department_id: UUID) -> Department | None:
        """按主键查询部门。"""

    def get_for_update(
        self, department_id: UUID, tenant_id: UUID | None = None
    ) -> Department | None:
        """按主键加行锁查询部门；传入租户时同时限定租户。"""

    def list_all(self, tenant_id: UUID) -> list[Department]:
        """按 path 排序返回租户全部部门，由应用层在内存组装树。"""

    def create(self, values: dict[str, Any]) -> Department:
        """创建部门。"""

    def update(self, department_id: UUID, values: dict[str, Any]) -> Department | None:
        """更新部门基础字段。"""

    def delete(self, department_id: UUID) -> bool:
        """物理删除部门。"""

    def code_exists(
        self, tenant_id: UUID, code: str, exclude_id: UUID | None = None
    ) -> bool:
        """租户内部门编码是否已存在（忽略大小写）。"""

    def name_exists_under_parent(
        self,
        tenant_id: UUID,
        parent_id: UUID | None,
        name: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        """同一父部门下名称是否已存在（忽略大小写，根部门父 id 为空）。"""

    def exists_child(self, tenant_id: UUID, department_id: UUID) -> bool:
        """是否存在直接子部门。"""

    def count_employments(self, tenant_id: UUID, department_id: UUID) -> int:
        """统计部门下全部任职记录数（含历史）。"""

    def lock_subtree_and_parent(
        self,
        tenant_id: UUID,
        subtree_prefix: str,
        new_parent_id: UUID | None,
    ) -> list[Department]:
        """按 path 顺序锁定待移动子树与目标父行并返回；跨租户父行不在结果中。"""

    def reparent_subtree(
        self,
        tenant_id: UUID,
        moved_id: UUID,
        old_prefix: str,
        new_prefix: str,
        new_parent_id: UUID | None,
        level_delta: int,
    ) -> None:
        """在已加锁前提下整体平移子树 path/level，并更新移动节点的 parent_id。"""


class EmploymentRepository(Protocol):
    """用户任职记录仓储。"""

    def get(self, employment_id: UUID) -> Employment | None:
        """按主键查询任职（含用户、部门、汇报上级与字典展示字段）。"""

    def list_page(
        self,
        tenant_id: UUID,
        page: int,
        page_size: int,
        keyword: str | None,
        department_path_prefix: str | None,
        user_id: UUID | None,
        is_current: bool | None,
    ) -> tuple[list[Employment], int]:
        """分页查询任职；部门前缀命中本部门及下级，关键字匹配用户名/昵称/岗位。"""

    def create(self, values: dict[str, Any]) -> Employment:
        """创建任职记录。"""

    def update(self, employment_id: UUID, values: dict[str, Any]) -> Employment | None:
        """更新任职记录字段。"""

    def delete(self, employment_id: UUID) -> bool:
        """物理删除任职记录。"""

    def get_current_for_update(self, tenant_id: UUID, user_id: UUID) -> Employment | None:
        """加行锁查询用户当前主任职。"""

    def map_current_for_users(
        self, tenant_id: UUID, user_ids: list[UUID]
    ) -> dict[UUID, tuple[UUID, str]]:
        """批量返回用户当前任职的 (部门id, 部门名)，避免用户列表 N+1。"""

    def list_current_user_ids_in_subtree(
        self, tenant_id: UUID, department_path_prefix: str
    ) -> set[UUID]:
        """返回当前任职部门落在给定部门前缀（本部门及下级）内的用户 ID。"""

    def get_current_department_brief(
        self, tenant_id: UUID, user_id: UUID
    ) -> tuple[UUID, str] | None:
        """返回用户当前任职的 (部门id, 部门 path)；无当前任职返回 None。"""


class HrDictionaryRepository(Protocol):
    """HR 字典仓储：雇佣类型/岗位职级/岗位序列。"""

    def get(self, dictionary_id: UUID) -> HrDictionary | None:
        """按主键查询字典项。"""

    def list_by_category(
        self, tenant_id: UUID, category: str, include_inactive: bool = False
    ) -> list[HrDictionary]:
        """按类别读取租户字典项，按 sort_order、id 升序返回。"""

    def list_by_categories(
        self, tenant_id: UUID, categories: list[str], include_inactive: bool = False
    ) -> list[HrDictionary]:
        """批量读取多个类别的字典项。"""

    def get_many(self, dictionary_ids: list[UUID]) -> list[HrDictionary]:
        """按主键集合批量读取。"""

    def create(self, values: dict[str, Any]) -> HrDictionary:
        """创建字典项。"""

    def update(self, dictionary_id: UUID, values: dict[str, Any]) -> HrDictionary | None:
        """更新字典项基础字段。"""

    def delete(self, dictionary_id: UUID) -> bool:
        """物理删除字典项。"""

    def code_exists(
        self,
        tenant_id: UUID,
        category: str,
        code: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        """同一租户同一类别下编码是否已存在（忽略大小写）。"""

    def count_references(self, dictionary_id: UUID) -> int:
        """统计该字典项被任职记录引用的次数。"""


class MgmtUnitRepository(Protocol):
    """管理单元仓储：物化路径树 + 部门/人员关联；所有调用均在单一租户作用域内。"""

    def get(self, unit_id: UUID) -> ManagementUnit | None:
        """按主键查询管理单元。"""

    def get_for_update(
        self, unit_id: UUID, tenant_id: UUID | None = None
    ) -> ManagementUnit | None:
        """按主键加行锁查询管理单元；传入租户时同时限定租户。"""

    def list_all(
        self, tenant_id: UUID, include_inactive: bool = True
    ) -> list[ManagementUnit]:
        """按物化路径顺序返回租户全部管理单元。"""

    def list_active(self, tenant_id: UUID) -> list[ManagementUnit]:
        """仅返回启用中的管理单元，用于授权勾选弹窗。"""

    def create(self, values: dict[str, Any]) -> ManagementUnit:
        """创建管理单元。"""

    def update(self, unit_id: UUID, values: dict[str, Any]) -> ManagementUnit | None:
        """更新管理单元基础字段（不含移动子树）。"""

    def delete(self, unit_id: UUID) -> bool:
        """物理删除管理单元。"""

    def code_exists(
        self, tenant_id: UUID, code: str, exclude_id: UUID | None = None
    ) -> bool:
        """租户内管理单元编码是否已存在（忽略大小写）。"""

    def name_exists_under_parent(
        self,
        tenant_id: UUID,
        parent_id: UUID | None,
        name: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        """同一父单元下名称是否已存在（忽略大小写，根单元父 id 为空）。"""

    def exists_child(self, tenant_id: UUID, unit_id: UUID) -> bool:
        """是否存在直接子单元。"""

    def list_departments(self, unit_id: UUID) -> list[MgmtUnitDepartment]:
        """读取管理单元已关联的部门列表。"""

    def list_users(self, unit_id: UUID) -> list[MgmtUnitUser]:
        """读取管理单元已关联的人员列表。"""

    def replace_departments(
        self, unit_id: UUID, bindings: list[tuple[UUID, bool]]
    ) -> None:
        """整体替换管理单元的部门关联；bindings 为 (department_id, include_subtree) 列表。"""

    def replace_users(self, unit_id: UUID, user_ids: list[UUID]) -> None:
        """整体替换管理单元的人员关联。"""

    def list_departments_for_units(
        self, unit_ids: list[UUID]
    ) -> list[MgmtUnitDepartment]:
        """批量读取多个单元的部门关联，避免 N+1；仅返回仍启用的单元关联。"""

    def list_users_for_units(self, unit_ids: list[UUID]) -> list[MgmtUnitUser]:
        """批量读取多个单元的人员关联，避免 N+1。"""

    def count_user_grants(self, tenant_id: UUID, unit_id: UUID) -> int:
        """统计该单元被授权给了多少用户。"""

    def lock_subtree_and_parent(
        self,
        tenant_id: UUID,
        subtree_prefix: str,
        new_parent_id: UUID | None,
    ) -> list[ManagementUnit]:
        """按 path 顺序锁定待移动子树与目标父行并返回；跨租户父行不在结果中。"""

    def reparent_subtree(
        self,
        tenant_id: UUID,
        moved_id: UUID,
        old_prefix: str,
        new_prefix: str,
        new_parent_id: UUID | None,
        level_delta: int,
    ) -> None:
        """在已加锁前提下整体平移子树 path/level，并更新移动节点的 parent_id。"""


class UserMgmtUnitGrantRepository(Protocol):
    """用户被授权的管理单元仓储。"""

    def list_for_user(self, tenant_id: UUID, user_id: UUID) -> list[UserMgmtUnitGrant]:
        """读取某用户在本租户被授权的全部管理单元。"""

    def list_for_users(
        self, tenant_id: UUID, user_ids: list[UUID]
    ) -> dict[UUID, list[UserMgmtUnitGrant]]:
        """批量读取多个用户的授权；返回 user_id -> 授权列表。"""

    def list_unit_ids_for_user(self, tenant_id: UUID, user_id: UUID) -> set[UUID]:
        """读取某用户被授权的单元 id 集合（行过滤用）。"""

    def add_grants(
        self,
        tenant_id: UUID,
        user_ids: list[UUID],
        unit_ids: list[UUID],
        granted_by: UUID | None,
    ) -> int:
        """批量追加（user, unit）授权；已存在的组合自动跳过，返回新增数量。"""

    def replace_for_users(
        self,
        tenant_id: UUID,
        user_ids: list[UUID],
        unit_ids: list[UUID],
        granted_by: UUID | None,
    ) -> None:
        """整体替换每个目标用户的管理单元授权：先清空再写入；unit_ids 为空即清空。"""

    def remove_grant(self, tenant_id: UUID, user_id: UUID, unit_id: UUID) -> bool:
        """移除某用户对某单元的授权。"""

    def list_unit_names(self, tenant_id: UUID, unit_ids: list[UUID]) -> dict[UUID, str]:
        """批量读取单元 id -> 名称映射（前端展示用）。"""


class UnitOfWork(Protocol):
    """请求级工作单元，负责事务提交与仓储访问。"""

    tenant_id: UUID | None
    tenants: TenantRepository
    admin_users: AdminUserRepository
    refresh_tokens: RefreshTokenRepository
    audit_logs: AuditLogRepository
    roles: RoleRepository
    permission_resources: PermissionResourceRepository
    role_permissions: RolePermissionRepository
    users: UserRepository
    user_refresh_tokens: UserRefreshTokenRepository
    resource_grants: ResourceGrantRepository
    departments: DepartmentRepository
    employments: EmploymentRepository
    hr_dictionaries: HrDictionaryRepository
    mgmt_units: MgmtUnitRepository
    user_mgmt_unit_grants: UserMgmtUnitGrantRepository
    tools: ResourceRepository[Tool]

    def resource_repo(self, resource_type: str) -> ResourceRepository[Tool]:
        """按资源类型返回当前作用域仓储；tools 等价于 resource_repo('tool')。"""

    def apply_scope(self, role_ids: tuple[UUID, ...] = (), apply_role_filter: bool = True) -> None:
        """按当前账号角色重建资源仓储。"""

    def commit(self) -> None:
        """提交事务。"""

    def rollback(self) -> None:
        """回滚事务。"""

    def close(self) -> None:
        """释放会话。"""
