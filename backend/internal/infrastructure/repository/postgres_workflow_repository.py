"""工作流与模板的 PostgreSQL 仓储实现。"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.workflow import Workflow, WorkflowTemplate
from internal.infrastructure.model.workflow import (
    WorkflowModel,
    WorkflowTemplateModel,
)


def _workflow_to_entity(row: Any) -> Workflow:
    return Workflow(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        graph=row.graph or {},
        is_enabled=row.is_enabled,
        visibility_mode=row.visibility_mode,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _template_to_entity(row: Any) -> WorkflowTemplate:
    return WorkflowTemplate(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        graph=row.graph or {},
        category=row.category,
        is_enabled=row.is_enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresWorkflowRepository:
    """工作流仓储。

    可见规则（MVP 不接入 resource_grants 角色授权，简化为租户自有 + 平台可见）：
    - 平台视角（tenant_id == PLATFORM_TENANT_ID）：仅返回产品级工作流；
    - 租户视角：返回本租户自有 + 产品级（只读）工作流。
    写操作（create/update/delete）只允许操作本租户自有的工作流。
    """

    def __init__(self, session: Session, tenant_id: UUID | None = None) -> None:
        self._session = session
        self._tenant_id: UUID = (
            tenant_id if tenant_id is not None else PLATFORM_TENANT_ID
        )

    def _visible(self, stmt):
        """读可见范围。"""
        if self._tenant_id == PLATFORM_TENANT_ID:
            return stmt.where(WorkflowModel.tenant_id == PLATFORM_TENANT_ID)
        return stmt.where(
            or_(
                WorkflowModel.tenant_id == self._tenant_id,
                WorkflowModel.tenant_id == PLATFORM_TENANT_ID,
            )
        )

    def _owned(self, stmt):
        """写归属范围：仅本租户自有工作流可写。"""
        return stmt.where(WorkflowModel.tenant_id == self._tenant_id)

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
    ) -> tuple[list[Workflow], int]:
        """分页查询可见工作流。"""
        base = select(WorkflowModel)
        base = self._visible(base)
        if keyword:
            like = f"%{keyword}%"
            base = base.where(WorkflowModel.name.ilike(like))
        if is_enabled is not None:
            base = base.where(WorkflowModel.is_enabled.is_(is_enabled))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = self._session.execute(count_stmt).scalar_one()

        rows = self._session.execute(
            base.order_by(WorkflowModel.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars().all()
        return [_workflow_to_entity(row) for row in rows], total

    def get(self, workflow_id: UUID) -> Workflow | None:
        """按主键查询；不可见返回 None。"""
        stmt = self._visible(select(WorkflowModel).where(WorkflowModel.id == workflow_id))
        row = self._session.execute(stmt).scalar_one_or_none()
        return _workflow_to_entity(row) if row else None

    def create(self, values: dict) -> Workflow:
        """创建工作流；tenant_id 由应用层按当前作用域写入。"""
        row = WorkflowModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _workflow_to_entity(row)

    def update(self, workflow_id: UUID, values: dict) -> Workflow | None:
        """全量更新仅本租户自有工作流。"""
        row = self._session.get(WorkflowModel, workflow_id)
        if row is None or row.tenant_id != self._tenant_id:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return _workflow_to_entity(row)

    def delete(self, workflow_id: UUID) -> bool:
        """删除仅本租户自有工作流。"""
        row = self._session.get(WorkflowModel, workflow_id)
        if row is None or row.tenant_id != self._tenant_id:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def name_exists(self, name: str, exclude_id: UUID | None = None) -> bool:
        """本租户作用域内名称是否已存在（忽略大小写）。"""
        stmt = select(func.count()).select_from(WorkflowModel).where(
            WorkflowModel.tenant_id == self._tenant_id,
            func.lower(WorkflowModel.name) == name.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(WorkflowModel.id != exclude_id)
        return self._session.execute(stmt).scalar_one() > 0


class PostgresWorkflowTemplateRepository:
    """工作流模板仓储。

    模板仅产品级（PLATFORM_TENANT_ID）使用：
    - 平台视角：可 CRUD；
    - 租户视角：只能列出启用中的模板，用于 clone。
    """

    def __init__(self, session: Session, tenant_id: UUID | None = None) -> None:
        self._session = session
        self._tenant_id: UUID = (
            tenant_id if tenant_id is not None else PLATFORM_TENANT_ID
        )

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        category: str | None,
        include_disabled: bool = False,
    ) -> tuple[list[WorkflowTemplate], int]:
        """分页查询模板。租户视角仅返回启用中的。"""
        base = select(WorkflowTemplateModel)
        if not include_disabled or self._tenant_id != PLATFORM_TENANT_ID:
            base = base.where(WorkflowTemplateModel.is_enabled.is_(True))
        if keyword:
            base = base.where(WorkflowTemplateModel.name.ilike(f"%{keyword}%"))
        if category:
            base = base.where(WorkflowTemplateModel.category == category)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = self._session.execute(count_stmt).scalar_one()

        rows = self._session.execute(
            base.order_by(WorkflowTemplateModel.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars().all()
        return [_template_to_entity(row) for row in rows], total

    def get(self, template_id: UUID) -> WorkflowTemplate | None:
        """按主键查询模板；租户视角仅允许读启用模板。"""
        row = self._session.get(WorkflowTemplateModel, template_id)
        if row is None:
            return None
        if (
            self._tenant_id != PLATFORM_TENANT_ID
            and not row.is_enabled
        ):
            return None
        return _template_to_entity(row)

    def create(self, values: dict) -> WorkflowTemplate:
        """创建模板：强制 tenant_id = PLATFORM_TENANT_ID。"""
        values = dict(values)
        values["tenant_id"] = PLATFORM_TENANT_ID
        row = WorkflowTemplateModel(**values)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _template_to_entity(row)

    def update(self, template_id: UUID, values: dict) -> WorkflowTemplate | None:
        """全量更新模板（仅平台视角）。"""
        if self._tenant_id != PLATFORM_TENANT_ID:
            return None
        row = self._session.get(WorkflowTemplateModel, template_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return _template_to_entity(row)

    def delete(self, template_id: UUID) -> bool:
        """删除模板（仅平台视角）。"""
        if self._tenant_id != PLATFORM_TENANT_ID:
            return False
        row = self._session.get(WorkflowTemplateModel, template_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def name_exists(self, name: str, exclude_id: UUID | None = None) -> bool:
        """模板名称是否已存在（忽略大小写，全表唯一）。"""
        stmt = select(func.count()).select_from(WorkflowTemplateModel).where(
            func.lower(WorkflowTemplateModel.name) == name.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(WorkflowTemplateModel.id != exclude_id)
        return self._session.execute(stmt).scalar_one() > 0
