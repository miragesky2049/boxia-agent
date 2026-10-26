"""用户任职记录用例：单一主任职、调岗归档、结束任职。"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from internal.application.audit import record_audit
from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.entity.common import Page
from internal.domain.entity.department import Department
from internal.domain.entity.employment import Employment
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.id.uuid7 import new_uuid

_UNIQUE_VIOLATION = "23505"


class EmploymentService:
    """租户内任职 CRUD、调岗、结束任职。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        department_id: UUID | None,
        user_id: UUID | None,
        is_current: bool | None,
    ) -> Page[Employment]:
        """分页查询任职记录；部门筛选命中本部门及下级。"""
        tenant_id = self._require_tenant()
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        prefix = None
        if department_id is not None:
            filter_department = self._uow.departments.get(department_id)
            if filter_department is None or filter_department.tenant_id != tenant_id:
                raise NotFoundError("筛选部门不存在")
            prefix = filter_department.path
        items, total = self._uow.employments.list_page(
            tenant_id, page, page_size, keyword, prefix, user_id, is_current
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    def create(
        self,
        *,
        user_id: UUID,
        department_id: UUID,
        position: str,
        started_at: date | None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Employment:
        """新增用户当前任职；用户已有当前任职时拒绝并引导调岗。"""
        tenant_id = self._require_tenant()
        self._require_user(user_id, tenant_id)
        department = self._require_active_department(department_id, tenant_id)
        effective_date = started_at or date.today()

        employment = self._insert_current(
            tenant_id,
            user_id,
            department.id,
            position.strip(),
            effective_date,
        )
        self._audit(
            "employment.created",
            employment.id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"user_id": user_id, "department_id": department.id},
        )
        self._uow.commit()
        return employment

    def update(
        self,
        employment_id: UUID,
        *,
        position: str | None,
        started_at: date | None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Employment:
        """更新任职岗位或生效日期（当前与历史记录均可），部门变更请走调岗。"""
        tenant_id = self._require_tenant()
        employment = self._get_owned(employment_id, tenant_id)

        values: dict = {}
        if position is not None:
            values["position"] = position.strip()
        if started_at is not None:
            if employment.ended_at is not None and started_at > employment.ended_at:
                raise ValidationError("生效日期不能晚于该任职的结束日期")
            values["started_at"] = started_at
        if not values:
            return employment

        updated = self._uow.employments.update(employment_id, values)
        if updated is None:
            raise NotFoundError("任职记录不存在")
        self._audit(
            "employment.updated",
            employment_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
        )
        self._uow.commit()
        return updated

    def transfer(
        self,
        employment_id: UUID,
        *,
        department_id: UUID,
        position: str | None,
        started_at: date | None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Employment:
        """调岗：归档原当前任职并插入新的当前任职，保留完整任职历史。"""
        tenant_id = self._require_tenant()
        current = self._get_owned(employment_id, tenant_id)
        if not current.is_current:
            raise ValidationError("仅当前生效中的任职可以调岗")

        locked = self._uow.employments.get_current_for_update(tenant_id, current.user_id)
        if locked is None or locked.id != current.id:
            raise ConflictError("当前任职已变化，请刷新后重试")
        department = self._require_active_department(department_id, tenant_id)
        effective_date = started_at or date.today()
        new_position = position.strip() if position is not None else current.position

        if department.id == current.department_id:
            updated = self._uow.employments.update(
                current.id, {"position": new_position, "started_at": effective_date}
            )
            if updated is None:
                raise NotFoundError("任职记录不存在")
            self._audit(
                "employment.updated",
                current.id,
                actor_id,
                actor_username,
                ip,
                user_agent,
                tenant_id,
            )
            self._uow.commit()
            return updated

        old_ended_at = effective_date - timedelta(days=1)
        if current.started_at > old_ended_at:
            raise ValidationError("调岗生效日期不能早于原任职生效日期")
        self._uow.employments.update(
            current.id,
            {"is_current": False, "ended_at": old_ended_at},
        )
        employment = self._insert_current(
            tenant_id,
            current.user_id,
            department.id,
            new_position,
            effective_date,
        )
        self._audit(
            "employment.transferred",
            employment.id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"from_department": current.department_id, "to_department": department.id},
        )
        self._uow.commit()
        return employment

    def archive(
        self,
        employment_id: UUID,
        *,
        ended_at: date | None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Employment:
        """结束当前任职：置为历史记录，用户变为无当前部门。"""
        tenant_id = self._require_tenant()
        current = self._get_owned(employment_id, tenant_id)
        if not current.is_current:
            raise ValidationError("仅当前生效中的任职可以结束")
        end_date = ended_at or date.today()
        if current.started_at > end_date:
            raise ValidationError("结束日期不能早于任职生效日期")

        updated = self._uow.employments.update(
            employment_id,
            {"is_current": False, "ended_at": end_date},
        )
        if updated is None:
            raise NotFoundError("任职记录不存在")
        self._audit(
            "employment.archived",
            employment_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
        )
        self._uow.commit()
        return updated

    def delete(
        self,
        employment_id: UUID,
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """物理删除任职记录；删除当前任职后用户无当前部门。"""
        tenant_id = self._require_tenant()
        employment = self._get_owned(employment_id, tenant_id)
        self._uow.employments.delete(employment_id)
        self._audit(
            "employment.deleted",
            employment_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"user_id": employment.user_id, "department_id": employment.department_id},
        )
        self._uow.commit()

    def _insert_current(
        self,
        tenant_id: UUID,
        user_id: UUID,
        department_id: UUID,
        position: str,
        started_at: date,
    ) -> Employment:
        """直接插入当前任职，靠部分唯一索引兜底并发，冲突码 23505 转业务冲突。"""
        values = {
            "id": new_uuid(),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "department_id": department_id,
            "position": position,
            "is_current": True,
            "started_at": started_at,
            "ended_at": None,
        }
        try:
            return self._uow.employments.create(values)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                raise ConflictError("用户已有当前生效任职，请使用调岗功能") from exc
            raise

    def _require_user(self, user_id: UUID, tenant_id: UUID) -> None:
        user = self._uow.users.get_by_id(user_id)
        if user is None or user.tenant_id != tenant_id:
            raise ValidationError("用户不存在或不属于当前租户")
        if not user.is_active:
            raise ValidationError("用户已停用")

    def _require_active_department(
        self, department_id: UUID, tenant_id: UUID
    ) -> Department:
        department = self._uow.departments.get(department_id)
        if department is None or department.tenant_id != tenant_id:
            raise ValidationError("部门不存在或不属于当前租户")
        if not department.is_active:
            raise ValidationError("部门已停用，不能新增任职或调岗")
        return department

    def _get_owned(self, employment_id: UUID, tenant_id: UUID) -> Employment:
        employment = self._uow.employments.get(employment_id)
        if employment is None or employment.tenant_id != tenant_id:
            raise NotFoundError("任职记录不存在")
        return employment

    def _require_tenant(self) -> UUID:
        if self._context.is_platform or self._context.tenant_id is None:
            raise ForbiddenError("组织架构仅可由租户平台维护")
        return self._context.tenant_id

    def _audit(
        self,
        action: str,
        resource_id: UUID,
        actor_id: UUID,
        actor_username: str,
        ip: str | None,
        user_agent: str | None,
        tenant_id: UUID,
        detail: dict | None = None,
    ) -> None:
        """写入任职操作审计记录。"""
        record_audit(
            self._uow,
            action=action,
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="employment",
            resource_id=str(resource_id),
            ip=ip,
            user_agent=user_agent,
            detail=detail,
            tenant_id=tenant_id,
        )


def _is_unique_violation(exc: IntegrityError) -> bool:
    """是否为 PostgreSQL 唯一约束/唯一索引冲突（SQLSTATE 23505）。"""
    return getattr(exc.orig, "sqlstate", None) == _UNIQUE_VIOLATION
