"""ORM 基类与统一主键类型。"""

from typing import Annotated
from uuid import UUID

from sqlalchemy import Uuid
from sqlalchemy.orm import DeclarativeBase, mapped_column

from internal.infrastructure.id.uuid7 import new_uuid


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


# 全部业务表主键统一由应用层生成 UUID v7，数据库不维护自增序列。
UuidPrimaryKey = Annotated[
    UUID,
    mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_uuid),
]
