"""工具通用用例。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields
from typing import Any, Generic, Protocol, TypeVar, cast

from internal.application.errors import ConflictError, ForbiddenError, NotFoundError
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.common import Page
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import ResourceRepository, UnitOfWork


class _ResourceEntity(Protocol):
    """资源实体最小契约：通用用例只依赖标识与名称。"""

    @property
    def id(self) -> object: ...

    @property
    def name(self) -> str: ...


T = TypeVar("T", bound=_ResourceEntity)

MAX_PAGE_SIZE = 100


class ResourceService(Generic[T]):
    """通用资源 CRUD 用例。"""

    def __init__(
        self,
        repository: ResourceRepository[T],
        label: str,
        resource_type: str,
        uow: UnitOfWork,
        context: RequestContext,
    ):
        self._repository = repository
        self._label = label
        self._resource_type = resource_type
        self._uow = uow
        self._context = context

    def list(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
    ) -> Page[T]:
        """分页查询。"""
        page, page_size = _normalize_paging(page, page_size)
        items, total = self._repository.list_page(page, page_size, keyword, is_enabled)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def get(self, resource_id: object) -> T:
        """查询详情。"""
        item = self._repository.get(resource_id)  # type: ignore[arg-type]
        if item is None:
            raise NotFoundError(f"{self._label}不存在")
        return item

    def create(self, values: dict, actor_role_ids: Sequence[object] = ()) -> T:
        """创建，并授权给创建者角色。"""
        if self._repository.name_exists(values["name"]):
            raise ConflictError(f"{self._label}名称已存在")
        item = self._repository.create(values)
        self._grant_actor(item, actor_role_ids)  # type: ignore[arg-type]
        self._uow.commit()
        return item

    def update(self, resource_id: object, values: dict) -> T:
        """全量更新；产品级资源仅产品级平台可维护。"""
        existing = self._repository.get(resource_id)  # type: ignore[arg-type]
        if existing is None:
            raise NotFoundError(f"{self._label}不存在")
        self._ensure_manageable(existing)
        if self._repository.name_exists(values["name"], exclude_id=resource_id):  # type: ignore[arg-type]
            raise ConflictError(f"{self._label}名称已存在")
        updated = self._repository.update(resource_id, values)  # type: ignore[arg-type]
        if updated is None:
            raise NotFoundError(f"{self._label}不存在")
        self._uow.commit()
        return updated

    def delete(self, resource_id: object) -> None:
        """删除；产品级资源仅产品级平台可维护。"""
        existing = self._repository.get(resource_id)  # type: ignore[arg-type]
        if existing is None:
            raise NotFoundError(f"{self._label}不存在")
        self._ensure_manageable(existing)
        if not self._repository.delete(resource_id):  # type: ignore[arg-type]
            raise NotFoundError(f"{self._label}不存在")
        self._uow.resource_grants.delete_for_resource(self._resource_type, resource_id)  # type: ignore[arg-type]
        self._uow.commit()

    def _grant_actor(self, item: T, actor_role_ids: Sequence[object]) -> None:
        """把租户自有资源授权给创建者角色，保证创建者立即可见；平台资源不授权。"""
        tenant_id = getattr(item, "tenant_id", None)
        role_ids = sorted(set(actor_role_ids))
        if tenant_id == PLATFORM_TENANT_ID or not role_ids:
            return
        existing = [
            grant
            for grant in self._uow.resource_grants.list_for_resource(self._resource_type, item.id)  # type: ignore[arg-type]
            if grant.tenant_id == tenant_id
        ]
        if existing:
            return
        for role_id in role_ids:
            self._uow.resource_grants.add_for_role(
                role_id, tenant_id, self._resource_type, [item.id], None  # type: ignore[arg-type]
            )

    def _ensure_manageable(self, resource: T) -> None:
        """校验当前作用域是否有权维护该资源。"""
        if not self._context.can_manage(getattr(resource, "tenant_id", None)):
            raise ForbiddenError(f"{self._label}属于产品级资源，仅产品级运营管理平台可维护")


def _clone_values[T](source: T, name: str) -> dict:
    """按实体字段生成克隆入参，排除服务端维护字段。"""
    skipped = {"id", "created_at", "updated_at", "tenant_id"}
    values = {
        field.name: getattr(source, field.name)
        for field in fields(cast(Any, source))
        if field.name not in skipped
    }
    values["name"] = name
    return values


def _normalize_paging(page: int, page_size: int) -> tuple[int, int]:
    return max(page, 1), min(max(page_size, 1), MAX_PAGE_SIZE)
