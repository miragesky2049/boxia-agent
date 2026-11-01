"""节点元数据注册表：给前端节点库动态渲染用。

每个节点类型登记：
- type_code: coze StandardNodeType 数字字符串（与 NodeType 枚举一致）
- type_key: 前端用的英文短 key（如 start/end/llm/http/if_else/code/dataset/...）
- title: 中文标题（左侧节点库按钮上显示）
- color: 节点展示色（十六进制）
- category: 分类（control/ai/data/logic/conversation 等，前端分组）
- description: 节点一句话描述（hover 提示）
- default_ports: 默认 input/output 端口列表
- config_fields: 配置表单字段 schema（B2 阶段细化，现阶段给空列表占位）

新增节点 handler 时，必须同时在本文件登记一条元数据，前端节点库才能看到。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PortMeta:
    """端口元数据。"""
    name: str = "default"
    type: str = "any"
    label: str = ""
    required: bool = False


@dataclass(frozen=True)
class ConfigFieldMeta:
    """配置表单字段元数据（B2 阶段细化）。"""
    name: str
    label: str
    field_type: str = "text"  # text/textarea/select/model_picker/http_auth/...
    options: list[dict[str, Any]] = field(default_factory=list)
    default: Any = None
    required: bool = False
    placeholder: str = ""
    description: str = ""


@dataclass(frozen=True)
class NodeMeta:
    """节点元数据。"""
    type_code: str          # 对应 NodeType.value
    type_key: str           # 前端英文 key
    title: str              # 中文标题
    color: str              # 展示色
    category: str           # 分类
    description: str = ""
    inputs: list[PortMeta] = field(default_factory=list)
    outputs: list[PortMeta] = field(default_factory=list)
    config_fields: list[ConfigFieldMeta] = field(default_factory=list)


# ========== 元数据注册表 ==========
_NODE_METAS: list[NodeMeta] = [
    # ---- 流程控制 ----
    NodeMeta(
        type_code="1", type_key="start", title="开始", color="#1677ff",
        category="control", description="工作流入口，定义启动参数",
        outputs=[PortMeta(name="default", label="出口")],
        config_fields=[
            ConfigFieldMeta(name="inputs", label="启动参数", field_type="parameter_list",
                            description="用户启动工作流时填写的参数列表；类型支持 string / number / boolean / file / image"),
        ],
    ),
    NodeMeta(
        type_code="2", type_key="end", title="结束", color="#52c41a",
        category="control", description="工作流出口，返回最终结果",
        inputs=[PortMeta(name="default", label="入口")],
        config_fields=[
            ConfigFieldMeta(name="content", label="输出内容", field_type="textarea",
                            description="返回给调用方的结果，支持 {{node.output.field}} 引用"),
        ],
    ),
    NodeMeta(
        type_code="31", type_key="comment", title="便签", color="#ffe58f",
        category="misc", description="画布便签，仅用于注释说明，不参与执行",
        config_fields=[
            ConfigFieldMeta(name="content", label="便签内容", field_type="textarea",
                            placeholder="写下这段工作流的说明..."),
        ],
    ),
    NodeMeta(
        type_code="8", type_key="if_else", title="条件分支", color="#eb2f96",
        category="control", description="按条件选择出口分支",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="true", label="满足"), PortMeta(name="false", label="不满足")],
        config_fields=[
            ConfigFieldMeta(name="cases", label="条件列表", field_type="case_list",
                            description="多条件 case，第一个为真的 case 会被路由"),
        ],
    ),
    NodeMeta(
        type_code="19", type_key="break", title="Break", color="#faad14",
        category="control", description="在 Loop 内跳出循环",
        inputs=[PortMeta(name="default", label="入口")],
    ),
    NodeMeta(
        type_code="29", type_key="continue", title="Continue", color="#faad14",
        category="control", description="在 Loop 内跳过本次迭代",
        inputs=[PortMeta(name="default", label="入口")],
    ),

    # ---- AI ----
    NodeMeta(
        type_code="3", type_key="llm", title="大模型", color="#722ed1",
        category="ai", description="调用 LLM，支持工具调用",
        inputs=[PortMeta(name="input", label="输入")],
        outputs=[PortMeta(name="output", label="输出")],
        config_fields=[
            ConfigFieldMeta(name="modleName", label="模型", field_type="model_picker", required=True),
            ConfigFieldMeta(name="tools", label="技能", field_type="tool_list",
                            description="向 LLM 暴露的工具列表，触发 ReAct 循环"),
            ConfigFieldMeta(name="inputs", label="输入变量", field_type="key_value_list",
                            description="定义本节点的输入变量，可在提示词中通过 {{key}} 引用"),
            ConfigFieldMeta(name="images", label="视觉理解输入", field_type="key_value_list",
                            description="图片 URL 列表，传入后以 multi-modal content part 发送"),
            ConfigFieldMeta(name="systemPrompt", label="系统提示词", field_type="textarea"),
            ConfigFieldMeta(name="prompt", label="用户提示词", field_type="textarea", required=True),
            ConfigFieldMeta(name="temperature", label="Temperature", field_type="number", default=0.7),
            ConfigFieldMeta(name="maxTokens", label="Max Tokens", field_type="number", default=1024),
            ConfigFieldMeta(name="needHistory", label="启用多轮记忆", field_type="boolean",
                            default=False,
                            description="开启后从会话历史拉取最近 N 条 user/assistant 消息拼进 prompt"),
            ConfigFieldMeta(name="historyLimit", label="历史消息条数", field_type="number",
                            default=10,
                            description="needHistory=true 时拉取的最大历史消息数（user+assistant 合计）"),
        ],
    ),
    NodeMeta(
        type_code="100", type_key="agent_loop", title="Agent 循环", color="#531dab",
        category="ai", description="plan/execute/reflect 三阶段自主 Agent",
        inputs=[PortMeta(name="input", label="用户目标")],
        outputs=[
            PortMeta(name="output", label="最终答案"),
            PortMeta(name="plan", label="任务计划"),
        ],
        config_fields=[
            ConfigFieldMeta(name="modleName", label="模型", field_type="model_picker", required=True),
            ConfigFieldMeta(name="systemPrompt", label="Agent 系统提示词", field_type="textarea"),
            ConfigFieldMeta(name="tools", label="工具", field_type="tool_list",
                            description="向 LLM 暴露的工具列表"),
            ConfigFieldMeta(name="maxToolRounds", label="Execute 最大工具轮次", field_type="number", default=5),
            ConfigFieldMeta(name="maxReflectRounds", label="Reflect 最大迭代轮次", field_type="number", default=3),
            ConfigFieldMeta(name="plannerPrompt", label="Plan 系统提示词", field_type="textarea",
                            description="留空则使用内置任务拆解提示词"),
            ConfigFieldMeta(name="reflectorPrompt", label="Reflect 系统提示词", field_type="textarea",
                            description="留空则使用内置质量评审提示词"),
        ],
    ),

    # ---- HTTP / 代码 ----
    NodeMeta(
        type_code="45", type_key="http", title="HTTP 请求", color="#fa8c16",
        category="logic", description="调用外部 HTTP 接口",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="body", label="响应体"), PortMeta(name="status", label="状态码")],
        config_fields=[
            ConfigFieldMeta(name="url", label="URL", field_type="text", required=True,
                            placeholder="https://api.example.com/endpoint/:id"),
            ConfigFieldMeta(name="method", label="Method", field_type="select", default="GET",
                            options=[{"value": "GET"}, {"value": "POST"}, {"value": "PUT"}, {"value": "DELETE"}]),
            ConfigFieldMeta(name="pathParams", label="路径参数", field_type="key_value_list",
                            description="URL 中 :param 形式的路径参数，运行时替换"),
            ConfigFieldMeta(name="queryParams", label="Query 参数", field_type="key_value_list",
                            description="拼接到 URL ? 后的查询参数"),
            ConfigFieldMeta(name="headers", label="请求头", field_type="key_value_list",
                            description="自定义 HTTP 请求头（如 Content-Type/Authorization）"),
            ConfigFieldMeta(name="authType", label="认证方式", field_type="select", default="none",
                            options=[{"value": "none"}, {"value": "bearer"}, {"value": "basic"}]),
            ConfigFieldMeta(name="authToken", label="Token / 用户名", field_type="text",
                            description="bearer 模式填 token；basic 模式填用户名"),
            ConfigFieldMeta(name="authSecret", label="密码", field_type="text",
                            description="仅 basic 模式生效"),
            ConfigFieldMeta(name="bodyType", label="Body 类型", field_type="select", default="none",
                            options=[{"value": "none"}, {"value": "json"}, {"value": "form"}]),
            ConfigFieldMeta(name="bodyJson", label="JSON Body", field_type="code_editor",
                            description="bodyType=json 时发送的 JSON 对象"),
            ConfigFieldMeta(name="bodyForm", label="Form Body", field_type="key_value_list",
                            description="bodyType=form 时发送的 x-www-form-urlencoded 键值对"),
            ConfigFieldMeta(name="timeoutMs", label="超时（毫秒）", field_type="number", default=30000),
        ],
    ),
    NodeMeta(
        type_code="4", type_key="api_plugin", title="插件调用", color="#fa541c",
        category="logic", description="调用工具市场已注册的插件",
        inputs=[PortMeta(name="default", label="入参")],
        outputs=[
            PortMeta(name="output", label="返回文本"),
            PortMeta(name="parsed", label="JSON 解析结果"),
        ],
        config_fields=[
            ConfigFieldMeta(name="pluginName", label="插件名", field_type="text", required=True,
                            placeholder="weather.get_forecast"),
            ConfigFieldMeta(name="description", label="插件描述", field_type="textarea",
                            placeholder="说明本节点调用该插件的用途"),
        ],
    ),
    NodeMeta(
        type_code="5", type_key="code", title="代码", color="#13c2c2",
        category="logic", description="运行 Python 代码片段",
        inputs=[PortMeta(name="input", label="输入")],
        outputs=[PortMeta(name="output", label="输出")],
        config_fields=[
            ConfigFieldMeta(name="inputs", label="输入变量", field_type="key_value_list",
                            description="定义本节点静态输入变量，合并进 sandbox.run 的 args 字典"),
            ConfigFieldMeta(name="code", label="Python 代码", field_type="code_editor", required=True,
                            placeholder="def main(input):\n    return {'output': input}"),
            ConfigFieldMeta(name="timeoutMs", label="超时（毫秒）", field_type="number", default=10000),
        ],
    ),

    # ---- 数据 / 知识库 ----
    NodeMeta(
        type_code="6", type_key="dataset", title="知识库检索", color="#2f54eb",
        category="data", description="从知识库检索相关片段",
        inputs=[PortMeta(name="query", label="查询")],
        outputs=[PortMeta(name="chunks", label="片段列表")],
        config_fields=[
            ConfigFieldMeta(name="datasetId", label="知识库 ID", field_type="text", required=True),
            ConfigFieldMeta(name="topK", label="Top K", field_type="number", default=5),
            ConfigFieldMeta(name="scoreThreshold", label="Score 阈值", field_type="number", default=0.0,
                            description="相似度分数低于此值的片段将被过滤，0 表示不过滤"),
        ],
    ),
    NodeMeta(
        type_code="27", type_key="dataset_write", title="知识库写入", color="#2f54eb",
        category="data", description="向知识库写入新片段",
        inputs=[PortMeta(name="doc", label="文档")],
        outputs=[PortMeta(name="status", label="写入状态")],
        config_fields=[
            ConfigFieldMeta(name="datasetId", label="知识库 ID", field_type="text", required=True),
        ],
    ),
    NodeMeta(
        type_code="15", type_key="text_processor", title="文本处理", color="#eb2f96",
        category="data", description="文本拼接、截取、替换等处理",
        inputs=[PortMeta(name="input", label="输入")],
        outputs=[PortMeta(name="output", label="输出")],
        config_fields=[
            ConfigFieldMeta(name="operation", label="操作", field_type="select", default="concat",
                            options=[{"value": "concat"}, {"value": "slice"}, {"value": "replace"}]),
            ConfigFieldMeta(name="find", label="查找文本", field_type="text"),
            ConfigFieldMeta(name="replaceWith", label="替换为", field_type="text"),
        ],
    ),
    NodeMeta(
        type_code="58", type_key="json_stringify", title="JSON 序列化", color="#a0d911",
        category="data", description="把对象转成 JSON 字符串",
        inputs=[PortMeta(name="input", label="输入对象")],
        outputs=[PortMeta(name="output", label="JSON 字符串")],
    ),
    NodeMeta(
        type_code="59", type_key="json_parser", title="JSON 解析", color="#a0d911",
        category="data", description="把 JSON 字符串解析成对象",
        inputs=[PortMeta(name="input", label="JSON 字符串")],
        outputs=[PortMeta(name="output", label="解析对象")],
    ),

    # ---- 循环 / 子图 ----
    NodeMeta(
        type_code="21", type_key="loop", title="循环", color="#722ed1",
        category="logic", description="按数组或次数循环执行子图",
        inputs=[PortMeta(name="input", label="数组输入")],
        outputs=[PortMeta(name="output", label="结果数组")],
        config_fields=[
            ConfigFieldMeta(name="loopType", label="循环类型", field_type="select", default="array",
                            options=[{"value": "array"}, {"value": "count"}]),
            ConfigFieldMeta(name="loopCount", label="循环次数", field_type="number", default=10),
            ConfigFieldMeta(name="parallel", label="并发执行", field_type="boolean", default=False),
        ],
    ),
    NodeMeta(
        type_code="28", type_key="batch", title="批处理", color="#722ed1",
        category="logic", description="并发批量处理数组元素",
        inputs=[PortMeta(name="input", label="数组输入")],
        outputs=[PortMeta(name="output", label="结果数组")],
        config_fields=[
            ConfigFieldMeta(name="parallelCount", label="并发数", field_type="number", default=5),
        ],
    ),
    NodeMeta(
        type_code="9", type_key="subworkflow", title="子工作流", color="#531dab",
        category="logic", description="调用另一个已发布的工作流",
        inputs=[PortMeta(name="input", label="输入")],
        outputs=[PortMeta(name="output", label="输出")],
        config_fields=[
            ConfigFieldMeta(name="workflowId", label="目标工作流 ID", field_type="text", required=True),
        ],
    ),
    NodeMeta(
        type_code="20", type_key="set_variable", title="设置变量", color="#1890ff",
        category="logic", description="给变量赋值",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="default", label="出口")],
        config_fields=[
            ConfigFieldMeta(name="variableName", label="变量名", field_type="text", required=True),
            ConfigFieldMeta(name="value", label="值", field_type="text"),
        ],
    ),
    NodeMeta(
        type_code="32", type_key="variable_merge", title="变量合并", color="#1890ff",
        category="logic", description="合并多个分支的变量",
        inputs=[PortMeta(name="branch_a", label="分支 A"), PortMeta(name="branch_b", label="分支 B")],
        outputs=[PortMeta(name="merged", label="合并结果")],
    ),

    # ---- 人审 ----
    NodeMeta(
        type_code="60", type_key="human_approval", title="人工审批", color="#fa541c",
        category="control", description="中断工作流，等待人工审批后继续",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="approved", label="通过"), PortMeta(name="rejected", label="拒绝")],
        config_fields=[
            ConfigFieldMeta(name="assignee_role", label="审批人角色", field_type="text"),
            ConfigFieldMeta(name="instructions", label="审批说明", field_type="textarea"),
        ],
    ),

    # ---- 会话 / 消息 ----
    NodeMeta(
        type_code="39", type_key="create_conversation", title="创建会话", color="#2f54eb",
        category="conversation", description="创建一个新的会话",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="conversation_id", label="会话 ID")],
        config_fields=[
            ConfigFieldMeta(name="title", label="会话标题", field_type="text", placeholder="留空则自动生成"),
            ConfigFieldMeta(name="app_id", label="应用 ID", field_type="text", placeholder="留空则用当前应用"),
        ],
    ),
    NodeMeta(
        type_code="51", type_key="update_conversation", title="更新会话", color="#2f54eb",
        category="conversation", description="更新会话标题等元信息",
        inputs=[PortMeta(name="conversation_id", label="会话 ID")],
        config_fields=[
            ConfigFieldMeta(name="title", label="新标题", field_type="text"),
        ],
    ),
    NodeMeta(
        type_code="52", type_key="delete_conversation", title="删除会话", color="#2f54eb",
        category="conversation", description="删除一个会话及其全部消息",
        inputs=[PortMeta(name="conversation_id", label="会话 ID")],
    ),
    NodeMeta(
        type_code="53", type_key="query_conversation_list", title="查询会话列表", color="#2f54eb",
        category="conversation", description="查询当前用户的会话列表",
        outputs=[PortMeta(name="conversations", label="会话列表")],
        config_fields=[
            ConfigFieldMeta(name="app_id", label="应用 ID", field_type="text", placeholder="留空则不限"),
            ConfigFieldMeta(name="limit", label="条数上限", field_type="text", default=20),
        ],
    ),
    NodeMeta(
        type_code="54", type_key="query_conversation_history", title="查询会话历史", color="#2f54eb",
        category="conversation", description="查询某个会话的历史消息",
        inputs=[PortMeta(name="conversation_id", label="会话 ID")],
        outputs=[PortMeta(name="messages", label="消息列表")],
        config_fields=[
            ConfigFieldMeta(name="limit", label="条数上限", field_type="text", default=100),
        ],
    ),
    NodeMeta(
        type_code="55", type_key="create_message", title="创建消息", color="#2f54eb",
        category="conversation", description="向会话追加一条消息",
        inputs=[PortMeta(name="conversation_id", label="会话 ID"), PortMeta(name="content", label="内容")],
        outputs=[PortMeta(name="message_id", label="消息 ID")],
        config_fields=[
            ConfigFieldMeta(
                name="role", label="角色", field_type="select", default="user",
                options=[
                    {"value": "user", "label": "用户"},
                    {"value": "assistant", "label": "助手"},
                    {"value": "system", "label": "系统"},
                    {"value": "tool", "label": "工具"},
                ],
            ),
            ConfigFieldMeta(
                name="content", label="消息内容", field_type="textarea",
                placeholder="支持 {{node.output.field}} 变量",
            ),
        ],
    ),
    NodeMeta(
        type_code="56", type_key="update_message", title="更新消息", color="#2f54eb",
        category="conversation", description="更新消息内容",
        inputs=[PortMeta(name="message_id", label="消息 ID")],
        config_fields=[
            ConfigFieldMeta(name="content", label="新内容", field_type="textarea"),
        ],
    ),
    NodeMeta(
        type_code="57", type_key="delete_message", title="删除消息", color="#2f54eb",
        category="conversation", description="删除一条消息",
        inputs=[PortMeta(name="message_id", label="消息 ID")],
    ),
    NodeMeta(
        type_code="38", type_key="clear_context", title="清空上下文", color="#2f54eb",
        category="conversation", description="清空当前会话的上下文",
        inputs=[PortMeta(name="conversation_id", label="会话 ID")],
    ),
]


def list_node_metas() -> list[NodeMeta]:
    """返回全部已登记节点元数据（按 category 分组在前端处理）。"""
    return list(_NODE_METAS)


def get_node_meta_by_type_code(type_code: str) -> NodeMeta | None:
    """按 coze type_code 查元数据。"""
    for meta in _NODE_METAS:
        if meta.type_code == type_code:
            return meta
    return None


def get_node_meta_by_type_key(type_key: str) -> NodeMeta | None:
    """按前端英文 key 查元数据。"""
    for meta in _NODE_METAS:
        if meta.type_key == type_key:
            return meta
    return None
