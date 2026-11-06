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

from internal.domain.entity.entitlement import EntitlementItem, EntitlementView
from internal.domain.entity.entitlement_plan import EntitlementPlan


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
        visibility_template: str = "all",
        visibility_lock: bool = False,
        admin_scope_mode: str = "creator_only",
    ) -> UUID: ...

    def update_application(
        self,
        application_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        avatar_url: str | None = None,
        flow_type: str | None = None,
        visibility_template: str | None = None,
        visibility_lock: bool | None = None,
        admin_scope_mode: str | None = None,
    ) -> None: ...

    def set_listed_in_market(self, application_id: UUID, listed: bool) -> None: ...

    def set_enabled(self, application_id: UUID, enabled: bool) -> None: ...

    # ========== v2 可见范围（0068：按 (application, tenant) 隔离） ==========
    def get_tenant_scope(self, application_id: UUID, tenant_id: UUID) -> dict | None:
        """读取某应用在某租户的可见范围配置；无记录返回 None。"""
        ...

    def upsert_tenant_scope(
        self,
        application_id: UUID,
        tenant_id: UUID,
        visibility: str,
        whitelist: list[dict],
    ) -> dict:
        """整体覆盖写入可见范围：upsert scope 行 + 清空并重写 whitelist，返回 {id, visibility, whitelist}。"""
        ...

    def ensure_scope_on_subscribe(self, application_id: UUID, tenant_id: UUID) -> None:
        """按平台 visibility_template 初始化 scope（已存在则跳过）；一期不显式调用，预留给未来钩子。"""
        ...

    def list_subscribed_apps_for_admin(self, tenant_id: UUID) -> list[dict]:
        """租户已订阅（生效中）的产品级应用列表，含 visibility_lock/visibility_template。"""
        ...

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
        """user 端可见应用卡片列表：租户自建 + 已开通实例，叠加 v2 可见范围（scope/白名单/模板兜底）过滤。"""
        ...

    def count_copies(self, source_name: str) -> int:
        """统计以「{source_name}的副本」或「{source_name}的副本N」命名的应用数（用于生成副本序号）。"""
        ...

    def get_full_application(self, application_id: UUID) -> dict | None:
        """读取应用主行全部列（复制用），与 get_application 列集不同。"""
        ...

    def insert_application_row(self, data: dict[str, Any]) -> UUID:
        """按显式字段集插入 application 行（复制路径专用，不复用 create_application 的精简列）。"""
        ...

    def get_graph_row(self, application_id: UUID) -> dict | None:
        """读取 application_graph 当前整行（复制用）。"""
        ...

    def insert_graph_row(self, application_id: UUID, graph: dict, runtime_mode: str) -> None:
        """向 application_graph 写入一行（复制路径专用）。"""
        ...

    def get_latest_graph_version_row(self, application_id: UUID) -> dict | None:
        """读取 application_graph_version 最新整行（复制用）。"""
        ...

    def insert_graph_version_row(
        self,
        application_id: UUID,
        version: int,
        graph: dict,
        runtime_mode: str,
        changelog: str = "",
        created_by: UUID | None = None,
    ) -> UUID:
        """向 application_graph_version 写入一行（复制路径专用，与 insert_graph_version 等价但显式命名）。"""
        ...


class AdminScopeRepositoryProtocol(Protocol):
    """app_admin_scope（应用 ↔ 管理单元）仓储端口（0069 二期）。"""

    def list_scopes(self, application_id: UUID, tenant_id: UUID) -> list[dict]:
        """列出应用关联的管理单元（JOIN mgmt_units 隐式过滤孤儿，带名称）。"""
        ...

    def list_unit_ids(self, application_id: UUID, tenant_id: UUID) -> list[UUID]:
        """列出应用关联的管理单元 ID 集合。"""
        ...

    def unit_exists(self, tenant_id: UUID, mgmt_unit_id: UUID) -> bool:
        """校验管理单元存在且属于本租户。"""
        ...

    def add_scope(
        self, application_id: UUID, tenant_id: UUID, mgmt_unit_id: UUID
    ) -> None:
        """新增关联（ON CONFLICT DO NOTHING，幂等）。"""
        ...

    def remove_scope(
        self, application_id: UUID, tenant_id: UUID, mgmt_unit_id: UUID
    ) -> None:
        """解除关联（不存在时静默）。"""
        ...

    def list_unit_ids_by_app(self, tenant_id: UUID) -> dict[UUID, set[UUID]]:
        """租户维度一次性取 {application_id: {mgmt_unit_id}}，供"我管理的应用"过滤。"""
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
        user_id: UUID | None = None,
    ) -> None: ...

    def update_run_status(
        self,
        run_id: UUID,
        *,
        execute_status: str,
        output: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None: ...

    def update_run_interrupt(self, run_id: UUID, payload: dict[str, Any]) -> None: ...

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
        user_id: UUID | None = None,
        limit: int = 50,
    ) -> list[dict]: ...

    def list_interrupted(
        self,
        tenant_id: UUID,
        workflow_id: UUID,
        *,
        assignee_role: str | None = None,
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
        review_status: str = "approved",
        created_by: UUID | None = None,
    ) -> UUID: ...

    def review_resource(
        self,
        resource_id: UUID,
        *,
        review_status: str,
        reviewer_id: UUID | None,
        remark: str = "",
    ) -> None: ...

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
        review_status: str | None = None,
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

    def claim_apply(self, apply_id: UUID, sales_user_id: UUID) -> bool:
        """CAS 认领：仅 SUBMITTED 行更新为 HANDLING 并写入销售归属，返回是否成功。"""
        ...

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


class EntitlementRepositoryProtocol(Protocol):
    """权益仓储端口：统一读写 tenant_application_instance（app）与 tenant_resource_entitlement（资源）。"""

    def list_by_tenant(
        self,
        tenant_id: UUID,
        object_type: str | None,
        status: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[EntitlementView], int]:
        """租户权益分页；status 按持久列过滤，视图状态另经时间计算。"""
        ...

    def list_tenants_by_object(
        self, object_type: str, object_id: UUID, page: int, page_size: int
    ) -> tuple[list[dict], int]:
        """对象反查持有权益的租户（分页）。"""
        ...

    def get(self, tenant_id: UUID, object_type: str, object_id: UUID) -> EntitlementView | None:
        """单条权益视图；无权益返回 None。"""
        ...

    def describe_object(self, object_type: str, object_id: UUID) -> dict | None:
        """对象元数据 {id, name, is_deprecated}；对象不存在返回 None。"""
        ...

    def grant(
        self,
        tenant_id: UUID,
        item: EntitlementItem,
        *,
        auth_source: str,
        auth_type: str,
        start_time: datetime | None,
        expire_time: datetime | None,
        quota: dict[str, Any],
        remark: str,
        granted_by: UUID | None,
    ) -> UUID:
        """开通权益；已存在（含 revoked/expired）则整行覆盖恢复，返回权益行 ID。"""
        ...

    def revoke(self, tenant_id: UUID, object_type: str, object_id: UUID, remark: str = "") -> bool:
        """软失效：置 status='revoked' 并记录原因，不删行；返回是否有行被更新。"""
        ...

    def purge(self, tenant_id: UUID, object_type: str, object_id: UUID) -> int:
        """物理删除权益行（退租/合规，接口由 P3-6 暴露），返回删除条数。"""
        ...

    def purge_role_grants(self, tenant_id: UUID, object_type: str, object_id: UUID) -> int:
        """物理删除该权益支撑的 resource_grants 角色授权行（purge 级联），返回删除条数。"""
        ...

    def list_resource_wait_effective(self, now: datetime) -> list[dict]:
        """tenant_resource_entitlement 中 wait_effect 且已过 start_time 的行（P3-1 生命周期流转）。"""
        ...

    def list_resource_expired(self, now: datetime) -> list[dict]:
        """tenant_resource_entitlement 中 active 且已过 expire_time 的行（P3-1 生命周期流转）。"""
        ...

    def revoke_grace_overdue(self, cutoff: datetime) -> int:
        """宽限期超期落库流转（P3-11）：双存储 expired 且 expire_time <= cutoff → revoked，返回影响行数。"""
        ...

    def update_entitlement_status(self, entitlement_id: UUID, status: str) -> None:
        """更新 tenant_resource_entitlement 行持久状态（wait_effect→active / active→expired）。"""
        ...

    def list_expiring(self, now: datetime, window_days: int) -> list[dict]:
        """window_days 天内到期的有效权益行 {object_type, object_id, tenant_id, name, expire_time}（P3-2 提醒扫描）。"""
        ...

    def affected_role_grants(
        self, tenant_id: UUID, object_type: str, object_id: UUID
    ) -> list[dict]:
        """该权益支撑的角色授权明细 [{role_id, role_name, subject_type}]，供 D-3 影响提示。"""
        ...


class EntitlementPlanRepositoryProtocol(Protocol):
    """套餐模板仓储端口：entitlement_plan + entitlement_plan_item 定义行读写（P3-3）。"""

    def get(self, plan_id: UUID) -> EntitlementPlan | None:
        """模板聚合（含条目）；不存在返回 None。"""
        ...

    def get_by_code(self, code: str) -> EntitlementPlan | None:
        """按唯一 code 取模板，供创建前重复校验。"""
        ...

    def list_page(
        self, keyword: str | None, page: int, page_size: int
    ) -> tuple[list[EntitlementPlan], int]:
        """模板分页（含条目），code/name 模糊过滤。"""
        ...

    def create(
        self,
        *,
        code: str,
        name: str,
        description: str,
        auth_type: str,
        duration_days: int | None,
        quota: dict[str, Any],
        items: tuple[EntitlementItem, ...],
    ) -> UUID:
        """新建模板与条目集合，返回模板 ID；调用方负责提交。"""
        ...

    def delete(self, plan_id: UUID) -> bool:
        """物理删除模板（条目行外键级联清除）；返回是否有行被删除。"""
        ...


class ResourceTypeCatalogRepositoryProtocol(Protocol):
    """资源类型注册表端口：resource_type_catalog 读侧（P3-5）。

    类型集合的唯一事实源：新增资源类型 = 目录插一行，免改迁移与 CHECK；
    服务层写路径以 list_active 为校验依据。app 不属于资源类型（权益对象
    固定类型），由服务层单独放行，不经本目录。
    """

    def list_active(self) -> list[str]:
        """启用中的资源类型 code，按 sort_order 稳定排序。"""
        ...


class EntitlementRequestLogRepositoryProtocol(Protocol):
    """幂等请求去重仓储端口：entitlement_request_log（P3-8）。

    生命周期：processing → completed / failed；failed 行可被同键重试接管（version+1）。
    状态以 JSONB result 承载首次结果，重放时原样返回。
    """

    def try_begin(self, request_id: str, tenant_id: UUID, action: str, payload: dict) -> bool:
        """INSERT ON CONFLICT DO NOTHING 占位；True=本请求获得执行权，False=键已存在。"""
        ...

    def get(self, request_id: str) -> dict | None:
        """取 {request_id, status, version, result}；不存在返回 None。"""
        ...

    def retry_begin(self, request_id: str) -> None:
        """failed 行接管重试：status 置回 processing、version+1、清空 result。"""
        ...

    def mark_completed(self, request_id: str, result: dict) -> None:
        """写入首次执行结果并置 completed、记录 completed_at。"""
        ...

    def mark_failed(self, request_id: str) -> None:
        """执行异常后标记 failed，保留 payload 供排查。"""
        ...
