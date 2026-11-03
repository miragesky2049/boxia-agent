"""apps 上下文仓储端口：应用层按 Protocol 依赖仓储，具体实现由组合根（web/deps）构造注入。

与 domain/repository/protocols.py（HR 上下文，UnitOfWork 携带仓储）分文件维护：
apps 上下文是 session-per-service 的裸 SQL 仓储风格，两上下文装配风格有意不合并。
infra 裸类（internal/infrastructure/repository/apps/*）结构性满足以下 Protocol，
零运行时改动；方法集取 application/apps/*、web/deps/graph.py 及 router 对 service._repo
窥探调用（marketplace.py 的 get_marketplace_application 等）的实际使用并集。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from internal.domain.entity.access import AppGrantRow


class ApplicationRepositoryProtocol(Protocol):
    """application / application_graph / graph_version / tenant_instance 仓储端口。"""

    def create_application(
        self,
        name: str,
        owner_type: str,
        owner_id: UUID | None,
        description: str = "",
        created_by: UUID | None = None,
        flow_type: str = "workflow",
    ) -> UUID: ...

    def update_application(
        self,
        application_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        avatar_url: str | None = None,
        flow_type: str | None = None,
    ) -> None: ...

    def set_listed_in_market(self, application_id: UUID, listed: bool) -> None: ...

    def set_enabled(self, application_id: UUID, enabled: bool) -> None: ...

    def get_application_visibility(self, application_id: UUID) -> dict: ...

    def replace_application_visibility(
        self,
        application_id: UUID,
        mode: str,
        departments: list[dict],
        users: list[UUID],
    ) -> None: ...

    def get_application(self, application_id: UUID) -> dict | None: ...

    def get_marketplace_application(self, application_id: UUID) -> dict | None: ...

    def get_application_variables(self, application_id: UUID) -> list[dict[str, Any]]: ...

    def set_application_variables(
        self,
        application_id: UUID,
        variables: list[dict[str, Any]],
    ) -> None: ...

    def get_user_variables(self, application_id: UUID, user_id: UUID) -> dict[str, Any]: ...

    def set_user_variables(
        self,
        application_id: UUID,
        user_id: UUID,
        values: dict[str, Any],
    ) -> None: ...

    def set_published_graph_version(self, application_id: UUID, version: int) -> None: ...

    def list_applications(
        self,
        owner_type: str | None = None,
        owner_id: UUID | None = None,
        include_marketplace_only: bool = False,
    ) -> list[dict]: ...

    def list_marketplace_paged(
        self,
        cursor_updated_at: datetime | None = None,
        limit: int = 20,
    ) -> list[dict]: ...

    def subscribe(self, tenant_id: UUID, application_id: UUID) -> UUID: ...

    def get_instance(self, tenant_id: UUID, application_id: UUID) -> dict | None: ...

    def get_active_instance(self, tenant_id: UUID, application_id: UUID) -> dict | None:
        """仅返回 status='active' 且未过期的实例。"""
        ...

    def list_instances(self, tenant_id: UUID) -> list[dict]: ...

    def insert_graph_version(
        self,
        application_id: UUID,
        version: int,
        graph: dict,
        runtime_mode: str,
        changelog: str = "",
        created_by: UUID | None = None,
    ) -> UUID: ...

    def get_latest_graph_version(self, application_id: UUID) -> dict | None: ...

    def get_graph_version(self, application_id: UUID, version: int) -> dict | None: ...

    def list_graph_versions(self, application_id: UUID, limit: int = 50) -> list[dict]: ...

    def update_graph(
        self, application_id: UUID, graph: dict, runtime_mode: str = "dag"
    ) -> None: ...

    def list_tenant_config(self, tenant_id: UUID, application_id: UUID) -> dict[str, Any]: ...

    def upsert_tenant_config(
        self,
        tenant_id: UUID,
        application_id: UUID,
        config_key: str,
        config_value: Any,
    ) -> None: ...

    def delete_tenant_config(
        self,
        tenant_id: UUID,
        application_id: UUID,
        config_key: str,
    ) -> None: ...

    def pin_graph_version(
        self,
        tenant_id: UUID,
        application_id: UUID,
        version: int | None,
    ) -> None: ...

    def list_visible_for_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        """user 端可见应用卡片列表：租户自建 + 已开通实例，叠加 visibility 白名单/部门过滤。"""
        ...


class ModelRepositoryProtocol(Protocol):
    """model_provider / model_catalog 仓储端口。"""

    def create_provider(
        self,
        name: str,
        base_url: str,
        api_key: str,
        owner_type: str = "platform",
        owner_id: UUID | None = None,
    ) -> UUID: ...

    def update_provider(
        self,
        provider_id: UUID,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        is_enabled: bool | None = None,
    ) -> None: ...

    def delete_provider(self, provider_id: UUID) -> None: ...

    def get_provider(self, provider_id: UUID) -> dict | None: ...

    def list_providers(self, owner_type: str | None = None) -> list[dict]: ...

    def create_catalog(
        self,
        provider_id: UUID,
        model_id: str,
        display_name: str = "",
        capabilities: dict[str, Any] | None = None,
    ) -> UUID: ...

    def update_catalog(
        self,
        catalog_id: UUID,
        *,
        provider_id: UUID | None = None,
        display_name: str | None = None,
        capabilities: dict[str, Any] | None = None,
        is_enabled: bool | None = None,
    ) -> None: ...

    def delete_catalog(self, catalog_id: UUID) -> None: ...

    def get_catalog(self, catalog_id: UUID) -> dict | None: ...

    def list_catalog_full(self) -> list[dict]: ...

    def list_catalog(self) -> list[dict]: ...

    def resolve_model(self, model_id: str) -> dict | None: ...

    def resolve_model_for_tenant(self, model_id: str, tenant_id: UUID) -> dict | None: ...


class ConversationRepositoryProtocol(Protocol):
    """conversation 仓储端口（sync；async 节点用 domain/agent/repository 的 ABC）。"""

    def insert_conversation(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        application_id: UUID,
        title: str = "",
        channel: str = "api",
    ) -> UUID: ...

    def get_conversation(self, conversation_id: UUID) -> dict | None: ...

    def list_conversations_by_user(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        application_id: UUID | None = None,
        channel: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]: ...

    def list_conversations_by_application(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]: ...

    def update_title(self, conversation_id: UUID, title: str) -> None: ...

    def touch(self, conversation_id: UUID) -> None: ...

    def delete_conversation(self, conversation_id: UUID) -> None: ...


class MessageRepositoryProtocol(Protocol):
    """message 仓储端口（sync）。"""

    def append_message(
        self,
        *,
        conversation_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        application_id: UUID,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID: ...

    def list_messages_by_conversation(
        self,
        conversation_id: UUID,
        *,
        limit: int = 50,
    ) -> list[dict]: ...

    def get_message(self, message_id: UUID) -> dict | None: ...

    def delete_message(self, message_id: UUID) -> None: ...

    def clear_messages(self, conversation_id: UUID) -> None: ...


class RunRepositoryProtocol(Protocol):
    """run / node_execution 运行审计仓储端口。"""

    def insert_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        workflow_id: UUID,
        graph_snapshot: dict[str, Any],
        input_data: dict[str, Any],
        thread_id: str,
    ) -> None: ...

    def update_run_status(
        self,
        run_id: UUID,
        *,
        execute_status: str,
        output: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None: ...

    def get_run(self, run_id: UUID) -> dict | None: ...

    def get_running_by_thread(
        self,
        tenant_id: UUID,
        workflow_id: UUID,
        thread_id: str,
    ) -> dict | None: ...

    def list_runs(
        self,
        tenant_id: UUID,
        *,
        workflow_id: UUID | None = None,
        limit: int = 50,
    ) -> list[dict]: ...

    def insert_node_execution(
        self,
        *,
        execute_id: UUID,
        node_id: str,
        node_type: str,
        input_data: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        duration_ms: int | None = None,
        usage: dict[str, int] | None = None,
    ) -> None: ...

    def list_node_executions(self, execute_id: UUID) -> list[dict]: ...


class UsageRepositoryProtocol(Protocol):
    """模型用量记录仓储端口。"""

    def record_usage(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        run_id: UUID,
        node_id: str,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        user_id: UUID | None = None,
    ) -> None: ...

    def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        application_id: UUID | None = None,
        limit: int = 100,
    ) -> list[dict]: ...


class WebhookRepositoryProtocol(Protocol):
    """webhook 订阅仓储端口。"""

    def list_for_event(
        self,
        tenant_id: UUID,
        event_type: str,
        application_id: UUID | None = None,
    ) -> list[dict[str, Any]]: ...

    def create(
        self,
        *,
        tenant_id: UUID,
        event_type: str,
        url: str,
        application_id: UUID | None = None,
    ) -> UUID: ...

    def list_by_tenant(self, tenant_id: UUID) -> list[dict[str, Any]]: ...

    def delete(self, webhook_id: UUID, tenant_id: UUID) -> None: ...


class AppResourceRepositoryProtocol(Protocol):
    """统一资源（tool/prompt/skill/knowledge）仓储端口。"""

    def create_resource(
        self,
        *,
        type: str,
        name: str,
        config: dict[str, Any],
        owner_type: str = "platform",
        owner_id: UUID | None = None,
    ) -> UUID: ...

    def get_resource(self, resource_id: UUID) -> dict | None: ...

    def update_resource(
        self,
        resource_id: UUID,
        *,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        is_enabled: bool | None = None,
        is_deprecated: bool | None = None,
    ) -> None: ...

    def delete_resource(self, resource_id: UUID) -> None: ...

    def list_resources(
        self,
        *,
        type: str | None = None,
        owner_type: str | None = None,
        owner_id: UUID | None = None,
        include_disabled: bool = False,
    ) -> list[dict]: ...

    def grant(self, resource_id: UUID, tenant_id: UUID) -> None: ...

    def revoke(self, resource_id: UUID, tenant_id: UUID) -> None: ...

    def list_grants(self, resource_id: UUID) -> list[dict]: ...

    def list_tenants_granted(self, resource_id: UUID) -> list[UUID]: ...

    def resolve_for_tenant(self, resource_id: UUID, tenant_id: UUID) -> dict | None: ...

    def list_available_for_tenant(
        self,
        tenant_id: UUID,
        *,
        type: str | None = None,
    ) -> list[dict]: ...


class AuthRepositoryProtocol(Protocol):
    """应用开通授权 / 申请单仓储端口（当前消费方在 web 层与后台任务，端口先行固化）。"""

    def find_active_grant(self, tenant_id: UUID, application_id: UUID) -> dict | None: ...

    def exists_active_grant(self, tenant_id: UUID, application_id: UUID) -> bool: ...

    def get_grant(self, instance_id: UUID) -> dict | None: ...

    def list_grants_by_tenant(self, tenant_id: UUID) -> list[dict]: ...

    def list_wait_effective(self, now: datetime) -> list[dict]: ...

    def list_expired(self, now: datetime) -> list[dict]: ...

    def create_grant(self, data: dict[str, Any]) -> UUID: ...

    def update_grant_status(self, instance_id: UUID, status: str) -> None: ...

    def get_apply(self, apply_id: UUID) -> dict | None: ...

    def create_apply(self, data: dict[str, Any]) -> UUID: ...

    def list_apply_by_tenant(self, tenant_id: UUID) -> list[dict]: ...

    def list_apply_by_sales(self, sales_user_id: UUID) -> list[dict]: ...

    def list_pass_pending_apply(self) -> list[dict]: ...

    def list_pending_applies(self) -> list[dict]: ...

    def get_latest_apply(self, tenant_id: UUID, application_id: UUID) -> dict | None: ...

    def ops_dashboard_stats(self) -> dict[str, Any]: ...

    def update_apply_status(
        self,
        apply_id: UUID,
        status: str,
        audit_msg: str = "",
        contract_no: str = "",
    ) -> None: ...

    def append_audit_log(self, data: dict[str, Any]) -> None: ...


class TenantSettingsRepositoryProtocol(Protocol):
    """租户运行时配置仓储端口。"""

    def get(self, tenant_id: UUID) -> dict | None: ...

    def upsert(
        self,
        tenant_id: UUID,
        *,
        default_model_catalog_id: UUID | None,
        allowed_catalog_ids: list[UUID],
        plugin_whitelist: list[str],
    ) -> dict: ...

    def list_all(self) -> list[dict]: ...


class AppGrantRepositoryProtocol(Protocol):
    """应用授权仓储端口：application 表适配为资源授权统一查询接口。"""

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        manageable_only: bool = False,
        grant_state: str | None = None,
        grant_tenant_id: UUID | None = None,
    ) -> tuple[list[AppGrantRow], int]: ...

    def get(self, resource_id: UUID) -> AppGrantRow | None: ...

    def ids_exist(self, ids: list[UUID]) -> set[UUID]: ...

    def ids_owned(self, ids: list[UUID]) -> set[UUID]: ...

    def list_grantable(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        ids: list[UUID] | None = None,
    ) -> tuple[list[AppGrantRow], int]: ...

    def ids_grantable(self, ids: list[UUID]) -> set[UUID]: ...
