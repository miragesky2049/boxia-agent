"""webhook 订阅应用服务：CRUD 与出站 URL SSRF 校验（DDD 五期从 marketplace router 下沉）。

SSRF 校验收口在 create 内部：订阅入口只有本服务一处，校验不放 router 防止
未来新增入口漏调。写操作创建/删除即提交（commit 回调由组合根传 uow.commit），
与迁移前 router 行为一致。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from internal.domain.repository.apps_protocols import WebhookRepositoryProtocol
from internal.domain.security.ssrf_guard import validate_outbound_url


class WebhookService:
    """租户 webhook 订阅管理。"""

    def __init__(
        self,
        commit: Callable[[], None],
        webhook_repo: WebhookRepositoryProtocol,
    ) -> None:
        self._commit = commit
        self._repo = webhook_repo

    def list_by_tenant(self, tenant_id: UUID) -> list[dict[str, Any]]:
        """租户列出自己的 webhook 订阅。"""
        return self._repo.list_by_tenant(tenant_id)

    def create(
        self,
        *,
        tenant_id: UUID,
        event_type: str,
        url: str,
        application_id: UUID | None = None,
    ) -> UUID:
        """创建订阅；SSRF 防护：拒绝 loopback/链路本地/云元数据/组播/保留地址，校验 DNS 解析。"""
        validate_outbound_url(url)
        webhook_id = self._repo.create(
            tenant_id=tenant_id,
            event_type=event_type,
            url=url,
            application_id=application_id,
        )
        self._commit()
        return webhook_id

    def delete(self, webhook_id: UUID, tenant_id: UUID) -> None:
        """删除订阅（仓储按 tenant_id 收口，跨租户删除不生效）。"""
        self._repo.delete(webhook_id, tenant_id)
        self._commit()
