"""应用管理范围服务（0069 二期）：应用 ↔ 管理单元关联与可管理性鉴权。

依赖注入风格与 ApplicationService 一致：仓储经构造函数注入（session-per-service 裸 SQL），
uow 仅用于 users.has_permission / user_mgmt_unit_grants 两个 HR 侧查询。
"""

from __future__ import annotations

from uuid import UUID

from internal.application.errors import ForbiddenError, NotFoundError, ValidationError
from internal.domain.repository.apps_protocols import (
    AdminScopeRepositoryProtocol,
    ApplicationRepositoryProtocol,
)
from internal.domain.repository.protocols import UnitOfWork


class AdminScopeService:
    """管理范围编排：关联增删查 + assert_manageable 鉴权 + 我管理的应用列表。"""

    def __init__(
        self,
        uow: UnitOfWork,
        app_repo: ApplicationRepositoryProtocol,
        admin_scope_repo: AdminScopeRepositoryProtocol,
    ):
        self._uow = uow
        self._app_repo = app_repo
        self._admin_scope_repo = admin_scope_repo

    def list_scopes(self, application_id: UUID, tenant_id: UUID) -> list[dict]:
        """列出应用已关联的管理单元（含名称，孤儿自动过滤）。"""
        return self._admin_scope_repo.list_scopes(application_id, tenant_id)

    def add_scope(
        self, application_id: UUID, tenant_id: UUID, user_id: UUID, mgmt_unit_id: UUID
    ) -> None:
        """新增应用与管理单元关联；先做可管理性鉴权，再校验单元归属本租户。"""
        self.assert_manageable(application_id, tenant_id, user_id)
        if not self._admin_scope_repo.unit_exists(tenant_id, mgmt_unit_id):
            raise ValidationError("管理单元不存在或不属于本租户")
        self._admin_scope_repo.add_scope(application_id, tenant_id, mgmt_unit_id)
        self._uow.commit()

    def remove_scope(
        self, application_id: UUID, tenant_id: UUID, user_id: UUID, mgmt_unit_id: UUID
    ) -> None:
        """解除应用与管理单元关联；先做可管理性鉴权。"""
        self.assert_manageable(application_id, tenant_id, user_id)
        self._admin_scope_repo.remove_scope(application_id, tenant_id, mgmt_unit_id)
        self._uow.commit()

    def assert_manageable(self, application_id: UUID, tenant_id: UUID, user_id: UUID) -> None:
        """鉴权：当前用户是否可管理该应用的租户侧配置，不可则 403。

        顺序：app:admin:all 直通 → 租户级应用创建者直通（未来扩展） →
        按 admin_scope_mode：all_admin 需 app:admin；mgmt_unit 需用户被授予管理单元
        与应用关联集合有交集；creator_only 对已订阅产品级应用不适用，直接拒绝。
        """
        uow = self._uow
        if uow.users.has_permission(user_id, tenant_id, "app:admin:all"):
            return
        app = self._app_repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        # 未来租户级应用：创建者可管理自建应用（一期产品级应用不走此分支）
        if (
            app["owner_type"] == "tenant"
            and app.get("created_by") is not None
            and str(app["created_by"]) == str(user_id)
        ):
            return
        mode = app["admin_scope_mode"]
        if mode == "all_admin":
            if uow.users.has_permission(user_id, tenant_id, "app:admin"):
                return
        elif mode == "mgmt_unit":
            user_units = uow.user_mgmt_unit_grants.list_unit_ids_for_user(tenant_id, user_id)
            app_units = set(self._admin_scope_repo.list_unit_ids(application_id, tenant_id))
            if user_units & app_units:
                return
        raise ForbiddenError("无权管理此应用")

    def list_managed_apps(self, user_id: UUID, tenant_id: UUID) -> list[dict]:
        """当前用户可管理的已订阅应用列表（"我管理的应用"数据源）。"""
        apps = self._app_repo.list_subscribed_apps_for_admin(tenant_id)
        uow = self._uow
        if uow.users.has_permission(user_id, tenant_id, "app:admin:all"):
            return apps
        can_all_admin = uow.users.has_permission(user_id, tenant_id, "app:admin")
        user_units = uow.user_mgmt_unit_grants.list_unit_ids_for_user(tenant_id, user_id)
        app_units = self._admin_scope_repo.list_unit_ids_by_app(tenant_id)
        managed: list[dict] = []
        for app in apps:
            app_id = UUID(app["id"])
            mode = app.get("admin_scope_mode") or "all_admin"
            manageable = (
                (mode == "all_admin" and can_all_admin)
                or (mode == "mgmt_unit" and bool(user_units & app_units.get(app_id, set())))
                or (mode == "creator_only" and str(app.get("created_by")) == str(user_id))
            )
            if manageable:
                managed.append(app)
        return managed
