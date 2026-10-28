"""工作流管理用例：CRUD、图校验、模板克隆。"""

from __future__ import annotations

from uuid import UUID

from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.application.resource_service import MAX_PAGE_SIZE
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.common import Page
from internal.domain.entity.request_context import RequestContext
from internal.domain.entity.workflow import Workflow, WorkflowTemplate
from internal.domain.repository.protocols import UnitOfWork
from internal.engine.workflow.validator import GraphValidationError, validate_graph


class WorkflowService:
    """工作流 CRUD 与图校验。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    # ---------- Workflow CRUD ----------

    def list(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
    ) -> Page[Workflow]:
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        items, total = self._uow.workflows.list_page(page, page_size, keyword, is_enabled)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def get(self, workflow_id: UUID) -> Workflow:
        workflow = self._uow.workflows.get(workflow_id)
        if workflow is None:
            raise NotFoundError("工作流不存在")
        return workflow

    def create(
        self,
        values: dict,
        actor_user_id: UUID | None = None,
    ) -> Workflow:
        """创建工作流：平台上下文只能建产品级；租户上下文只能建租户级。"""
        self._validate_graph(values.get("graph") or {})
        if self._uow.workflows.name_exists(values["name"]):
            raise ConflictError("工作流名称已存在")

        payload = dict(values)
        # 强制按当前作用域写入 tenant_id，避免越权建平台资源
        payload["tenant_id"] = self._context.tenant_id
        if actor_user_id is not None and not self._context.is_platform:
            payload.setdefault("created_by", actor_user_id)
        else:
            payload.pop("created_by", None)
        workflow = self._uow.workflows.create(payload)
        self._uow.commit()
        return workflow

    def update(self, workflow_id: UUID, values: dict) -> Workflow:
        existing = self._uow.workflows.get(workflow_id)
        if existing is None:
            raise NotFoundError("工作流不存在")
        self._ensure_manageable(existing)
        self._validate_graph(values.get("graph") or {})
        if self._uow.workflows.name_exists(values["name"], exclude_id=workflow_id):
            raise ConflictError("工作流名称已存在")
        updated = self._uow.workflows.update(workflow_id, values)
        if updated is None:
            raise NotFoundError("工作流不存在")
        self._uow.commit()
        return updated

    def delete(self, workflow_id: UUID) -> None:
        existing = self._uow.workflows.get(workflow_id)
        if existing is None:
            raise NotFoundError("工作流不存在")
        self._ensure_manageable(existing)
        if not self._uow.workflows.delete(workflow_id):
            raise NotFoundError("工作流不存在")
        self._uow.commit()

    def validate_graph(self, graph: dict) -> dict:
        """对外暴露的图校验：不落库，返回节点/边摘要。"""
        self._validate_graph(graph)
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []
        return {
            "valid": True,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "node_types": sorted({node.get("type", "") for node in nodes}),
        }

    def clone_from_template(
        self,
        template_id: UUID,
        name: str,
        description: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> Workflow:
        """把产品级模板复制为当前租户自有的工作流。"""
        if self._context.is_platform:
            raise ForbiddenError("平台上下文请直接创建工作流，无需从模板克隆")
        template = self._uow.workflow_templates.get(template_id)
        if template is None or not template.is_enabled:
            raise NotFoundError("模板不存在或已停用")
        if self._uow.workflows.name_exists(name):
            raise ConflictError("工作流名称已存在")

        payload = {
            "name": name,
            "description": description if description is not None else template.description,
            "graph": dict(template.graph or {}),
            "is_enabled": True,
            "visibility_mode": "all",
            "tenant_id": self._context.tenant_id,
            "created_by": actor_user_id,
        }
        workflow = self._uow.workflows.create(payload)
        self._uow.commit()
        return workflow

    # ---------- Template CRUD ----------

    def list_templates(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        category: str | None,
    ) -> Page[WorkflowTemplate]:
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        items, total = self._uow.workflow_templates.list_page(
            page,
            page_size,
            keyword,
            category,
            include_disabled=self._context.is_platform,
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    def get_template(self, template_id: UUID) -> WorkflowTemplate:
        template = self._uow.workflow_templates.get(template_id)
        if template is None:
            raise NotFoundError("模板不存在")
        return template

    def create_template(self, values: dict) -> WorkflowTemplate:
        if not self._context.is_platform:
            raise ForbiddenError("仅产品级平台可维护模板")
        self._validate_graph(values.get("graph") or {})
        if self._uow.workflow_templates.name_exists(values["name"]):
            raise ConflictError("模板名称已存在")
        template = self._uow.workflow_templates.create(values)
        self._uow.commit()
        return template

    def update_template(self, template_id: UUID, values: dict) -> WorkflowTemplate:
        if not self._context.is_platform:
            raise ForbiddenError("仅产品级平台可维护模板")
        existing = self._uow.workflow_templates.get(template_id)
        if existing is None:
            raise NotFoundError("模板不存在")
        self._validate_graph(values.get("graph") or {})
        if self._uow.workflow_templates.name_exists(values["name"], exclude_id=template_id):
            raise ConflictError("模板名称已存在")
        updated = self._uow.workflow_templates.update(template_id, values)
        if updated is None:
            raise NotFoundError("模板不存在")
        self._uow.commit()
        return updated

    def delete_template(self, template_id: UUID) -> None:
        if not self._context.is_platform:
            raise ForbiddenError("仅产品级平台可维护模板")
        if not self._uow.workflow_templates.delete(template_id):
            raise NotFoundError("模板不存在")
        self._uow.commit()

    # ---------- 内部 ----------

    def _ensure_manageable(self, workflow: Workflow) -> None:
        if not self._context.can_manage(workflow.tenant_id):
            raise ForbiddenError("该工作流属于产品级资源，仅产品级运营管理平台可维护")

    def _validate_graph(self, graph: dict) -> None:
        """委托给 engine.workflow.validator 做统一图校验。"""
        try:
            validate_graph(graph)
        except GraphValidationError as exc:
            raise ValidationError(exc.message) from exc
