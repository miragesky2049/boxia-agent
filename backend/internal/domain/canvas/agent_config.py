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

from internal.domain.agent.memory import parse_memory_config

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
# 0074 PRD F6：MCP server 数与单 server 勾选工具数上限（防 spec 膨胀）
MAX_MCP_SERVERS = 5
MAX_MCP_TOOLS_PER_SERVER = 20


def find_agent_loop_node(graph: dict[str, Any]) -> dict[str, Any] | None:
    """在原始画布 JSON 中定位 agent_loop 节点（数字类型码形态）。"""
    for node in graph.get("nodes") or []:
        if str(node.get("type")) == AGENT_NODE_TYPE_CODE:
            return node
    return None


def node_config_to_form(node_cfg: dict[str, Any]) -> dict[str, Any]:
    """把运行时口径节点 config 补齐为配置面表单（GET /agent-config 响应体）。"""
    memory = parse_memory_config(node_cfg.get("memory"))
    return {
        "systemPrompt": str(node_cfg.get("systemPrompt") or ""),
        "modleName": str(node_cfg.get("modleName") or ""),
        "maxToolRounds": _positive_int_or_default(node_cfg.get("maxToolRounds"), 10),
        "openingRemarks": str(node_cfg.get("openingRemarks") or ""),
        "suggestedQuestions": _string_list(node_cfg.get("suggestedQuestions")),
        "tools": _dict_list(node_cfg.get("tools")),
        "datasets": _dict_list(node_cfg.get("datasets")),
        "mcpServers": _dict_list(node_cfg.get("mcpServers")),
        "workflows": _dict_list(node_cfg.get("workflows")),
        "memory": {"shortTerm": memory},
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


def validate_form(form: dict[str, Any]) -> list[str]:
    """校验配置表单，返回问题清单（空列表 = 通过）。契约式：调用方决定抛错形态。"""
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

    # 0074 PRD F6：MCP server 快照结构校验（url 非空即可，SSRF 在 discover/运行时判）
    mcp_servers = form.get("mcpServers") or []
    if len(mcp_servers) > MAX_MCP_SERVERS:
        issues.append(f"mcpServers 最多 {MAX_MCP_SERVERS} 个")
    for index, entry in enumerate(mcp_servers):
        if not isinstance(entry, dict) or not str(entry.get("serverUrl") or "").strip():
            issues.append(f"mcpServers[{index}] 缺少 serverUrl")
            continue
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

    return issues


def apply_form_to_node(node: dict[str, Any], form: dict[str, Any]) -> None:
    """把表单写回 agent_loop 节点 data.inputs（literal 脱壳形态）。

    必写键全量覆盖（含显式空列表 tools: []——纯聊天 agent 的预期形态）；
    可空扩展键（plannerPrompt/reflectorPrompt/maxReflectRounds/tokenBudget）
    传 None 时删除节点上的旧值，避免"表单清空但运行仍生效"的漂移。
    """
    inputs: dict[str, Any] = node.setdefault("data", {}).setdefault("inputs", {})
    memory = parse_memory_config(form.get("memory"))

    required: dict[str, Any] = {
        "modleName": str(form.get("modleName") or ""),
        "systemPrompt": str(form.get("systemPrompt") or ""),
        "tools": _dict_list(form.get("tools")),
        "maxToolRounds": _positive_int_or_default(form.get("maxToolRounds"), 10),
        "openingRemarks": str(form.get("openingRemarks") or ""),
        "suggestedQuestions": _string_list(form.get("suggestedQuestions")),
        "datasets": _dict_list(form.get("datasets")),
        "mcpServers": _dict_list(form.get("mcpServers")),
        "workflows": _dict_list(form.get("workflows")),
        "memory": {"shortTerm": memory},
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
