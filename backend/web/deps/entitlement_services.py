"""权益上下文组合根：EntitlementService 与 OPS 直开引擎的装配点。

与 apps_services.py 同为 web 层允许的"application + infra"装配模块；
entitlement 相关工厂统一收口本文件，不再往 apps_services.py 加同名工厂（P1-5）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from internal.application.apps.entitlement_service import EntitlementService
from internal.domain.auth.grant_service import GrantService
from internal.domain.auth.service import AuthService
from internal.domain.entity.request_context import RequestContext
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.repository.apps.auth_repository import AuthRepository
from internal.infrastructure.repository.apps.entitlement_plan_repository import (
    EntitlementPlanRepository,
)
from internal.infrastructure.repository.apps.entitlement_repository import EntitlementRepository
from internal.infrastructure.repository.apps.entitlement_request_log_repository import (
    EntitlementRequestLogRepository,
)
from internal.infrastructure.repository.apps.resource_type_catalog_repository import (
    ResourceTypeCatalogRepository,
)
from web.deps.db import UowDep
from web.deps.tenant import RequestContextDep


def make_entitlement_service(
    uow: SqlAlchemyUnitOfWork, context: RequestContext
) -> EntitlementService:
    """权益读写服务：双表统一仓储 + 套餐模板仓储 + 类型注册表 + AuthService 失效 + 严格模式开关（cache 当前为 None）。"""
    auth_service = AuthService(AuthRepository(uow.session), cache=None)
    return EntitlementService(
        uow,
        EntitlementRepository(uow.session),
        context,
        auth_service=auth_service,
        plan_repo=EntitlementPlanRepository(uow.session),
        type_catalog=ResourceTypeCatalogRepository(uow.session),
        request_log=EntitlementRequestLogRepository(uow.session),
        revoke_strict=get_settings().entitlement_revoke_strict,
    )


def make_grant_engine_service(uow: SqlAlchemyUnitOfWork) -> GrantService:
    """OPS 直开应用引擎（P1-7 消费）：与 make_apply_service 同构装配。"""
    repo = AuthRepository(uow.session)
    auth_service = AuthService(repo, cache=None)
    return GrantService(repo, auth_service)


def get_entitlement_service(uow: UowDep, context: RequestContextDep) -> EntitlementService:
    """请求级权益用例装配（P1-6 router 消费）。"""
    return make_entitlement_service(uow, context)


def get_grant_engine_service(uow: UowDep) -> GrantService:
    """请求级 OPS 直开引擎装配（P1-7 router 消费）。"""
    return make_grant_engine_service(uow)


EntitlementServiceDep = Annotated[EntitlementService, Depends(get_entitlement_service)]
GrantEngineServiceDep = Annotated[GrantService, Depends(get_grant_engine_service)]
