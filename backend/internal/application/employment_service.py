"""用户任职记录用例：单一主任职、调岗归档、结束任职、HR 字段维护。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
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
from internal.domain.entity.employment import (
    EMPLOYMENT_CHANGE_TYPES,
    EMPLOYMENT_NATURES,
    TERMINATION_TYPES,
    Employment,
)
from internal.domain.entity.hr_dictionary import HR_DICTIONARY_CATEGORIES
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.id.uuid7 import new_uuid

_UNIQUE_VIOLATION = "23505"

# 字典类别与任职表列名映射；校验字典归属时使用。
_DICTIONARY_CATEGORY_COLUMNS = {
    "employment_type": "employment_type_id",
    "job_level": "job_level_id",
    "job_family": "job_family_id",
}


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
        hr_fields: dict | None = None,
    ) -> Employment:
        """新增用户当前任职；用户已有当前任职时拒绝并引导调岗。"""
        tenant_id = self._require_tenant()
        self._require_user(user_id, tenant_id)
        department = self._require_active_department(department_id, tenant_id)
        effective_date = started_at or date.today()
        hr_fields = self._normalize_hr_fields(hr_fields or {}, tenant_id)
        self._validate_hr_dates(hr_fields, started_at=effective_date)

        values = {
            "id": new_uuid(),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "department_id": department.id,
            "position": position.strip(),
            "is_current": True,
            "started_at": effective_date,
            "ended_at": None,
        }
        values.update(hr_fields)
        # 新建任职默认变动类型为 hire；显式传入时允许覆盖（如重新入职走 rehire 场景）
        values.setdefault("change_type", "hire")

        try:
            employment = self._insert(values)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                raise ConflictError("用户已有当前生效任职，请使用调岗功能") from exc
            raise
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
        hr_fields: dict | None = None,
    ) -> Employment:
        """更新任职岗位/生效日期与 HR 字段（当前与历史记录均可），部门变更请走调岗。"""
        tenant_id = self._require_tenant()
        employment = self._get_owned(employment_id, tenant_id)

        values: dict = {}
        if position is not None:
            values["position"] = position.strip()
        if started_at is not None:
            if employment.ended_at is not None and started_at > employment.ended_at:
                raise ValidationError("生效日期不能晚于该任职的结束日期")
            values["started_at"] = started_at

        normalized = self._normalize_hr_fields(hr_fields or {}, tenant_id)
        values.update(normalized)
        effective_start = started_at or employment.started_at
        self._validate_hr_dates(values, started_at=effective_start)

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
        hr_fields: dict | None = None,
        change_type: str = "transfer",
    ) -> Employment:
        """调岗：归档原当前任职并插入新的当前任职，保留完整任职历史。"""
        tenant_id = self._require_tenant()
        current = self._get_owned(employment_id, tenant_id)
        if not current.is_current:
            raise ValidationError("仅当前生效中的任职可以调岗")
        if change_type not in EMPLOYMENT_CHANGE_TYPES:
            raise ValidationError(f"变动类型必须为：{', '.join(EMPLOYMENT_CHANGE_TYPES)}")

        locked = self._uow.employments.get_current_for_update(tenant_id, current.user_id)
        if locked is None or locked.id != current.id:
            raise ConflictError("当前任职已变化，请刷新后重试")
        department = self._require_active_department(department_id, tenant_id)
        effective_date = started_at or date.today()
        new_position = position.strip() if position is not None else current.position
        new_hr = self._normalize_hr_fields(hr_fields or {}, tenant_id, inherit_from=current)
        self._validate_hr_dates(new_hr, started_at=effective_date)

        if department.id == current.department_id:
            values = {"position": new_position}
            values.update(new_hr)
            values["change_type"] = change_type
            updated = self._uow.employments.update(current.id, values)
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
        values = {
            "id": new_uuid(),
            "tenant_id": tenant_id,
            "user_id": current.user_id,
            "department_id": department.id,
            "position": new_position,
            "is_current": True,
            "started_at": effective_date,
            "ended_at": None,
        }
        values.update(new_hr)
        values["change_type"] = change_type
        try:
            employment = self._insert(values)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                raise ConflictError("用户已有当前生效任职，请刷新后重试") from exc
            raise
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
        termination_type: str | None = None,
        change_reason: str | None = None,
    ) -> Employment:
        """结束当前任职：置为历史记录，用户变为无当前部门。"""
        tenant_id = self._require_tenant()
        current = self._get_owned(employment_id, tenant_id)
        if not current.is_current:
            raise ValidationError("仅当前生效中的任职可以结束")
        end_date = ended_at or date.today()
        if current.started_at > end_date:
            raise ValidationError("结束日期不能早于任职生效日期")
        if termination_type is not None and termination_type not in TERMINATION_TYPES:
            raise ValidationError(f"离职类型必须为：{', '.join(TERMINATION_TYPES)}")

        values: dict = {
            "is_current": False,
            "ended_at": end_date,
        }
        if termination_type is not None:
            values["termination_type"] = termination_type
        if change_reason is not None:
            values["change_reason"] = change_reason.strip()[:255]

        updated = self._uow.employments.update(employment_id, values)
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

    # ---- 内部辅助 ----

    def _insert(self, values: dict) -> Employment:
        """写入任职记录，靠部分唯一索引兜底并发。"""
        return self._uow.employments.create(values)

    def _normalize_hr_fields(
        self,
        raw: dict,
        tenant_id: UUID,
        *,
        inherit_from: Employment | None = None,
    ) -> dict:
        """把外部传入的 HR 字段归一化并校验归属；inherit_from 用于调岗时继承原值。"""
        out: dict = {}
        # 字典外键
        for category, column in _DICTIONARY_CATEGORY_COLUMNS.items():
            key = f"{category}_id"
            if key in raw:
                value = raw[key]
                if value is None:
                    out[column] = None
                else:
                    self._require_dictionary(value, category, tenant_id)
                    out[column] = value
            elif inherit_from is not None:
                out[column] = getattr(inherit_from, column)

        # 汇报上级
        if "manager_id" in raw:
            manager_id = raw["manager_id"]
            if manager_id is not None:
                self._require_user(manager_id, tenant_id)
                if inherit_from is not None and manager_id == inherit_from.user_id:
                    raise ValidationError("汇报上级不能是任职人自己")
            out["manager_id"] = manager_id
        elif inherit_from is not None:
            out["manager_id"] = inherit_from.manager_id

        # 文本/数值字段
        text_fields = (
            "work_location",
            "cost_center",
            "contract_no",
        )
        for field in text_fields:
            if field in raw:
                value = raw[field]
                out[field] = value.strip() if isinstance(value, str) else value
            elif inherit_from is not None:
                out[field] = getattr(inherit_from, field)

        if "weekly_hours" in raw:
            out["weekly_hours"] = self._normalize_weekly_hours(raw["weekly_hours"])
        elif inherit_from is not None:
            out["weekly_hours"] = inherit_from.weekly_hours

        # 用工性质枚举
        if "employment_nature" in raw:
            nature = raw["employment_nature"]
            if nature is not None and nature not in EMPLOYMENT_NATURES:
                raise ValidationError(
                    f"用工性质必须为：{', '.join(EMPLOYMENT_NATURES)}"
                )
            out["employment_nature"] = nature
        elif inherit_from is not None:
            out["employment_nature"] = inherit_from.employment_nature

        # 日期字段
        date_fields = (
            "probation_started_at",
            "probation_ended_at",
            "regularized_at",
        )
        for field in date_fields:
            if field in raw:
                out[field] = raw[field]
            elif inherit_from is not None:
                out[field] = getattr(inherit_from, field)

        # 变动原因/备注
        if "change_reason" in raw:
            value = raw["change_reason"]
            out["change_reason"] = value.strip()[:255] if isinstance(value, str) else value
        elif inherit_from is not None:
            out["change_reason"] = inherit_from.change_reason

        if "remark" in raw:
            value = raw["remark"]
            out["remark"] = value or ""
        elif inherit_from is not None:
            out["remark"] = inherit_from.remark

        return out

    @staticmethod
    def _normalize_weekly_hours(value) -> float | None:
        """归一化标准工时；None 透传，数值范围 0-168。"""
        if value is None:
            return None
        try:
            hours = float(Decimal(str(value)))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("标准工时必须为数值") from exc
        if hours < 0 or hours > 168:
            raise ValidationError("标准工时必须在 0-168 之间")
        return round(hours, 1)

    def _validate_hr_dates(self, values: dict, *, started_at: date) -> None:
        """校验试用期日期范围与转正日期不早于任职开始日期。"""
        probation_started = values.get("probation_started_at")
        probation_ended = values.get("probation_ended_at")
        if (
            probation_started is not None
            and probation_ended is not None
            and probation_started > probation_ended
        ):
            raise ValidationError("试用期开始日期不能晚于结束日期")
        regularized = values.get("regularized_at")
        if regularized is not None and regularized < started_at:
            raise ValidationError("转正日期不能早于任职开始日期")

    def _require_dictionary(self, dictionary_id: UUID, category: str, tenant_id: UUID) -> None:
        """校验字典项属于当前租户且类别匹配。"""
        item = self._uow.hr_dictionaries.get(dictionary_id)
        if item is None or item.tenant_id != tenant_id:
            raise ValidationError("字典项不存在或不属于当前租户")
        if item.category != category or category not in HR_DICTIONARY_CATEGORIES:
            raise ValidationError(f"字典项类别必须为 {category}")
        if not item.is_active:
            raise ValidationError("字典项已停用")

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
        if self._context.is_platform:
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
