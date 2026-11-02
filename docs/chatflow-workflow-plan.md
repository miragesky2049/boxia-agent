# 画布双形态支持计划：工作流（Workflow）与对话流（Chatflow）

> 目标：画布同时支持 coze 的两种流程形态，可通过类型切换器切换；两种流程的节点库、配置项、试运行方式和用户端运行体验都完整可用。
>
> 事实来源：2026-11-02 对 coze 实机画布的逐节点截图分析（截图见 `docs/assets/chatflow/`）+ 本地代码逐文件盘点。
>
> 关联文档：`docs/canvas-roadmap.md`（画布基础能力 T1–T18 已完成）。

---

## 一、coze 实机梳理结论

### 1.1 两种形态在 coze 中的入口

- 同一项目内可同时存在工作流和对话流：资源侧栏「工作流」分组的 `+` 菜单提供 **新建工作流 / 新建对话流 / 导入资源库文件** 三项（`assets/chatflow/coze-add-resource-menu.png`）。
- 应用画布的「业务逻辑」是一个对话流（含会话管理、变量、输出节点），见 `coze-chatflow-initial.png`。
- 独立对话流编辑器仍是同一套画布，只是没有应用资源栏，见 `coze-chatflow-7703450571454775346.png`（WorkflowChat003）。

### 1.2 节点库全量（实机，2026-11-02 二次补测）

对对话流编辑器（`workflow_id=7703450571454775346`）和工作流编辑器（`workflow_id=7702003162006077455`）分别打开「添加节点」面板并滚动到底，逐项比对，**两者节点库完全相同，共 57 项**。截图见 `explore-nodepanel.png`、`wf-panel-s0.png`、`wf-panel-s2.png`、`wf-panel-s6.png`、`wf-panel-mid3/6.png`。

| 分组 | 节点 |
| --- | --- |
| 无分组 | 大模型、插件 |
| 工作流 | 工作流（调用子工作流） |
| 业务逻辑 | 代码、选择器、意图识别、循环、批处理、变量聚合、异步任务 |
| 输入&输出 | 输入、输出 |
| 数据库 | SQL 自定义、新增数据、更新数据、查询数据、删除数据 |
| 知识库&数据 | 知识库写入、知识库检索、知识库删除、变量赋值、长期记忆写入、长期记忆检索 |
| 图像处理 | 图像生成、画板、抠图、提示词优化、画质提升、更多图像插件 |
| 音视频处理 | 视频生成、视频提取音频、视频抽帧 |
| 组件 | 问答、文本处理、HTTP 请求、JSON 序列化、JSON 反序列化 |
| 会话管理 | 创建会话、修改会话、删除会话、查询会话列表 |
| 会话历史 | 查询会话历史、清空会话历史 |
| 消息 | 创建消息、修改消息、删除消息、查询消息列表 |

**修正原结论**
- 原记录中的「触发器」分组在当前 coze 版本节点库中不存在；触发器已移到应用配置/发布管理侧（`触发器管理`），不作为画布节点。
- 原计划认为"工作流编辑器不显示输出/问答/会话消息节点"**与实际不符**：实机工作流编辑器的节点库同样包含输出、问答、会话管理、会话历史、消息全部节点。
- `知识库删除`、`变量赋值`、`长期记忆写入/检索`、`画板` 等属于当前版本新增，需补进本地节点元数据。

### 1.3 应用配置页操作链路（2026-11-02 实机补测）

应用 `对话流应用001` 的配置页由「顶部形态切换 + 左侧资源栏 + 画布 + 设置 + 发布」组成，完整链路如下：

| 层级 | 入口 | 实机行为 | 对本地项目的含义 |
| --- | --- | --- | --- |
| 应用壳层 | 顶部 `业务逻辑 / 用户界面` | 业务逻辑 = 画布；用户界面 = UI 搭建类型选择（小程序和 H5 / 桌面网页 → 开始搭建） | 本期只做业务逻辑；UI Builder 明确标记为范围外 |
| 资源栏 | 工作流 `+` | 新建工作流 / 新建对话流 / 导入资源库文件 | 资源级双类型；本地目前只有应用级 `flow_type`，资源库/子流程创建后续补 |
| 资源栏 | 插件 / 数据 | 空态 + `+`；插件为工具资源，数据为知识库/数据库 | 已有 tool/knowledge 资源，本期不重做 |
| 资源栏 | 引用关系 | 弹出「资源引用」面板，按工作流查看引用关系 | 可选能力，本期不做 |
| 设置 | 会话管理 | `调试数据 / API` 两个数据域；会话列表（含 `Default`）；「会话节点创建」区展示创建会话节点产生的会话；右侧为该会话完整聊天记录 | 试运行会话必须与线上数据域隔离；会话切换 + 历史查看是试运行面板的一部分 |
| 设置 | 变量 | `变量设置 / 测试数据`；变量分三层：应用变量（每次新请求初始化为默认值）、用户变量（按用户持久化）、系统变量（只读、按渠道自动产生，如 `sys_uuid`）；底部保存 | 原计划里的“会话变量”需按这三层重新定义 |
| 画布 | 添加节点 | 分组：大模型/插件/工作流、业务逻辑、输入&输出、数据库、知识库&数据、音视频处理、组件、会话管理、会话历史、消息、触发器 | 节点库分组需整体对齐，不能只补 output/question |
| 画布 | 试运行 | 右侧聊天面板：选择会话、历史消息、输入框；`查看日志` 打开底部调试日志抽屉 | T4-1 需要会话切换 + 历史恢复 + 日志入口 |
| 画布 | 角色 | 角色信息、头像、开场白、预置问题、用户问题建议、背景图片、Agent 声音、用户输入方式 | 用户端聊天体验配置；本期只做开场白/建议占位，或标记范围外 |
| 顶部 | 发布 | 最近发布版本、发布管理、分析、日志、触发器管理、Playground 调试、API、去发布 | 本地已有 graph publish；应用级发布/渠道/日志需单独立项，本期只做最小闭环 |

### 1.4 关键节点配置（实机）

**开始节点**（0.0 实机复核）
- 右侧面板分 `基础设置 / 触发器设置` 两页；`基础设置` 下为输入变量表。
- 对话流内置两个系统输入：`USER_INPUT`（用户本轮输入）、`CONVERSATION_NAME`（会话名），均可勾选是否必填。
- 可继续 `+` 自定义输入变量，每个变量有名称/类型（String 等）/必填；实机输入表未展示必填默认值以外的字段。

**大模型节点**（实机复核）
- 运行模式：`单次 / 批处理`。
- 模型选择器（实机为 `豆包·2.0-pro`）；技能区（当前提示"暂不支持技能"）。
- 输入区（实机为 `input`）、视觉理解输入、系统提示词、用户提示词。
- 输出区：`输出格式`（实机为 JSON）、输出变量 `output` / `reasoning_content`，以及 `支持流式` 开关。
- 底部为 `异常处理` 配置。

**选择器节点**（实机复核）
- 条件分支：可新增多个「如果」条件组，右侧为「否则」分支。
- 每个条件由变量选择器（如 `大模型·output`）+ 运算符（实机为「为空/不为空」类）+ 比较值组成。
- 与本地 `if_else` 的 `case_list` 语义一致，但 coze 支持多条件组 + 否则兜底。

**输出节点**（实机复核，修正原结论）
- 面板说明："节点从『消息』更名为『输出』，支持中间过程的消息输出，支持流式和非流式两种方式"。
- 实际配置只有两块：`输出变量`（结构化变量表，如 `output = 大模型·output`）+ `输出内容`（`{{变量名}}` / `{{变量名.子变量名}}` / `{{变量名[数组索引]}}` 模板）。
- **实机没有独立的「流式输出」开关**；流式能力由上游大模型的 `支持流式` 和结束节点的 `流式输出` 控制。
- 一个对话流可以挂多个输出节点，对应聊天中多条中间消息。

**结束节点**（实机复核）
- 二选一：`返回变量` / `返回文本`（实机当前为返回文本）。
- 两种模式下都存在 `输出变量` 表（实机 `output = 大模型·output`）。
- `返回文本` 额外有 `回答内容` 模板（实机 `{{output}}`）+ `流式输出` 开关（实机为开启）。

**问答节点**（实机复核，`node-问答.png/txt`）
- 节点会先做一次模型调用生成提问，再等待用户回答；顶部有模型选择（实机 `豆包·2.0·lite`）。
- `提问内容` 支持 `{{变量名}}` 模板；回答类型三选一：
  1. `直接回答`：用户自由文本；
  2. `选项回答`：配置预置选项；
  3. `从回复中提取字段`：用模型从用户回复中抽取结构化字段。
- 输出固定两个变量：`USER_RESPONSE`（String）、`QUESTION_DATA`（Array<Object>，含 `content_type/content`）。
- 运行上等价于一次中断（interrupt）后由下一条用户消息恢复；工作流 API 无 resume 通道，因此该节点在纯工作流执行中需阻断并给出可读错误。

**试运行**（实机复核）
- 右侧聊天面板：顶部 `选择会话`（实机含 `Default`），中间为所选会话的完整历史，底部为消息输入框。
- `查看日志` 打开底部调试日志抽屉，可按轮次/节点查看执行日志。
- 运行前先做节点级校验，底部「错误列表」逐条列出（如"选择器：变量不可为空"），点击可定位节点。
- 对话流试运行为聊天窗口，多轮输入；工作流试运行为一次性输入表单。

### 1.5 两种形态的差异矩阵

| 维度 | 工作流 Workflow | 对话流 Chatflow |
| --- | --- | --- |
| 触发方式 | 单次 API / 被其他流程调用 | 用户消息驱动，可多轮 |
| 开始节点系统参数 | 无（仅自定义） | `USER_INPUT` + `CONVERSATION_NAME` |
| 结束节点 | 返回变量 | 返回变量 / 返回文本（可流式） |
| 中间消息 | 无 | 输出节点，一条流程可多条；输出变量 + 内容模板 |
| 等待用户输入 | 不支持 | 问答节点（中断 + 恢复） |
| 会话上下文 | 无（可由节点显式传参） | `conversation_id` / `thread_id` 贯穿 |
| 会话/消息节点 | 节点库可用，但无聊天通道，需显式会话名 | 会话管理、会话历史、消息 CRUD 全可用 |
| 变量体系 | 无应用/用户变量；仅自定义输入 | 应用变量（每请求初始化）/ 用户变量（按用户持久化）/ 系统变量（只读、按渠道产生） |
| 试运行 | 表单输入 → 最终输出 | 聊天窗口 + 选择会话 + 查看日志 |
| 用户端 | 表单运行页 | 聊天页（含开场白、预置问题、用户问题建议） |
| 画布工具 | 添加节点 / 封装工作流(Ctrl+G) / 试运行 | 添加节点 / 角色 / 试运行 |
| 节点库 | **与对话流完全相同（57 项）** | **与工作流完全相同（57 项）** |

> 结论：两种形态**共用同一套图结构、同一套节点库和执行器**，差异集中在「开始/结束节点系统字段 + 运行/中断语义 + 试运行界面 + 应用壳层（角色/变量/会话管理）」。因此实现策略是"一个画布、一个执行引擎、按 flow_type 切换运行语义与壳层能力"，而不是两套编辑器，也不按类型裁剪节点库。

### 1.6 创建入口与两类应用壳层对照（2026-11-02 实机补测）

**创建入口（coze 工作台「项目开发」）**
- 右上角 `+ 项目` / 左侧 `创建` 打开同一创建弹窗，顶层二选一：
  - `创建智能体`：对话式智能体，直接进入 Bot 编排；
  - `创建应用`：包含用户界面的完整应用，低代码搭建，进入应用 IDE。
- 进入应用 IDE 后，`业务逻辑` 默认落到该应用绑定的流程画布；应用名称/图标/流程类型在应用壳层统一管理。
- 资源侧栏「工作流 `+`」可在同一应用内继续 `新建工作流 / 新建对话流 / 导入资源库文件`，说明**流程类型是资源级属性**，应用级 `flow_type` 只是"主流程"类型。

**对话流应用 vs 工作流应用壳层差异（实机）**

| 区域 | 对话流应用（对话流应用001） | 工作流应用（工作流应用001） |
| --- | --- | --- |
| 顶部 | `业务逻辑 / 用户界面`，右上发布 | 同左 |
| 左侧资源 | 工作流、插件、数据、设置（会话管理、变量） | 同左（工作流应用也显示会话管理与变量） |
| 画布底部 | `添加节点`、`角色`、`试运行` | `添加节点`、`试运行`（无角色） |
| 开始节点 | `USER_INPUT` + `CONVERSATION_NAME` + 自定义输入 | 仅自定义输入（如实机 `input`） |
| 结束节点 | 返回变量 / 返回文本 + 流式输出 | 返回变量 / 返回文本 |
| 试运行 | 右侧聊天面板 + 选择会话 + 历史 + 查看日志 | 右侧表单：可用测试集、JSON 模式、AI 补全、保存为测试集 + 查看日志 |
| 角色配置 | 有：角色信息、开场白、预置问题、用户问题建议、背景图、Agent 声音、输入方式 | 无 |
| 节点库 | 全部 57 项 | **同样全部 57 项（实机修正，不裁剪）** |

**创建入口优化结论**
- 本地当前用 `Select` 选择"工作流应用/对话流应用/智能体"三种模板（`AppListPage.tsx:13-30`），问题：
  1. 类型差异只靠一行描述，用户看不到创建后的画布/运行形态；
  2. "智能体"与"工作流"共用 `workflow` 画布，但列表只显示工作流/对话流，语义不一致；
  3. 创建后不区分初始画布，用户需要自己理解 `USER_INPUT`、输出节点等差异。
- 建议改为 coze 风格的**卡片式类型选择**（仅保留 `工作流 / 对话流` 两种本期可完整支持的形态），每张卡片展示：适用场景、初始节点、试运行形态；选择后直接创建并按类型初始化画布。
- "创建并进入编排"保留，创建成功后进入画布；列表保留类型徽标并新增类型筛选。

**两类应用的初始画布建议**
- 工作流：`开始(自定义输入) → 结束(返回变量)`。
- 对话流：`开始(USER_INPUT / CONVERSATION_NAME) → 大模型 → 输出 → 结束(返回文本 + 流式输出)`，或在空白画布上至少放 `开始` 与 `结束`，并高亮系统输入提示。

**工作流编辑器补充事实**
- 工作流编辑器底部比对话流多一个 `封装工作流`（Ctrl+G）入口；试运行为右侧表单（可用测试集 / JSON 模式 / AI 补全 / 保存为测试集 + 查看日志），无角色配置。
- 工作流画布可以放置输出/问答/会话/消息节点（节点库一致），但试运行和 API 运行没有聊天通道；这类节点只能靠显式参数工作，问答节点无法等待用户回答。

### 1.7 新增节点配置事实（实机逐节点抓取）

以下节点本地尚无元数据或配置字段不完整，抓取结果作为实现依据（对应 `docs/assets/chatflow/node-*.png/txt`）：

| 节点 | 输入 | 输出 | 关键配置 |
| --- | --- | --- | --- |
| 意图识别 | `query` | `classificationId`(Integer) | 模式（极速/完整）、模型、会话历史、意图选项列表 + `其他` 兜底、异常处理 |
| 异步任务 | 任务参数（由所选任务定义） | `taskId`(String)、`msg`(String) | 选择「任务中心」预定义任务，仅支持 1 个任务；不阻塞主流程 |
| SQL 自定义 | 用户变量表 | `rowNum`(Integer)、自定义输出变量 | 绑定 1 张数据表 + SQL 模板（`{{变量}}` 引用） |
| 新增数据 | 自定义字段表 | `outputList`(Array<Object>)、`rowNum`(Integer) | 绑定 1 张数据表 + 字段映射 |
| 更新数据 | 主键/条件 + 字段值 | `rowNum`(Integer) | 绑定 1 张数据表 |
| 查询数据 | 条件变量表 | `outputList`(Array<Object>)、`rowNum` | 绑定 1 张数据表 |
| 删除数据 | 条件变量表 | `rowNum`(Integer) | 绑定 1 张数据表 |
| 知识库写入 | 文档内容 | `isSuccess`(Boolean) | 绑定 1 个文档类型知识库 |
| 知识库删除 | `documentID`(String) | `isSuccess`(Boolean) | 绑定 1 个文档类型知识库 |
| 长期记忆写入 | `messageList`(Array<Object>) | `isSuccess`(Boolean) | 选择记忆库 |
| 长期记忆检索 | `query`(String)、`limit`（必填） | `outputList`(Array<Object>) | 选择记忆库 |
| 变量赋值 | 任意变量 | 同入参 | 变量名/值列表，写入当前作用域 |
| 查询消息列表 | `beforeId`、`afterId` | `messageList`、`firstId`、`lastId`、`hasMore` | 会话名由上下文或上游提供 |

> 数据库/知识库/长期记忆节点均依赖 coze 平台侧资源（数据表、知识库、记忆库），本地无对应存储，按平台约定只做元数据 + 禁用态，不接关系库。

---

## 二、本地现状盘点

### 2.1 已有能力（无需重做）

- 画布：FlowGram `FreeLayoutEditor`，节点元数据以后端 `backend/internal/domain/canvas/node_meta.py` 为事实源，前端动态渲染端口和配置（`frontend/admin/src/pages/apps/AppEditPage.tsx`）。
- 执行器：LangGraph 编译 + 19 类节点 handler + ErrorPolicy + checkpointer + 人审 `interrupt()` + 子图（`backend/internal/domain/graph/`）。
- 流式：admin debug SSE（`node_start/node_end/llm_token/result`，`backend/web/admin/routers/apps_admin.py`）；用户聊天 SSE（`run_start/llm_*/tool_*/result/final`，`backend/internal/application/apps/chat_service.py`）。
- 会话与消息仓储：`ConversationRepository` / `MessageRepository`，表见 `migrations/versions/0044_conversation_message.py`。
- 节点元数据已含：start/end/llm/http/if_else/code/dataset/dataset_write/text_processor/json_*/loop/batch/subworkflow/set_variable/variable_merge/human_approval/agent_loop，以及 9 个会话/消息节点。

### 2.2 关键缺口

| # | 缺口 | 状态 | 证据/说明 |
| --- | --- | --- | --- |
| G1 | 应用无 `flow_type`，创建接口不接收类型 | 已完成 | 迁移 `0049_application_flow_type`；service 校验 + API + 前端类型链路 |
| G2 | 画布无类型切换器 | 已完成 | 切换器、系统变量、后端切换校验、按类型初始化画布；已按实机回退节点裁剪，两种形态均展示全部节点 |
| G3 | 对话流系统输入缺失 | 已完成 | `RuntimeEnv` / `run_chatflow_stream` 注入 `USER_INPUT` / `CONVERSATION_NAME` / `CONVERSATION_ID` |
| G4 | 输出节点（type=13）未实现 | 已完成 | `nodes/output.py` + `test_chatflow_nodes.py` |
| G5 | 问答节点（type=18）未实现 | 已完成 | `nodes/question.py` + interrupt/resume 单测；支持模型选择、`direct/options/extract` 三种回答类型，输出对齐 coze `USER_RESPONSE`/`QUESTION_DATA` |
| G6 | 意图识别（22）、异步任务、数据库 CRUD、知识库删除、长期记忆缺失 | 部分完成 | 意图识别（22）handler + 动态出口、知识库删除（211）已落地；数据库 5 节点、长期记忆（26）、异步任务（212）以禁用态元数据占位，待外部能力就绪 |
| G7 | 对话流无图驱动流式入口 | 已完成 | `POST /agents/{id}/chatflow/run/stream` + `run_chatflow_stream`；入口已校验 `flow_type` |
| G8 | 节点执行上下文无 conversation_id | 已修复 | 见第四节 BUG-01 |
| G9 | 变量体系无存储与求值命名空间 | 已完成（后端 + admin 变量面板） | 三层变量落地：`application.variables` JSONB、`application_user_variable` 表、`{{variables.xxx}}` / `{{system.XXX}}` 命名空间；admin `VariablesDrawer` 支持定义与用户取值编辑 |
| G10 | 用户端无中间消息/问答等待 UI | 已完成 | `ChatPage.tsx` 消费 `output_message`/`question`：中间输出独立气泡，问答渲染选项按钮并走 `resume={answer}` 续跑 |
| G11 | 结束节点无“返回文本/流式”行为 | 已完成 | `end.py` 支持 `returnType=text/variables` + `stream` 推送 `output_message` |
| G12 | 创建入口未区分流程形态 | 已完成 | 卡片式二选一 + 按类型默认画布 + 列表类型筛选 |
| G13 | admin 无对话流聊天式试运行面板 | 已完成 | `ChatflowDebugPanel.tsx`：多轮气泡、问答选项、会话/线程复用、错误提示；日志仍走底部面板 |
| G14 | 试运行会话数据域未隔离 | 已完成 | `conversation.channel=debug` + 试运行自动创建 debug 会话；消息 run_id 置空避免 run 外键约束 |
| G15 | 类型切换/保存缺后端兼容校验 | 已完成 | `update_application` 校验最新图：对话流→工作流禁止专属节点；工作流→对话流要求开始+结束 |
| G16 | 应用级发布/渠道/日志缺失 | 范围外/后续 | coze 有发布管理、分析、日志、触发器管理、Playground、API；本期只做 graph publish 最小闭环 |
| G17 | 节点库分组未对齐 coze | 已完成（现有节点） | 分类改为 basic/ai/plugin/workflow/logic/io/control/knowledge/component/conversation/history/message/database/memory/image/media/misc；数据库/长期记忆/图像/音视频分组以禁用态节点展示 |

### 2.3 实施进展（2026-11-02）

- **已完成**：Phase 0 全部（迁移/仓储/服务/API/前端类型/卡片创建/类型筛选）；Phase 1 全部（Segmented、节点可见性、系统变量、切换删除确认、后端校验、按类型默认画布）；Phase 2 的 T2-1/T2-2/T2-3/T2-4/T2-6 主链路/T2-7 线程归属/T2-8 调试会话隔离（后端）；Phase 4 的 T4-1 对话流试运行面板、T4-6 SSE 事件扩展；Phase 5 全部（用户端 chatflow SSE 多轮对话、问答选项续跑、应用卡片类型徽标）。
- **已完成（本轮补齐）**：T2-1 请求级预检前移到 `StreamingResponse` 之前（`prepare_chatflow_run`：应用类型、message/resume 组合、会话归属、thread_id 归属均返回 JSON 4xx）；T2-6 统一 `run_id` 审计字段、resume 复用中断 run、用户消息含 resume 回答落库一次、END 流式文本落库、中断/成功均更新 `conversation.updated_at`。
- **未开始**：Phase 6 中依赖外部能力的跟踪项（admin vitest 历史用例修复）。
- **验证**：后端全量 `pytest` 428 例通过；`alembic upgrade head` 到 `0050_conversation_channel`；admin/user `npm run typecheck` 通过；用户端 `npm run test` 6 例通过。admin `npm run test` 仍有 1 例历史用例 `capabilities.test.ts`（期望 start 可复制，实际已在 0373051 改为不可复制）与 2 个 lottie/jsdom 环境失败，均与本方案改动无关。
- **2026-11-02 二次实机补测（工作流编辑器）**：工作流节点库与对话流逐项比对一致；`知识库删除/变量赋值/长期记忆写入/长期记忆检索/画板` 需补元数据；当前版本无触发器节点分组。据此修订 §1.2、§1.5、§1.6、T1-2、T1-3、§3.2、§3.8 与验收清单——**不再按 flow_type 裁剪节点库**。
- **2026-11-02 三轮已实施（变量体系 / 意图识别 / 禁用节点占位）**：① 变量三层落地——迁移 `0051_application_variables`、仓储/服务/admin API、`EvalContext` 新增 `variables/system` 命名空间、Runtime 注入并回写用户变量、admin 变量抽屉四 Tab；② 意图识别——`nodes/intent.py`、Compiler `INTENT` 条件边、元数据与前端意图列表编辑器/动态出口；③ 数据库 5 节点与长期记忆节点以 `available=False` 元数据 + 前端置灰占位，契约测试改为只强校验可用节点有 handler。验证：后端全量 `pytest` 396 例通过（`test_loop_parallel_break_continue` 并行取消用例存在偶发 flake，单跑通过），admin `typecheck` 通过。
- **2026-11-02 本轮已实施**：① `flowCapabilities` 与类型切换逻辑改为全部节点可见、切换不删节点，后端切换校验只要求对话流具备开始/结束；② 节点分类整体对齐 coze 分组并同步契约测试白名单；③ 新增 `变量赋值（40）` 元数据、`查询消息列表（37）` 元数据与 handler；④ 输出节点落库消息补充 `run_id/node_id` 元数据；⑤ 移除输出节点多余的流式开关配置；⑥ 工作流执行入口拦截问答节点并给出可读错误；⑦ 上一轮问答未回答时直接发新消息，自动换子线程放弃旧中断，不再报错卡死。验证：后端全量 `pytest` 382 例通过，admin `typecheck` 通过（前端单测仍有 1 例历史 capabilities 用例与 lottie/jsdom 环境失败，与本次改动无关）。
- **2026-11-02 五轮已实施（请求级预检 + 落库一致性）**：① `/chatflow/run/stream` 在返回流前调用 `prepare_chatflow_run` 完成应用类型、参数组合、会话归属、`thread_id` 归属校验，错误以 JSON 4xx 返回；② `build_runner` 统一生成一次 `run_id` 并传给 runtime / tool_executor / message_repo，用户消息先 `ensure_run` 再落库；③ resume 复用 `RunRepository.get_running_by_thread` 找到的中断 run，中断问题与用户回答共用同一 `run_id`；④ END 流式最终文本复用 `persist_assistant_message` 落库，最终文本按 `emitted_outputs` 判重；⑤ 中断与正常结束均 `conversation.touch`。验证：后端全量 `pytest` 428 例通过，admin `typecheck` 通过。
- **2026-11-02 四轮已实施（问答/输入/知识库/变量告警/禁用占位）**：① 问答节点补齐 `direct/options/extract` 三种回答类型与模型抽取，输出对齐 `USER_RESPONSE`/`QUESTION_DATA`；② 新增输入节点（30），复用问答中断内核固定自由文本；③ 新增知识库删除节点（211）与 `VectorStore.delete_by_document` 三实现；检索/写入输出对齐 `outputList`/`isSuccess`，写入保留 `documentId`；④ 输出节点支持 `outputVariables`；LLM 节点支持流式开关、JSON 输出与 `reasoning_content`；⑤ 异步任务/画布/图像/音视频 9 个节点以 `available=False` 元数据占位并同步分类白名单；⑥ 校验链路新增未声明 `{{variables.x}}`/`{{system.X}}` 告警（不阻断保存），admin 校验接口携带 `application_id`，试运行前遇 error 自动打开校验面板并滚动定位。验证：后端全量 `pytest` 411 例通过，admin `typecheck` 通过。

---

## 三、设计决策

### 3.1 类型落库

- `application.flow_type VARCHAR(20) NOT NULL DEFAULT 'workflow'`，约束 `IN ('workflow','chatflow')`。
- 版本快照不存类型：类型是应用级属性，切换类型不产生 graph 版本，但切换时做兼容性校验。
- 存量应用默认 `workflow`，零迁移成本。

### 3.2 类型切换语义

- 顶部 Segmented：`工作流` / `对话流`。
- 切换后**不重置画布**，只改变：
  1. 开始/结束节点的系统字段（系统输入、返回文本/流式开关）；
  2. 试运行界面（表单 vs 聊天）；
  3. 应用壳层（角色、变量、会话管理入口）；
  4. 运行时的语义校验规则。
- **节点库不随类型变化**（2026-11-02 实机修正，对齐 coze）：切换既不隐藏节点，也不删除节点。
- **切换前只做提示，不做破坏性操作**：
  1. 工作流 → 对话流 且图中无开始/结束节点：`Modal.confirm` 提示"对话流需要开始/结束节点"，选项 `取消切换` / `保留切换（稍后补节点）`；
  2. 对话流 → 工作流 且图中存在 `question` 节点：提示"问答节点在工作流执行中会中断且无恢复通道"，选项 `取消切换` / `保留切换`（不删除）；
  3. 用户取消：`Segmented` 回弹到原类型，**不调用 `updateApp`**。
- 当前 `AppEditPage.handleFlowTypeChange` 在用户取消后仍执行 `updateApp`（`Modal.confirm` 的 `onOk/onCancel` 未正确分支），必须修正。
- 后端二次校验只拦截**结构非法**（如对话流缺开始/结束节点），不因为图里存在 `output`/`question`/会话消息节点而 400；真正的语义冲突在执行入口处理（工作流跑到 `question` 时返回可读错误）。

### 3.3 运行模型

**工作流**：维持现状（单次 invoke，返回最终 output）。

**对话流**：
- 一次用户消息 = 一次 graph invoke；同一个 `thread_id` 承载多轮上下文。
- **线程生命周期**（当前缺失，必须明确）：
  - `thread_id` 默认等于 `conversation_id`，一轮对话结束（`result` 或 `question` 中断）后线程保留，下一轮复用；
  - 若上一轮停在 `interrupt`（问答节点）且用户没有回答就直接发新消息：**放弃旧中断**，以新消息重新 invoke，避免线程永久卡在 interrupt；
  - 服务端只接受 `thread_id == conversation_id` 或符合 `<conversation_id>:<子线程>` 的格式，且必须先校验该 conversation 属于当前 `tenant_id + user_id + application_id`；当前 `make_checkpoint_thread_id` 只做租户前缀隔离，客户端可传任意 `thread_id` 读到同租户他人的 checkpoint，属于越权，必须修。
- SSE 事件契约（以现有实现为准，前端 `DebugStreamEvent` 需同步扩展）：

  | 事件 | 触发点 | 载荷 |
  | --- | --- | --- |
  | `run_start` | 本轮开始 | `{run_id, conversation_id, thread_id}` |
  | `node_start` / `node_end` | 图节点 | 现有调试事件，保留 |
  | `llm_token` | LLM 流式 | `{node_id, content}` |
  | `output_message` | 输出节点（13） | `{node_id, content, role:'assistant'}` |
  | `question` | 问答节点（18）中断 | `{node_id, node_title, question, options}` |
  | `interrupted` | 其他 interrupt（人审） | 现有载荷 |
  | `result` | 本轮结束 | `{run_id, conversation_id, content}` |
  | `error` | 运行异常 | `{message}` |

  `answer_required` 不再单独定义：问答节点的 `question` 事件本身即"等待回答"信号，前端收到后开放输入框并以 `resume={answer}` 续跑。
- **消息落库唯一性**：用户消息在本轮开始时落库一次；输出节点消息在产生时落库；结束节点文本作为最终 assistant 消息由服务层落库，**若该文本已作为 `output_message` 推送过则不重复落库**（当前 `run_chatflow_stream` 已用 `emitted_outputs` 判重，保留）。
- resume 请求允许 `message` 为空（纯续跑），但 `resume` 必须非空；当前 `ChatflowRunRequest` 用 `min_length=1` 强制 message，会把纯续跑挡住，需改为二选一校验。

### 3.4 节点补齐优先级

先做对话流闭环需要的 **输出节点、问答节点**，再做意图识别，最后做异步任务、数据库、知识库删除、长期记忆、变量赋值/查询消息列表。数据库/长期记忆节点与平台约束冲突，先只提供元数据与禁用提示，需产品裁决后再实现；当前 coze 版本无触发器画布节点，触发器不进入节点补齐范围。

### 3.5 变量体系（对齐 coze，替代原"会话变量"设计）

coze 变量页分三层，本地只实现前两层 + 只读系统变量：

| 层 | 作用域 | 生命周期 | 本地实现 |
| --- | --- | --- | --- |
| 应用变量 | 单次请求内所有节点可见 | 每次请求用默认值初始化，运行期可写 | `RuntimeEnv.variables` + `initial_state.globals`，表达式 `{{variables.xxx}}` |
| 用户变量 | 按 `tenant_id + user_id + application_id` 持久化 | 跨会话、跨请求 | 新表 `application_user_variable`（`application_id, user_id, key, value JSONB`，唯一键三元组） |
| 系统变量 | 运行时注入，只读 | 单次运行 | `USER_INPUT`/`CONVERSATION_NAME`/`CONVERSATION_ID`/`USER_ID`/`RUN_ID`（对话流）；工作流仅有 `USER_ID`/`RUN_ID` |

- 表达式取值统一走现有 `ExpressionEvaluator`，作用域顺序：`node_outputs` → `variables` → `system` → `globals`。
- 会话表**不再新增 `variables` 字段**：原 T2-5"会话变量"作废，避免和用户变量语义重叠。
- 变量增删改需在运行前校验引用（`VariablesDrawer` 已在渲染层做），后端 `validate_graph` 增加"引用了未声明变量"告警（已实现 `lint_variable_refs`，warning 不阻断；admin 校验接口传 `application_id` 获取声明作用域）。

### 3.6 试运行会话隔离

- 当前 admin debug 用固定 `DEBUG_APPLICATION_ID` 且 `_register_conversation_services` 写真实 `conversation`/`message` 表，调试数据会污染用户会话列表。
- 方案：调试会话统一打标记 `conversation.channel = 'debug'`（新增列，默认 `'api'`）：
  - admin 试运行创建的会话 `channel='debug'`，用户端列表默认过滤 `channel != 'debug'`；
  - 用户端会话 `channel='api'`，admin 试运行面板可通过"选择会话"看到两类，默认只看 debug；
  - 用户消息、输出消息落库保持真实，便于调试回放，但不再混入线上会话。
- 过渡期若不想加列：admin debug 的 `conversation_id` 由前端显式传入，未传时**只推 SSE 不落库**；这是次选，优先做 `channel` 列。

### 3.7 创建入口与初始画布

- `AppListPage` 创建弹窗从 `Select` 三模板改为**卡片式二选一**：
  - 工作流：适用"一次输入→一次输出"的批处理/API 场景；初始画布 `开始 → 结束`；
  - 对话流：适用"多轮聊天/问答中断"场景；初始画布 `开始 → 大模型 → 输出 → 结束`（LLM 节点带默认提示词模板，减少空画布成本）。
- 保留"创建并进入编排"；创建 api 直接带 `flow_type` 和初始 graph，避免前端二次编辑。
- 列表增加类型筛选（全部/工作流/对话流）+ 类型 Tag，创建入口旁提供"查看示例"跳转已有的两类示例应用（若有）。
- 后端 `create_platform_application` 支持 `flow_type` 与可选 `graph`，未传 `graph` 时按类型生成默认 graph（在服务层构造，不依赖前端）。

### 3.8 发布与版本边界

- 应用发布仍以 graph 版本为准，`flow_type` 不进入版本快照；发布校验按类型执行（对话流必须有开始节点、结束节点；工作流允许输出节点，但含 `question` 节点时给出"运行会中断"告警，不阻断发布）。
- 类型切换后未重新发布时，线上仍运行上一版 graph；前端在类型与已发布版本不一致时展示"有未发布变更"提示（复用现有发布状态），不在本计划新增发布流程。

---

## 四、已修复项（2026-11-02）

### BUG-01 创建消息节点报错 `{"error": "缺少 conversation_id"}`

**根因**
- `create_message`（type=55）只能从上游连线输入或节点 config 取 `conversation_id`；
- 图运行的 `RuntimeEnv` / state 没有会话上下文，独立新增节点后直接试运行必然缺参；
- handler 把错误写进 `outputs` 返回，前端表现为一条看不懂的 `{"error": ...}`，且下游节点会继续消费这个错误对象。

**修复**
1. `RuntimeEnv` 增加 `conversation_id`（`backend/internal/domain/graph/node_base.py`）；
2. `GraphRuntime` 构造函数与 `initial_state.env` 注入 `conversation_id`（`runtime.py`）；
3. `Compiler` 的表达式求值环境注入 `conversation_id`（`compiler.py`）；
4. 会话/消息节点新增 `_resolve_conversation_id()`：显式输入 > config > 当前会话上下文；完全缺失时抛可读 `ValueError`，由 ErrorPolicy 统一处理；
5. 运行入口透传：`DebugRunPayload` / `DebugNodeRunPayload` / `DebugResumePayload` / `WorkflowRunRequest` 增加 `conversation_id`；`build_runner` 增加参数；
6. 画布 debug 的会话仓储增加 `enforce_application=False`，避免试运行写入真实应用会话时报"会话不属于当前应用"。

**测试**：`backend/tests/test_conversation_node_context.py`（上下文回退、显式优先、缺失报错、清空上下文）。

---

## 五、分阶段实施计划

> 每个任务独立可验证；标注 P 级别与预估工时（1 人日 = 8h）。

### Phase 0 类型地基（P0，1.5 天）

| ID | 任务 | 改动点 | 验收 |
| --- | --- | --- | --- |
| T0-1 | 数据库迁移 | `0049_application_flow_type.py`（`flow_type` + CHECK）+ `0050_conversation_channel.py`（`conversation.channel`，默认 `'api'`） | `alembic upgrade head` 通过；存量行默认 workflow/api |
| T0-2 | 仓储读写类型 | `application_repository.create_application / update_application / get_application / list_applications` 增 `flow_type`；`conversation_repository` 增 `channel` | 单测覆盖创建/更新/读取/过滤 |
| T0-3 | 服务与 API | `ApplicationService.create_platform_application` 接收 `flow_type` 与可选 `graph`，未传 graph 时按类型生成默认画布；`apps_admin.py` 请求/响应透传 | `POST /admin/applications` 传 `flow_type=chatflow` 得到对话流默认图 |
| T0-4 | 前端类型链路 | `frontend/admin/src/api/apps.ts` 的 `Application`/`createApp`/`updateApp`；列表类型徽标与筛选 | 创建时选类型，刷新后保持 |
| T0-5 | 卡片式创建入口 | `AppListPage.tsx` 创建弹窗改为工作流/对话流两张卡片（适用场景、初始节点、试运行形态），移除 `chatbot`/`agent` 模板映射 | 创建弹窗只有两种类型；`创建并进入编排` 可用 |
| T0-6 | 列表类型筛选 | 列表顶部 Segmented：全部/工作流/对话流，与名称过滤组合（平台应用列表量级小，先前端过滤） | 筛选结果正确 |

### Phase 1 画布类型切换（P0，1.5 天）

| ID | 任务 | 改动点 | 验收 |
| --- | --- | --- | --- |
| T1-1 | 顶部切换器 | `AppEditPage.tsx` 画布顶部 Segmented；`flowType` state；**取消切换时回弹且不调用 `updateApp`**（修正现有 `Modal.confirm` 分支） | 切换后刷新保持；取消后类型不变 |
| T1-2 | 节点可见性（实机修正） | `canvas/metadata/flowCapabilities.ts`：**两种类型均返回全部节点**；当前隐藏 `output`/`question` 的逻辑回退。仅保留 `output`/`question` 卡片上的"对话流"语义角标（可选） | 工作流与对话流添加节点面板均显示 57 项 |
| T1-3 | 切换兼容校验（前端 + 后端） | 前端切换前只做非破坏性提示（见 §3.2）；后端 `PATCH /admin/applications` 只拦截结构非法（对话流缺开始/结束），不因 output/question 存在而 400 | 取消切换回弹且不落库；对话流缺开始/结束被拦截；含 output/question 的图可切换为工作流 |
| T1-4 | 系统变量注入 | 对话流 start 节点元数据动态追加 `USER_INPUT`/`CONVERSATION_NAME`/`CONVERSATION_ID`；`VariablesDrawer` 展示系统变量分组（只读） | 对话流下拉可见系统变量，工作流不可见 |
| T1-5 | 初始化默认画布 | 新建时按类型落默认 graph（工作流 `开始→结束`；对话流 `开始→LLM→输出→结束`），LLM 节点带占位提示词 | 新建后画布即可直接试运行 |

### Phase 2 对话流运行内核（P0，3 天）

| ID | 任务 | 改动点 | 验收 |
| --- | --- | --- | --- |
| T2-1 | 对话流 SSE 入口 | **已完成**：`prepare_chatflow_run` 在返回 `StreamingResponse` 之前校验应用 `flow_type == 'chatflow'`、message/resume 组合、会话归属、thread_id 归属，错误以 JSON 4xx 返回；工作流应用提示走工作流接口 | 工作流应用无法走对话流接口；非法请求不产生 SSE 帧 |
| T2-2 | 输出节点 handler | `nodes/output.py`（type=13）：模板渲染 + `output_message` SSE + `message_repo.append`（带 `run_id`）；**不实现独立流式开关**（实机输出节点无此配置） | 流程中每条输出成为一条消息 |
| T2-3 | 问答节点 handler | `nodes/question.py`（type=18）：`interrupt({type:'question', question, options})`；resume 兼容 `{answer}`/字符串；答案写入 `node_outputs` | 问答中断→回答→续跑 |
| T2-4 | 对话流结束节点 | `nodes/end.py` 支持 `return_type=text/variables` + `stream`；返回文本作为本轮最终回答 | 返回文本模式聊天可见最终回答 |
| T2-5 | 变量体系 | **已完成**：迁移 `0051_application_variables`（`application.variables` JSONB + `application_user_variable`）；服务层校验/coerce、admin 变量 API；`RuntimeEnv.variables/system` + `EvalContext` 命名空间；Runtime 运行成功后回写用户变量；admin `VariablesDrawer` 四 Tab | 应用变量运行期可读写；用户变量跨会话保留 |
| T2-6 | 消息落库一致性 | **已完成**：统一 `run_id`（runtime/tool_executor/message_repo 共用）；用户消息含 resume 回答每轮落库一次；输出节点与 END 流式文本产生即落库；最终文本按 `emitted_outputs` 判重；中断与结束均 `conversation.touch` | 刷新历史顺序正确、无重复消息；消息 `run_id` 可关联 run |
| T2-7 | 线程归属与多轮语义 | `thread_id` 必须是 `conversation_id` 或带该前缀；resume/invoke 前校验 conversation 的 `tenant_id+user_id+application_id`；新消息到来时放弃未完成 interrupt；`ChatflowRunRequest` 允许 `message` 与 `resume` 二选一 | 伪造 thread_id 返回 403；纯 resume 请求可用；上一轮中断未答时发新消息不卡死 |
| T2-8 | 调试会话隔离 | admin debug 创建会话 `channel='debug'`；用户端会话列表过滤 debug；admin 试运行可选会话 | 调试对话不出现在用户会话列表 |

### Phase 3 节点补齐（P1，3 天）

| ID | 任务 | 说明 |
| --- | --- | --- |
| T3-1 | 意图识别（22） | **已完成**：`nodes/intent.py`（LLM 分类 / 关键词兜底 / 失败落「其他」）；Compiler 条件边；node_meta + 前端 `intent_list` 编辑器与动态出口 |
| T3-2 | 异步任务 | **已完成占位**：`async_task`（212）`available=False` 元数据 + 前端置灰，待任务中心能力就绪再实现 handler |
| T3-3 | 数据库 5 节点（SQL 自定义/增/改/查/删） | **已完成占位**：5 条 `available=False` 元数据 + 前端置灰与原因提示；运行期仍由 `UNSUPPORTED_TYPES` 拦截 |
| T3-4 | 知识库写入/检索/删除 | **已完成**：新增 `nodes/dataset_delete.py`（documentID → isSuccess）与 `VectorStore.delete_by_document`（内存/pgvector/milvus）；检索补 `outputList`，写入补 `isSuccess` 与 `documentId` |
| T3-5 | 长期记忆写入/检索 | **已完成占位**：`long_term_memory` 元数据 `available=False` + 前端置灰；待接入记忆库后补 handler |
| T3-6 | 变量赋值 + 查询消息列表 | **已完成**：`variable_assign`（40）与 `variable_merge` handler；`query_message_list`（37）输出 `messageList/firstId/lastId/hasMore` |
| T3-7 | 输入节点 | **已完成**：`nodes/input.py`（30）复用问答中断内核，固定自由文本回答 |
| T3-8 | 图像/音视频/画板节点 | **已完成占位**：画布（23）/图像生成/抠图/提示词优化/画质增强/视频生成/音频提取/抽帧 共 8 条 `available=False` 元数据 |

### Phase 4 前端画布体验（P1，2.5 天）

| ID | 任务 | 改动点 | 验收 |
| --- | --- | --- | --- |
| T4-1 | 对话流试运行面板 | ~~新增 `ChatflowRunPanel.tsx`~~ 已实现为 `ChatflowDebugPanel.tsx`：右侧聊天窗口、多轮输入、中间输出气泡、问答选项按钮/自由输入、会话/线程自动复用、底部日志联动 | 画布内完成多轮对话调试与问答续跑 |
| T4-2 | 节点配置增强 | **已完成**：输出节点 `输出变量 + 输出内容`（无流式开关）；问答节点问题/回答类型/选项/抽取字段/模型；输入节点提示语；结束节点返回变量/返回文本+流式开关；LLM 输出 `output`/`reasoning_content`/流式开关/JSON 格式 | 各节点配置可编辑并保存 |
| T4-3 | 节点库分组对齐 | **已完成**：`nodePresentation.CATEGORY_ORDER` 与 coze 分组对齐，新增 image/media 分组；后端 `test_node_meta_contract.ALLOWED_CATEGORIES` 同步 | 添加节点面板分组一致，契约测试通过 |
| T4-4 | 节点级校验面板 | **已完成**：校验接口携带 `application_id`（变量声明作用域）；试运行前遇 error 阻断、切到校验 Tab 并滚动定位首个问题节点；节点红框高亮复用 `collectIssuesForNodes` | 缺参节点有明确提示 |
| T4-5 | 变量设置面板 | **已完成**：`VariablesDrawer` 四 Tab（应用变量定义 / 用户变量取值 / 系统变量只读 / 节点输出引用）；类型支持 string/number/boolean/object/array | 变量改动能落库并被表达式引用 |
| T4-6 | SSE 事件类型扩展 | 已完成：`DebugStreamEvent` 增加 `run_start`/`output_message`/`question`/`llm_token` 等；`debugRunAppStream` 支持 `conversation_id`/`thread_id`/`application_id`；`debugRunAppStreamResume` 支持 `resume: { answer }`；后端 debug 路由同步发 `run_start`，问答中断改发 `question` | typecheck 通过，画布可消费新事件 |

### Phase 5 用户端（P1，1.5 天）

| ID | 任务 | 改动点 | 验收 |
| --- | --- | --- | --- |
| T5-1 | ChatPage 对话流渲染 | 已完成：`ChatPage.tsx` 消费 `run_start`/`output_message`/`question`/`result`/`interrupted`；每条输出独立 assistant 气泡；问答选项渲染为按钮，回答走 `resume={answer}` | 多轮对话与中间消息正常 |
| T5-2 | 运行分流 | 已完成：`handleSend` 按 `agent.flow_type` 分流到 `runChatflowStream`，工作流/普通智能体继续走 `runAgentStream`；`conversation_id` 为空时省略字段避免 422 | 工作流表单回归正常 |
| T5-3 | 应用列表类型标识 | 已完成：`AgentListPage` 卡片展示“工作流/对话流”徽标；用户端接口 `flow_type` 已透传 | — |

### Phase 6 测试与验收（P0，1.5 天）

- 后端：`pytest` 全量（当前 428 用例通过），新增 flow_type/output/question/输入/知识库删除/变量告警/LLM reasoning/线程越权/入口类型校验/请求级预检/落库一致性用例。
- 前端：`npm run typecheck`（已通过）+ `npm run test`（admin 遗留 1 例 capabilities 与 2 个 lottie/jsdom 环境失败，均与方案无关）。
- 手工 E2E：
  1. 新建工作流（卡片入口）→ 默认画布 → 执行 → 输出正确；
  2. 新建对话流（卡片入口）→ 默认画布 → 用户端多轮对话；
  3. 输出节点产生中间消息，刷新后不重复；
  4. 问答节点中断 → 回复 → 续跑；未回复直接发新消息不卡死；
  5. 类型切换拦截、取消回弹、后端 400 校验；
  6. admin 调试会话不出现在用户会话列表。

---

## 六、风险与约束

1. **线程越权风险（最高优先级）**：`make_checkpoint_thread_id` 只做租户前缀隔离，客户端传任意 `thread_id` 可读同租户他人 checkpoint。T2-7 必须在放量前完成，不能以"前端不会传错"作为兜底。
2. **画布切换成本（已降低）**：实机确认两种编辑器节点库一致，切换类型**无需重载节点注册表**，只刷新开始/结束系统字段与试运行面板；图数据保持不变。
3. **SSE 协议双轨**：现有 ChatPage 依赖 `llm_token` 单气泡模型；对话流新增事件必须增量兼容，不改已有事件语义。`DebugStreamEvent` 类型与后端契约需成对修改（T4-6）。
4. **流式输出**：实机确认输出节点**无独立流式开关**；流式能力由 LLM 节点"支持流式"与结束节点"流式输出"控制，本地按此实现，不再给输出节点加伪开关。
5. **调试数据污染**：admin debug 当前写真实会话表，T2-8 的 `channel` 列是必须项，否则用户会话列表会被调试数据淹没。
6. **数据库节点**：平台约定禁止关系库，本计划只做元数据占位，不擅自接入。
7. **存量兼容**：`flow_type` 默认 `workflow`、`conversation.channel` 默认 `'api'`，所有现有应用行为不变；`conversation_id` 为可选参数，旧调用方不受影响。
8. **契约测试联动**：节点分类白名单在后端 `test_node_meta_contract.py` 硬编码，前端分组调整必须同 PR 修改白名单，否则 CI 失败。
9. **纯 resume 兼容**：`ChatflowRunRequest.message` 当前 `min_length=1`，改成二选一校验会放宽入参；需补"既无 message 又无 resume"返回 422 的用例。

---

## 七、验收清单

- [x] `application.flow_type` 落库，创建/更新/列表/详情全链路透传
- [x] 创建入口为卡片式二选一，工作流/对话流各自生成可运行的默认画布
- [x] 列表支持按类型筛选
- [x] 画布顶部可切换类型，刷新保持；取消切换回弹且不落库
- [x] 切换兼容性有前端确认 + 后端 400 双重保护
- [x] 两种类型节点库一致（对齐 coze 分组，含禁用态占位），试运行界面、系统输入、结束语义按类型不同；工作流执行 `question` 时返回可读错误
- [x] 对话流支持 `USER_INPUT`/`CONVERSATION_NAME`/`CONVERSATION_ID` 系统输入
- [x] 应用变量运行期可读写，用户变量跨会话保留，系统变量只读；未声明 `{{variables.x}}`/`{{system.X}}` 以 warning 提示
- [x] 输出节点产生中间消息并可在用户端看到，刷新后不重复
- [x] 问答节点可中断并恢复（direct/options/extract），未回复直接发新消息不卡死；输入节点复用同一中断内核
- [x] 结束节点支持返回变量/返回文本 + 流式开关
- [x] 对话流接口拒绝非 chatflow 应用；工作流接口拒绝聊天式请求
- [x] 伪造 `thread_id` 无法读取他人 checkpoint（返回 403）
- [x] admin 调试会话不出现在用户会话列表
- [x] 工作流原有功能全部回归通过
- [x] `create_message` 不再出现 `{"error": "缺少 conversation_id"}`；无上下文时给出可操作错误
- [ ] 后端全量测试、前端 typecheck/vitest 通过（含节点契约测试）：后端 428 例与前端 typecheck 已通过；admin vitest 仍有历史 capabilities 用例与 lottie/jsdom 环境失败，与本方案无关，待单独修复
