"""技能/工具/组件/提示词通用用例。"""

from typing import Generic, TypeVar

from internal.application.errors import ConflictError, NotFoundError
from internal.domain.entity.common import Page
from internal.domain.repository.protocols import ResourceRepository, UnitOfWork

T = TypeVar("T")

MAX_PAGE_SIZE = 100


class ResourceService(Generic[T]):
    """通用资源 CRUD 用例。"""

    def __init__(self, repository: ResourceRepository[T], label: str, uow: UnitOfWork):
        self._repository = repository
        self._label = label
        self._uow = uow

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
        """全量更新。"""
        if self._repository.get(resource_id) is None:
            raise NotFoundError(f"{self._label}不存在")
        if self._repository.name_exists(values["name"], exclude_id=resource_id):
            raise ConflictError(f"{self._label}名称已存在")
        updated = self._repository.update(resource_id, values)
        if updated is None:
            raise NotFoundError(f"{self._label}不存在")
        self._uow.commit()
        return updated

    def delete(self, resource_id: int) -> None:
        """删除。"""
        if not self._repository.delete(resource_id):
            raise NotFoundError(f"{self._label}不存在")
        self._uow.commit()


def _normalize_paging(page: int, page_size: int) -> tuple[int, int]:
    return max(page, 1), min(max(page_size, 1), MAX_PAGE_SIZE)
