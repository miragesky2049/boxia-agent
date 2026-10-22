"""请求作用域上下文：产品级平台或某个租户。"""

from dataclasses import dataclass

from internal.domain.entity.tenant import Tenant

PLATFORM_SCOPE = "platform"
TENANT_SCOPE = "tenant"


@dataclass(frozen=True)
class RequestContext:
    """当前请求所处的作用域，应用层据此做资源归属校验。"""

    scope: str
    tenant: Tenant | None
    host: str

    @property
    def is_platform(self) -> bool:
        """是否为产品级平台上下文。"""
        return self.scope == PLATFORM_SCOPE

    @property
    def tenant_id(self) -> int | None:
        """当前租户 ID；产品级为 None。"""
        return self.tenant.id if self.tenant else None

    def can_manage(self, resource_tenant_id: int | None) -> bool:
        """当前作用域能否维护指定归属的资源。"""
        return resource_tenant_id == self.tenant_id
