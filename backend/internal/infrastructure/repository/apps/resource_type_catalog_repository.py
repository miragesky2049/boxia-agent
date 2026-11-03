"""资源类型注册表仓储：resource_type_catalog 读侧裸 SQL（P3-5）。

只依赖 SQLAlchemy Core / text，不 import application 层（DDD 依赖方向：infra → domain）。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


class ResourceTypeCatalogRepository:
    """结构性满足 ResourceTypeCatalogRepositoryProtocol 的 PostgreSQL 实现。"""

    def __init__(self, session: Session):
        self._session = session

    def list_active(self) -> list[str]:
        rows = self._session.execute(
            text("SELECT code FROM resource_type_catalog WHERE is_active ORDER BY sort_order, code")
        ).all()
        return [row.code for row in rows]
