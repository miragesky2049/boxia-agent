"""HR 字典的 PostgreSQL 仓储实现。"""

from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from internal.domain.entity.hr_dictionary import HrDictionary
from internal.infrastructure.model.employment import EmploymentModel
from internal.infrastructure.model.hr_dictionary import HrDictionaryModel


class PostgresHrDictionaryRepository:
    """基于 SQLAlchemy 的 HR 字典仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def get(self, dictionary_id: UUID) -> HrDictionary | None:
        """按主键查询字典项。"""
        row = self._session.get(HrDictionaryModel, dictionary_id)
        return self._to_entity(row) if row else None

    def list_by_category(
        self, tenant_id: UUID, category: str, include_inactive: bool = False
    ) -> list[HrDictionary]:
        """按类别读取租户字典项，按 sort_order、id 升序返回。"""
        stmt = select(HrDictionaryModel).where(
            HrDictionaryModel.tenant_id == tenant_id,
            HrDictionaryModel.category == category,
        )
        if not include_inactive:
            stmt = stmt.where(HrDictionaryModel.is_active.is_(True))
        stmt = stmt.order_by(
            HrDictionaryModel.sort_order.asc(),
            HrDictionaryModel.id.asc(),
        )
        rows = self._session.scalars(stmt).all()
        return [self._to_entity(row) for row in rows]

    def list_by_categories(
        self, tenant_id: UUID, categories: list[str], include_inactive: bool = False
    ) -> list[HrDictionary]:
        """批量读取多个类别的字典项，用于任职列表一次性回填名称。"""
        stmt = select(HrDictionaryModel).where(
            HrDictionaryModel.tenant_id == tenant_id,
            HrDictionaryModel.category.in_(categories),
        )
        if not include_inactive:
            stmt = stmt.where(HrDictionaryModel.is_active.is_(True))
        stmt = stmt.order_by(
            HrDictionaryModel.category.asc(),
            HrDictionaryModel.sort_order.asc(),
            HrDictionaryModel.id.asc(),
        )
        rows = self._session.scalars(stmt).all()
        return [self._to_entity(row) for row in rows]

    def get_many(self, dictionary_ids: list[UUID]) -> list[HrDictionary]:
        """按主键集合批量读取，用于任职列表 join 后回填名称。"""
        if not dictionary_ids:
            return []
        rows = self._session.scalars(
            select(HrDictionaryModel).where(HrDictionaryModel.id.in_(dictionary_ids))
        ).all()
        return [self._to_entity(row) for row in rows]

    def create(self, values: dict[str, Any]) -> HrDictionary:
        """创建字典项。"""
        row = HrDictionaryModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def update(self, dictionary_id: UUID, values: dict[str, Any]) -> HrDictionary | None:
        """更新字典项基础字段。"""
        row = self._session.get(HrDictionaryModel, dictionary_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def delete(self, dictionary_id: UUID) -> bool:
        """物理删除字典项。"""
        row = self._session.get(HrDictionaryModel, dictionary_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def code_exists(
        self,
        tenant_id: UUID,
        category: str,
        code: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        """同一租户同一类别下编码是否已存在（忽略大小写）。"""
        stmt = select(HrDictionaryModel.id).where(
            HrDictionaryModel.tenant_id == tenant_id,
            HrDictionaryModel.category == category,
            func.lower(HrDictionaryModel.code) == code.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(HrDictionaryModel.id != exclude_id)
        return self._session.scalar(stmt) is not None

    def count_references(self, dictionary_id: UUID) -> int:
        """统计该字典项被任职记录引用的次数（三类字典列分别统计）。"""
        stmt = select(
            func.coalesce(
                func.sum(
                    case(
                        (EmploymentModel.employment_type_id == dictionary_id, 1),
                        else_=0,
                    )
                ),
                0,
            )
            + func.coalesce(
                func.sum(
                    case(
                        (EmploymentModel.job_level_id == dictionary_id, 1),
                        else_=0,
                    )
                ),
                0,
            )
            + func.coalesce(
                func.sum(
                    case(
                        (EmploymentModel.job_family_id == dictionary_id, 1),
                        else_=0,
                    )
                ),
                0,
            )
        ).select_from(EmploymentModel)
        total = self._session.scalar(stmt)
        return int(total or 0)

    @staticmethod
    def _to_entity(row: HrDictionaryModel) -> HrDictionary:
        return HrDictionary(
            id=row.id,
            tenant_id=row.tenant_id,
            category=row.category,
            code=row.code,
            name=row.name,
            sort_order=row.sort_order,
            is_active=row.is_active,
            remark=row.remark,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
