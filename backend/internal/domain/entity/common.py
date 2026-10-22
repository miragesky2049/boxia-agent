"""通用领域模型。"""

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    """分页结果。"""

    items: list[T]
    total: int
    page: int
    page_size: int
