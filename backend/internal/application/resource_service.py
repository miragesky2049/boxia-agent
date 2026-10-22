"""技能/工具/组件/提示词通用用例。"""

from typing import Generic, TypeVar

from internal.application.errors import ConflictError, ForbiddenError, NotFoundError
from internal.domain.entity.common import Page
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import ResourceRepository, UnitOfWork

T = TypeVar("T")

MAX_PAGE_SIZE = 100


class ResourceService(Generic[T]):
    """通用资源 CRUD 用例。"""

    def __init__(
        self,
        repository: ResourceRepository[T],
        label: str,
        uow: UnitOfWork,
        context: RequestContext,
    ):
        self._repository = repository
        self._label = label
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

    def get(self, resource_id: int) -> T:
        """查询详情。"""
        item = self._repository.get(resource_id)
        if item is None:
            raise NotFoundError(f"{self._label}不存在")
        return item

    def create(self, values: dict) -> T:
        """创建。"""
        if self._repository.name_exists(values["name"]):
            raise ConflictError(f"{self._label}名称已存在")
        item = self._repository.create(values)
        self._uow.commit()
        return item

    def update(self, resource_id: int, values: dict) -> T:
        """全量更新；产品级资源仅产品级平台可维护。"""
        existing = self._repository.get(resource_id)
        if existing is None:
            raise NotFoundError(f"{self._label}不存在")
        self._ensure_manageable(existing)
        if self._repository.name_exists(values["name"], exclude_id=resource_id):
            raise ConflictError(f"{self._label}名称已存在")
        updated = self._repository.update(resource_id, values)
        if updated is None:
            raise NotFoundError(f"{self._label}不存在")
        self._uow.commit()
        return updated

    def delete(self, resource_id: int) -> None:
        """删除；产品级资源仅产品级平台可维护。"""
        existing = self._repository.get(resource_id)
        if existing is None:
            raise NotFoundError(f"{self._label}不存在")
        self._ensure_manageable(existing)
        if not self._repository.delete(resource_id):
            raise NotFoundError(f"{self._label}不存在")
        self._uow.commit()

    def _ensure_manageable(self, resource: T) -> None:
        """校验当前作用域是否有权维护该资源。"""
        if not self._context.can_manage(getattr(resource, "tenant_id", None)):
            raise ForbiddenError(f"{self._label}属于产品级资源，仅产品级运营管理平台可维护")


def _normalize_paging(page: int, page_size: int) -> tuple[int, int]:
    return max(page, 1), min(max(page_size, 1), MAX_PAGE_SIZE)
