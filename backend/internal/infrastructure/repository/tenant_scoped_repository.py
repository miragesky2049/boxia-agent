"""多租户仓储基类：在 Repository 层强制注入 tenant_id 过滤条件。

业务仓储继承本类后，所有 list/get 调用自动带上 tenant_id 隔离，避免漏写 WHERE 条件。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.sql import Select

from internal.domain.entity.access import AccessScope


class TenantScopedRepository:
    """带 tenant_id 隔离的仓储基类。

    子类使用 `self._scope_stmt(stmt, model)` 自动给 SELECT 加 tenant_id 条件；
    平台超管（is_platform）时跳过。
    """

    def __init__(self, scope: AccessScope) -> None:
        self._scope = scope

    def _scope_stmt(self, stmt: Select[Any], model: Any) -> Select[Any]:
        """根据当前 scope 给 SELECT 注入 tenant_id 过滤。"""
        if self._scope.is_platform and not self._scope.apply_role_filter:
            return stmt
        if self._scope.tenant_id is None:
            # 无租户上下文：返回空结果集
            return stmt.where(False)
        return stmt.where(model.tenant_id == self._scope.tenant_id)

    def _tenant_id(self) -> UUID | None:
        return self._scope.tenant_id

    def _new_query(self, model: Any) -> Select[Any]:
        return self._scope_stmt(select(model), model)
