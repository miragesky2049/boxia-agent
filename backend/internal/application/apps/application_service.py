"""应用服务：应用市场、自助开通、graph 整图版本、租户 config 覆盖、运行时 graph 解析。

性能设计（对齐 coze / dify）：
- graph 运行时读取走 Redis 缓存（key=`graph:{application_id}:v{version}`）
- save_graph 写新版本后主动失效缓存 + 发布 Pub/Sub 广播
- 租户 config 一次性 mget，不再 N+1
- marketplace cursor 分页，走部分覆盖索引
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from internal.application.audit import record_audit
from internal.application.errors import AppError, ForbiddenError, NotFoundError, ValidationError
from internal.domain.cache.base import KvCache
from internal.domain.canvas.validate import validate_raw_graph
from internal.domain.canvas.variable_types import coerce as coerce_variable
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.repository.apps_protocols import ApplicationRepositoryProtocol
from internal.domain.repository.protocols import UnitOfWork
from internal.domain.storage.object_storage import ObjectStorage
from internal.infrastructure.repository.apps.app_purge_repository import (
    PostgresAppPurgeRepository,
)

logger = logging.getLogger(__name__)


def _infer_runtime_mode(graph: dict[str, Any]) -> str:
    """根据 coze 画布 JSON 推断运行模式：dag / agent_loop。

    A6：含显式 agent_loop 节点（type_code=100）即走 agent_loop；其余一律按 dag 执行。
    不再用"含 LLM 节点即 agent_loop"的启发式——LLM 节点是 dag 内的普通节点。
    """
    for node in graph.get("nodes", []) or []:
        if str(node.get("type")) == "100":
            return "agent_loop"
    return "dag"

FLOW_TYPE_WORKFLOW = "workflow"
FLOW_TYPE_CHATFLOW = "chatflow"
SUPPORTED_FLOW_TYPES = frozenset({FLOW_TYPE_WORKFLOW, FLOW_TYPE_CHATFLOW})

_BATCH_DELETE_LIMIT = 100

# ========== 变量体系（应用 / 用户 / 系统） ==========
VARIABLE_TYPES = frozenset({"string", "number", "boolean", "object", "array"})
VARIABLE_SCOPES = frozenset({"app", "user"})
_VARIABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 系统变量只读，禁止用户以同名声明普通变量
SYSTEM_VARIABLE_DEFS: dict[str, list[dict[str, str]]] = {
    FLOW_TYPE_WORKFLOW: [
        {"name": "USER_ID", "label": "当前用户 ID"},
        {"name": "RUN_ID", "label": "本次运行 ID"},
    ],
    FLOW_TYPE_CHATFLOW: [
        {"name": "USER_INPUT", "label": "本轮用户输入"},
        {"name": "CONVERSATION_NAME", "label": "会话名称"},
        {"name": "CONVERSATION_ID", "label": "会话 ID"},
        {"name": "USER_ID", "label": "当前用户 ID"},
        {"name": "RUN_ID", "label": "本次运行 ID"},
    ],
}
_RESERVED_VARIABLE_NAMES = frozenset(
    item["name"] for items in SYSTEM_VARIABLE_DEFS.values() for item in items
)


def _normalize_variables(raw: Any) -> list[dict[str, Any]]:
    """校验并规范化变量定义列表。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError("variables 必须是数组")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("每个变量定义必须是对象")
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValidationError("变量名不能为空")
        if not _VARIABLE_NAME_RE.match(name):
            raise ValidationError(f"变量名不合法：{name}（仅支持字母、数字、下划线，且不能以数字开头）")
        if name in _RESERVED_VARIABLE_NAMES:
            raise ValidationError(f"变量名 {name} 与系统变量冲突")
        if name in seen:
            raise ValidationError(f"变量名重复：{name}")
        seen.add(name)

        type_name = str(item.get("type") or "string").lower()
        if type_name not in VARIABLE_TYPES:
            raise ValidationError(f"变量 {name} 类型不合法：{type_name}")
        scope = str(item.get("scope") or "app").lower()
        if scope not in VARIABLE_SCOPES:
            raise ValidationError(f"变量 {name} 作用域不合法：{scope}")

        normalized.append({
            "name": name,
            "type": type_name,
            "default": coerce_variable(item.get("default"), type_name),
            "description": str(item.get("description") or ""),
            "scope": scope,
        })
    return normalized


def system_variables_for(flow_type: str) -> list[dict[str, str]]:
    """返回当前流程类型可见的系统变量（只读）。"""
    return list(SYSTEM_VARIABLE_DEFS.get(flow_type or FLOW_TYPE_WORKFLOW, []))

def _assert_flow_type(flow_type: str) -> None:
    """校验流程类型取值，避免脏值写入 CHECK 约束。"""
    if flow_type not in SUPPORTED_FLOW_TYPES:
        raise ValidationError(
            f"flow_type 不合法：{flow_type}，可选 {'/'.join(sorted(SUPPORTED_FLOW_TYPES))}"
        )


GRAPH_CACHE_TTL_SECONDS = 300
GRAPH_INVALIDATE_CHANNEL = "graph:invalidate"
# 草稿保存只拦截会破坏图结构的致命错误。必填项为空、表达式语法错、新节点未连线等
# 都是编辑中间态，允许保存；发布时再用全量校验拦截。
def _literal(value: Any) -> dict[str, Any]:
    """构造画布参数值：与前端保存的 {value:{type,content}} 结构一致。"""
    return {"value": {"type": "literal", "content": value}}


def _default_graph(flow_type: str, llm_model_id: str) -> dict[str, Any]:
    """按流程类型生成最小可运行画布；默认模型 ID 由组合根显式传入。

    workflow: 开始 -> 结束；
    chatflow: 开始 -> 大模型 -> 输出 -> 结束（模型留空，由用户选择）。
    """
    nodes: list[dict[str, Any]] = [
        {"id": "start_1", "type": "1", "data": {"inputs": {}, "outputs": []}},
    ]
    if flow_type == FLOW_TYPE_CHATFLOW:
        nodes.extend([
            {
                "id": "llm_1",
                "type": "3",
                "data": {
                    "inputs": {
                        "modleName": _literal(llm_model_id),
                        "systemPrompt": _literal("你是一个乐于助人的助手。"),
                        "prompt": _literal("{{start_1.output.USER_INPUT}}"),
                    },
                    "outputs": [],
                },
            },
            {
                "id": "output_1",
                "type": "13",
                "data": {
                    "inputs": {"content": _literal("{{llm_1.output.output}}")},
                    "outputs": [],
                },
            },
            {
                "id": "end_1",
                "type": "2",
                "data": {
                    "inputs": {
                        "returnType": _literal("text"),
                        "content": _literal("{{llm_1.output.output}}"),
                        # 输出节点已推送聊天气泡，结束节点不再重复输出
                        "stream": _literal(False),
                    },
                    "outputs": [],
                },
            },
        ])
        node_ids = ["start_1", "llm_1", "output_1", "end_1"]
    else:
        nodes.append({
            "id": "end_1",
            "type": "2",
            "data": {
                "inputs": {
                    "returnType": _literal("text"),
                    "content": _literal("运行完成"),
                },
                "outputs": [],
            },
        })
        node_ids = ["start_1", "end_1"]

    edges = [
        {"sourceNodeID": source, "targetNodeID": target, "sourcePortID": ""}
        for source, target in zip(node_ids, node_ids[1:])
    ]
    return {"nodes": nodes, "edges": edges}


DRAFT_BLOCKING_CODES = frozenset({
    "missing_start",
    "multiple_start",
    "dangling_edge_source",
    "dangling_edge_target",
    "convert_failed",
})
# graph JSONB 超过该阈值时只存 URI（对象存储留给后续接入）
GRAPH_INLINE_SIZE_THRESHOLD = 1024 * 1024  # 1MB


def flatten_config(graph: dict[str, Any]) -> dict[str, Any]:
    """把 graph 中每个节点的 config 展平为 {field_path: value}。"""
    result: dict[str, Any] = {}
    for node in graph.get("nodes", []) or []:
        node_id = node.get("id")
        if not node_id:
            continue
        config = node.get("config") or {}
        if not isinstance(config, dict):
            continue
        for field, value in config.items():
            path = f"graph.nodes.{node_id}.config.{field}"
            result[path] = value
    return result


def values_equal(a: Any, b: Any) -> bool:
    try:
        return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
            b, sort_keys=True, ensure_ascii=False
        )
    except TypeError:
        return a == b


def _parse_graph(raw: Any, storage: ObjectStorage | None = None) -> dict[str, Any]:
    """解析 graph JSON：若 DB 里存的是对象存储 URI 引用（A12），则从对象存储拉取真实 graph。"""
    if raw is None:
        return {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        return raw
    ref = raw.get("__graph_ref__")
    if not ref or storage is None:
        return raw
    # A12：DB 里只存了 URI，真实 graph 在对象存储里
    try:
        data = asyncio_run(storage.get(ref))
        return json.loads(data)
    except Exception as exc:  # noqa: BLE001
        logger.error("从对象存储拉取 graph 失败 ref=%s err=%s", ref, exc)
        return {}


def asyncio_run(coro: Any) -> Any:
    """在同步上下文里跑 async 协程（对象存储 get 是 async）。"""
    import asyncio as _asyncio

    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        return _asyncio.run(coro)
    # 已有 running loop（如 async router 里）：用 nest_asyncio 或直接在新线程跑
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: _asyncio.run(coro)).result()


class ApplicationService:
    def __init__(
        self,
        uow: UnitOfWork,
        app_repo: ApplicationRepositoryProtocol,
        cache: KvCache,
        object_storage: ObjectStorage | None = None,
        *,
        default_llm_model_id: str,
    ):
        """仓储/缓存/默认模型 ID 由组合根（web/deps/apps_services.py）构造注入。"""
        self._uow = uow
        self._repo: ApplicationRepositoryProtocol = app_repo
        self._cache = cache
        # A12：对象存储（可选）；未配置时为 None，大画布降级内联存 DB
        self._storage = object_storage
        self._default_llm_model_id = default_llm_model_id

    # ========== 缓存 key ==========
    @staticmethod
    def _graph_cache_key(application_id: UUID, version: int | None = None) -> str:
        suffix = f":v{version}" if version is not None else ":latest"
        return f"graph:{application_id}{suffix}"

    # ========== 市场浏览（租户端） ==========
    def list_marketplace(
        self,
        cursor_updated_at: datetime | None = None,
        limit: int = 20,
    ) -> dict:
        """cursor 分页返回市场应用。下一页用最后一条的 updated_at 作 cursor。"""
        rows = self._repo.list_marketplace_paged(cursor_updated_at, limit)
        next_cursor = rows[-1]["updated_at"].isoformat() if rows and len(rows) == limit else None
        return {"items": rows, "next_cursor": next_cursor}

    def subscribe(self, tenant_id: UUID, application_id: UUID) -> dict:
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
        # sale_mode：1=仅运营后台开通；2=市场可见+可申请（语义见 domain/entity/auth_constants）
        if int(app.get("sale_mode") or 1) != 2:
            raise ValidationError("该应用仅支持运营后台开通")

        instance_id = self._repo.subscribe(tenant_id, application_id)
        self._uow.commit()
        return {"instance_id": instance_id, "application_id": application_id}

    def list_my_apps(self, tenant_id: UUID) -> list[dict]:
        return self._repo.list_instances(tenant_id)

    def get_marketplace_application(self, application_id: UUID) -> dict | None:
        """市场应用详情（未上架/不存在返回 None；NotFoundError 语义由调用方决定）。"""
        return self._repo.get_marketplace_application(application_id)

    def get_tenant_instance(self, tenant_id: UUID, application_id: UUID) -> dict | None:
        """租户已开通实例查询（未开通返回 None）。"""
        return self._repo.get_instance(tenant_id, application_id)

    @staticmethod
    def instance_is_active(instance: dict) -> bool:
        """实例是否生效：status='active' 且未过期（expire_time 为空视为永久）。"""
        if instance.get("status") != "active":
            return False
        expire_time = instance.get("expire_time")
        return expire_time is None or expire_time > datetime.now(UTC)

    def require_runtime_instance(self, tenant_id: UUID, application_id: UUID) -> dict:
        """运行前门槛：未开通 404，已开通但失效（撤销/过期）403。"""
        instance = self._repo.get_instance(tenant_id, application_id)
        if instance is None:
            raise NotFoundError("该应用未开通或不存在")
        if not self.instance_is_active(instance):
            raise ForbiddenError("应用授权已失效")
        return instance

    def list_applications(
        self,
        owner_type: str | None = None,
        include_marketplace_only: bool = False,
    ) -> list[dict]:
        return self._repo.list_applications(
            owner_type=owner_type,
            include_marketplace_only=include_marketplace_only,
        )

    # ========== 平台管理端 ==========
    def create_platform_application(
        self,
        *,
        name: str,
        description: str = "",
        created_by: UUID | None = None,
        flow_type: str = "workflow",
        visibility_template: str = "all",
        visibility_lock: bool = False,
    ) -> UUID:
        """创建产品级应用。

        0068 默认口径：admin_scope_mode 固定 all_admin（产品级应用默认所有
        租户管理员可配租户侧可见范围）；creator_only 预留给未来租户级应用。
        """
        if not name.strip():
            raise ValidationError("应用名称不能为空")
        _assert_flow_type(flow_type)
        if visibility_template not in ("all", "whitelist"):
            raise ValidationError("visibility_template 只能是 all 或 whitelist")
        app_id = self._repo.create_application(
            name=name.strip(),
            owner_type="platform",
            owner_id=None,
            description=description,
            created_by=created_by,
            flow_type=flow_type,
            visibility_template=visibility_template,
            visibility_lock=visibility_lock,
            admin_scope_mode="all_admin",
        )
        # 新应用直接落一版可运行的最小画布，避免进编排页面对空白画布
        self.save_graph(
            app_id,
            _default_graph(flow_type, self._default_llm_model_id),
            changelog="初始化画布",
            actor_id=created_by,
        )
        self._uow.commit()
        return app_id

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
    ) -> None:
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        if flow_type is not None:
            _assert_flow_type(flow_type)
            if flow_type != app.get("flow_type"):
                self._assert_flow_switch_allowed(application_id, flow_type)
        # 0068：可见范围模板/锁定/管理范围属平台侧配置，仅产品级应用可设置
        if (
            visibility_template is not None
            or visibility_lock is not None
            or admin_scope_mode is not None
        ) and app.get("owner_type") != "platform":
            raise ValidationError("仅产品级应用可设置可见范围模板/锁定/管理范围")
        if visibility_template is not None and visibility_template not in ("all", "whitelist"):
            raise ValidationError("visibility_template 只能是 all 或 whitelist")
        if admin_scope_mode is not None and admin_scope_mode not in (
            "creator_only",
            "mgmt_unit",
            "all_admin",
        ):
            raise ValidationError("admin_scope_mode 只能是 creator_only / mgmt_unit / all_admin")
        self._repo.update_application(
            application_id,
            name=name,
            description=description,
            avatar_url=avatar_url,
            flow_type=flow_type,
            visibility_template=visibility_template,
            visibility_lock=visibility_lock,
            admin_scope_mode=admin_scope_mode,
        )
        self._uow.commit()

    # ========== 变量设置 ==========
    def get_variables(self, application_id: UUID) -> dict[str, Any]:
        """读取应用变量定义 + 当前流程类型的只读系统变量。"""
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        variables = _normalize_variables(self._repo.get_application_variables(application_id))
        return {
            "variables": variables,
            "system": system_variables_for(app.get("flow_type", FLOW_TYPE_WORKFLOW)),
        }

    def save_variables(
        self,
        application_id: UUID,
        variables: Any,
    ) -> dict[str, Any]:
        """保存变量定义；名称/类型/作用域在服务层统一校验。"""
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        normalized = _normalize_variables(variables)
        self._repo.set_application_variables(application_id, normalized)
        self._uow.commit()
        app = self._repo.get_application(application_id)
        return {
            "variables": normalized,
            "system": system_variables_for(
                (app or {}).get("flow_type", FLOW_TYPE_WORKFLOW)
            ),
        }

    def get_user_variables(
        self,
        application_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        """读取当前用户的变量取值（缺失项回退默认值）。"""
        defaults, _ = self.build_runtime_variables(application_id, user_id)
        return defaults

    def save_user_variables(
        self,
        application_id: UUID,
        user_id: UUID,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """写入用户变量实际取值；仅允许已声明为 user 作用域的变量。"""
        definitions = _normalize_variables(
            self._repo.get_application_variables(application_id)
        )
        user_defs = {item["name"]: item for item in definitions if item["scope"] == "user"}
        unknown = sorted(set(values) - set(user_defs))
        if unknown:
            raise ValidationError("未声明的用户变量：" + "、".join(unknown))
        coerced = {
            name: coerce_variable(value, user_defs[name]["type"])
            for name, value in values.items()
        }
        self._repo.set_user_variables(application_id, user_id, coerced)
        self._uow.commit()
        return self.get_user_variables(application_id, user_id)

    def build_runtime_variables(
        self,
        application_id: UUID,
        user_id: UUID | None,
    ) -> tuple[dict[str, Any], set[str]]:
        """计算运行时变量默认值池与用户变量键集合。

        应用变量每次请求用默认值初始化；用户变量优先取当前用户已持久化的值，
        缺失时回退定义默认值。运行期写入统一落在 state.globals，由 Runtime
        在成功后把用户变量键的变化写回（见 GraphRuntime._flush_user_variables）。
        """
        definitions = _normalize_variables(
            self._repo.get_application_variables(application_id)
        )
        stored_values: dict[str, Any] = {}
        if user_id is not None:
            try:
                stored_values = self._repo.get_user_variables(application_id, user_id)
            except Exception:  # noqa: BLE001
                logger.exception("读取用户变量失败 application=%s", application_id)
                stored_values = {}

        values: dict[str, Any] = {}
        user_keys: set[str] = set()
        for item in definitions:
            name = item["name"]
            if item["scope"] == "user":
                user_keys.add(name)
                values[name] = (
                    stored_values[name]
                    if name in stored_values
                    else coerce_variable(item.get("default"), item["type"])
                )
            else:
                values[name] = coerce_variable(item.get("default"), item["type"])
        return values, user_keys

    def validation_variable_scope(
        self,
        application_id: UUID,
    ) -> tuple[set[str], set[str]]:
        """收集校验用的变量声明集合（应用变量 + 当前流程类型系统变量）。

        校验链路只做未声明引用告警，读不到变量定义时降级为空集合，
        避免因变量元数据异常阻断画布保存。
        """
        try:
            info = self.get_variables(application_id)
        except Exception:  # noqa: BLE001
            logger.exception("读取变量定义失败 application=%s", application_id)
            return set(), set()

        variable_names = {
            str(item.get("name"))
            for item in info.get("variables", [])
            if item.get("name")
        }
        system_names = {
            str(item.get("name"))
            for item in info.get("system", [])
            if item.get("name")
        }
        return variable_names, system_names

    def _assert_flow_switch_allowed(
        self,
        application_id: UUID,
        next_flow_type: str,
    ) -> None:
        """切换流程类型前校验当前最新画布的图结构。

        两种形态共用同一套节点库，因此对话流 -> 工作流不因存在输出/问答/会话节点而拒绝；
        工作流 -> 对话流仍要求图中已有开始和结束节点。
        """
        if next_flow_type != FLOW_TYPE_CHATFLOW:
            return
        latest = self._repo.get_latest_graph_version(application_id)
        if latest is None:
            return
        graph = _parse_graph(latest["graph"], self._storage)
        nodes = graph.get("nodes") or []
        type_codes = {str(n.get("type")) for n in nodes}
        missing = []
        if "1" not in type_codes:
            missing.append("开始")
        if "2" not in type_codes:
            missing.append("结束")
        if missing:
            raise ValidationError(
                "当前画布缺少节点，无法切换为对话流：" + "、".join(missing)
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
        self._uow.commit()

    def set_enabled(self, application_id: UUID, enabled: bool) -> None:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        self._repo.set_enabled(application_id, enabled)
        self._uow.commit()

    # ========== 数据可见范围 v2（0068：按 (应用, 租户) 隔离） ==========
    def get_tenant_visibility(self, application_id: UUID, tenant_id: UUID) -> dict:
        """读取本租户内某应用的可见范围。

        scope 不存在时按平台 visibility_template 兜底返回（不写库）；
        返回值带 configured 字段，前端据此区分「未配置」和「已配置」。
        """
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        scope = self._repo.get_tenant_scope(application_id, tenant_id)
        if scope is None:
            return {
                "configured": False,
                "visibility": app["visibility_template"],
                "whitelist": [],
                "visibility_lock": app["visibility_lock"],
            }
        scope["configured"] = True
        scope["visibility_lock"] = app["visibility_lock"]
        return scope

    def replace_tenant_visibility(
        self,
        application_id: UUID,
        tenant_id: UUID,
        visibility: str,
        whitelist: list[dict],
    ) -> dict:
        """覆盖写入本租户可见范围。

        业务规则（0068）：
        1. visibility_lock=True 时平台锁定可见范围，租户不可修改（403）；
        2. visibility='all' 强制清空白名单；
        3. visibility='whitelist' 整体覆盖白名单（先 DELETE 再 INSERT）；
        4. scope.updated_at 由 upsert 的 DO UPDATE 分支维护。
        """
        if visibility not in ("all", "whitelist"):
            raise ValidationError("visibility 只能是 all 或 whitelist")

        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        if app["visibility_lock"]:
            raise ForbiddenError("该应用的可见范围已被平台锁定，租户不可修改")

        if visibility == "all":
            whitelist = []

        normalized: list[dict] = []
        for item in whitelist:
            subject_type = item.get("subject_type")
            if subject_type not in ("DEPARTMENT", "ROLE", "USER"):
                raise ValidationError(f"非法 subject_type: {subject_type}")
            subject_id = item.get("subject_id")
            if isinstance(subject_id, str):
                subject_id = UUID(subject_id)
            normalized.append(
                {
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "include_subtree": bool(item.get("include_subtree", False)),
                }
            )

        result = self._repo.upsert_tenant_scope(
            application_id, tenant_id, visibility, normalized
        )
        self._uow.commit()
        return result

    # ========== graph 整图版本（新 hot path） ==========
    def save_graph(
        self,
        application_id: UUID,
        graph: dict[str, Any],
        changelog: str = "",
        actor_id: UUID | None = None,
        actor_username: str = "",
    ) -> dict:
        """保存 graph：写入新版本（整图快照），写审计，失效缓存，发布广播。"""
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        if not graph.get("nodes"):
            raise ValidationError("graph 至少需要一个节点")

        # A11: 保存前结构校验；草稿只拦截致命结构错误，其余问题留给发布校验
        variable_names, system_names = self.validation_variable_scope(application_id)
        issues = validate_raw_graph(
            graph,
            variable_names=variable_names,
            system_names=system_names,
        )
        blocking = [
            i for i in issues
            if i.severity == "error" and i.code in DRAFT_BLOCKING_CODES
        ]
        if blocking:
            detail = "; ".join(i.message for i in blocking)
            raise ValidationError(f"画布结构不合法：{detail}")

        runtime_mode = _infer_runtime_mode(graph)
        latest = self._repo.get_latest_graph_version(application_id)
        previous_version = latest["version"] if latest else 0
        next_version = previous_version + 1

        # A12：大 graph 超过内联阈值时写入对象存储，DB 只存 URI 引用
        graph_size = len(json.dumps(graph, ensure_ascii=False))
        graph_to_persist: dict[str, Any] = graph
        if graph_size > GRAPH_INLINE_SIZE_THRESHOLD and self._storage is not None:
            key = f"graphs/{application_id}/v{next_version}.json"
            try:
                uri = asyncio_run(self._storage.put(
                    key,
                    json.dumps(graph, ensure_ascii=False).encode("utf-8"),
                    content_type="application/json",
                ))
                graph_to_persist = {"__graph_ref__": uri}
                logger.info(
                    "graph 超过内联阈值，已写入对象存储: app=%s size=%d uri=%s",
                    application_id, graph_size, uri,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("写入对象存储失败，降级为内联写 DB: %s", exc)
                graph_to_persist = graph
        elif graph_size > GRAPH_INLINE_SIZE_THRESHOLD:
            logger.warning(
                "graph 超过内联阈值 %d bytes 但对象存储未配置，降级为内联: app=%s size=%d",
                GRAPH_INLINE_SIZE_THRESHOLD, application_id, graph_size,
            )

        self._repo.insert_graph_version(
            application_id=application_id,
            version=next_version,
            graph=graph_to_persist,
            runtime_mode=runtime_mode,
            changelog=changelog,
            created_by=actor_id,
        )
        # 同步更新 application_graph（兼容旧读取）
        self._repo.update_graph(application_id, graph_to_persist, runtime_mode)

        # P2-7: 写审计日志（平台级操作使用 PLATFORM_TENANT_ID，audit_logs.tenant_id 不允许 NULL）
        self._uow.audit_logs.record({
            "actor_id": actor_id,
            "actor_username": actor_username,
            "action": "GRAPH_SAVE",
            "resource_type": "application",
            "resource_id": str(application_id),
            "tenant_id": PLATFORM_TENANT_ID,
            "detail": {
                "previous_version": previous_version,
                "new_version": next_version,
                "runtime_mode": runtime_mode,
                "changelog": changelog,
                "node_count": len(graph.get("nodes", [])),
                "size_bytes": graph_size,
            },
        })

        self._uow.commit()

        # 失效缓存 + 广播
        self._invalidate_graph_cache(application_id)
        return {"runtime_mode": runtime_mode, "version": next_version}

    def get_graph(self, application_id: UUID) -> dict | None:
        """读取最新版本的 graph 整图快照；没有则返回 None。"""
        latest = self._repo.get_latest_graph_version(application_id)
        if latest is None:
            return None
        graph = _parse_graph(latest["graph"], self._storage)
        app = self._repo.get_application(application_id)
        return {
            "graph": graph,
            "runtime_mode": latest.get("runtime_mode", "dag"),
            "graph_schema_version": latest.get("version", 1),
            "published_graph_version": app.get("published_graph_version") if app else None,
            "flow_type": app.get("flow_type", "workflow") if app else "workflow",
        }

    def list_graph_versions(self, application_id: UUID, limit: int = 50) -> list[dict]:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        return self._repo.list_graph_versions(application_id, limit)

    def rollback_graph(self, application_id: UUID, version: int) -> dict:
        """回滚到指定历史版本：把该版本 graph 作为新版本再写一次。"""
        record = self._repo.get_graph_version(application_id, version)
        if record is None:
            raise NotFoundError("指定 graph 版本不存在")
        graph = _parse_graph(record["graph"], self._storage)
        return self.save_graph(application_id, graph, changelog=f"回滚到版本 {version}")

    # ========== 运行时 graph（缓存 hot path） ==========
    async def get_runtime_graph(
        self,
        application_id: UUID,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """运行时 graph：Redis 缓存命中即返回；miss 回 DB，应用租户 config 覆盖。

        版本选择顺序（T13）：
        1. 租户 pinned_graph_version（最高优先级，运营兜底）
        2. application.published_graph_version（用户端实际跑的 live 版本）
        3. latest version（未发布时回退，向后兼容）
        """
        # 1. 读 latest version 兜底
        latest = self._repo.get_latest_graph_version(application_id)
        if latest is None:
            raise NotFoundError("graph 不存在")
        latest_version = latest["version"]

        # 2. 应用 published_graph_version（未发布时为 None，回退 latest）
        app = self._repo.get_application(application_id)
        published_version = app.get("published_graph_version") if app else None
        base_version = int(published_version) if published_version else latest_version

        # 3. 租户 pin 覆盖；实例存在但已失效（撤销/过期）时兜底拒绝，防绕过入口门槛
        pinned_version = base_version
        if tenant_id is not None:
            inst = self._repo.get_instance(tenant_id, application_id)
            if inst and not self.instance_is_active(inst):
                raise ForbiddenError("应用授权已失效")
            if inst and inst.get("pinned_graph_version"):
                pinned_version = int(inst["pinned_graph_version"])

        # 4. 查缓存（key 含 version，天然按版本隔离）
        cache_key = self._graph_cache_key(application_id, pinned_version)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            graph = cached.get("graph") or {}
        else:
            version_record = self._repo.get_graph_version(application_id, pinned_version)
            if version_record is None:
                raise NotFoundError(f"graph 版本 {pinned_version} 不存在")
            graph = _parse_graph(version_record["graph"], self._storage)
            await self._cache.set(
                cache_key,
                {"graph": graph, "runtime_mode": version_record["runtime_mode"]},
                ttl_seconds=GRAPH_CACHE_TTL_SECONDS,
            )

        # 5. 应用租户 config 覆盖（一次性读，不再 N+1）
        if tenant_id is not None:
            tenant_config = self._repo.list_tenant_config(tenant_id, application_id)
            graph = self._apply_config_overrides(graph, tenant_config)

        return graph

    # ========== 发布动作（draft → live 快照） ==========
    def publish_graph(
        self,
        application_id: UUID,
        *,
        actor_id: UUID | None = None,
        actor_username: str = "",
    ) -> dict:
        """把当前 latest 版本快照为 live：写 application.published_graph_version。

        - 没有任何 graph 版本时抛 NotFoundError
        - 重复发布同一版本号幂等
        """
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        latest = self._repo.get_latest_graph_version(application_id)
        if latest is None:
            raise NotFoundError("graph 不存在，请先保存画布")

        # 发布是运行态闸门：结构、必填项、表达式、未连线节点全部按 error 拦截
        latest_graph = _parse_graph(latest.get("graph"), self._storage)
        variable_names, system_names = self.validation_variable_scope(application_id)
        issues = validate_raw_graph(
            latest_graph if isinstance(latest_graph, dict) else {},
            variable_names=variable_names,
            system_names=system_names,
        )
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            detail = "; ".join(i.message for i in errors[:5])
            raise ValidationError(f"画布校验不通过，无法发布：{detail}")

        target_version = latest["version"]
        previous_version = app.get("published_graph_version")

        self._repo.set_published_graph_version(application_id, target_version)

        self._uow.audit_logs.record({
            "actor_id": actor_id,
            "actor_username": actor_username,
            "action": "GRAPH_PUBLISH",
            "resource_type": "application",
            "resource_id": str(application_id),
            "tenant_id": PLATFORM_TENANT_ID,
            "detail": {
                "previous_published_version": previous_version,
                "new_published_version": target_version,
                "runtime_mode": latest.get("runtime_mode", "dag"),
            },
        })
        self._uow.commit()
        self._invalidate_graph_cache(application_id)

        return {
            "published_version": target_version,
            "previous_published_version": previous_version,
            "runtime_mode": latest.get("runtime_mode", "dag"),
        }

    def build_effective_graph_sync(
        self,
        application_id: UUID,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """同步版本：HTTP router 里没有 async context 时用。

        直接走 DB，跳过缓存（运行时 hot path 一般是异步 router 调用）。
        """
        latest = self._repo.get_latest_graph_version(application_id)
        if latest is None:
            raise NotFoundError("graph 不存在")
        pinned_version = latest["version"]
        if tenant_id is not None:
            inst = self._repo.get_instance(tenant_id, application_id)
            if inst and not self.instance_is_active(inst):
                raise ForbiddenError("应用授权已失效")
            if inst and inst.get("pinned_graph_version"):
                pinned_version = int(inst["pinned_graph_version"])

        version_record = self._repo.get_graph_version(application_id, pinned_version)
        if version_record is None:
            raise NotFoundError(f"graph 版本 {pinned_version} 不存在")
        graph = _parse_graph(version_record["graph"], self._storage)

        if tenant_id is not None:
            tenant_config = self._repo.list_tenant_config(tenant_id, application_id)
            graph = self._apply_config_overrides(graph, tenant_config)
        return graph

    @staticmethod
    def _apply_config_overrides(graph: dict[str, Any], tenant_config: dict[str, Any]) -> dict[str, Any]:
        """把 tenant_config 里的 key 形如 graph.nodes.{node_id}.config.{field} 覆盖到 graph 上。"""
        if not tenant_config:
            return graph
        nodes_copy: list[dict[str, Any]] = []
        for node in graph.get("nodes", []):
            nodes_copy.append({**node, "config": {**(node.get("config") or {})}})

        for path, value in tenant_config.items():
            parts = path.split(".")
            if len(parts) < 5 or parts[0] != "graph" or parts[1] != "nodes" or parts[3] != "config":
                continue
            node_id = parts[2]
            field = ".".join(parts[4:])
            for node in nodes_copy:
                if node.get("id") == node_id:
                    node["config"][field] = value
                    break
        return {**graph, "nodes": nodes_copy}

    # ========== 租户 config 覆盖（替代旧 pin_field） ==========
    def set_tenant_config(
        self,
        tenant_id: UUID,
        application_id: UUID,
        config_key: str,
        config_value: Any,
    ) -> None:
        if self._repo.get_application(application_id) is None:
            raise NotFoundError("应用不存在")
        self._repo.upsert_tenant_config(tenant_id, application_id, config_key, config_value)
        self._uow.commit()
        self._invalidate_graph_cache(application_id)

    def delete_tenant_config(
        self,
        tenant_id: UUID,
        application_id: UUID,
        config_key: str,
    ) -> None:
        self._repo.delete_tenant_config(tenant_id, application_id, config_key)
        self._uow.commit()
        self._invalidate_graph_cache(application_id)

    def pin_graph_version(
        self,
        tenant_id: UUID,
        application_id: UUID,
        version: int | None,
    ) -> None:
        """租户锁定整图版本；version=None 回到 latest。"""
        if version is not None:
            record = self._repo.get_graph_version(application_id, version)
            if record is None:
                raise NotFoundError(f"graph 版本 {version} 不存在")
        self._repo.pin_graph_version(tenant_id, application_id, version)
        self._uow.commit()
        self._invalidate_graph_cache(application_id)

    # ========== user 端可见性 ==========
    def list_visible_apps_for_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        keyword: str | None = None,
    ) -> list[dict]:
        """当前用户可见应用 = 本租户自建 + 已开通的产品级实例，叠加 visibility 白名单/部门过滤。"""
        return self._repo.list_visible_for_user(tenant_id, user_id, keyword)

    def get_visible_app_for_user(
        self,
        application_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> dict | None:
        """单个应用：用户是否可见。返回卡片 dict 或 None。"""
        items = self.list_visible_apps_for_user(tenant_id, user_id)
        return next((it for it in items if it["id"] == str(application_id)), None)

    def assert_user_can_view(
        self,
        application_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> dict:
        """用户访问应用前的鉴权闸门：不可见抛 NotFoundError。"""
        app = self.get_visible_app_for_user(application_id, tenant_id, user_id)
        if app is None:
            raise NotFoundError("应用不存在或未开通")
        return app

    # ========== 缓存失效 + 广播 ==========
    def _invalidate_graph_cache(self, application_id: UUID) -> None:
        """失效本地 + 广播其它节点。同步上下文里 fire-and-forget，吞掉异常不阻塞主流程。"""
        import asyncio
        import logging

        async def _run() -> None:
            # 清 latest 和所有已缓存 version
            await self._cache.delete(self._graph_cache_key(application_id, None))
            await self._cache.publish(GRAPH_INVALIDATE_CHANNEL, str(application_id))

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # threadpool 线程里没有 running loop：fire-and-forget，不阻塞
            try:
                asyncio.run(_run())
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning("graph cache invalidate failed: %s", exc)
            return
        loop.create_task(_run())

    # ========== 应用删除（硬删除 + 关联数据级联） ==========
    def delete_application(
        self,
        application_id: UUID,
        *,
        confirm: bool,
        actor_id: UUID,
        actor_username: str,
        actor_role_code: str,
        ip: str | None = None,
        user_agent: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """物理删除平台应用及其全部关联数据（不可逆）。

        仅平台 superadmin，confirm=True 为二次确认位；租户自有应用不在此删除。
        返回删除计数与审计 id。
        """
        if actor_role_code != "superadmin":
            raise ForbiddenError("应用删除仅限平台 superadmin")
        if not confirm:
            raise ValidationError("删除应用为不可逆操作，需显式二次确认")
        app = self._repo.get_application(application_id)
        if app is None:
            raise NotFoundError("应用不存在")
        if app.get("owner_type") != "platform":
            raise ValidationError("管理端仅支持删除平台应用")

        try:
            purge = PostgresAppPurgeRepository(self._uow.session)
            purge.configure_timeouts()
            snapshot = purge.snapshot(application_id)
            deleted = purge.purge_business_data(application_id)
            audit_id = record_audit(
                self._uow,
                action="app.deleted",
                actor_id=actor_id,
                actor_username=actor_username,
                resource_type="app",
                resource_id=str(application_id),
                ip=ip,
                user_agent=user_agent,
                detail={
                    "name": app["name"],
                    "flow_type": app.get("flow_type"),
                    "reason": reason,
                    "snapshot": snapshot,
                    "deleted": deleted,
                },
                tenant_id=None,
            )
            # 审计先落库，再删 application 行触发全部 CASCADE
            self._uow.session.flush()
            purge.delete_application_row(application_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return {
            "application_id": str(application_id),
            "name": app["name"],
            "audit_id": str(audit_id),
            "deleted": deleted,
        }

    def batch_delete_applications(
        self,
        application_ids: list[UUID],
        *,
        confirm: bool,
        actor_id: UUID,
        actor_username: str,
        actor_role_code: str,
        ip: str | None = None,
        user_agent: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """批量物理删除应用：逐应用独立事务，部分成功，返回每项明细。"""
        if actor_role_code != "superadmin":
            raise ForbiddenError("应用删除仅限平台 superadmin")
        if not confirm:
            raise ValidationError("删除应用为不可逆操作，需显式二次确认")
        unique_ids = list(dict.fromkeys(application_ids))
        if not unique_ids:
            raise ValidationError("待删除应用列表不能为空")
        if len(unique_ids) > _BATCH_DELETE_LIMIT:
            raise ValidationError(f"单次批量删除不能超过 {_BATCH_DELETE_LIMIT} 个应用")

        items: list[dict[str, Any]] = []
        succeeded = 0
        for application_id in unique_ids:
            name: str | None = None
            existing = self._repo.get_application(application_id)
            if existing is not None:
                name = existing["name"]
            try:
                result = self.delete_application(
                    application_id,
                    confirm=True,
                    actor_id=actor_id,
                    actor_username=actor_username,
                    actor_role_code=actor_role_code,
                    ip=ip,
                    user_agent=user_agent,
                    reason=reason,
                )
            except AppError as exc:
                items.append(
                    {
                        "application_id": str(application_id),
                        "name": name,
                        "success": False,
                        "audit_id": None,
                        "error_code": exc.code,
                        "error": exc.message,
                    }
                )
                continue
            except Exception:
                logger.exception("批量删除应用失败 application_id=%s", application_id)
                items.append(
                    {
                        "application_id": str(application_id),
                        "name": name,
                        "success": False,
                        "audit_id": None,
                        "error_code": "INTERNAL_ERROR",
                        "error": "删除失败，请稍后重试",
                    }
                )
                continue
            succeeded += 1
            items.append(
                {
                    "application_id": result["application_id"],
                    "name": result["name"],
                    "success": True,
                    "audit_id": result["audit_id"],
                    "error_code": None,
                    "error": None,
                }
            )
        return {
            "total": len(unique_ids),
            "succeeded": succeeded,
            "failed": len(unique_ids) - succeeded,
            "items": items,
        }

    # ========== 复制应用 ==========
    def copy_application(
        self,
        application_id: UUID,
        *,
        actor_id: UUID | None = None,
        actor_username: str = "",
    ) -> dict[str, Any]:
        """复制产品级应用的全部定义数据为一个新应用。

        复制范围（应用「定义」层）：
        - application 主行（owner_type/owner_id/avatar_url/description/flow_type/
          variables/visibility_lock/visibility_template/admin_scope_mode/
          sale_mode/support_trial/doc_url/ext_json）
        - application_graph 当前整图
        - application_graph_version 最新一版（作为副本的 v1）

        不复制（运行态/租户关系数据）：
        - app_visibility_scope / whitelist（v2 可见范围按 (应用, 租户) 隔离，
          属租户侧配置；副本新租户按继承的 visibility_template 走兜底）
        - tenant_application_instance、tenant_application_config、application_user_variable
        - conversation、message、run、run_node_execution、tenant_usage_ledger
        - event_webhook、resource_grants、entitlement_plan_item、application_apply

        副本默认 is_enabled=False、is_listed_in_market=False、published_graph_version=NULL，
        由运营在副本上自行启用/上架/发布。名称格式：「{原名}的副本」或「{原名}的副本N」。
        """
        source = self._repo.get_full_application(application_id)
        if source is None:
            raise NotFoundError("应用不存在")
        if source.get("owner_type") != "platform":
            raise ValidationError("仅产品级应用支持复制")

        source_name = str(source.get("name") or "").strip()
        if not source_name:
            raise ValidationError("源应用名称为空，无法复制")

        existing_copies = self._repo.count_copies(source_name)
        if existing_copies == 0:
            new_name = f"{source_name}的副本"
        else:
            new_name = f"{source_name}的副本{existing_copies + 1}"
        # 名称长度兜底（application.name 列长度 200）
        if len(new_name) > 200:
            new_name = new_name[:197] + "..."

        try:
            new_app_id = self._repo.insert_application_row({
                "owner_type": "platform",
                "owner_id": None,
                "name": new_name,
                "avatar_url": source.get("avatar_url"),
                "description": source.get("description", ""),
                "is_enabled": False,
                "is_listed_in_market": False,
                "sale_mode": source.get("sale_mode", 1),
                "support_trial": source.get("support_trial", False),
                "doc_url": source.get("doc_url", ""),
                "ext_json": source.get("ext_json") or {},
                "visibility_lock": source.get("visibility_lock", False),
                "visibility_template": source.get("visibility_template", "all"),
                "admin_scope_mode": source.get("admin_scope_mode", "all_admin"),
                "published_graph_version": None,
                "flow_type": source.get("flow_type", "workflow"),
                "variables": source.get("variables") or [],
                "created_by": actor_id,
            })

            # 复制当前 graph（application_graph 行）
            graph_row = self._repo.get_graph_row(application_id)
            runtime_mode = "dag"
            graph_payload: dict[str, Any] = {}
            if graph_row is not None:
                graph_payload = _parse_graph(graph_row.get("graph"), self._storage) or {}
                runtime_mode = graph_row.get("runtime_mode") or "dag"
                if graph_payload:
                    self._repo.insert_graph_row(new_app_id, graph_payload, runtime_mode)

            # 复制最新 graph 版本（作为副本的 v1，changelog 标注来源）
            latest_version = self._repo.get_latest_graph_version_row(application_id)
            if latest_version is not None and graph_payload:
                self._repo.insert_graph_version_row(
                    application_id=new_app_id,
                    version=1,
                    graph=graph_payload,
                    runtime_mode=latest_version.get("runtime_mode") or runtime_mode,
                    changelog=f"复制自应用 {source_name}（源版本 v{latest_version.get('version')}）",
                    created_by=actor_id,
                )

            # v2 可见范围（app_visibility_scope）属租户侧配置，随副本新租户订阅按模板兜底，不复制

            # 写审计日志
            self._uow.audit_logs.record({
                "actor_id": actor_id,
                "actor_username": actor_username,
                "action": "APP_COPY",
                "resource_type": "application",
                "resource_id": str(new_app_id),
                "tenant_id": PLATFORM_TENANT_ID,
                "detail": {
                    "source_application_id": str(application_id),
                    "source_name": source_name,
                    "new_application_id": str(new_app_id),
                    "new_name": new_name,
                    "flow_type": source.get("flow_type"),
                },
            })

            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise

        return {
            "application_id": str(new_app_id),
            "name": new_name,
            "source_application_id": str(application_id),
        }
