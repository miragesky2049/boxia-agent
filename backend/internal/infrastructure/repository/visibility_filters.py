"""统一可见性 SQL 表达式：把 Visibility 枚举 + ResourceGrant 授权收敛成一个布尔条件。

用法（在 Repository 的 list 方法里）：
    stmt = stmt.where(visibility_filter(
        resource_type="app",
        resource_model=AppModel,
        scope=access_scope,
    ))
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from internal.domain.entity.access import AccessScope
from internal.domain.entity.visibility import Visibility
from internal.infrastructure.repository.grant_filters import grant_exists


def visibility_filter(
    resource_type: str,
    resource_model: Any,
    scope: AccessScope,
) -> ColumnElement[bool]:
    """根据资源表上的 visibility 字段生成可见性过滤条件。

    要求 resource_model 至少有列：
        - visibility (String)
        - tenant_id (UUID)
        - tenant_group_id (UUID, nullable)
        - creator_user_id (UUID, nullable，PRIVATE 用)

    平台超管（is_platform=True）直接返回 true()。
    """
    from sqlalchemy import true

    if scope.is_platform and not scope.apply_role_filter:
        return true()

    tenant_id = scope.tenant_id
    if tenant_id is None:
        # 无租户上下文：fail-closed，返回 false
        from sqlalchemy import false
        return false()

    vis_col = resource_model.visibility
    owner_tenant_col = resource_model.tenant_id
    group_col = getattr(resource_model, "tenant_group_id", None)
    creator_col = getattr(resource_model, "creator_user_id", None)
    resource_id_col = resource_model.id

    conditions: list[ColumnElement[bool]] = []

    # PRIVATE: 创建者本人可见
    if creator_col is not None:
        conditions.append(
            and_(
                vis_col == Visibility.PRIVATE.value,
                creator_col == _current_user_id(scope),
            )
        )

    # TENANT: 同租户
    conditions.append(
        and_(
            vis_col == Visibility.TENANT.value,
            owner_tenant_col == tenant_id,
        )
    )

    # TENANT_GROUP: 同租户组
    if group_col is not None:
        conditions.append(
            and_(
                vis_col == Visibility.TENANT_GROUP.value,
                group_col == _current_tenant_group_id(scope),
            )
        )

    # WHITELIST: 通过 ResourceGrant 显式授权
    conditions.append(
        and_(
            vis_col == Visibility.WHITELIST.value,
            grant_exists(
                resource_type=resource_type,
                resource_id_col=resource_id_col,
                tenant_id=tenant_id,
                role_ids=scope.role_ids,
                apply_role_filter=scope.apply_role_filter,
            ),
        )
    )

    return or_(*conditions)


def _current_user_id(scope: AccessScope) -> Any:
    """从 scope 取当前用户 ID。

    AccessScope 当前没有 user_id 字段；通过动态属性读取。
    若 scope 未携带 user_id，PRIVATE 分支直接不可达（返回空 UUID 强制 fail-closed）。
    """
    user_id = getattr(scope, "user_id", None)
    if user_id is None:
        # 返回一个不可能匹配的常量
        from uuid import UUID
        return UUID(int=0)
    return user_id


def _current_tenant_group_id(scope: AccessScope) -> Any:
    group_id = getattr(scope, "tenant_group_id", None)
    if group_id is None:
        from uuid import UUID
        return UUID(int=0)
    return group_id
