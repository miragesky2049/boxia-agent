"""HR 字典用例：租户级雇佣类型/岗位职级/岗位序列维护。"""

from __future__ import annotations

from uuid import UUID

from internal.application.audit import record_audit
from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.domain.entity.hr_dictionary import HR_DICTIONARY_CATEGORIES, HrDictionary
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.id.uuid7 import new_uuid


class HrDictionaryService:
    """租户级 HR 字典 CRUD。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list(self, category: str, include_inactive: bool = False) -> list[HrDictionary]:
        """按类别读取租户字典项。"""
        tenant_id = self._require_tenant()
        self._require_category(category)
        return self._uow.hr_dictionaries.list_by_category(
            tenant_id, category, include_inactive=include_inactive
        )

    def create(
        self,
        *,
        category: str,
        code: str,
        name: str,
        sort_order: int,
        remark: str,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> HrDictionary:
        """新建字典项。"""
        tenant_id = self._require_tenant()
        self._require_category(category)
        normalized_code = self._normalize_code(code)
        normalized_name = self._normalize_name(name)
        if self._uow.hr_dictionaries.code_exists(tenant_id, category, normalized_code):
            raise ConflictError("同一类别下编码已存在")
        item = self._uow.hr_dictionaries.create(
            {
                "id": new_uuid(),
                "tenant_id": tenant_id,
                "category": category,
                "code": normalized_code,
                "name": normalized_name,
                "sort_order": sort_order,
                "is_active": True,
                "remark": remark.strip()[:255],
            }
        )
        self._audit(
            "hr_dictionary.created",
            item.id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"category": category, "code": normalized_code},
        )
        self._uow.commit()
        return item

    def update(
        self,
        dictionary_id: UUID,
        *,
        name: str | None,
        sort_order: int | None,
        is_active: bool | None,
        remark: str | None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> HrDictionary:
        """更新字典项基础字段；编码与类别不可改。"""
        tenant_id = self._require_tenant()
        existing = self._get_owned(dictionary_id, tenant_id)
        values: dict = {}
        if name is not None:
            values["name"] = self._normalize_name(name)
        if sort_order is not None:
            values["sort_order"] = sort_order
        if is_active is not None:
            values["is_active"] = is_active
        if remark is not None:
            values["remark"] = remark.strip()[:255]
        if not values:
            return existing
        updated = self._uow.hr_dictionaries.update(dictionary_id, values)
        if updated is None:
            raise NotFoundError("字典项不存在")
        self._audit(
            "hr_dictionary.updated",
            dictionary_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail=values,
        )
        self._uow.commit()
        return updated

    def delete(
        self,
        dictionary_id: UUID,
        *,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """删除字典项；仍被任职记录引用时拒绝。"""
        tenant_id = self._require_tenant()
        existing = self._get_owned(dictionary_id, tenant_id)
        references = self._uow.hr_dictionaries.count_references(dictionary_id)
        if references > 0:
            raise ConflictError(f"该字典项仍被 {references} 条任职记录引用，不能删除")
        self._uow.hr_dictionaries.delete(dictionary_id)
        self._audit(
            "hr_dictionary.deleted",
            dictionary_id,
            actor_id,
            actor_username,
            ip,
            user_agent,
            tenant_id,
            detail={"category": existing.category, "code": existing.code},
        )
        self._uow.commit()

    def _get_owned(self, dictionary_id: UUID, tenant_id: UUID) -> HrDictionary:
        item = self._uow.hr_dictionaries.get(dictionary_id)
        if item is None or item.tenant_id != tenant_id:
            raise NotFoundError("字典项不存在")
        return item

    @staticmethod
    def _require_category(category: str) -> None:
        if category not in HR_DICTIONARY_CATEGORIES:
            raise ValidationError(
                f"字典类别必须为：{', '.join(HR_DICTIONARY_CATEGORIES)}"
            )

    @staticmethod
    def _normalize_code(code: str) -> str:
        normalized = code.strip()
        if not normalized:
            raise ValidationError("编码不能为空")
        if len(normalized) > 64:
            raise ValidationError("编码长度不能超过 64")
        return normalized

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValidationError("名称不能为空")
        if len(normalized) > 100:
            raise ValidationError("名称长度不能超过 100")
        return normalized

    def _require_tenant(self) -> UUID:
        if self._context.is_platform or self._context.tenant_id is None:
            raise ForbiddenError("HR 字典仅可由租户平台维护")
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
        record_audit(
            self._uow,
            action=action,
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type="hr_dictionary",
            resource_id=str(resource_id),
            ip=ip,
            user_agent=user_agent,
            detail=detail,
            tenant_id=tenant_id,
        )
