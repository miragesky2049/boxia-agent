"""智能体配置表单 ⇄ 画布 agent_loop 节点 config 的双向映射（0074 PRD F2，20261107）。

设计约束（画布 = 唯一事实源，不新增配置表）：
- 读：调用方先用 convert.find_agent_loop_config 拿"运行时口径"config（与
  AgentLoopNodeHandler / chat 通道判定 use_canvas / 应用详情卡片同一口径），
  本模块只做缺省补齐（node_config_to_form）；
- 写：apply_form_to_node 直接改原始画布 JSON 中 agent_loop 节点的
  data.inputs，采用与 _default_graph / 前端画布一致的 literal 脱壳形态
  {value: {type: "literal", content: ...}}，保证转换层可逆；
- 键名沿用 coze camelCase；datasets/memory/reasoningMode/openingRemarks 等
  为本 PRD 扩展键，agent 型配置面禁止写出 snake_case 旧键。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from internal.domain.agent.memory import (
    MAX_MAX_MEMORIES,
    MAX_RECALL_TOPK,
    MIN_MAX_MEMORIES,
    MIN_RECALL_TOPK,
    parse_long_term_config,
    parse_memory_config,
)

AGENT_NODE_TYPE_CODE = "100"

MAX_SYSTEM_PROMPT_LENGTH = 4000
MAX_OPENING_REMARKS_LENGTH = 2000
MAX_SUGGESTED_QUESTIONS = 4
# 知识库上限（PRD F5.4）：过多检索工具会让模型路由困难
MAX_DATASETS = 5
DATASET_MODES = ("onDemand", "always")
DEFAULT_DATASET_TOP_K = 5
MAX_DATASET_TOP_K = 20
# 工具轮次上限：防单 run 成本失控（PRD F11）
MAX_TOOL_ROUNDS_LIMIT = 50
REASONING_MODES = ("react", "planExecuteReflect")
# 检索工具名保留前缀（agent_loop 节点按此合成，用户工具不得占用）
KNOWLEDGE_TOOL_NAME_PREFIX = "knowledge_search_"
# 0074 PRD F7.1：工作流即工具合成名 workflow_N（同配置序），前缀同样保留
WORKFLOW_TOOL_NAME_PREFIX = "workflow_"
MAX_WORKFLOWS = 5
# M4-c PRD F14.2：智能体即工具合成名 agent_{slug}，前缀同样保留（用户工具不得占用）
AGENT_TOOL_NAME_PREFIX = "agent_"
# 批末 review #5：hand_back 为内核保留的接管归位工具名（graph agent_loop 节点注入），
# 与 agent_loop.HAND_BACK_TOOL_NAME 保持一致；用户自定义 toolName 撞名会导致归位注入被跳过
HAND_BACK_TOOL_NAME = "hand_back"
# M4-c PRD F14.1：协作挂载形态——delegate 工具化委派 / handoff 接管式移交
SUB_AGENT_MODES = ("delegate", "handoff")
DEFAULT_SUB_AGENT_MODE = "delegate"
# delegate+handoff 合计上限（U7 裁决口径）：过多专家同样让模型路由困难
MAX_SUB_AGENTS = 5
# 0074 PRD F6：MCP server 数与单 server 勾选工具数上限（防 spec 膨胀）
MAX_MCP_SERVERS = 5
MAX_MCP_TOOLS_PER_SERVER = 20
# M4-b F17.3②：条目级调用超时（秒，表单严格整数校验；运行期兜底解析在 agent_loop）
MIN_MCP_TIMEOUT_SECONDS = 1
MAX_MCP_TIMEOUT_SECONDS = 300
# M4-b F17.4：会话保持档位；缺省 run 级（会话档池为 P1，本批仅落键与校验）
MCP_SESSION_SCOPES = ("run", "conversation")
DEFAULT_MCP_SESSION_SCOPE = "run"


def find_agent_loop_node(graph: dict[str, Any]) -> dict[str, Any] | None:
    """在原始画布 JSON 中定位 agent_loop 节点（数字类型码形态）。"""
    for node in graph.get("nodes") or []:
        if str(node.get("type")) == AGENT_NODE_TYPE_CODE:
            return node
    return None


def node_config_to_form(node_cfg: dict[str, Any]) -> dict[str, Any]:
    """把运行时口径节点 config 补齐为配置面表单（GET /agent-config 响应体）。"""
    raw_memory = node_cfg.get("memory")
    memory = parse_memory_config(raw_memory)
    return {
        "systemPrompt": str(node_cfg.get("systemPrompt") or ""),
        "modleName": str(node_cfg.get("modleName") or ""),
        "maxToolRounds": _positive_int_or_default(node_cfg.get("maxToolRounds"), 10),
        "openingRemarks": str(node_cfg.get("openingRemarks") or ""),
        "suggestedQuestions": _string_list(node_cfg.get("suggestedQuestions")),
        "tools": _dict_list(node_cfg.get("tools")),
        "datasets": _dict_list(node_cfg.get("datasets")),
        "mcpServers": _dict_list(node_cfg.get("mcpServers")),
        # M4-b F17.4：会话档位恒携带（历史图无此键时补默认 run），表单⇄config 口径一致
        "mcpSession": _mcp_session_form(node_cfg.get("mcpSession")),
        "workflows": _dict_list(node_cfg.get("workflows")),
        # M4-c F14.1：智能体协作挂载恒携带（历史图无此键补空列表），表单⇄config 口径一致
        "subAgents": _dict_list(node_cfg.get("subAgents")),
        # M4 PRD F16.1：longTerm 键组恒携带（默认关闭），表单⇄config 口径与短记忆一致
        "memory": {"shortTerm": memory, "longTerm": parse_long_term_config(raw_memory)},
        "reasoningMode": (
            "planExecuteReflect"
            if str(node_cfg.get("reasoningMode")) == "planExecuteReflect"
            else "react"
        ),
        "plannerPrompt": _optional_str(node_cfg.get("plannerPrompt")),
        "reflectorPrompt": _optional_str(node_cfg.get("reflectorPrompt")),
        "maxReflectRounds": _optional_positive_int(node_cfg.get("maxReflectRounds")),
        "sensitiveTools": _dict_list(node_cfg.get("sensitiveTools")),
        # 0074 PRD F9（M3）：视觉开关，仅当所选模型 supports_vision 时运行侧才放行图片
        "visionEnabled": bool(node_cfg.get("visionEnabled")),
        "tokenBudget": _optional_positive_int(node_cfg.get("tokenBudget")),
    }


def validate_form(
    form: dict[str, Any],
    *,
    long_term_admin_available: bool = True,
    self_application_id: str | None = None,
) -> list[str]:
    """校验配置表单，返回问题清单（空列表 = 通过）。契约式：调用方决定抛错形态。

    long_term_admin_available：M4 PRD F16.6 隐私硬条件的部署开关——用户端"我的记忆"
    管理面未部署的实例必须拒绝开启 longTerm（组合根从 settings 传入）。
    self_application_id：当前被配置应用 ID（M4-c F14.1）——传入时拒绝 subAgents
    自引用；同租户可见/已发布/flow_type 属 DB 事实，配置面不做在线核验，
    运行期由 AgentToolService.describe 兜底跳过（与 workflows 同口径）。
    """
    issues: list[str] = []

    system_prompt = str(form.get("systemPrompt") or "").strip()
    if not system_prompt:
        issues.append("systemPrompt 不能为空")
    elif len(system_prompt) > MAX_SYSTEM_PROMPT_LENGTH:
        issues.append(f"systemPrompt 超长（最多 {MAX_SYSTEM_PROMPT_LENGTH} 字）")

    if not str(form.get("modleName") or "").strip():
        issues.append("modleName 不能为空（请为智能体选择模型）")

    max_rounds = form.get("maxToolRounds")
    if max_rounds is not None:
        rounds_int = _as_positive_int(max_rounds)
        if rounds_int is None or rounds_int > MAX_TOOL_ROUNDS_LIMIT:
            issues.append(f"maxToolRounds 需为 1~{MAX_TOOL_ROUNDS_LIMIT} 的整数")

    opening = str(form.get("openingRemarks") or "")
    if len(opening) > MAX_OPENING_REMARKS_LENGTH:
        issues.append(f"openingRemarks 超长（最多 {MAX_OPENING_REMARKS_LENGTH} 字）")

    questions = form.get("suggestedQuestions") or []
    if len(questions) > MAX_SUGGESTED_QUESTIONS:
        issues.append(f"suggestedQuestions 最多 {MAX_SUGGESTED_QUESTIONS} 条")

    if str(form.get("reasoningMode") or "react") not in REASONING_MODES:
        issues.append("reasoningMode 只能是 react 或 planExecuteReflect")

    datasets = form.get("datasets") or []
    if len(datasets) > MAX_DATASETS:
        issues.append(f"datasets 最多 {MAX_DATASETS} 个")
    for index, entry in enumerate(datasets):
        if not isinstance(entry, dict) or not str(entry.get("datasetId") or "").strip():
            issues.append(f"datasets[{index}] 缺少 datasetId")
            continue
        if str(entry.get("mode") or "onDemand") not in DATASET_MODES:
            issues.append(f"datasets[{index}] mode 只能是 onDemand 或 always")
        top_k = entry.get("topK")
        if top_k is not None:
            top_k_int = _as_positive_int(top_k)
            if top_k_int is None or top_k_int > MAX_DATASET_TOP_K:
                issues.append(f"datasets[{index}] topK 需为 1~{MAX_DATASET_TOP_K} 的整数")

    tools = form.get("tools") or []
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict) or not str(tool.get("name") or "").strip():
            issues.append(f"tools[{index}] 缺少 name")
            continue
        tool_name = str(tool.get("name"))
        if tool_name.startswith(KNOWLEDGE_TOOL_NAME_PREFIX):
            issues.append(
                f"tools[{index}] 名称不得以 {KNOWLEDGE_TOOL_NAME_PREFIX} 开头（知识库检索工具保留前缀）"
            )
        elif tool_name.startswith(WORKFLOW_TOOL_NAME_PREFIX):
            issues.append(
                f"tools[{index}] 名称不得以 {WORKFLOW_TOOL_NAME_PREFIX} 开头（工作流工具保留前缀）"
            )
        elif tool_name.startswith(AGENT_TOOL_NAME_PREFIX):
            issues.append(
                f"tools[{index}] 名称不得以 {AGENT_TOOL_NAME_PREFIX} 开头（智能体委派工具保留前缀）"
            )

    # 0074 PRD F6：MCP server 快照结构校验（url 非空即可，SSRF 在 discover/运行时判）
    mcp_servers = form.get("mcpServers") or []
    if len(mcp_servers) > MAX_MCP_SERVERS:
        issues.append(f"mcpServers 最多 {MAX_MCP_SERVERS} 个")
    for index, entry in enumerate(mcp_servers):
        if not isinstance(entry, dict) or not str(entry.get("serverUrl") or "").strip():
            issues.append(f"mcpServers[{index}] 缺少 serverUrl")
            continue
        # M4-b F17.3②：timeoutSeconds 可选，携带时必须为 1~300 的整数
        timeout_raw = entry.get("timeoutSeconds")
        if timeout_raw is not None and not _int_in_range(
            timeout_raw, MIN_MCP_TIMEOUT_SECONDS, MAX_MCP_TIMEOUT_SECONDS
        ):
            issues.append(
                f"mcpServers[{index}].timeoutSeconds 需为 "
                f"{MIN_MCP_TIMEOUT_SECONDS}~{MAX_MCP_TIMEOUT_SECONDS} 的整数"
            )
        enabled_tools = entry.get("enabledTools")
        if enabled_tools is None:
            continue
        if not isinstance(enabled_tools, list):
            issues.append(f"mcpServers[{index}] enabledTools 需为列表")
            continue
        if len(enabled_tools) > MAX_MCP_TOOLS_PER_SERVER:
            issues.append(f"mcpServers[{index}] enabledTools 最多 {MAX_MCP_TOOLS_PER_SERVER} 个")
        for tool_index, tool in enumerate(enabled_tools):
            if not isinstance(tool, dict) or not str(tool.get("name") or "").strip():
                issues.append(f"mcpServers[{index}].enabledTools[{tool_index}] 缺少 name")

    # M4-b F17.4：会话保持档位键（缺省 run 级；conversation 档的连接池为 P1 T-b5，
    # 本批只落键与校验，配置面可先行声明）
    mcp_session = form.get("mcpSession")
    if mcp_session is not None:
        if not isinstance(mcp_session, dict):
            issues.append("mcpSession 需为对象")
        elif str(mcp_session.get("scope") or DEFAULT_MCP_SESSION_SCOPE) not in MCP_SESSION_SCOPES:
            issues.append("mcpSession.scope 只能是 run 或 conversation")

    # 0074 PRD F7：工作流即工具条目校验（applicationId 必须是 UUID 形态）
    workflows = form.get("workflows") or []
    if len(workflows) > MAX_WORKFLOWS:
        issues.append(f"workflows 最多 {MAX_WORKFLOWS} 个")
    for index, entry in enumerate(workflows):
        if not isinstance(entry, dict) or not str(entry.get("applicationId") or "").strip():
            issues.append(f"workflows[{index}] 缺少 applicationId")
            continue
        if not _is_uuid_str(str(entry.get("applicationId"))):
            issues.append(f"workflows[{index}] applicationId 不是合法 UUID")

    # M4-c PRD F14.1：智能体协作挂载条目校验（上限含 handoff 形态，合计 5）
    sub_agents = form.get("subAgents") or []
    if len(sub_agents) > MAX_SUB_AGENTS:
        issues.append(f"subAgents 最多 {MAX_SUB_AGENTS} 个")
    mounted_ids: set[str] = set()
    for index, entry in enumerate(sub_agents):
        if not isinstance(entry, dict) or not str(entry.get("applicationId") or "").strip():
            issues.append(f"subAgents[{index}] 缺少 applicationId")
            continue
        application_id = str(entry.get("applicationId")).strip()
        if not _is_uuid_str(application_id):
            issues.append(f"subAgents[{index}] applicationId 不是合法 UUID")
        if application_id in mounted_ids:
            issues.append(f"subAgents[{index}] applicationId 重复挂载")
        mounted_ids.add(application_id)
        if self_application_id and application_id == str(self_application_id):
            issues.append(f"subAgents[{index}] 不能把当前应用委派给自己（自引用）")
        mode = entry.get("mode")
        if mode is not None and str(mode) not in SUB_AGENT_MODES:
            issues.append(f"subAgents[{index}] mode 只能是 delegate 或 handoff")
        tool_name = str(entry.get("toolName") or "").strip()
        if tool_name == HAND_BACK_TOOL_NAME:
            issues.append(
                f"subAgents[{index}].toolName 不得使用内核保留名 {HAND_BACK_TOOL_NAME}（接管归位工具）"
            )
        if tool_name and (
            tool_name.startswith(KNOWLEDGE_TOOL_NAME_PREFIX)
            or tool_name.startswith(WORKFLOW_TOOL_NAME_PREFIX)
        ):
            issues.append(
                f"subAgents[{index}].toolName 不得以 {KNOWLEDGE_TOOL_NAME_PREFIX} 或 "
                f"{WORKFLOW_TOOL_NAME_PREFIX} 开头（合成工具保留前缀）"
            )

    # M4 PRD F16.1/F16.6：longTerm 键组显式校验（配置面报错优先于运行期静默回退）
    memory_raw = form.get("memory")
    long_term_raw = memory_raw.get("longTerm") if isinstance(memory_raw, dict) else None
    if not isinstance(long_term_raw, dict):
        long_term_raw = {}
    if long_term_raw.get("enabled") and not long_term_admin_available:
        issues.append("不能开启长期记忆：用户端记忆管理面未部署（F16.6 隐私硬条件）")
    recall_top_k = long_term_raw.get("recallTopK")
    if recall_top_k is not None and not _int_in_range(
        recall_top_k, MIN_RECALL_TOPK, MAX_RECALL_TOPK
    ):
        issues.append(f"memory.longTerm.recallTopK 需为 {MIN_RECALL_TOPK}~{MAX_RECALL_TOPK} 的整数")
    max_memories = long_term_raw.get("maxMemories")
    if max_memories is not None and not _int_in_range(
        max_memories, MIN_MAX_MEMORIES, MAX_MAX_MEMORIES
    ):
        issues.append(
            f"memory.longTerm.maxMemories 需为 {MIN_MAX_MEMORIES}~{MAX_MAX_MEMORIES} 的整数"
        )

    return issues


def _int_in_range(value: Any, min_value: int, max_value: int) -> bool:
    # review 修正：bool 是 int 子类、int(8.9) 静默截断，二者都不算配置面的"整数"
    # 输入，严格类型判定让脏值显式报错而不是被转译成 1/8
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return min_value <= value <= max_value


def apply_form_to_node(node: dict[str, Any], form: dict[str, Any]) -> None:
    """把表单写回 agent_loop 节点 data.inputs（literal 脱壳形态）。

    必写键全量覆盖（含显式空列表 tools: []——纯聊天 agent 的预期形态）；
    可空扩展键（plannerPrompt/reflectorPrompt/maxReflectRounds/tokenBudget）
    传 None 时删除节点上的旧值，避免"表单清空但运行仍生效"的漂移。
    """
    inputs: dict[str, Any] = node.setdefault("data", {}).setdefault("inputs", {})
    memory = parse_memory_config(form.get("memory"))
    long_term = parse_long_term_config(form.get("memory"))

    required: dict[str, Any] = {
        "modleName": str(form.get("modleName") or ""),
        "systemPrompt": str(form.get("systemPrompt") or ""),
        "tools": _dict_list(form.get("tools")),
        "maxToolRounds": _positive_int_or_default(form.get("maxToolRounds"), 10),
        "openingRemarks": str(form.get("openingRemarks") or ""),
        "suggestedQuestions": _string_list(form.get("suggestedQuestions")),
        "datasets": _dict_list(form.get("datasets")),
        "mcpServers": _dict_list(form.get("mcpServers")),
        # M4-b F17.4：档位键全量覆盖写出（缺省恒为 {"scope": "run"}）
        "mcpSession": _mcp_session_form(form.get("mcpSession")),
        "workflows": _dict_list(form.get("workflows")),
        # M4-c F14.1：协作挂载全量覆盖写出（未挂载即显式空列表，与 workflows 同口径）
        "subAgents": _dict_list(form.get("subAgents")),
        # M4 PRD F16.1：shortTerm/longTerm 两组键全量覆盖写出（未勾选即显式 false）
        "memory": {"shortTerm": memory, "longTerm": long_term},
        "reasoningMode": str(form.get("reasoningMode") or "react"),
        "sensitiveTools": _dict_list(form.get("sensitiveTools")),
        # 0074 PRD F9（M3）：视觉开关随表单全量覆盖，未勾选即显式写 false
        "visionEnabled": bool(form.get("visionEnabled")),
    }
    for key, value in required.items():
        inputs[key] = _literal(value)

    nullable: dict[str, Any] = {
        "plannerPrompt": _optional_str(form.get("plannerPrompt")),
        "reflectorPrompt": _optional_str(form.get("reflectorPrompt")),
        "maxReflectRounds": _optional_positive_int(form.get("maxReflectRounds")),
        "tokenBudget": _optional_positive_int(form.get("tokenBudget")),
    }
    for key, value in nullable.items():
        if value is None:
            inputs.pop(key, None)
        else:
            inputs[key] = _literal(value)


# ---------- helpers ----------
def _mcp_session_form(raw: Any) -> dict[str, str]:
    """mcpSession 键组归一：缺键/非法 scope 补默认 run（F17.4 P0 默认档位）。"""
    if isinstance(raw, dict) and str(raw.get("scope") or "") in MCP_SESSION_SCOPES:
        return {"scope": str(raw["scope"])}
    return {"scope": DEFAULT_MCP_SESSION_SCOPE}


def _literal(value: Any) -> dict[str, Any]:
    """与 _default_graph / 前端画布一致的 literal 包装。"""
    return {"value": {"type": "literal", "content": value}}


def _as_positive_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _positive_int_or_default(value: Any, default: int) -> int:
    return _as_positive_int(value) or default


def _optional_positive_int(value: Any) -> int | None:
    return _as_positive_int(value)


def _is_uuid_str(value: str) -> bool:
    """applicationId 形态校验：仅要求可解析为 UUID，不做存在性检查（运行时解析）。"""
    try:
        UUID(value)
    except (TypeError, ValueError):
        return False
    return True


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
