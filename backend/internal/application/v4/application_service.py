"""v4 应用服务：应用市场浏览、自助开通、我的应用列表、平台管理。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from internal.application.errors import NotFoundError, ValidationError
from internal.engine.v4.compiler import infer_runtime_mode
from internal.infrastructure.repository.v4.application_repository import V4ApplicationRepository


class V4ApplicationService:
    def __init__(self, session: Session):
        self._repo = V4ApplicationRepository(session)

    # ========== 市场浏览（租户端） ==========
    def list_marketplace(self) -> list[dict]:
        """列出应用市场中所有产品级应用。"""
        return self._repo.list_marketplace()

    def subscribe(self, tenant_id: UUID, application_id: UUID) -> dict:
        """租户自助开通一个产品级应用。"""
        existing = self._repo.get_instance(tenant_id, application_id)
        if existing:
            raise ValidationError("该应用已开通")

        app = self._repo.get_application(application_id)
        if not app:
            raise NotFoundError("应用不存在")
        if app["owner_type"] != "platform":
            raise ValidationError("只能开通产品级应用")
        if not app["is_listed_in_market"]:
            raise ValidationError("该应用未上架市场")
        if not app["is_enabled"]:
            raise ValidationError("该应用已被禁用")

        instance_id = self._repo.subscribe(tenant_id, application_id)
        return {"instance_id": instance_id, "application_id": application_id}

    def list_my_apps(self, tenant_id: UUID) -> list[dict]:
        """租户查看自己已开通的应用列表。"""
        return self._repo.list_instances(tenant_id)

    # ========== graph 读取 ==========
    def get_graph(self, application_id: UUID) -> dict | None:
        """获取应用的 graph 定义。"""
        return self._repo.get_graph(application_id)

    # ========== 平台管理端 ==========
    def create_platform_application(
        self,
        *,
        name: str,
        description: str = "",
        created_by: UUID | None = None,
    ) -> UUID:
        """平台管理员创建新应用（未上架）。"""
        if not name.strip():
            raise ValidationError("应用名称不能为空")
        return self._repo.create_application(
            name=name.strip(),
            owner_type="platform",
            owner_id=None,
            description=description,
            created_by=created_by,
        )

    def update_application(
        self,
        application_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        self._repo.update_application(
            application_id, name=name, description=description, avatar_url=avatar_url
        )

    def set_listed_in_market(self, application_id: UUID, listed: bool) -> None:
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        if app["owner_type"] != "platform":
            raise ValidationError("只能上架产品级应用")
        if listed and not app["is_enabled"]:
            raise ValidationError("应用已被禁用，无法上架")
        self._repo.set_listed_in_market(application_id, listed)

    def set_enabled(self, application_id: UUID, enabled: bool) -> None:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        self._repo.set_enabled(application_id, enabled)

    def save_graph(self, application_id: UUID, graph: dict[str, Any]) -> str:
        """保存 graph 定义，自动推断 runtime_mode。"""
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        if not graph.get("nodes"):
            raise ValidationError("graph 至少需要一个节点")
        runtime_mode = infer_runtime_mode(graph)
        self._repo.update_graph(application_id, graph, runtime_mode)
        return runtime_mode

    def list_applications(
        self,
        owner_type: str | None = None,
        include_marketplace_only: bool = False,
    ) -> list[dict]:
        """平台管理端列表。"""
        return self._repo.list_applications(
            owner_type=owner_type,
            include_marketplace_only=include_marketplace_only,
        )
