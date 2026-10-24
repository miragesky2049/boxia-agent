"""技能/工具/组件/提示词通用用例。"""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Generic, Protocol, TypeVar, cast

from internal.application.audit import record_audit
from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.domain.entity.common import Page
from internal.domain.entity.request_context import RequestContext
from internal.domain.repository.protocols import ResourceRepository, UnitOfWork


class _ResourceEntity(Protocol):
    """资源实体最小契约：通用用例只依赖标识与名称。"""

    @property
    def id(self) -> int: ...

    @property
    def name(self) -> str: ...


T = TypeVar("T", bound=_ResourceEntity)

MAX_PAGE_SIZE = 100


class ResourceService(Generic[T]):
    """通用资源 CRUD 用例。"""

    def __init__(
        self,
        repository: ResourceRepository[T],
        label: str,
        resource_type: str,
        uow: UnitOfWork,
        context: RequestContext,
    ):
        self._repository = repository
        self._label = label
        self._resource_type = resource_type
        self._uow = uow
        self._context = context

    def list(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        agent_id: int | None = None,
    ) -> Page[T]:
        """分页查询；agent_id 限定所属智能体。"""
        page, page_size = _normalize_paging(page, page_size)
        items, total = self._repository.list_page(
            page, page_size, keyword, is_enabled, agent_id
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    def get(self, resource_id: int) -> T:
        """查询详情。"""
        item = self._repository.get(resource_id)
        if item is None:
            raise NotFoundError(f"{self._label}不存在")
        return item

    def create(self, values: dict) -> T:
        """创建；所属智能体必须与资源同租户。"""
        if self._repository.name_exists(values["name"]):
            raise ConflictError(f"{self._label}名称已存在")
        payload = self._with_validated_agent(values)
        item = self._repository.create(payload)
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
        payload = self._with_validated_agent(values)
        updated = self._repository.update(resource_id, payload)
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
        self._uow.resource_grants.delete_for_resource(self._resource_type, resource_id)
        self._uow.commit()

    def clone_to_agent(
        self,
        resource_id: int,
        *,
        agent_id: int,
        name: str | None,
        actor_id: int,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> T:
        """克隆资源到目标智能体，生成独立副本并按规则复制角色授权。"""
        source = self._repository.get(resource_id)
        if source is None:
            raise NotFoundError(f"{self._label}不存在")
        agent = self._uow.agents.get(agent_id)
        if agent is None:
            raise NotFoundError("目标智能体不存在")
        if not self._context.can_manage(agent.tenant_id):
            raise ForbiddenError("无权在该智能体下维护资源")

        target_name = (name or f"{source.name}（副本）").strip()
        if not target_name:
            raise ValidationError(f"{self._label}名称不能为空")
        if len(target_name) > 100:
            raise ValidationError(f"{self._label}名称不能超过 100 个字符")
        if self._repository.name_exists(target_name):
            raise ConflictError(f"{self._label}名称已存在")

        values = _clone_values(source, target_name)
        values["agent_id"] = agent.id
        clone = self._repository.create(values)
        self._copy_grants(source, clone)
        self._after_clone(source, clone)
        record_audit(
            self._uow,
            action="resource.cloned",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type=self._resource_type,
            resource_id=str(clone.id),
            ip=ip,
            user_agent=user_agent,
            detail={"source_id": resource_id, "agent_id": agent.id},
            tenant_id=getattr(clone, "tenant_id", None),
        )
        self._uow.commit()
        return clone

    def _after_clone(self, source: T, clone: T) -> None:
        """子类扩展点：在同一事务内复制资源附加数据。"""

    def _copy_grants(self, source: T, clone: T) -> None:
        """同租户克隆复制授权；跨租户克隆不继承授权。"""
        source_tenant = getattr(source, "tenant_id", None)
        clone_tenant = getattr(clone, "tenant_id", None)
        if source_tenant != clone_tenant or clone_tenant is None:
            return
        grants = self._uow.resource_grants.list_for_resource(
            self._resource_type, source.id
        )
        role_ids = sorted(
            {grant.role_id for grant in grants if grant.tenant_id == clone_tenant and grant.role_id}
        )
        if role_ids:
            self._uow.resource_grants.replace_for_tenant(
                self._resource_type,
                clone.id,
                clone_tenant,
                list(role_ids),
                None,
            )

    def _with_validated_agent(self, values: dict) -> dict:
        """校验 agent_id 归属：资源与智能体必须同租户。"""
        payload = dict(values)
        agent_id = payload.get("agent_id")
        if agent_id is None:
            return payload
        agent = self._uow.agents.get(int(agent_id))
        if agent is None:
            raise ValidationError("所属智能体不存在或无权访问")
        if not self._context.can_manage(agent.tenant_id):
            raise ForbiddenError("无权在该智能体下维护资源")
        payload["agent_id"] = agent.id
        return payload

    def _ensure_manageable(self, resource: T) -> None:
        """校验当前作用域是否有权维护该资源。"""
        if not self._context.can_manage(getattr(resource, "tenant_id", None)):
            raise ForbiddenError(f"{self._label}属于产品级资源，仅产品级运营管理平台可维护")


def _clone_values[T](source: T, name: str) -> dict:
    """按实体字段生成克隆入参，排除服务端维护字段。"""
    skipped = {"id", "created_at", "updated_at", "tenant_id", "agent_id"}
    values = {
        field.name: getattr(source, field.name)
        for field in fields(cast(Any, source))
        if field.name not in skipped
    }
    values["name"] = name
    return values


def _normalize_paging(page: int, page_size: int) -> tuple[int, int]:
    return max(page, 1), min(max(page_size, 1), MAX_PAGE_SIZE)
