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
        """鉴权：当前用户是否可管理该应用的租户侧配置，不可则 403。"""
        if not self.is_manageable(application_id, tenant_id, user_id):
            raise ForbiddenError("无权管理此应用")

    def is_manageable(self, application_id: UUID, tenant_id: UUID, user_id: UUID) -> bool:
        """当前用户是否可管理该应用的租户侧配置（口径见 _is_manageable_row）。"""
        uow = self._uow
        if uow.users.has_permission(user_id, tenant_id, "app:admin:all"):
            return True
        app = self._app_repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        # 未来租户级应用：创建者可管理自建应用（一期产品级应用不走此分支）
        if (
            app["owner_type"] == "tenant"
            and app.get("created_by") is not None
            and str(app["created_by"]) == str(user_id)
        ):
            return True
        app_units = set(self._admin_scope_repo.list_unit_ids(application_id, tenant_id))
        can_all_admin = uow.users.has_permission(user_id, tenant_id, "app:admin")
        user_units = uow.user_mgmt_unit_grants.list_unit_ids_for_user(tenant_id, user_id)
        return self._is_manageable_row(
            app, app_units, user_id, is_super=False,
            can_all_admin=can_all_admin, user_units=user_units,
        )

    def _is_manageable_row(
        self,
        app: dict,
        units: set[UUID],
        user_id: UUID,
        is_super: bool,
        can_all_admin: bool,
        user_units: set[UUID],
    ) -> bool:
        """单行可管理性判定，assert/list 共用口径。

        生效模式推导：本租户已关联管理单元时按 mgmt_unit，不再依赖平台侧
        application.admin_scope_mode（该列跨租户共享，租户侧加关联无法、也不应改写它）；
        未关联时回退平台列：all_admin 需 app:admin，creator_only 仅创建者。
        """
        if is_super:
            return True
        effective_mode = self._effective_mode(app, units)
        if effective_mode == "all_admin":
            return can_all_admin
        if effective_mode == "mgmt_unit":
            return bool(user_units & units)
        return str(app.get("created_by")) == str(user_id)

    @staticmethod
    def _effective_mode(app: dict, units: set[UUID]) -> str:
        """生效管理模式：有关联单元即 mgmt_unit，否则回退平台列。"""
        return "mgmt_unit" if units else (app.get("admin_scope_mode") or "all_admin")

    def list_subscribed_apps(self, user_id: UUID, tenant_id: UUID) -> list[dict]:
        """已订阅应用列表（含 admin_scope_mode 生效值与 manageable 可管理标记）。

        manageable 供前端在"已订阅的产品级应用"tab 判断能否进入编辑；
        admin_scope_mode 回填生效口径，避免已圈定管理范围的应用仍显示
        「全部管理员可管理」。批量判定：权限与授权单元各查一次。
        """
        apps = self._app_repo.list_subscribed_apps_for_admin(tenant_id)
        uow = self._uow
        app_units = self._admin_scope_repo.list_unit_ids_by_app(tenant_id)
        is_super = uow.users.has_permission(user_id, tenant_id, "app:admin:all")
        can_all_admin = False
        user_units: set[UUID] = set()
        if not is_super:
            can_all_admin = uow.users.has_permission(user_id, tenant_id, "app:admin")
            user_units = uow.user_mgmt_unit_grants.list_unit_ids_for_user(tenant_id, user_id)
        for app in apps:
            units = app_units.get(UUID(app["id"]), set())
            app["admin_scope_mode"] = self._effective_mode(app, units)
            app["manageable"] = self._is_manageable_row(
                app, units, user_id, is_super, can_all_admin, user_units
            )
        return apps

    def list_managed_apps(self, user_id: UUID, tenant_id: UUID) -> list[dict]:
        """当前用户可管理的已订阅应用列表（"我管理的应用"数据源）。"""
        return [
            app for app in self.list_subscribed_apps(user_id, tenant_id) if app["manageable"]
        ]
