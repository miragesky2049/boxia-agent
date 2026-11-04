"""统一资源服务：tool / prompt / skill / knowledge 的 CRUD、grant、租户可用资源查询与审核。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from internal.application.audit import record_audit
from internal.application.errors import (
    NotFoundError,
    SelfReviewForbiddenError,
    ValidationError,
)
from internal.domain.entity.access import RESOURCE_TABLE_TYPES
from internal.domain.entity.resource import (
    REVIEW_STATUS_APPROVED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUSES,
)
from internal.domain.repository.apps_protocols import (
    AppResourceRepositoryProtocol,
    ResourceTypeCatalogRepositoryProtocol,
)
from internal.domain.repository.protocols import UnitOfWork

_VALID_REVIEW_DECISIONS = frozenset({"approve", "reject"})


class AppResourceService:
    """统一资源服务。"""

    def __init__(
        self,
        repo: AppResourceRepositoryProtocol,
        uow: UnitOfWork,
        type_catalog: ResourceTypeCatalogRepositoryProtocol | None = None,
    ):
        """仓储与 UoW 由组合根（web/deps/apps_services.py）构造注入；审核审计共享 UoW 事务。

        type_catalog 为资源类型注册表读侧（P3-5）：类型合法性以目录为准，
        新增类型插目录行即可放行；未装配时退回 RESOURCE_TABLE_TYPES 常量（单测场景）。
        """
        self._repo: AppResourceRepositoryProtocol = repo
        self._uow: UnitOfWork = uow
        self._type_catalog = type_catalog
        self._valid_types: frozenset[str] | None = None

    def _require_valid_type(self, type: str) -> None:
        """类型枚举校验：目录为事实源，请求级缓存一次查询。"""
        if self._valid_types is None:
            if self._type_catalog is not None:
                self._valid_types = frozenset(self._type_catalog.list_active())
            else:
                self._valid_types = frozenset(RESOURCE_TABLE_TYPES)
        if type not in self._valid_types:
            raise ValidationError(f"resource type 必须是 {sorted(self._valid_types)} 之一")

    # ========== admin / 租户自建 CRUD ==========
    def create_resource(
        self,
        *,
        type: str,
        name: str,
        config: dict[str, Any],
        owner_type: str = "platform",
        owner_id: UUID | None = None,
        created_by: UUID | None = None,
        review_status: str = REVIEW_STATUS_APPROVED,
    ) -> UUID:
        self._require_valid_type(type)
        if not name.strip():
            raise ValidationError("资源名称不能为空")
        if owner_type == "tenant" and owner_id is None:
            raise ValidationError("租户资源必须指定 owner_id")
        # pending 只由租户自助入口（POST /my-resources）显式传入；
        # 平台代建即使归属租户也不拦审核（P1-9）
        return self._repo.create_resource(
            type=type,
            name=name.strip(),
            config=config or {},
            owner_type=owner_type,
            owner_id=owner_id,
            review_status=review_status,
            created_by=created_by,
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
        review_status: str | None = None,
    ) -> list[dict]:
        """admin 用：列出全部资源（含禁用），可按审核状态过滤（P1-9 审核队列）。"""
        if type is not None:
            self._require_valid_type(type)
        if review_status is not None and review_status not in REVIEW_STATUSES:
            raise ValidationError(f"review_status 必须是 {', '.join(REVIEW_STATUSES)} 之一")
        return self._repo.list_resources(
            type=type,
            owner_type=owner_type,
            owner_id=owner_id,
            include_disabled=True,
            review_status=review_status,
        )

    # ========== 审核 ==========
    def review_resource(
        self,
        resource_id: UUID,
        *,
        decision: str,
        reviewer_id: UUID,
        reviewer_username: str,
        remark: str = "",
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """审核资源：通过=approved、驳回=rejected；创建人审核自己的资源按职责分离拒绝（P1-9）。"""
        if decision not in _VALID_REVIEW_DECISIONS:
            raise ValidationError(
                f"decision 必须是 {', '.join(sorted(_VALID_REVIEW_DECISIONS))} 之一"
            )
        record = self._repo.get_resource(resource_id)
        if record is None:
            raise NotFoundError("资源不存在")
        created_by = record.get("created_by")
        if created_by is not None and created_by == reviewer_id:
            # created_by 为 NULL 的历史资源放行（职责分离只约束新资源）
            raise SelfReviewForbiddenError("不能审核自己创建的资源")
        after = REVIEW_STATUS_APPROVED if decision == "approve" else REVIEW_STATUS_REJECTED
        before = record.get("review_status")
        self._repo.review_resource(
            resource_id,
            review_status=after,
            reviewer_id=reviewer_id,
            remark=remark,
        )
        record_audit(
            self._uow,
            action="resource.reviewed",
            actor_id=reviewer_id,
            actor_username=reviewer_username,
            resource_type=str(record.get("type", "")),
            resource_id=str(resource_id),
            ip=ip,
            user_agent=user_agent,
            detail={
                "before": before,
                "after": after,
                "remark": remark,
                "reviewer_id": str(reviewer_id),
            },
            tenant_id=record.get("owner_id"),
        )
        return {"resource_id": resource_id, "review_status": after, "review_remark": remark}

    def resubmit_for_review(
        self,
        resource_id: UUID,
        *,
        tenant_id: UUID,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """重新提交审核：仅本租户自建且被驳回的资源，置回 pending 并清空审核痕迹（P2-4）。"""
        record = self._repo.get_resource(resource_id)
        if record is None:
            raise NotFoundError("资源不存在")
        if record.get("owner_type") != "tenant" or record.get("owner_id") != tenant_id:
            raise ValidationError("只能重新提交本租户自建的资源")
        if record.get("review_status") != REVIEW_STATUS_REJECTED:
            raise ValidationError("仅被驳回的资源可重新提交审核")
        self._repo.review_resource(
            resource_id,
            review_status=REVIEW_STATUS_PENDING,
            reviewer_id=None,
            remark="",
        )
        record_audit(
            self._uow,
            action="resource.resubmitted",
            actor_id=actor_id,
            actor_username=actor_username,
            resource_type=str(record.get("type", "")),
            resource_id=str(resource_id),
            ip=ip,
            user_agent=user_agent,
            detail={"before": REVIEW_STATUS_REJECTED, "after": REVIEW_STATUS_PENDING},
            tenant_id=tenant_id,
        )
        return {"resource_id": resource_id, "review_status": REVIEW_STATUS_PENDING}

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
        if type is not None:
            self._require_valid_type(type)
        return self._repo.list_available_for_tenant(tenant_id, type=type)

    def resolve_for_tenant(self, resource_id: UUID, tenant_id: UUID) -> dict | None:
        """运行时解析：校验租户是否有权访问该资源。"""
        return self._repo.resolve_for_tenant(resource_id, tenant_id)
