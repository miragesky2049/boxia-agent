"""资源可见性 SQL 片段：统一智能体、资源与角色授权的过滤规则。"""

from typing import Any

from sqlalchemy import and_, exists, false, or_, true
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from internal.infrastructure.model.access import ResourceGrantModel
from internal.infrastructure.model.agent import AgentModel, AgentTenantOpeningModel

# 内层 EXISTS 必须使用别名表，否则在智能体列表查询中会编译成 agents.id = agents.id 恒真条件
_VisibleAgent = aliased(AgentModel, name="visible_agent")


def _role_condition(role_ids: tuple[int, ...], apply_role_filter: bool) -> ColumnElement[bool]:
    """租户内角色命中条件；关闭角色过滤时任意授权均命中。"""
    if not apply_role_filter:
        return ResourceGrantModel.role_id.is_not(None) | ResourceGrantModel.role_id.is_(None)
    if not role_ids:
        # 没有角色的账号只能命中“整租户授权”
        return ResourceGrantModel.role_id.is_(None)
    return or_(
        ResourceGrantModel.role_id.is_(None),
        ResourceGrantModel.role_id.in_(role_ids),
    )


def grant_exists(
    resource_type: str,
    resource_id_col: Any,
    tenant_id: int,
    role_ids: tuple[int, ...],
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
        ResourceGrantModel.tenant_id.is_not(None),
    )


def platform_role_grant_exists(
    resource_type: str, resource_id_col: Any, role_ids: tuple[int, ...]
) -> ColumnElement[bool]:
    """平台资源是否授权给指定平台角色；无角色时 fail-closed。"""
    if not role_ids:
        return false()
    return exists().where(
        ResourceGrantModel.resource_type == resource_type,
        ResourceGrantModel.resource_id == resource_id_col,
        ResourceGrantModel.tenant_id.is_(None),
        ResourceGrantModel.role_id.in_(role_ids),
    )


def tenant_grant_exists(
    resource_type: str, resource_id_col: Any, tenant_id: int
) -> ColumnElement[bool]:
    """资源是否存在对指定租户的授权（不区分角色）。"""
    return exists().where(
        ResourceGrantModel.resource_type == resource_type,
        ResourceGrantModel.resource_id == resource_id_col,
        ResourceGrantModel.tenant_id == tenant_id,
    )


def tenant_grant_absent(
    resource_type: str, resource_id_col: Any, tenant_id: int
) -> ColumnElement[bool]:
    """资源是否未对指定租户直接授权，用于产品级资源继承所属智能体。"""
    return ~tenant_grant_exists(resource_type, resource_id_col, tenant_id)


def agent_opening_exists(agent_id_col: Any, tenant_id: int) -> ColumnElement[bool]:
    """平台智能体是否已对指定租户开通。"""
    return exists().where(
        AgentTenantOpeningModel.agent_id == agent_id_col,
        AgentTenantOpeningModel.tenant_id == tenant_id,
    )


def agent_visible(
    agent_id_col: Any,
    tenant_id: int,
    role_ids: tuple[int, ...],
    apply_role_filter: bool,
) -> ColumnElement[bool]:
    """资源所属智能体对当前租户是否可见。

    严格 RBAC：租户自有智能体必须显式授权；管理端超级管理员全量可见。
    产品级智能体必须先对本租户开通；租户内再由角色数据授权细分可见范围。
    """
    if apply_role_filter:
        tenant_owned = and_(
            _VisibleAgent.tenant_id == tenant_id,
            grant_exists("agent", _VisibleAgent.id, tenant_id, role_ids, True),
        )
        platform_available = and_(
            _VisibleAgent.tenant_id.is_(None),
            agent_opening_exists(_VisibleAgent.id, tenant_id),
            grant_exists("agent", _VisibleAgent.id, tenant_id, role_ids, True),
        )
    else:
        tenant_owned = _VisibleAgent.tenant_id == tenant_id
        platform_available = and_(
            _VisibleAgent.tenant_id.is_(None),
            agent_opening_exists(_VisibleAgent.id, tenant_id),
        )
    return exists().where(
        _VisibleAgent.id == agent_id_col,
        or_(tenant_owned, platform_available),
    )


def tenant_resource_visible(
    resource_type: str,
    resource_id_col: Any,
    tenant_id: int,
    role_ids: tuple[int, ...],
    apply_role_filter: bool,
) -> ColumnElement[bool]:
    """租户自有资源：必须显式授权；管理端超级管理员全量可见。"""
    if not apply_role_filter:
        return true()
    return grant_exists(resource_type, resource_id_col, tenant_id, role_ids, True)


def platform_resource_visible(
    resource_type: str,
    resource_id_col: Any,
    agent_id_col: Any,
    tenant_id: int,
    role_ids: tuple[int, ...],
    apply_role_filter: bool,
) -> ColumnElement[bool]:
    """产品级资源：直接授权命中，或本租户无直接授权时继承所属智能体授权。"""
    direct = grant_exists(resource_type, resource_id_col, tenant_id, role_ids, apply_role_filter)
    inherited = and_(
        tenant_grant_absent(resource_type, resource_id_col, tenant_id),
        agent_id_col.is_not(None),
        agent_visible(agent_id_col, tenant_id, role_ids, apply_role_filter),
    )
    return or_(direct, inherited)
