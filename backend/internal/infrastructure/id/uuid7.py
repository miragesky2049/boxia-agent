"""应用层主键生成：RFC 9562 UUID v7。"""

from uuid import UUID

from uuid6 import uuid7


def new_uuid() -> UUID:
    """生成 UUID v7；高位为毫秒时间戳，同毫秒内单调递增，便于 B 树索引。"""
    return uuid7()
