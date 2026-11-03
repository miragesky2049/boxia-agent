"""资源可见性 SQL 片段：统一资源与角色授权的过滤规则。"""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, false, func, or_, true
from sqlalchemy.sql.elements import ColumnElement

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.entitlement import STATUS_ACTIVE, STATUS_WAIT_EFFECT
from internal.infrastructure.model.access import ResourceGrantModel
from internal.infrastructure.model.resource import ResourceEntitlementModel


def _role_condition(role_ids: tuple[UUID, ...], apply_role_filter: bool) -> ColumnElement[bool]:
    """租户内授权命中条件（P1-10 起以 subject_type 显式表达）。

    tenant 档全员可见（含新增角色自动继承）；role 档仅命中指定角色时可见；
    关闭角色过滤时两档均命中；无角色上下文时 fail-closed 只命中 tenant 档。
    """
    if not apply_role_filter:
        return true()
    if not role_ids:
        return ResourceGrantModel.subject_type == "tenant"
    return or_(
        ResourceGrantModel.subject_type == "tenant",
        and_(
            ResourceGrantModel.subject_type == "role",
            ResourceGrantModel.role_id.in_(role_ids),
        ),
    )


def grant_exists(
    resource_type: str,
    resource_id_col: Any,
    tenant_id: UUID,
    role_ids: tuple[UUID, ...],
    apply_role_filter: bool,
) -> ColumnElement[bool]:
    """资源是否存在对当前租户（且角色命中）的授权。"""
    return exists().where(
        ResourceGrantModel.resource_type == resource_type,
        ResourceGrantModel.resource_id == resource_id_col,
        ResourceGrantModel.tenant_id == tenant_id,
        _role_condition(role_ids, apply_role_filter),
    )


def has_any_grant(resource_type: str, resource_id_col: Any) -> ColumnElement[bool]:
    """资源是否存在任意租户授权（跨租户）；平台角色授权不计入。"""
    return exists().where(
        ResourceGrantModel.resource_type == resource_type,
        ResourceGrantModel.resource_id == resource_id_col,
        ResourceGrantModel.tenant_id != PLATFORM_TENANT_ID,
    )


def platform_role_grant_exists(
    resource_type: str, resource_id_col: Any, role_ids: tuple[UUID, ...]
) -> ColumnElement[bool]:
    """平台资源是否授权给指定平台角色；无角色时 fail-closed。"""
    if not role_ids:
        return false()
    return exists().where(
        ResourceGrantModel.resource_type == resource_type,
        ResourceGrantModel.resource_id == resource_id_col,
        ResourceGrantModel.tenant_id == PLATFORM_TENANT_ID,
        ResourceGrantModel.role_id.in_(role_ids),
    )


def tenant_grant_exists(
    resource_type: str, resource_id_col: Any, tenant_id: UUID
) -> ColumnElement[bool]:
    """资源是否存在对指定租户的授权（不区分角色）。"""
    return exists().where(
        ResourceGrantModel.resource_type == resource_type,
        ResourceGrantModel.resource_id == resource_id_col,
        ResourceGrantModel.tenant_id == tenant_id,
    )


def tenant_resource_visible(
    resource_type: str,
    resource_id_col: Any,
    tenant_id: UUID,
    role_ids: tuple[UUID, ...],
    apply_role_filter: bool,
) -> ColumnElement[bool]:
    """租户自有资源：必须显式授权；管理端超级管理员全量可见。"""
    if not apply_role_filter:
        return true()
    return grant_exists(resource_type, resource_id_col, tenant_id, role_ids, True)


def entitlement_active_exists(resource_id_col: Any, tenant_id: UUID) -> ColumnElement[bool]:
    """单数 resource_grant 权益有效谓词（P1-8）。

    时间语义与读侧 effective_status 对齐（D-3）：wait_effect 行过 start_time 后
    即计入有效，expired/revoked/suspended/disabled 不计入；NULL 视为不限。
    """
    return exists().where(
        ResourceEntitlementModel.resource_id == resource_id_col,
        ResourceEntitlementModel.tenant_id == tenant_id,
        ResourceEntitlementModel.status.in_((STATUS_ACTIVE, STATUS_WAIT_EFFECT)),
        or_(
            ResourceEntitlementModel.start_time.is_(None),
            ResourceEntitlementModel.start_time <= func.now(),
        ),
        or_(
            ResourceEntitlementModel.expire_time.is_(None),
            ResourceEntitlementModel.expire_time > func.now(),
        ),
    )


def platform_resource_visible(
    resource_type: str,
    resource_id_col: Any,
    tenant_id: UUID,
    role_ids: tuple[UUID, ...],
    apply_role_filter: bool,
) -> ColumnElement[bool]:
    """产品级资源：角色授权命中 且 租户权益已开通（授权≠开通，P1-8 双条件）。"""
    return and_(
        grant_exists(resource_type, resource_id_col, tenant_id, role_ids, apply_role_filter),
        entitlement_active_exists(resource_id_col, tenant_id),
    )
