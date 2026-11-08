"""节点元数据注册表：给前端节点库动态渲染用。

每个节点类型登记：
- type_code: coze StandardNodeType 数字字符串（与 NodeType 枚举一致）
- type_key: 前端用的英文短 key（如 start/end/llm/http/if_else/code/dataset/...）
- title: 中文标题（左侧节点库按钮上显示）
- color: 节点展示色（十六进制）
- category: 分类（basic/ai/plugin/workflow/logic/io/control/knowledge/component/conversation/history/message/misc，前端分组对齐 coze）
- icon: 图标字符（emoji/短文本，前端直接渲染）
- description: 节点一句话描述（hover 提示）
- subtitle_hint: 静态副标题兜底（依赖运行期 config 的动态副标题仍由前端生成）
- next_recommendations: 推荐下游 type_key 列表（「下一步」区块）
- capabilities: 能力声明（可删/可复制/可试运行/有子图/有输出）
- default_ports: 默认 input/output 端口列表
- config_fields: 配置表单字段 schema，每个字段带 group（配置抽屉分组标题）

新增节点 handler 时，必须同时在本文件登记一条元数据，前端节点库才能看到。
展示层图标/分组/副标题兜底/推荐/配置分组全部由本文件驱动，前端只保留离线 fallback。
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
    group: str = ""  # 配置抽屉分组标题；为空时前端按本地 fallback 分组


@dataclass(frozen=True)
class NodeCapabilities:
    """节点能力声明：前端据此控制删除/复制/试运行/子图/输出入口。"""

    runnable: bool = True
    copyable: bool = True
    deletable: bool = True
    has_subgraph: bool = False
    has_outputs: bool = True


@dataclass(frozen=True)
class NodeMeta:
    """节点元数据。"""

    type_code: str  # 对应 NodeType.value
    type_key: str  # 前端英文 key
    title: str  # 中文标题
    color: str  # 展示色
    category: str  # 分类
    description: str = ""
    icon: str = ""
    subtitle_hint: str = ""
    next_recommendations: list[str] = field(default_factory=list)
    capabilities: NodeCapabilities = field(default_factory=NodeCapabilities)
    inputs: list[PortMeta] = field(default_factory=list)
    outputs: list[PortMeta] = field(default_factory=list)
    config_fields: list[ConfigFieldMeta] = field(default_factory=list)
    # 占位节点：available=False 时前端置灰不可添加，hover 展示 unavailable_reason
    available: bool = True
    unavailable_reason: str = ""


# ========== 元数据注册表 ==========
_NODE_METAS: list[NodeMeta] = [
    # ---- 流程控制 ----
    NodeMeta(
        type_code="1",
        type_key="start",
        title="开始",
        color="#1677ff",
        category="basic",
        description="工作流入口，定义启动参数",
        icon="▶",
        subtitle_hint="工作流入口",
        next_recommendations=["llm", "dataset", "if_else", "code"],
        capabilities=NodeCapabilities(deletable=False),
        outputs=[PortMeta(name="default", label="出口")],
        config_fields=[
            ConfigFieldMeta(
                name="inputs",
                label="启动参数",
                field_type="parameter_list",
                description="用户启动工作流时填写的参数列表；类型支持 string / number / boolean / file / image",
                group="启动参数",
            ),
        ],
    ),
    NodeMeta(
        type_code="2",
        type_key="end",
        title="结束",
        color="#52c41a",
        category="basic",
        description="工作流出口，返回最终结果",
        icon="■",
        subtitle_hint="工作流出口",
        capabilities=NodeCapabilities(has_outputs=False),
        inputs=[PortMeta(name="default", label="入口")],
        config_fields=[
            ConfigFieldMeta(
                name="returnType",
                label="返回类型",
                field_type="select",
                default="text",
                options=[
                    {"label": "返回文本", "value": "text"},
                    {"label": "返回变量", "value": "variables"},
                ],
                description="返回文本按 content 模板输出；返回变量输出上游节点声明的变量",
                group="输出设置",
            ),
            ConfigFieldMeta(
                name="content",
                label="输出内容",
                field_type="textarea",
                description="返回给调用方的结果，支持 {{node.output.field}} 引用；对话流中作为最终回答",
                group="输出设置",
            ),
            ConfigFieldMeta(
                name="stream",
                label="流式输出",
                field_type="boolean",
                default=False,
                description="对话流中开启后最终回答通过 output_message 推送",
                group="输出设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="31",
        type_key="comment",
        title="便签",
        color="#ffe58f",
        category="basic",
        description="画布便签，仅用于注释说明，不参与执行",
        icon="✎",
        subtitle_hint="",
        capabilities=NodeCapabilities(runnable=False, has_outputs=False),
        config_fields=[
            ConfigFieldMeta(
                name="content",
                label="便签内容",
                field_type="textarea",
                placeholder="写下这段工作流的说明...",
                group="便签内容",
            ),
        ],
    ),
    NodeMeta(
        type_code="7",
        type_key="note",
        title="注释",
        color="#fbbf24",
        category="basic",
        description="画布注释，仅用于说明，不参与执行",
        icon="📝",
        subtitle_hint="画布注释",
        capabilities=NodeCapabilities(runnable=False, has_outputs=False),
        config_fields=[
            ConfigFieldMeta(
                name="content",
                label="注释内容",
                field_type="textarea",
                placeholder="写下说明文字...",
                group="注释内容",
            ),
        ],
    ),
    NodeMeta(
        type_code="8",
        type_key="if_else",
        title="条件分支",
        color="#eb2f96",
        category="logic",
        description="按条件选择出口分支",
        icon="IF",
        subtitle_hint="条件分支",
        next_recommendations=["llm", "code", "end"],
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="true", label="满足"), PortMeta(name="false", label="不满足")],
        config_fields=[
            ConfigFieldMeta(
                name="cases",
                label="条件列表",
                field_type="case_list",
                description="多条件 case，第一个为真的 case 会被路由",
                group="条件分支",
            ),
        ],
    ),
    NodeMeta(
        type_code="22",
        type_key="intent",
        title="意图识别",
        color="#eb2f96",
        category="logic",
        description="用 LLM 把用户输入分类到预定义意图，按意图路由",
        icon="◎",
        subtitle_hint="意图分类路由",
        next_recommendations=["llm", "output", "end"],
        inputs=[PortMeta(name="query", label="用户输入")],
        outputs=[
            PortMeta(name="classificationId", label="意图 ID", type="integer"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="mode",
                label="识别模式",
                field_type="select",
                default="fast",
                options=[
                    {"value": "fast", "label": "极速（仅当前输入）"},
                    {"value": "full", "label": "完整（拼接会话历史）"},
                ],
                group="意图设置",
            ),
            ConfigFieldMeta(
                name="modleName",
                label="模型",
                field_type="model_picker",
                description="留空或模型不可用时按关键词包含匹配兜底",
                group="意图设置",
            ),
            ConfigFieldMeta(
                name="intents",
                label="意图列表",
                field_type="intent_list",
                description="每个意图生成一个出口；未命中任何意图时走「其他」出口",
                group="意图列表",
            ),
            ConfigFieldMeta(
                name="needHistory",
                label="启用会话历史",
                field_type="boolean",
                default=False,
                description="开启后拉取最近 N 条 user/assistant 消息辅助分类",
                group="高级",
            ),
            ConfigFieldMeta(
                name="historyLimit",
                label="历史消息条数",
                field_type="number",
                default=10,
                group="高级",
            ),
        ],
    ),
    NodeMeta(
        type_code="19",
        type_key="break",
        title="Break",
        color="#faad14",
        category="control",
        description="在 Loop 内跳出循环",
        icon="‖",
        subtitle_hint="跳出循环",
        capabilities=NodeCapabilities(has_outputs=False),
        inputs=[PortMeta(name="default", label="入口")],
    ),
    NodeMeta(
        type_code="29",
        type_key="continue",
        title="Continue",
        color="#faad14",
        category="control",
        description="在 Loop 内跳过本次迭代",
        icon="→",
        subtitle_hint="跳过本次迭代",
        capabilities=NodeCapabilities(has_outputs=False),
        inputs=[PortMeta(name="default", label="入口")],
    ),
    # ---- AI ----
    NodeMeta(
        type_code="3",
        type_key="llm",
        title="大模型",
        color="#722ed1",
        category="ai",
        description="调用 LLM，支持工具调用",
        icon="AI",
        subtitle_hint="调用大模型",
        next_recommendations=["if_else", "dataset", "http", "end"],
        inputs=[PortMeta(name="input", label="输入")],
        outputs=[
            PortMeta(name="output", label="输出", type="string"),
            PortMeta(name="reasoning_content", label="思考过程", type="string"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="modleName",
                label="模型",
                field_type="model_picker",
                required=True,
                group="模型设置",
            ),
            ConfigFieldMeta(
                name="responseFormat",
                label="输出格式",
                field_type="select",
                default="text",
                options=[
                    {"value": "text", "label": "文本"},
                    {"value": "json", "label": "JSON"},
                ],
                group="模型设置",
            ),
            ConfigFieldMeta(
                name="stream",
                label="支持流式",
                field_type="boolean",
                default=True,
                description="开启后逐 token 推送；工具调用场景自动回退为非流式",
                group="模型设置",
            ),
            ConfigFieldMeta(
                name="tools",
                label="技能",
                field_type="tool_list",
                description="向 LLM 暴露的工具列表，触发 ReAct 循环",
                group="技能",
            ),
            ConfigFieldMeta(
                name="inputs",
                label="输入变量",
                field_type="key_value_list",
                description="定义本节点的输入变量，可在提示词中通过 {{key}} 引用",
                group="输入变量",
            ),
            ConfigFieldMeta(
                name="images",
                label="视觉理解输入",
                field_type="key_value_list",
                description="图片 URL 列表，传入后以 multi-modal content part 发送",
                group="视觉理解",
            ),
            ConfigFieldMeta(
                name="systemPrompt", label="系统提示词", field_type="textarea", group="提示词"
            ),
            ConfigFieldMeta(
                name="prompt",
                label="用户提示词",
                field_type="textarea",
                required=True,
                group="提示词",
            ),
            ConfigFieldMeta(
                name="temperature",
                label="Temperature",
                field_type="number",
                default=0.7,
                group="模型设置",
            ),
            ConfigFieldMeta(
                name="maxTokens",
                label="Max Tokens",
                field_type="number",
                default=1024,
                group="模型设置",
            ),
            ConfigFieldMeta(
                name="needHistory",
                label="启用多轮记忆",
                field_type="boolean",
                default=False,
                description="开启后从会话历史拉取最近 N 条 user/assistant 消息拼进 prompt",
                group="高级",
            ),
            ConfigFieldMeta(
                name="historyLimit",
                label="历史消息条数",
                field_type="number",
                default=10,
                description="needHistory=true 时拉取的最大历史消息数（user+assistant 合计）",
                group="高级",
            ),
        ],
    ),
    NodeMeta(
        type_code="100",
        type_key="agent_loop",
        title="Agent 循环",
        color="#531dab",
        category="ai",
        description="plan/execute/reflect 三阶段自主 Agent",
        icon="◉",
        subtitle_hint="Agent 自主循环",
        next_recommendations=["if_else", "end"],
        inputs=[PortMeta(name="input", label="用户目标")],
        outputs=[
            PortMeta(name="output", label="最终答案"),
            PortMeta(name="plan", label="任务计划"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="modleName",
                label="模型",
                field_type="model_picker",
                required=True,
                group="模型设置",
            ),
            ConfigFieldMeta(
                name="systemPrompt", label="Agent 系统提示词", field_type="textarea", group="提示词"
            ),
            ConfigFieldMeta(
                name="tools",
                label="工具",
                field_type="tool_list",
                description="向 LLM 暴露的工具列表",
                group="模型设置",
            ),
            ConfigFieldMeta(
                name="maxToolRounds",
                label="Execute 最大工具轮次",
                field_type="number",
                default=5,
                group="高级",
            ),
            ConfigFieldMeta(
                name="maxReflectRounds",
                label="Reflect 最大迭代轮次",
                field_type="number",
                default=3,
                group="高级",
            ),
            ConfigFieldMeta(
                name="plannerPrompt",
                label="Plan 系统提示词",
                field_type="textarea",
                description="留空则使用内置任务拆解提示词",
                group="提示词",
            ),
            ConfigFieldMeta(
                name="reflectorPrompt",
                label="Reflect 系统提示词",
                field_type="textarea",
                description="留空则使用内置质量评审提示词",
                group="提示词",
            ),
        ],
    ),
    # ---- HTTP / 代码 ----
    NodeMeta(
        type_code="45",
        type_key="http",
        title="HTTP 请求",
        color="#fa8c16",
        category="component",
        description="调用外部 HTTP 接口",
        icon="🌐",
        subtitle_hint="调用外部接口",
        next_recommendations=["code", "if_else", "end"],
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="body", label="响应体"), PortMeta(name="status", label="状态码")],
        config_fields=[
            ConfigFieldMeta(
                name="url",
                label="URL",
                field_type="text",
                required=True,
                placeholder="https://api.example.com/endpoint/:id",
                group="请求设置",
            ),
            ConfigFieldMeta(
                name="method",
                label="Method",
                field_type="select",
                default="GET",
                options=[
                    {"value": "GET"},
                    {"value": "POST"},
                    {"value": "PUT"},
                    {"value": "DELETE"},
                ],
                group="请求设置",
            ),
            ConfigFieldMeta(
                name="pathParams",
                label="路径参数",
                field_type="key_value_list",
                description="URL 中 :param 形式的路径参数，运行时替换",
                group="请求设置",
            ),
            ConfigFieldMeta(
                name="queryParams",
                label="Query 参数",
                field_type="key_value_list",
                description="拼接到 URL ? 后的查询参数",
                group="请求设置",
            ),
            ConfigFieldMeta(
                name="headers",
                label="请求头",
                field_type="key_value_list",
                description="自定义 HTTP 请求头（如 Content-Type/Authorization）",
                group="请求设置",
            ),
            ConfigFieldMeta(
                name="authType",
                label="认证方式",
                field_type="select",
                default="none",
                options=[{"value": "none"}, {"value": "bearer"}, {"value": "basic"}],
                group="认证",
            ),
            ConfigFieldMeta(
                name="authToken",
                label="Token / 用户名",
                field_type="text",
                description="bearer 模式填 token；basic 模式填用户名",
                group="认证",
            ),
            ConfigFieldMeta(
                name="authSecret",
                label="密码",
                field_type="text",
                description="仅 basic 模式生效",
                group="认证",
            ),
            ConfigFieldMeta(
                name="bodyType",
                label="Body 类型",
                field_type="select",
                default="none",
                options=[{"value": "none"}, {"value": "json"}, {"value": "form"}],
                group="请求设置",
            ),
            ConfigFieldMeta(
                name="bodyJson",
                label="JSON Body",
                field_type="code_editor",
                description="bodyType=json 时发送的 JSON 对象",
                group="请求设置",
            ),
            ConfigFieldMeta(
                name="bodyForm",
                label="Form Body",
                field_type="key_value_list",
                description="bodyType=form 时发送的 x-www-form-urlencoded 键值对",
                group="请求设置",
            ),
            ConfigFieldMeta(
                name="timeoutMs",
                label="超时（毫秒）",
                field_type="number",
                default=30000,
                group="高级",
            ),
        ],
    ),
    NodeMeta(
        type_code="4",
        type_key="api_plugin",
        title="插件调用",
        color="#fa541c",
        category="plugin",
        description="调用工具市场已注册的插件",
        icon="⌗",
        subtitle_hint="调用插件",
        next_recommendations=["code", "if_else", "end"],
        inputs=[PortMeta(name="default", label="入参")],
        outputs=[
            PortMeta(name="output", label="返回文本"),
            PortMeta(name="parsed", label="JSON 解析结果"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="pluginName",
                label="插件名",
                field_type="text",
                required=True,
                placeholder="weather.get_forecast",
                group="插件设置",
            ),
            ConfigFieldMeta(
                name="description",
                label="插件描述",
                field_type="textarea",
                placeholder="说明本节点调用该插件的用途",
                group="插件设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="5",
        type_key="code",
        title="代码",
        color="#13c2c2",
        category="logic",
        description="运行 Python 代码片段",
        icon="{;}",
        subtitle_hint="编写 Python 代码",
        next_recommendations=["if_else", "llm", "end"],
        inputs=[PortMeta(name="input", label="输入")],
        outputs=[PortMeta(name="output", label="输出")],
        config_fields=[
            ConfigFieldMeta(
                name="inputs",
                label="输入变量",
                field_type="key_value_list",
                description="定义本节点静态输入变量，合并进 sandbox.run 的 args 字典",
                group="输入变量",
            ),
            ConfigFieldMeta(
                name="code",
                label="Python 代码",
                field_type="code_editor",
                required=True,
                placeholder="def main(input):\n    return {'output': input}",
                group="代码",
            ),
            ConfigFieldMeta(
                name="timeoutMs",
                label="超时（毫秒）",
                field_type="number",
                default=10000,
                group="代码",
            ),
        ],
    ),
    # ---- 数据 / 知识库 ----
    NodeMeta(
        type_code="6",
        type_key="dataset",
        title="知识库检索",
        color="#2f54eb",
        category="knowledge",
        description="从知识库检索相关片段",
        icon="DB",
        subtitle_hint="检索知识库",
        next_recommendations=["llm", "if_else"],
        inputs=[PortMeta(name="query", label="查询")],
        outputs=[
            PortMeta(name="outputList", label="检索结果", type="array"),
            PortMeta(name="chunks", label="片段列表", type="array"),
            PortMeta(name="count", label="命中数量", type="integer"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="datasetId",
                label="知识库 ID",
                field_type="text",
                required=True,
                group="知识库设置",
            ),
            ConfigFieldMeta(
                name="topK", label="Top K", field_type="number", default=5, group="知识库设置"
            ),
            ConfigFieldMeta(
                name="scoreThreshold",
                label="Score 阈值",
                field_type="number",
                default=0.0,
                description="相似度分数低于此值的片段将被过滤，0 表示不过滤",
                group="知识库设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="27",
        type_key="dataset_write",
        title="知识库写入",
        color="#2f54eb",
        category="knowledge",
        description="向知识库写入新片段",
        icon="✎",
        subtitle_hint="写入知识库",
        next_recommendations=["llm", "end"],
        inputs=[
            PortMeta(name="content", label="文档内容"),
            PortMeta(name="metadata", label="元数据", type="object"),
            PortMeta(name="documentId", label="文档 ID"),
        ],
        outputs=[
            PortMeta(name="isSuccess", label="是否成功", type="boolean"),
            PortMeta(name="chunkId", label="片段 ID"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="datasetId",
                label="知识库 ID",
                field_type="text",
                required=True,
                group="知识库设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="211",
        type_key="dataset_delete",
        title="知识库删除",
        color="#2f54eb",
        category="knowledge",
        description="按文档 ID 删除知识库内容",
        icon="🗑",
        subtitle_hint="删除知识库文档",
        next_recommendations=["llm", "end"],
        inputs=[PortMeta(name="documentID", label="文档 ID")],
        outputs=[PortMeta(name="isSuccess", label="是否成功", type="boolean")],
        config_fields=[
            ConfigFieldMeta(
                name="datasetId",
                label="知识库 ID",
                field_type="text",
                required=True,
                group="知识库设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="15",
        type_key="text_processor",
        title="文本处理",
        color="#eb2f96",
        category="component",
        description="文本拼接、截取、替换等处理",
        icon="¶",
        subtitle_hint="文本处理",
        next_recommendations=["llm", "if_else", "end"],
        inputs=[PortMeta(name="input", label="输入")],
        outputs=[PortMeta(name="output", label="输出")],
        config_fields=[
            ConfigFieldMeta(
                name="operation",
                label="操作",
                field_type="select",
                default="concat",
                options=[{"value": "concat"}, {"value": "slice"}, {"value": "replace"}],
                group="文本处理设置",
            ),
            ConfigFieldMeta(name="find", label="查找文本", field_type="text", group="文本处理设置"),
            ConfigFieldMeta(
                name="replaceWith", label="替换为", field_type="text", group="文本处理设置"
            ),
        ],
    ),
    NodeMeta(
        type_code="58",
        type_key="json_stringify",
        title="JSON 序列化",
        color="#a0d911",
        category="component",
        description="把对象转成 JSON 字符串",
        icon="{}",
        subtitle_hint="对象转 JSON 字符串",
        next_recommendations=["code", "llm", "end"],
        inputs=[PortMeta(name="input", label="输入对象")],
        outputs=[PortMeta(name="output", label="JSON 字符串")],
    ),
    NodeMeta(
        type_code="59",
        type_key="json_parser",
        title="JSON 解析",
        color="#a0d911",
        category="component",
        description="把 JSON 字符串解析成对象",
        icon="{ }",
        subtitle_hint="JSON 字符串转对象",
        next_recommendations=["code", "llm", "end"],
        inputs=[PortMeta(name="input", label="JSON 字符串")],
        outputs=[PortMeta(name="output", label="解析对象")],
    ),
    # ---- 循环 / 子图 ----
    NodeMeta(
        type_code="21",
        type_key="loop",
        title="循环",
        color="#722ed1",
        category="logic",
        description="按数组或次数循环执行子图",
        icon="↻",
        subtitle_hint="循环执行",
        next_recommendations=["llm", "if_else", "end"],
        capabilities=NodeCapabilities(has_subgraph=True),
        inputs=[PortMeta(name="input", label="数组输入")],
        outputs=[PortMeta(name="output", label="结果数组")],
        config_fields=[
            ConfigFieldMeta(
                name="loopType",
                label="循环类型",
                field_type="select",
                default="array",
                options=[{"value": "array"}, {"value": "count"}],
                group="循环设置",
            ),
            ConfigFieldMeta(
                name="loopCount",
                label="循环次数",
                field_type="number",
                default=10,
                group="循环设置",
            ),
            ConfigFieldMeta(
                name="parallel",
                label="并发执行",
                field_type="boolean",
                default=False,
                group="循环设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="28",
        type_key="batch",
        title="批处理",
        color="#722ed1",
        category="logic",
        description="并发批量处理数组元素",
        icon="≡",
        subtitle_hint="批量处理",
        next_recommendations=["llm", "end"],
        capabilities=NodeCapabilities(has_subgraph=True),
        inputs=[PortMeta(name="input", label="数组输入")],
        outputs=[PortMeta(name="output", label="结果数组")],
        config_fields=[
            ConfigFieldMeta(
                name="parallelCount",
                label="并发数",
                field_type="number",
                default=5,
                group="批处理设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="9",
        type_key="subworkflow",
        title="子工作流",
        color="#531dab",
        category="workflow",
        description="调用另一个已发布的工作流",
        icon="▣",
        subtitle_hint="调用子流程",
        next_recommendations=["llm", "if_else", "end"],
        capabilities=NodeCapabilities(has_subgraph=True),
        inputs=[PortMeta(name="input", label="输入")],
        outputs=[PortMeta(name="output", label="输出")],
        config_fields=[
            ConfigFieldMeta(
                name="workflowId",
                label="目标工作流 ID",
                field_type="text",
                required=True,
                group="调用设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="20",
        type_key="set_variable",
        title="设置变量",
        color="#1890ff",
        category="knowledge",
        description="给变量赋值",
        icon="ƒ",
        subtitle_hint="给变量赋值",
        next_recommendations=["llm", "if_else", "end"],
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="default", label="出口")],
        config_fields=[
            ConfigFieldMeta(
                name="variableName",
                label="变量名",
                field_type="text",
                required=True,
                group="变量设置",
            ),
            ConfigFieldMeta(name="value", label="值", field_type="text", group="变量设置"),
        ],
    ),
    NodeMeta(
        type_code="40",
        type_key="variable_assign",
        title="变量赋值",
        color="#1890ff",
        category="knowledge",
        description="给变量赋值，与设置变量节点行为一致",
        icon="ƒ",
        subtitle_hint="给变量赋值",
        next_recommendations=["llm", "if_else", "end"],
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="default", label="出口")],
        config_fields=[
            ConfigFieldMeta(
                name="variableName",
                label="变量名",
                field_type="text",
                required=True,
                group="变量设置",
            ),
            ConfigFieldMeta(
                name="variableType",
                label="变量类型",
                field_type="select",
                options=[
                    {"value": "string", "label": "String"},
                    {"value": "number", "label": "Number"},
                    {"value": "boolean", "label": "Boolean"},
                    {"value": "object", "label": "Object"},
                    {"value": "array", "label": "Array"},
                ],
                group="变量设置",
            ),
            ConfigFieldMeta(name="value", label="值", field_type="text", group="变量设置"),
        ],
    ),
    NodeMeta(
        type_code="32",
        type_key="variable_merge",
        title="变量合并",
        color="#1890ff",
        category="logic",
        description="合并多个分支的变量",
        icon="⋈",
        subtitle_hint="合并分支变量",
        next_recommendations=["llm", "end"],
        inputs=[
            PortMeta(name="branch_a", label="分支 A"),
            PortMeta(name="branch_b", label="分支 B"),
        ],
        outputs=[PortMeta(name="merged", label="合并结果")],
    ),
    # ---- 人审 ----
    NodeMeta(
        type_code="60",
        type_key="human_approval",
        title="人工审批",
        color="#fa541c",
        category="control",
        description="中断工作流，等待人工审批后继续",
        icon="👤",
        subtitle_hint="等待人工审批",
        next_recommendations=["llm", "end"],
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="approved", label="通过"), PortMeta(name="rejected", label="拒绝")],
        config_fields=[
            ConfigFieldMeta(
                name="assignee_role", label="审批人角色", field_type="text", group="审批设置"
            ),
            ConfigFieldMeta(
                name="instructions", label="审批说明", field_type="textarea", group="审批设置"
            ),
        ],
    ),
    # ---- 输入 / 输出（对话流） ----
    NodeMeta(
        type_code="13",
        type_key="output",
        title="输出",
        color="#13c2c2",
        category="io",
        description="向对话输出一条中间消息，支持流式",
        icon="◤",
        subtitle_hint="中间消息输出",
        next_recommendations=["llm", "output", "end"],
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[
            PortMeta(name="output", label="消息内容", type="string"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="outputVariables",
                label="输出变量",
                field_type="key_value_list",
                description="结构化输出变量，供下游通过 {{节点.output.变量名}} 引用",
                group="输出设置",
            ),
            ConfigFieldMeta(
                name="content",
                label="输出内容",
                field_type="textarea",
                required=True,
                placeholder="支持 {{node.output.field}} 变量",
                description="内容会作为一条 assistant 消息出现在对话中",
                group="输出设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="18",
        type_key="question",
        title="问答",
        color="#722ed1",
        category="component",
        description="向用户提问并等待回答，回答可供后续节点使用",
        icon="?",
        subtitle_hint="等待用户回答",
        next_recommendations=["llm", "if_else", "output", "end"],
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[
            PortMeta(name="USER_RESPONSE", label="用户回答", type="string"),
            PortMeta(name="QUESTION_DATA", label="回答数据", type="array"),
            PortMeta(name="answer", label="用户回答（兼容）", type="string"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="modleName",
                label="模型",
                field_type="model_picker",
                description="回答类型为「从回复中提取字段」时用于抽取结构化数据",
                group="问答设置",
            ),
            ConfigFieldMeta(
                name="question",
                label="问题内容",
                field_type="textarea",
                required=True,
                placeholder="支持 {{node.output.field}} 变量",
                group="问答设置",
            ),
            ConfigFieldMeta(
                name="answerType",
                label="回答类型",
                field_type="select",
                default="direct",
                options=[
                    {"value": "direct", "label": "直接回答"},
                    {"value": "options", "label": "选项回答"},
                    {"value": "extract", "label": "从回复中提取字段"},
                ],
                description="直接回答：自由文本；选项回答：从预置选项中选择；提取字段：用模型抽取结构",
                group="问答设置",
            ),
            ConfigFieldMeta(
                name="options",
                label="选项",
                field_type="textarea",
                placeholder="每行一个选项，仅「选项回答」使用",
                group="问答设置",
            ),
            ConfigFieldMeta(
                name="extractFields",
                label="提取字段",
                field_type="textarea",
                placeholder="每行一个字段名，仅「从回复中提取字段」使用",
                description="模型会按这些字段名从用户回复中抽取 JSON",
                group="问答设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="30",
        type_key="input",
        title="输入",
        color="#722ed1",
        category="io",
        description="等待用户输入一段文本",
        icon="⌨",
        subtitle_hint="等待用户输入",
        next_recommendations=["llm", "if_else", "output", "end"],
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[
            PortMeta(name="USER_RESPONSE", label="用户输入", type="string"),
            PortMeta(name="QUESTION_DATA", label="输入数据", type="array"),
            PortMeta(name="answer", label="用户输入（兼容）", type="string"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="prompt",
                label="提示内容",
                field_type="textarea",
                placeholder="展示给用户的输入提示",
                group="输入设置",
            ),
        ],
    ),
    # ---- 会话 / 消息 ----
    NodeMeta(
        type_code="39",
        type_key="create_conversation",
        title="创建会话",
        color="#2f54eb",
        category="conversation",
        description="创建一个新的会话",
        icon="＋",
        subtitle_hint="创建会话",
        next_recommendations=["create_message", "end"],
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="conversation_id", label="会话 ID")],
        config_fields=[
            ConfigFieldMeta(
                name="title",
                label="会话标题",
                field_type="text",
                placeholder="留空则自动生成",
                group="会话设置",
            ),
            ConfigFieldMeta(
                name="app_id",
                label="应用 ID",
                field_type="text",
                placeholder="留空则用当前应用",
                group="会话设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="51",
        type_key="update_conversation",
        title="更新会话",
        color="#2f54eb",
        category="conversation",
        description="更新会话标题等元信息",
        icon="✎",
        subtitle_hint="更新会话",
        capabilities=NodeCapabilities(has_outputs=False),
        inputs=[PortMeta(name="conversation_id", label="会话 ID")],
        config_fields=[
            ConfigFieldMeta(name="title", label="新标题", field_type="text", group="会话设置"),
        ],
    ),
    NodeMeta(
        type_code="52",
        type_key="delete_conversation",
        title="删除会话",
        color="#2f54eb",
        category="conversation",
        description="删除一个会话及其全部消息",
        icon="✕",
        subtitle_hint="删除会话",
        capabilities=NodeCapabilities(has_outputs=False),
        inputs=[PortMeta(name="conversation_id", label="会话 ID")],
    ),
    NodeMeta(
        type_code="53",
        type_key="query_conversation_list",
        title="查询会话列表",
        color="#2f54eb",
        category="conversation",
        description="查询当前用户的会话列表",
        icon="☰",
        subtitle_hint="查询会话列表",
        outputs=[PortMeta(name="conversations", label="会话列表")],
        config_fields=[
            ConfigFieldMeta(
                name="app_id",
                label="应用 ID",
                field_type="text",
                placeholder="留空则不限",
                group="查询设置",
            ),
            ConfigFieldMeta(
                name="limit", label="条数上限", field_type="text", default=20, group="查询设置"
            ),
        ],
    ),
    NodeMeta(
        type_code="54",
        type_key="query_conversation_history",
        title="查询会话历史",
        color="#2f54eb",
        category="history",
        description="查询某个会话的历史消息",
        icon="☷",
        subtitle_hint="查询会话历史",
        inputs=[PortMeta(name="conversation_id", label="会话 ID")],
        outputs=[PortMeta(name="messages", label="消息列表")],
        config_fields=[
            ConfigFieldMeta(
                name="limit", label="条数上限", field_type="text", default=100, group="查询设置"
            ),
        ],
    ),
    NodeMeta(
        type_code="55",
        type_key="create_message",
        title="创建消息",
        color="#2f54eb",
        category="message",
        description="向会话追加一条消息",
        icon="↑",
        subtitle_hint="创建消息",
        inputs=[
            PortMeta(name="conversation_id", label="会话 ID"),
            PortMeta(name="content", label="内容"),
        ],
        outputs=[PortMeta(name="message_id", label="消息 ID")],
        config_fields=[
            ConfigFieldMeta(
                name="role",
                label="角色",
                field_type="select",
                default="user",
                options=[
                    {"value": "user", "label": "用户"},
                    {"value": "assistant", "label": "助手"},
                    {"value": "system", "label": "系统"},
                    {"value": "tool", "label": "工具"},
                ],
                group="消息设置",
            ),
            ConfigFieldMeta(
                name="content",
                label="消息内容",
                field_type="textarea",
                placeholder="支持 {{node.output.field}} 变量",
                group="消息设置",
            ),
        ],
    ),
    NodeMeta(
        type_code="56",
        type_key="update_message",
        title="更新消息",
        color="#2f54eb",
        category="message",
        description="更新消息内容",
        icon="✎",
        subtitle_hint="更新消息内容",
        capabilities=NodeCapabilities(has_outputs=False),
        inputs=[PortMeta(name="message_id", label="消息 ID")],
        config_fields=[
            ConfigFieldMeta(
                name="content", label="新内容", field_type="textarea", group="消息设置"
            ),
        ],
    ),
    NodeMeta(
        type_code="57",
        type_key="delete_message",
        title="删除消息",
        color="#2f54eb",
        category="message",
        description="删除一条消息",
        icon="✕",
        subtitle_hint="删除消息",
        capabilities=NodeCapabilities(has_outputs=False),
        inputs=[PortMeta(name="message_id", label="消息 ID")],
    ),
    NodeMeta(
        type_code="37",
        type_key="query_message_list",
        title="查询消息列表",
        color="#2f54eb",
        category="message",
        description="按游标分页查询会话消息",
        icon="☰",
        subtitle_hint="查询消息列表",
        inputs=[
            PortMeta(name="conversation_id", label="会话 ID"),
            PortMeta(name="beforeId", label="起始游标"),
            PortMeta(name="afterId", label="结束游标"),
        ],
        outputs=[
            PortMeta(name="messageList", label="消息列表"),
            PortMeta(name="firstId", label="首条 ID"),
            PortMeta(name="lastId", label="末条 ID"),
            PortMeta(name="hasMore", label="是否还有更多"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="limit", label="条数上限", field_type="text", default=20, group="查询设置"
            ),
        ],
    ),
    NodeMeta(
        type_code="38",
        type_key="clear_context",
        title="清空上下文",
        color="#2f54eb",
        category="history",
        description="清空当前会话的上下文",
        icon="⌫",
        subtitle_hint="清空会话上下文",
        capabilities=NodeCapabilities(has_outputs=False),
        inputs=[PortMeta(name="conversation_id", label="会话 ID")],
    ),
    # ---- 占位（暂不可用，前端置灰） ----
    NodeMeta(
        type_code="12",
        type_key="database_sql",
        title="SQL 自定义",
        color="#8c8c8c",
        category="database",
        description="自定义 SQL 访问平台数据表（当前未启用）",
        icon="SQL",
        subtitle_hint="自定义 SQL",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="result", label="执行结果")],
        config_fields=[
            ConfigFieldMeta(
                name="sql", label="SQL 语句", field_type="code_editor", group="SQL 设置"
            ),
        ],
        available=False,
        unavailable_reason="当前部署未启用数据库节点，请使用 HTTP 节点调用自有接口替代",
    ),
    NodeMeta(
        type_code="46",
        type_key="database_create",
        title="新增数据",
        color="#8c8c8c",
        category="database",
        description="向数据表插入一行记录（当前未启用）",
        icon="＋",
        subtitle_hint="新增数据",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="record_id", label="记录 ID")],
        available=False,
        unavailable_reason="当前部署未启用数据库节点，请使用 HTTP 节点调用自有接口替代",
    ),
    NodeMeta(
        type_code="42",
        type_key="database_update",
        title="更新数据",
        color="#8c8c8c",
        category="database",
        description="按条件更新数据表记录（当前未启用）",
        icon="✎",
        subtitle_hint="更新数据",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="affected", label="影响行数")],
        available=False,
        unavailable_reason="当前部署未启用数据库节点，请使用 HTTP 节点调用自有接口替代",
    ),
    NodeMeta(
        type_code="43",
        type_key="database_query",
        title="查询数据",
        color="#8c8c8c",
        category="database",
        description="按条件查询数据表记录（当前未启用）",
        icon="☰",
        subtitle_hint="查询数据",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="rows", label="记录列表")],
        available=False,
        unavailable_reason="当前部署未启用数据库节点，请使用 HTTP 节点调用自有接口替代",
    ),
    NodeMeta(
        type_code="44",
        type_key="database_delete",
        title="删除数据",
        color="#8c8c8c",
        category="database",
        description="按条件删除数据表记录（当前未启用）",
        icon="✕",
        subtitle_hint="删除数据",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="affected", label="影响行数")],
        available=False,
        unavailable_reason="当前部署未启用数据库节点，请使用 HTTP 节点调用自有接口替代",
    ),
    NodeMeta(
        type_code="26",
        type_key="long_term_memory",
        title="长期记忆",
        color="#8c8c8c",
        category="memory",
        description="读写跨会话长期记忆（当前未启用）",
        icon="◎",
        subtitle_hint="长期记忆",
        inputs=[PortMeta(name="default", label="入口")],
        outputs=[PortMeta(name="memory", label="记忆内容")],
        available=False,
        unavailable_reason="当前部署尚未接入长期记忆存储，可先用会话/消息节点维护上下文",
    ),
    NodeMeta(
        type_code="212",
        type_key="async_task",
        title="异步任务",
        color="#8c8c8c",
        category="logic",
        description="触发任务中心的预定义任务，不阻塞主流程（当前未启用）",
        icon="⏱",
        subtitle_hint="触发异步任务",
        inputs=[PortMeta(name="params", label="任务参数", type="object")],
        outputs=[
            PortMeta(name="taskId", label="任务 ID", type="string"),
            PortMeta(name="msg", label="提示信息", type="string"),
        ],
        config_fields=[
            ConfigFieldMeta(
                name="taskId",
                label="任务",
                field_type="text",
                description="选择任务中心预定义任务",
                group="任务设置",
            ),
        ],
        available=False,
        unavailable_reason="当前部署未接入任务中心，暂时无法创建异步任务实例",
    ),
    NodeMeta(
        type_code="213",
        type_key="image_generate",
        title="图像生成",
        color="#8c8c8c",
        category="image",
        description="根据提示词生成图像（当前未启用）",
        icon="🖼",
        subtitle_hint="生成图像",
        inputs=[
            PortMeta(name="prompt", label="提示词"),
            PortMeta(name="image", label="参考图", type="image"),
        ],
        outputs=[PortMeta(name="image_url", label="图像地址", type="string")],
        available=False,
        unavailable_reason="当前部署未接入图像生成服务",
    ),
    NodeMeta(
        type_code="23",
        type_key="image_canvas",
        title="画板",
        color="#8c8c8c",
        category="image",
        description="在画布上编辑图像（当前未启用）",
        icon="🎨",
        subtitle_hint="编辑画板",
        inputs=[PortMeta(name="image", label="图像", type="image")],
        outputs=[PortMeta(name="image_url", label="图像地址", type="string")],
        available=False,
        unavailable_reason="当前部署未接入图像编辑服务",
    ),
    NodeMeta(
        type_code="214",
        type_key="image_cutout",
        title="抠图",
        color="#8c8c8c",
        category="image",
        description="移除图像背景（当前未启用）",
        icon="✂",
        subtitle_hint="图像抠图",
        inputs=[PortMeta(name="image", label="图像", type="image")],
        outputs=[PortMeta(name="image_url", label="图像地址", type="string")],
        available=False,
        unavailable_reason="当前部署未接入图像处理服务",
    ),
    NodeMeta(
        type_code="215",
        type_key="prompt_optimize",
        title="提示词优化",
        color="#8c8c8c",
        category="image",
        description="用模型优化图像提示词（当前未启用）",
        icon="✎",
        subtitle_hint="优化提示词",
        inputs=[PortMeta(name="prompt", label="提示词")],
        outputs=[PortMeta(name="optimized_prompt", label="优化后提示词", type="string")],
        available=False,
        unavailable_reason="当前部署未接入图像生成服务",
    ),
    NodeMeta(
        type_code="216",
        type_key="image_enhance",
        title="画质提升",
        color="#8c8c8c",
        category="image",
        description="提升图像清晰度（当前未启用）",
        icon="↑",
        subtitle_hint="提升画质",
        inputs=[PortMeta(name="image", label="图像", type="image")],
        outputs=[PortMeta(name="image_url", label="图像地址", type="string")],
        available=False,
        unavailable_reason="当前部署未接入图像处理服务",
    ),
    NodeMeta(
        type_code="217",
        type_key="video_generate",
        title="视频生成",
        color="#8c8c8c",
        category="media",
        description="根据提示词生成视频（当前未启用）",
        icon="▶",
        subtitle_hint="生成视频",
        inputs=[PortMeta(name="prompt", label="提示词")],
        outputs=[PortMeta(name="video_url", label="视频地址", type="string")],
        available=False,
        unavailable_reason="当前部署未接入视频生成服务",
    ),
    NodeMeta(
        type_code="218",
        type_key="video_extract_audio",
        title="视频提取音频",
        color="#8c8c8c",
        category="media",
        description="从视频中提取音频（当前未启用）",
        icon="♪",
        subtitle_hint="提取音频",
        inputs=[PortMeta(name="video", label="视频", type="string")],
        outputs=[PortMeta(name="audio_url", label="音频地址", type="string")],
        available=False,
        unavailable_reason="当前部署未接入音视频处理服务",
    ),
    NodeMeta(
        type_code="219",
        type_key="video_frame",
        title="视频抽帧",
        color="#8c8c8c",
        category="media",
        description="按间隔抽取视频帧（当前未启用）",
        icon="▣",
        subtitle_hint="视频抽帧",
        inputs=[PortMeta(name="video", label="视频", type="string")],
        outputs=[PortMeta(name="frames", label="帧列表", type="array")],
        available=False,
        unavailable_reason="当前部署未接入音视频处理服务",
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
