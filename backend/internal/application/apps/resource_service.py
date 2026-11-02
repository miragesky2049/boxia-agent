"""统一资源服务：tool / prompt / skill / knowledge 的 CRUD、grant、租户可用资源查询。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from internal.application.errors import NotFoundError, ValidationError
from internal.domain.repository.apps_protocols import AppResourceRepositoryProtocol

_VALID_TYPES = {"tool", "prompt", "skill", "knowledge"}


class AppResourceService:
    """统一资源服务。"""

    def __init__(self, repo: AppResourceRepositoryProtocol):
        """仓储由组合根（web/deps/apps_services.py）构造注入。"""
        self._repo: AppResourceRepositoryProtocol = repo

    # ========== admin / 租户自建 CRUD ==========
    def create_resource(
        self,
        *,
        type: str,
        name: str,
        config: dict[str, Any],
        owner_type: str = "platform",
        owner_id: UUID | None = None,
    ) -> UUID:
        if type not in _VALID_TYPES:
            raise ValidationError(f"resource type 必须是 {sorted(_VALID_TYPES)} 之一")
        if not name.strip():
            raise ValidationError("资源名称不能为空")
        if owner_type == "tenant" and owner_id is None:
            raise ValidationError("租户资源必须指定 owner_id")
        return self._repo.create_resource(
            type=type,
            name=name.strip(),
            config=config or {},
            owner_type=owner_type,
            owner_id=owner_id,
        )

    def get_resource(self, resource_id: UUID) -> dict:
        record = self._repo.get_resource(resource_id)
        if record is None:
            raise NotFoundError("资源不存在")
        return record

    def update_resource(
        self,
        resource_id: UUID,
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        is_enabled: bool | None = None,
        is_deprecated: bool | None = None,
    ) -> None:
        if self._repo.get_resource(resource_id) is None:
            raise NotFoundError("资源不存在")
        self._repo.update_resource(
            resource_id,
            name=name,
            config=config,
            is_enabled=is_enabled,
            is_deprecated=is_deprecated,
        )

    def delete_resource(self, resource_id: UUID) -> None:
        if self._repo.get_resource(resource_id) is None:
            raise NotFoundError("资源不存在")
        self._repo.delete_resource(resource_id)

    def list_resources(
        self,
        *,
        type: str | None = None,
        owner_type: str | None = None,
        owner_id: UUID | None = None,
    ) -> list[dict]:
        """admin 用：列出全部资源（含禁用）。"""
        if type is not None and type not in _VALID_TYPES:
            raise ValidationError(f"resource type 必须是 {sorted(_VALID_TYPES)} 之一")
        return self._repo.list_resources(
            type=type,
            owner_type=owner_type,
            owner_id=owner_id,
            include_disabled=True,
        )

    # ========== grant ==========
    def grant_resource(self, resource_id: UUID, tenant_id: UUID) -> None:
        """平台把资源开放给租户。"""
        record = self._repo.get_resource(resource_id)
        if record is None:
            raise NotFoundError("资源不存在")
        if record["owner_type"] != "platform":
            raise ValidationError("只能 grant 平台级资源")
        self._repo.grant(resource_id, tenant_id)

    def revoke_resource(self, resource_id: UUID, tenant_id: UUID) -> None:
        self._repo.revoke(resource_id, tenant_id)

    def list_grants(self, resource_id: UUID) -> list[dict]:
        if self._repo.get_resource(resource_id) is None:
            raise NotFoundError("资源不存在")
        return self._repo.list_grants(resource_id)

    # ========== 租户视角 ==========
    def list_available(self, tenant_id: UUID, *, type: str | None = None) -> list[dict]:
        """租户浏览可用资源：平台已 grant 的 + 自建私有资源。"""
        if type is not None and type not in _VALID_TYPES:
            raise ValidationError(f"resource type 必须是 {sorted(_VALID_TYPES)} 之一")
        return self._repo.list_available_for_tenant(tenant_id, type=type)

    def resolve_for_tenant(self, resource_id: UUID, tenant_id: UUID) -> dict | None:
        """运行时解析：校验租户是否有权访问该资源。"""
        return self._repo.resolve_for_tenant(resource_id, tenant_id)
