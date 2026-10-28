"""请求作用域上下文：产品级平台或某个租户。"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.tenant import Tenant

PLATFORM_SCOPE = "platform"
TENANT_SCOPE = "tenant"
TenantResolution = Literal["host", "header", "default"]


@dataclass(frozen=True)
class RequestContext:
    """当前请求所处的作用域，应用层据此做资源归属校验。"""

    scope: str
    tenant: Tenant | None
    host: str
    # 作用域解析来源：host=域名，header=本地调试请求头，default=本地兜底
    resolution: TenantResolution = "host"

    @property
    def is_platform(self) -> bool:
        """是否为产品级平台上下文。"""
        return self.scope == PLATFORM_SCOPE

    @property
    def tenant_id(self) -> UUID:
        """当前租户 ID；产品级返回 PLATFORM_TENANT_ID（全零 UUID）。"""
        return self.tenant.id if self.tenant else PLATFORM_TENANT_ID

    def can_manage(self, resource_tenant_id: UUID) -> bool:
        """当前作用域能否维护指定归属的资源。"""
        return resource_tenant_id == self.tenant_id
