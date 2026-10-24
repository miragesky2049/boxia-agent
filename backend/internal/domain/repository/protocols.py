"""仓储与工作单元协议：应用层只依赖接口，不感知数据库实现。"""

from datetime import datetime
from typing import Any, Protocol, TypeVar
from uuid import UUID

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

    def get_by_username(self, username: str, tenant_id: int | None) -> AdminUser | None:
        """按用户名与所属租户查询。"""

    def get_by_username_for_update(self, username: str, tenant_id: int | None) -> AdminUser | None:
        """按用户名与所属租户加行锁查询，用于登录失败计数。"""

    def get_by_id(self, user_id: int) -> AdminUser | None:
        """按主键查询。"""

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        tenant_id: int | None,
        all_tenants: bool = False,
    ) -> tuple[list[AdminUser], int]:
        """分页查询管理员；all_tenants 为真时跨租户。"""

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
    ) -> tuple[list[TResource], int]:
        """分页查询。"""

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

    def ids_exist(self, ids: list[int]) -> set[int]:
        """返回给定 id 中真实存在的部分。"""

    def get_by_name(self, name: str) -> TResource | None:
        """按名称在当前归属范围内精确查询（忽略大小写）。"""


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
    ) -> tuple[list[Agent], int]:
        """分页查询。"""

    def get(self, agent_id: int) -> Agent | None:
        """查询详情（含工具/技能关联）。"""

    def create(self, values: dict) -> Agent:
        """创建智能体并写入关联。"""

    def update(self, agent_id: int, values: dict) -> Agent | None:
        """全量更新并替换关联。"""

    def delete(self, agent_id: int) -> bool:
        """删除。"""

    def name_exists(self, name: str, exclude_id: int | None = None) -> bool:
        """名称是否已存在。"""


class UnitOfWork(Protocol):
    """请求级工作单元，负责事务提交与仓储访问。"""

    tenant_id: int | None
    tenants: TenantRepository
    admin_users: AdminUserRepository
    refresh_tokens: RefreshTokenRepository
    audit_logs: AuditLogRepository
    agents: AgentRepository
    skills: ResourceRepository[Skill]
    skill_files: SkillFileRepository
    tools: ResourceRepository[Tool]
    components: ResourceRepository[Component]
    prompts: ResourceRepository[Prompt]

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
