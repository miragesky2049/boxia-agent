"""多租户 ORM mixin：业务表统一带 tenant_id / visibility / tenant_group_id / creator_user_id。

新表继承该 mixin 即获得多租户可见性字段，配合 `visibility_filters.visibility_filter`
可以直接复用统一的可见性 SQL。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from sqlalchemy import String, Uuid
from sqlalchemy.orm import mapped_column

from internal.domain.entity.visibility import Visibility


# 可见性字段长度：枚举值短，32 足够
VisibilityColumn = Annotated[
    str,
    mapped_column(String(32), default=Visibility.default().value, nullable=False),
]

TenantIdColumn = Annotated[
    UUID,
    mapped_column(Uuid(as_uuid=True), index=True, nullable=False),
]

TenantGroupIdColumn = Annotated[
    UUID | None,
    mapped_column(Uuid(as_uuid=True), index=True, nullable=True),
]

CreatorUserIdColumn = Annotated[
    UUID | None,
    mapped_column(Uuid(as_uuid=True), index=True, nullable=True),
]
