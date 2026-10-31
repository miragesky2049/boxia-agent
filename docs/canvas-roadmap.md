# 画布对齐 coze 结构 — 完成计划

> 目标：画布完全复用 coze 的节点结构为标准，后端用 Python + LangGraph 做画布接口适配和执行引擎的完整适配。
>
> 本文件是阶段性工作计划，记录现状差距和分阶段执行路径。后续可直接读取本文件继续推进。

---

## 一、现状盘点

### ✅ 已完成（骨架已通）

**后端**
- `internal/domain/canvas/`：IR 强类型模型（`model.py`）+ coze JSON→IR 转换器（`convert.py`）+ 字段映射配置表（`field_mapping.py`）+ ValueExpressionDTO 解析
- `internal/domain/graph/compiler.py`：CanvasGraph IR → langgraph StateGraph，IF 走 conditional_edges，START/END 处理
- 19 个节点 handler 已注册（`internal/domain/graph/nodes/`）：start / end / llm / http / if_else / code / dataset / dataset_write / loop / batch / break / continue / variable_merge / set_variable / subworkflow / text_processor / json_tools / conversation_nodes / human_task
- `internal/engine/runtime.py`：astream_events 逐节点事件、checkpointer、run_repo 持久化、usage ledger、webhook、SSE 回调
- `internal/application/apps/application_service.py`：graph 整图版本快照、Redis 缓存、租户 config 覆盖、版本回滚、marketplace
- API（`web/admin/routers/apps_admin.py`）：graph get/save/versions/rollback、tenant-config、pin、`/debug/run/stream` SSE 试运行

**前端**
- `frontend/admin/src/pages/apps/AppEditPage.tsx`：FlowGram `FreeLayoutEditor` 集成，节点拖拽、output→input 连线校验、800ms 自动保存、SSE 试运行节点高亮
- 5 种节点：start / end / llm / http / if_else
- coze IR ↔ FlowGram JSON 互转（`toCozeIR` / `fromCozeIR`）

---

### ❌ 未完成 / 简化 stub（关键差距）

#### A. 后端执行引擎深度差距

| # | 模块 | 现状 | coze 标准要求 |
|---|------|------|--------------|
| A1 | **表达式系统** | 仅 Literal/Ref/GlobalVar/EnvVar 四种封闭类型，prompt 只做 `{{input}}` 占位符（见 `expression.py` / `llm.py:80 _render_prompt`） | coze 真实表达式：`{{start.output.x == 'admin'}}`、字符串拼接、内置函数（text/json/array）、jinja-like 模板 |
| A2 | **IF 节点** | 单条件 `bool(condition)` → true/false（见 `nodes/if_else.py`） | 多 case（if/elif/else），每个 case 一个 expression，出口端口是 case_id |
| A3 | **ErrorPolicy** | 已建模（`ErrorPolicy` dataclass：retry/timeout/process_type/data_on_err），但 compiler 未应用 | 节点级重试、超时中断、process_type=1 跳过+dataOnErr 作为输出 |
| A4 | **LLM 节点** | 一次性 chat，无 tool calling（`nodes/llm.py`） | ReAct 循环、function call、token-by-token 流式输出、vision、记忆开关 |
| A5 | **HumanApproval(60)** | `NotImplementedError` stub（`nodes/human_task.py`） | langgraph `interrupt()` + `Command(resume=...)` 中断续跑、审批面板 |
| A6 | **Agent loop 模式** | `_infer_runtime_mode` 只判断"含 LLM 即 agent_loop"，无实际循环（`application_service.py:30`） | coze agent_loop 是独立图协议（plan/execute/reflect），不是 dag |
| A7 | **Loop/Batch 子图** | 每次迭代 new Compiler + ainvoke，无流式、无 break/continue 原生语义、无并发（`nodes/loop.py`） | langgraph 原生 Send API 并行、break/continue 控制流 |
| A8 | **变量系统** | `state.globals` 简单 merge，无类型/默认值/作用域 | coze typed variable pool（string/number/boolean/object/array）、默认值、作用域控制 |
| A9 | **Conversation 节点（38/39/51-57）** | handler 已注册但大概率是 stub（`nodes/conversation_nodes.py`） | 消息列表持久化、会话历史查询、消息 CRUD |
| A10 | **API/插件节点(4)** | 无 handler 实现（`nodes/__init__.py` 未 import api） | coze 插件市场、工具调用、参数映射 |
| A11 | **Graph 校验** | 保存时只查 `nodes` 非空（`application_service.py:240`） | START 唯一、END 可达、悬空边、端口类型匹配、环检测 |
| A12 | **大 graph 对象存储** | 1MB 阈值只 logger.info（`application_service.py:250`） | 真正接 S3/对象存储 URI |
| A13 | **Checkpointer 隔离** | thread_id 拼接但多租户隔离/断点续跑未验证 | 租户级 thread 隔离、历史重放 |

#### B. 前端画布体验差距

| # | 模块 | 现状 | coze 标准要求 |
|---|------|------|--------------|
| B1 | **节点库** | 5 种按钮（`AppEditPage.tsx:29 NODE_TYPES`） | 后端已支持 19 种，前端缺 code/dataset/text_processor/variable_set/loop/batch/subworkflow/json_tools/human_approval/conversation |
| B2 | **节点配置表单** | 纯文本框（`NodeConfigForm`） | LLM 缺模型 picker/输出格式/记忆开关；HTTP 缺 query/path/认证/响应解析；IF 缺可视化 case 列表（左值/操作符/右值下拉） |
| B3 | **变量引用选择器** | 无 | coze 核心体验：点击输入框 → 弹出上游节点输出/全局变量/环境变量选择器 |
| B4 | **端口系统** | 静态 defaultPorts | 按节点类型动态生成 input/output 端口（如 IF 每个 case 一个出口） |
| B5 | **节点 outputs 面板** | 无 | 每个节点右下角"输出字段"面板（name/type/desc） |
| B6 | **子图编辑** | 无 | loop/batch/subworkflow 双击进入内嵌子图画布 |
| B7 | **试运行输入表单** | inputs 写死 `{}`（`AppEditPage.tsx:514`） | 按 START 节点 inputParameters 动态生成表单 |
| B8 | **节点调试面板** | 底部黑色日志条 | 右侧面板：每个节点 inputs/outputs/耗时/token |
| B9 | **版本历史 UI** | API 有（`list_graph_versions` / `rollback_graph`），前端无 | 版本列表 + 回滚按钮 |
| B10 | **画布校验提示** | 无 | 保存前红框标错（悬空节点、START 缺失） |
| B11 | **人审审批 UI** | 无 | 中断时弹出审批框，批准后 resume |
| B12 | **用户端 RunPage** | 对话式运行不完整 | 消息流式输出、历史会话、附件 |

---

## 二、分阶段完成计划

### 阶段 1：执行引擎补齐（后端优先）

**目标**：让现有 19 个节点 handler 达到"生产可用"，不再是 demo stub。

- [x] **A3 ErrorPolicy 落地**：在 `compiler._build_node_fn` 包一层 try/except + retry + timeout，process_type=1 时把 dataOnErr 写入 outputs
- [x] **A2 IF 多 case**：扩展 IfElseNodeHandler 读 `config.cases: [{id, expression, port_id}]`，router 按 case_id 路由
- [x] **A1 表达式系统**：实现 jinja-like 求值器（`{{ref}}`、字符串拼接、内置函数 `len/upper/lower/json_parse`），替换 `_render_prompt` 的 `{{input}}` 硬替换
- [x] **A5 HumanApproval**：接 `langgraph.types.interrupt()`，Runtime 捕获 `GraphInterrupted`，新增 `/run/{id}/resume` API
- [x] **A7 Loop/Batch 并发**：Loop 子图编译缓存（一次编译多次复用）+ 可选并发（config.parallel=true，asyncio.gather + Semaphore 限流）
- [x] **A11 Graph 校验**：`save_graph` 前跑 validate（START 唯一/END 可达/悬空边/端口存在）
- [x] **A4 LLM tool calling**：LLM handler 支持 `tools` 参数，循环调用直到无 tool_call

### 阶段 2：前端画布对齐 coze

**目标**：节点库和配置表单达到 coze 80% 体验。

- [x] **B1 节点库扩展**：从后端拉节点元数据（新增 `/node-meta` API 返回 19 种节点的 port/config schema），前端动态渲染
- [x] **B3 变量引用选择器**：实现 `VariablePicker` 组件，点击 inputs 弹出上游节点输出树
- [x] **B2 配置表单**：按节点类型 schema 动态渲染（LLM 模型 picker 拉 `/models`、HTTP query/path/认证、IF 可视化 case 编辑器）
- [x] **B4/B5 端口系统**：按节点类型动态生成 ports，IF 每个 case 一个出口端口
- [x] **B7/B8 试运行面板**：START inputParameters 动态生成输入表单；右侧节点调试面板展示 inputs/outputs
- [x] **B10 画布校验**：保存前调后端 validate API，红框标错

### 阶段 3：子图/会话/审批闭环

- [x] **B6 子图编辑**：FlowGram 嵌套子图（loop/batch/subworkflow 双击进入）
- [x] **B11 人审 UI**：中断时弹出审批抽屉，批准后调 resume API
- [x] **A9 Conversation 节点**：消息列表持久化 + 会话历史 API
- [x] **B12 用户端 RunPage**：消息流式输出、历史会话列表
- [x] **A6 Agent loop 模式**：独立图协议（plan/execute/reflect）
- [x] **B9 版本历史 UI**：版本列表 + 回滚

### 阶段 4：生产化

- [x] **A12 大 graph 对象存储**：接 S3 / MinIO，>1MB graph 落对象存储，DB 存 `{"__graph_ref__": uri}`
- [x] **A13 Checkpointer 多租户隔离**：thread_id 加租户前缀、历史重放
- [x] **A8 变量系统**：typed variable pool 完整实现（string/number/boolean/object/array 强制转换 + 默认值注入）
- [x] **A10 API/插件节点**：工具市场对接（`tool_executor` 服务抽象 + pluginName 配置）

---

## 三、推进记录

> 每次推进时在此追加一行，记录完成的任务和日期。

- 2026-10-30：完成现状盘点和阶段划分，输出本计划文件。
- 2026-10-30：阶段 1 A1 + A2 + A3 完成。
  - A1：`domain/canvas/expression.py` 新增 `TemplatedString` + `TemplateEvaluator`（ast 白名单），支持 `{{node.output.field}}` 插值、比较/逻辑/内置函数（len/upper/lower/trim/json_parse/json_stringify/default）。`convert.py` 把含 `{{` 的字面量翻译成 TemplatedString。`ExpressionEvaluator.resolve_config` 递归求值 config。
  - A2：`nodes/if_else.py` 支持 `config.cases: [{case_id, expression}]` 多 case，逐个求值，第一个为真的 case_id 作为 route；兼容旧版单条件。
  - A3：`graph/compiler.py` 新增 `_execute_with_policy`，按 `ErrorPolicy` 应用 retry/timeout/降级（process_type=1 时 dataOnErr 写 outputs，错误信息写 state.errors）。
  - LLM handler 兼容 coze 真实格式（`llmParam` 数组）和前端简化格式（config 顶层），prompt 先替换 `{{input}}` 再用 evaluator 求值其他引用。
  - 199 个测试全过。
- 2026-10-30：阶段 1 A5 + A7 完成。
  - A5：`nodes/human_task.py` 用 `langgraph.types.interrupt({type, node_id, assignee_role, instructions, snapshot})` 中断；`engine/runtime.py` 执行后用 `aget_state` 检查 `tasks[].interrupts`，有中断则标记 run 为 interrupted 并抛 `GraphInterrupted`；新增 `runtime.resume(resume_payload)` 方法，用 `Command(resume=...)` 从断点继续。
  - A7：`nodes/loop.py` 优化——子图只编译一次（之前每次迭代 new Compiler），新增 `config.parallel` 开关，并发模式下用 `asyncio.gather` + `Semaphore(MAX_PARALLELISM=10)` 执行；串行模式保持 break/continue 语义。
  - 199 个测试全过。
- 2026-10-30：阶段 1 A11 + A4 完成。
  - A11：新增 `domain/canvas/validate.py`——`validate_graph(CanvasGraph)` 与 `validate_raw_graph(dict)` 两个入口，检查 START 唯一、END 至少一个、边引用节点存在、入边/出边悬空、从 START DFS 不可达孤立子图。`application_service.save_graph` 在 nodes 非空检查后调用 `validate_raw_graph`，error 级问题抛 `ValidationError` 阻塞保存；warning 级仅记录不阻塞。
  - A4：`nodes/llm.py` 重写 ReAct 循环——从 `config.tools` 解析 `LLMToolSpec` 列表（兼容 dict/LLMToolSpec 两种形状），通过 `ctx.services.get("tool_executor")` 拿执行器（签名 `async (name, args) -> str`）。循环最多 `maxToolRounds`（默认 5）轮：调 LLM → 若 `wants_tool_call` 则把 assistant tool_calls + 每个 tool 的 observation 回灌 messages → 再调。跨轮 usage 累加；工具执行失败/未注册时回灌 `[error] ...` 文本而非抛异常，保证主循环不中断。`llm_adapter.chat()` 已透传 `tools` 参数。
  - marketplace detail 路由 START 节点识别兼容 coze 标准 `type="1"` 与早期简化格式 `type="start"`。
  - 新增 `tests/test_llm_node_tools.py`（2 例：正常 ReAct 循环 + 工具未注册降级）。201 个测试全过。
- 2026-10-30：阶段 2 B1 完成。
  - 后端新增 `domain/canvas/node_meta.py`：定义 `NodeMeta`/`PortMeta`/`ConfigFieldMeta` 数据类，注册 25 种节点元数据（流程控制 6 种、AI 1 种、HTTP/代码 2 种、数据/知识库 5 种、循环/子图 5 种、人审 1 种、会话/消息 9 种）。每种含 type_code（coze 数字）、type_key（英文短 key）、title、color、category、inputs/outputs 端口、config_fields 配置表单 schema。
  - 新增 `web/admin/routers/node_meta.py`：`GET /api/v1/admin/node-meta` 返回全部节点元数据，按 category 分组。
  - 前端新增 `api/nodeMeta.ts`：定义 NodeMeta 类型 + getNodeMeta() API。
  - `AppEditPage.tsx` 重写：删掉硬编码 NODE_TYPES（原 5 种），改为从 API 动态拉取 25 种节点；节点库按 category 分组渲染（流程控制/AI/逻辑/数据/会话）；nodeRegistries/renderNodes/addNode/handleNodeDoubleClick 全部用动态 nodeMetas。
  - 后端 201 个测试全过，前端 typecheck 通过（仅剩 main.tsx 一个旧错误）。
- 2026-10-30：阶段 2 B2 完成。
  - 重写 `node_meta.py`：对齐后端 handler 实际读取的字段名（datasetId/topK/timeoutMs/workflowId/variableName/parallelCount/find/replaceWith 等），修复 dataset_write 重复条目；LLM 保留 coze 原始拼写 `modleName`。
  - `AppEditPage.tsx` 删掉按节点类型硬编码的 NodeConfigForm（原 llm/http/if_else 三块 JSX），改为通用 `FieldControl` 组件按 `field.field_type` 分发：text/number/select/boolean/textarea/code_editor/case_list/model_picker。`NodeConfigForm` 遍历 `nodeMeta.config_fields.map()` 动态渲染。`NodeConfigValues` 由强类型 interface 改为 `Record<string, any>`，避免新增字段时同步改两处。
  - model_picker 暂用 Input 占位（TODO 接 `/models` API）；case_list 暂用 textarea 占位（TODO 可视化左值/操作符/右值编辑器）。
  - 后端 201 个测试全过，前端 typecheck 仅剩 main.tsx 旧错误。
- 2026-10-30：阶段 2 B3 完成。
  - 新增 `RefPickerButton` 组件：Popover + Tree，展示当前图全部节点（排除自身），每个节点展开显示其 outputs 端口（来自 NodeMeta）；START 节点额外展示 `config.inputs` 里的入参作为虚拟输出。
  - 点击叶子节点后插入 `{{nodeId.output.portName}}` 到当前字段值末尾（自动补空格分隔），与后端 `TemplateEvaluator` 的 `{{...}}` 插值格式对齐。
  - `FieldControl` 新增 `picker` prop：text 字段挂在 Input suffix，textarea/code_editor/各种 list 字段挂在输入框上方。number/select/boolean/model_picker 不挂（这些字段不支持表达式引用）。
  - `refreshPickerNodes()` 在双击节点打开抽屉时从 `ctx.document.toJSON()` 提取节点摘要（id/typeKey/title/config），存入 state 供 picker 使用。
  - 前端 typecheck 通过（仅剩 main.tsx 旧错误）。
- 2026-10-30：阶段 2 B4/B5 完成。
  - `nodeRegistries` 的 `defaultPorts` 从空类型 `{ type: 'input'/'output' }` 改为带 `id`：`{ id: p.name, type: 'input'/'output' }`，端口 id 直接用 NodeMeta 里 PortMeta.name（如 IF 的 true/false、HTTP 的 body/status、conversation 的 conversation_id/message_id）。连线时 FlowGram 自动把端口 id 写入 edge 的 sourcePortID/targetPortID，`toCozeIR`/`fromCozeIR` 已在透传这两个字段，后端 IF 节点 router 可直接按 case_id 路由。
  - 节点 size 从固定 `{ width: 160, height: 40 }` 改为按 outputs 数量动态计算高度（每个 output 占 16px + 6px 分隔），避免 outputs 列表溢出节点框。
  - `makeNodeRenderer` 在节点色块下方渲染 outputs 列表（B5：outputs 面板），用半透明白色小字显示每个出口的 label（如"满足"/"不满足"/"响应体"），左侧对齐。
  - 前端 typecheck 通过（仅剩 main.tsx 旧错误）。
  - TODO：IF 节点 case 端口随 config.cases 动态增删（FlowGram 0.1.28 动态端口 API 未确认，现阶段静态 true/false 两出口与 NodeMeta 对齐）。
- 2026-10-30：阶段 2 B7/B8 完成。
  - 后端 `runtime.py::_stream_and_record`：`on_chain_start` 事件加 `inputs`（取自 `data.input`）；`on_chain_end` 成功分支加 `outputs`（node_out）+ `duration_ms`；`on_chain_error` 分支加 `error` + `duration_ms`。前端 201 测试全过。
  - B7 前端：`extractStartParams()` 从当前图 START 节点的 `config.inputs` 提取入参 schema；点击"试运行"时若有入参则弹 Modal（每个参数一个 Input，type 作 placeholder），确认后把收集到的 inputs 传给 `debugRunAppStream`；无入参直接运行。
  - B8 前端：新增 `nodeDebugMap` state 按 node_id 累积每个节点的 `status/inputs/outputs/duration_ms/error`；画布右侧绝对定位渲染调试面板（Collapse 折叠列表，每个节点显示状态色点 + node_id + duration_ms，展开后显示 JSON 格式化的输入/输出/错误）。
  - 前端 typecheck 通过（仅剩 main.tsx 旧错误）。
- 2026-10-30：阶段 2 B10 完成。
  - 后端新增 `POST /admin/apps/validate-graph`（`apps_admin.py`）：接收 `{graph}`，调 `validate_raw_graph(graph)`，返回 `{valid, issues: [{severity, code, message, node_id}]}`。不保存、不执行，只做结构校验。后端 201 测试全过。
  - 前端新增 `validateGraph(graph)` API（`api/apps.ts`）。`AppEditPage.tsx`：
    - `doValidate()` 把当前画布转 cozeIR 后调校验 API，收集 `issues`，对 `node_id` 非空的问题节点加 `.boxia-node-invalid` class（红框）。
    - `scheduleSave` 在调 `saveAppGraph` 前先 `doValidate()`，有 error 则不保存、setSaveStatus('error')，直接展示问题面板。
    - 左侧面板新增"✔ 校验"按钮（手动触发），底部（run logs 上方）渲染问题面板：错误红圆点、警告黄三角、node_id Tag。
    - 右上角保存状态在校验期间显示"校验中…"。
  - 前端 typecheck 通过（仅剩 main.tsx 旧错误）。
- 2026-10-30：阶段 3 B9 完成。
  - 前端新增 `listGraphVersions(applicationId)` / `rollbackGraph(applicationId, version)` API（`api/apps.ts`），对应后端已有的 `GET /admin/apps/{id}/graph-versions` 和 `POST /admin/apps/{id}/graph-rollback`。版本记录字段：id/version/runtime_mode/changelog/created_by/created_at。
  - `AppEditPage.tsx` 左侧面板新增"🕘 版本历史"按钮，点击打开 Drawer：按版本倒序渲染卡片，当前版本（第一条）绿色高亮 + "当前" Tag；非当前版本显示"回滚到此版本"按钮，确认后调 rollback API，成功后重新 `getAppGraph` 刷新画布。
  - 前端 typecheck 通过（仅剩 main.tsx 旧错误）。
- 2026-10-30：阶段 3 B11 完成。
  - 后端 `apps_admin.py`：
    - `debug_run_stream` 去掉 `checkpointer=None`（改用默认 checkpointer，否则 interrupt 无法持久化）；新增 `except GraphInterrupted` 分支，yield `interrupted` SSE 事件，payload 含 `approval`（节点 interrupt payload）+ `thread_id` + `run_id`。
    - 新增 `POST /admin/apps/debug/run/stream/resume`：接收 `{graph, thread_id, run_id, approval}`，构造 `GraphRuntime(thread_id, run_id, on_node_event)` 调 `runtime.resume(approval)`，逐节点 SSE 推送，遇到下一个人审中断再发 `interrupted` 事件。
    - 后端 201 测试全过。
  - 前端 `api/apps.ts`：`DebugStreamEvent.event` 联合类型加 `'interrupted'`；新增 `ApprovalInterruptPayload` 类型（type/node_id/node_title/assignee_role/instructions/snapshot）；新增 `debugRunAppStreamResume(...)` SSE 函数（抽出 `_postSse` 复用 fetch + ReadableStream 解析）。
  - 前端 `AppEditPage.tsx`：
    - 抽出共用 `handleRunEvent(event, appendLog)` 处理器（初次 + resume 复用）；`interrupted` 分支把 approval payload / thread_id / run_id 存入 `approvalState`，弹审批抽屉。
    - 新增审批 Drawer：显示审批人角色 Tag、审批说明、节点输入快照（JSON pre）、审批人 Input、审批意见 TextArea、通过/拒绝按钮。
    - `handleApprovalSubmit(approved)`：关抽屉、调 `debugRunAppStreamResume`，把 `{approved, comment, approver}` 作为 `approval` 字段传后端；SSE 事件继续走同一个 `handleRunEvent`，多个人审节点会循环弹抽屉直到 result。
  - 前端 typecheck 通过（仅剩 main.tsx 旧错误）。
- 2026-10-30：阶段 3 A9 完成。
  - 后端 sync 仓储补全：
    - `internal/infrastructure/repository/apps/conversation_repository.py` 新增 `list_conversations_by_user(tenant_id, user_id, application_id?, limit, offset)` 与 `delete_conversation(id)`（message 表 ON DELETE CASCADE 级联）。
    - `internal/infrastructure/repository/apps/message_repository.py` 新增 `delete_message(id)` 与 `clear_messages(conversation_id)`。
  - 新增 async 适配层 `internal/infrastructure/repository/apps/async_conversation_adapter.py`：
    - `AsyncConversationRepository` / `AsyncMessageRepository` 实现 `internal.domain.agent.repository` 下的 ABC，把 sync Session 操作包成 async 方法；构造时绑定 tenant_id/user_id/application_id/run_id，append 时缺省字段用绑定值兜底。
  - 节点 handler 统一命名：
    - `internal/domain/graph/nodes/conversation_nodes.py` 把输入键从 camelCase（conversationId/appId/...）改为 snake_case，与 node_meta 端口对齐；新增 `_pick(ctx, key, default)` 助手，优先取上游连线 input，再退到节点 config 表单值（title/role/limit/metadata/app_id 等用户在表单里配的字段走 config）。
    - `internal/domain/canvas/node_meta.py` 为 9 个 conversation 节点补 `config_fields`：create_conversation(title/app_id)、update_conversation(title)、query_conversation_list(app_id/limit)、query_conversation_history(limit)、create_message(role select)、update_message(content textarea)。
  - 试运行接线：
    - `web/admin/routers/apps_admin.py` 新增 `DEBUG_APPLICATION_ID`（固定 UUID，初始 run 与 resume 共用，避免会话历史断裂）和 `_register_conversation_services(...)` 助手；`debug_run_stream` 与 `debug_run_stream_resume` 在构造 ServiceRegistry 后注册 `conversation_repo` / `message_repo`，并把 `run_id`/`application_id` 显式传给 `GraphRuntime`。
  - 9 个 conversation 节点不再返回 stub 值，真实读写 conversation/message 表。
- 2026-10-30：阶段 3 B12 完成。
  - 后端 `internal/application/apps/chat_service.py`：新增 `list_conversations(application_id, limit, offset)` 和 `list_messages(application_id, conversation_id, limit)`——都先 `assert_user_can_view` 做可见性闸门，list_messages 还校验会话归属（user_id/application_id/tenant_id 三对齐），返回 user/assistant 消息并附带 tool_calls 元信息。
  - 后端 `web/user/routers/chat.py`：新增 `GET /user/agents/{id}/conversations` 和 `GET /user/agents/{id}/conversations/{cid}/messages` 两个只读端点。
  - 前端 `frontend/user/src/api/conversations.ts`：新增 `ConversationSummary` / `ConversationMessage` 类型与 `listConversations` / `listConversationMessages` 两个 API 封装。
  - 前端 `ChatPage.tsx`：
    - 左侧新增历史会话 sidebar：默认隐藏（移动端抽屉 + 遮罩），桌面端 ≥900px 时常驻；顶部"历史会话"标题 + "新会话"按钮；列表项显示会话标题 + updated_at，当前会话高亮。
    - 切换会话时调 `listConversationMessages` 恢复历史消息（只渲染 user/assistant 角色）；新会话按钮清空 messages + conversationId。
    - 每轮对话 result 事件返回后自动刷新会话列表，新会话会出现在列表顶部。
    - header 新增"会话"按钮切换 sidebar 显隐。
  - 前端 typecheck 通过；后端语法通过。
- 2026-10-30：阶段 3 B6 完成。
  - 前端 `AppEditPage.tsx`：
    - `toCozeIR`/`fromCozeIR` 递归处理 `blocks`/`edges`：子图节点（loop/batch/subworkflow）把 `data.subgraph` (WorkflowJSON) 序列化到 coze IR 的 `blocks`/`edges`；反序列化时把 `blocks`/`edges` 还原成 `data.subgraph`。
    - 新增 `rootGraphRef` 持有完整嵌套 WorkflowJSON；`subgraphStack` 记录从 root 到当前编辑层的 node_id 路径；`editorKey` 强制 FreeLayoutEditor 重挂载。
    - `persistCurrentEditor()`：切换层级前把当前画布 JSON 回写到 rootGraphRef 对应位置；`resolveEditorData(stack)`：按 stack 取出要编辑的子图。
    - 双击子图节点自动初始化 START 入口（如果是空 subgraph）并进入；非子图节点照旧打开配置抽屉。
    - 顶部加面包屑导航：返回根图 + 每一层子图标题可点击跳回。
    - `scheduleSave`/`doValidate` 改用 `collectFullGraph()` 收集完整嵌套图后再序列化/校验，确保子图改动一并保存。
  - 前端 typecheck 通过。
- 2026-10-30：阶段 3 A6 完成。
  - 新增 `NodeType.AGENT_LOOP = "100"`（coze 无数字编码，本项目自定义 100），注册 handler `internal/domain/graph/nodes/agent_loop.py`：
    - 三阶段协议：PLAN（LLM 把用户目标拆成 tasks JSON）→ EXECUTE（ReAct 循环，支持 tool_calls）→ REFLECT（LLM 评审 done/critique/suggestion，未 done 则追加 critique 消息回到 execute，最多 maxReflectRounds 轮）。
    - PLAN / REFLECT 用 `response_format={"type": "json_object"}` 强制 JSON；解析失败时兜底：plan 兜底为单任务、reflect 兜底 done=true。
    - config 字段：`modleName` / `systemPrompt` / `tools` / `maxToolRounds`（默认 5）/ `maxReflectRounds`（默认 3）/ `plannerPrompt` / `reflectorPrompt`（后两项留空则用内置默认）。
    - 依赖 `ctx.services.get("llm")` 与可选 `tool_executor`；未注册 llm 时返回 stub 不阻塞开发态。
  - 节点元数据：`node_meta.py` 新增 `agent_loop`（category=ai，inputs=input，outputs=output+plan），前端节点库可直接从 API 拉到。
  - `_infer_runtime_mode`：从"含 LLM=agent_loop"的启发式改为"含 type=100 节点即 agent_loop"，其余一律 dag。LLM 节点作为 dag 内普通节点不再触发特殊运行模式。
  - 新增 `tests/test_agent_loop_node.py` 4 例：plan-execute-reflect 一轮 done / reflect 未 done 触发二次 execute / execute 阶段 tool_call 回灌 / llm 未注册 stub。后端 205 个测试全过。
- 2026-10-30：阶段 4 A13 完成。
  - `internal/engine/runtime.py`：
    - 抽出 `make_checkpoint_thread_id(tenant_id, thread_id) -> "{tenant}:{thread_id}"` 助手。
    - `GraphRuntime.__init__` 把传入 thread_id 经过 `_strip_tenant_prefix()` 规范化：若带"当前租户"前缀则剥掉（兼容 SSE 原样回传）；若带"别的租户"前缀直接 `RuntimeError` 拒绝（防跨租户读取）；裸 thread_id 原样保留。
    - `_config()` 改用 `make_checkpoint_thread_id()` 统一拼 key，不再现场 f-string。
    - 新增 `list_state_history(limit=20)`：调 `compiled.get_state_history(config)` 返回快照列表（checkpoint_id / next / interrupts / output / node_outputs_keys），无 checkpointer 时返回空列表。
  - `internal/domain/graph/nodes/loop.py::_invoke_once`：子迭代 checkpointer thread_id 从 `f"{ctx.env.thread_id}:loop:{index}"`（无租户前缀，会与主图 key 错位）改为 `f"{ctx.env.tenant_id}:{ctx.env.thread_id}:loop:{index}"`；state.env.thread_id 仍保留业务裸 ID。
  - 新增 `tests/test_checkpointer_tenant_isolation.py` 5 例：helper 拼接 / 剥当前租户前缀 / 拒别的租户前缀 / 同业务 thread_id 跨租户落到不同 checkpoint key / list_state_history 返回快照。后端 210 个测试全过。
- 2026-10-31：阶段 4 A12 完成。
  - 新增 `internal/domain/storage/object_storage.py` ABC（`put/get/delete`）+ `internal/infrastructure/storage/fake_storage.py`（`InMemoryObjectStorage` 测试用）+ `internal/infrastructure/storage/minio_storage.py`（lazy Minio client、自动建 bucket）+ `factory.py` 单例。
  - `settings.py` 新增 `object_storage_endpoint/access_key/secret_key/bucket/secure` 配置；空 endpoint 时 factory 返回内存实现（开发态零依赖）。
  - `application_service.py`：`save_graph` 在 graph_size > 1MB 且 storage 可用时上传到对象存储，DB 只存 `{"__graph_ref__": "minio://bucket/key"}`；读取时 `_parse_graph` 识别 `__graph_ref__` 自动回源拉取。storage 失败降级为内联存储，不阻塞保存。
  - 新增 `tests/test_graph_object_storage.py` 4 例：1MB 以上 graph 走对象存储 / 小 graph 内联 / `__graph_ref__` 回源拉取 / storage 不可用时降级。
- 2026-10-31：阶段 4 A8 完成。
  - `internal/domain/canvas/model.py`：`CanvasGraph` 新增 `variables: list[VariableDef]`；`VariableDef` dataclass（name/type/default/description）。
  - 新增 `internal/domain/canvas/variable_types.py`：`coerce(value, type_name)` 支持 string/number/boolean/object/array，转换失败返回 None（宽容模式）。
  - `convert.py`：从 raw `variables` 或 `globalVariables` 字段解析变量，同时兼容简化格式 `{name,type,default}` 和 coze 格式 `{variableName,variableType,defaultValue}`。
  - `compiler.py`：新增 `default_globals()` 方法，按 graph.variables 声明类型把默认值强制转换后返回。
  - `set_variable.py`：节点按 `config.variableType` 对写入值做类型强制转换，失败时保留原值并记 warning。
  - `runtime.py`：`invoke()` 构造 initial_state 时调 `self._compiler_instance.default_globals()` 注入初始 globals；`_ensure_compiled` 保存 compiler 实例引用（修复 `self._compiler` 拼写为 `self._compiled` 的回归）。
  - 新增 `tests/test_variable_system.py` 18 例：coerce 五种类型 / convert 两种格式 / default_globals 类型强制转换 / SetVariable 写入转换 / runtime initial_state 注入。后端 228 个测试全过。
- 2026-10-31：阶段 4 A10 完成。
  - 新增 `internal/domain/graph/nodes/api_plugin.py`：`ApiPluginNodeHandler`（type=4）。从 `config.pluginName`（兼容 `toolName` / `name`）取工具名，`ctx.inputs` 作为 args 调 `ctx.services.get("tool_executor")`；无服务时返回 stub（与 LLM / HTTP 节点开发态降级一致）；返回文本尝试 JSON 解析，成功时额外给 `parsed` 字段；异常包装为 `RuntimeError` 抛给 Runtime 走 ErrorPolicy。
  - `nodes/__init__.py` import `api_plugin` 触发注册。
  - `node_meta.py` 新增插件调用元数据（category=logic，config_fields=pluginName/description，outputs=output/parsed）。
  - 新增 `tests/test_api_plugin_node.py` 8 例：缺 pluginName / 无 tool_executor stub / 正常调用 / JSON parsed / 非 JSON 无 parsed / 异常包装 / toolName alias。后端 240 个测试全过。

---

## 四、2026-10-31 真实差距复核（重要）

> 上面 4 个阶段全部打勾，但那是**结构层打勾**（IR 模型、compiler、handler 注册、前端骨架）。
> 真机跑一遍后发现：**大量节点 handler 在没有 service 注入时直接走 stub 分支**，而这些 service 在 runtime 根本没注册。
> 也就是说，"完成"≠"能跑通"。下面是按运行时真实依赖重新盘的差距。

### 4.1 运行时 service 注册现状（grep `services.register`）

| service 名 | 谁在用 | 谁注册了 | 现状 |
|---|---|---|---|
| `llm` | LLM / AgentLoop | admin debug + user chat 路由 | ✅ 已接 |
| `http` | HTTP 节点 | 所有路由 | ✅ 已接（HttpService） |
| `conversation_repo` / `message_repo` | 9 个会话节点 | admin debug 路由 | ⚠️ 仅 debug 路由接了，**正式 user chat 路由没接** |
| `subgraph_loader` | SubWorkflow 节点 | user chat 路由 | ⚠️ admin debug 路由没接 |
| `sandbox` | Code 节点（type=5） | **无人注册** | ❌ 永远走 stub |
| `vector_store` | Dataset / DatasetWrite（6/27） | **无人注册** | ❌ 永远走 stub |
| `embedding` | Dataset 检索时向量化 | **无人注册**（engine/embedding.py 存在但没接进 services） | ❌ 永远走 stub |
| `tool_executor` | LLM ReAct / API 插件节点（4） | **无人注册** | ❌ LLM 声明 tool_calls 时回灌"[error] 工具未注册" |

**结论**：Code / Dataset / DatasetWrite / API 插件 / LLM-tool-calls 这 5 类节点真机跑全是假输出。

### 4.2 前端配置表单仍是占位

roadmap B2 记了"model_picker 暂用 Input 占位 / case_list 暂用 textarea 占位"，但没后续任务。真实 coze 体验里：

| 控件 | 现状 | coze 标准 |
|---|---|---|
| LLM 模型选择 | 纯 Input（手填字符串） | 模型下拉（按租户可用模型列表），且切换模型时自动更新支持的参数（temperature/maxTokens 范围） |
| IF case 编辑器 | textarea 一行 JSON | 可视化：左值下拉（变量/上游输出）+ 操作符（==/!=/>/in/contains）+ 右值输入，可增删 case |
| HTTP 节点 | 只有 url/method | headers / query params / path params / body JSON 模板 / 认证（Bearer/Basic/签名） |
| 变量引用 | RefPicker 已能弹树 | 已接近 coze，但选完后**没回显 chip**（coze 在输入框内渲染成蓝色变量胶囊） |
| 节点 outputs 面板 | 静态从 NodeMeta 读 | 应支持用户在配置里**自定义输出字段**（coze 节点可声明 outputs） |

### 4.3 与 coze 对比的结构性遗漏（roadmap 里没列的）

1. **节点注释/便签（Comment, type=31）**：枚举有，但前端节点库和 handler 都没接——coze 画布核心辅助元素。
2. **Note 节点（type=7）**：coze 实际存在，本项目枚举缺失。
3. **流式输出（token-by-token）**：LLM handler 一次性返回 content，前端 SSE 只拿到整段 result，没有 token 级流式体验；用户端 ChatPage 也没打字机效果。
4. **LLM 记忆开关 / 多轮对话历史拼接**：coze LLM 节点可配置"是否带历史会话消息"；本项目 messages 是 node 内独立构造，从不读 conversation 历史。
5. **知识库写入（DatasetWrite, 27）**：handler 已注册但没接 vector_store，等同 stub。
6. **批量/并发 loop 的 break/continue 语义**：并发模式下 break/continue 控制流没实现（roadmap A7 只做了串行版本）。
7. **子图调用（SubWorkflow, 9）**：subgraph_loader 只在 user chat 路由注册，admin debug 试运行子图节点会报错。
8. **租户级模型/插件市场配置**：application_service 有 tenant config 覆盖，但前端没暴露"租户默认模型"配置页。
9. **运行日志/调试追踪**：节点 inputs/outputs 有了，但没有 trace 树（哪个 tool_call 调了什么、耗时多少、prompt 原文）。
10. **发布/版本/灰度**：graph versions + rollback 有了，但缺"发布到用户端"动作——admin 改完画布，user chat 还在用旧版本。

---

## 五、修正后的执行任务清单（按优先级）

> 上面的 A1–A13 / B1–B12 标记完成的，结构上不再返工。下面是**让画布真正可跑、对齐 coze 体验**的增量任务。

### P0：让核心节点真能跑（不接就是 demo）

- [x] **T1 注册 tool_executor**：把 `internal/engine/tool_gateway.py` 包成 `tool_executor` service，在 admin debug / user chat / subworkflow 三处路由统一注册。覆盖 HTTP 节点 + LLM ReAct + API 插件节点三类调用方。
- [x] **T2 接入 embedding + vector_store**：把 `internal/engine/embedding.py` 和已有 Milvus/PGVector 仓储实例化进 services；Dataset 节点真机检索，DatasetWrite 节点真机写入。
- [x] **T3 实现 sandbox service**：Code 节点不能再 stub。最低要求：独立子进程 `python -I -c` 运行用户代码，超时 kill，限制 import（白名单 json/re/datetime），stdout/stderr 捕获。
- [x] **T4 user chat 路由补齐 service**：`web/deps/graph.py` 注册 `conversation_repo` / `message_repo` / `subgraph_loader`，否则用户端跑会话节点全部报"service not found"。

### P1：流式 + 真实体验（对齐 coze 核心体感）

- [x] **T5 LLM token 流式输出**：LLM handler 改 `llm_service.chat_stream()`，每个 token 通过 `ctx.emit_event("llm_token", {delta})` 推到 SSE；前端 ChatPage 打字机渲染。实现：`LLMClient.chat_stream` SSE 解析（OpenAICompat），`NodeContext.emit_event` 由 Compiler 注入，admin/AppEditPage 累积 streamingText，user/ChatPage 逐 delta 追加。
- [x] **T6 LLM 记忆开关**：config 加 `needHistory: bool` + `historyLimit: int`（默认 10）；为 true 时从 message_repo 拉最近 N 条 user/assistant 消息拼进 messages（system 之后、当前 user 之前）。conversation_id 来源：ctx.inputs["conversation_id"] → ctx.config["conversation_id"]；缺失/非法/未注册 message_repo 时静默跳过。
- [x] **T7 IF case 可视化编辑器**：替换 case_list textarea，实现左值下拉 + 操作符下拉 + 右值输入 + case 增删；与后端 `config.cases` schema 对齐。
- [x] **T8 LLM model picker**：复用 `/admin/models/catalog/available`，返回字段含 `default_temperature`/`default_max_tokens`，空表回退到 `settings.llm_model_id`；前端 LLM 节点 `model_picker` 改下拉，选中时回填 temperature/maxTokens。
- [x] **T9 HTTP 节点配置扩展**：headers / query / body form 三组动态 key-value 编辑器，认证类型下拉（none/bearer/basic），url 路径参数 `:param` 提取。

### P2：补结构遗漏

- [x] **T10 Comment 节点（type=31）**：画布便签，无执行语义，前端渲染为黄色便签块，handler 直接返回 outputs。
- [x] **T11 并发 loop 的 break/continue**：A7 并发模式下 break 应取消其余 pending task，continue 应跳过当前迭代——用 `asyncio.gather` + 手动 create_task/as_completed/cancel 实现。
- [x] **T12 admin debug 路由接 subgraph_loader**：否则试运行含 SubWorkflow 节点的图会失败。
- [x] **T13 发布动作**：新增 `POST /admin/apps/{id}/publish`，把当前 draft graph 快照为 live 版本；user chat 路由读 live 而非 draft。
- [x] **T14 节点 outputs 自定义**：NodeConfigForm 加 outputs 字段编辑器（name/type/desc 动态列表），保存时写回 `data.outputs`。

### P3：生产化打磨

- [x] **T15 运行 trace 面板**：SSE 事件加 `tool_call_start` / `tool_call_end` / `prompt_text`，前端调试面板展开后能看到每轮 ReAct 的 prompt 原文和 tool 入参出参。
- [x] **T16 租户模型/插件配置页**：admin 新增租户设置页，配置默认模型、允许的插件白名单。（2026-10-31：migration 0047 tenant_settings 表 + TenantSettingsRepository/Service + GET/PUT `/admin/tenants/{id}/settings` + 前端 `/tenants/:id/settings` 页；5 个单测；313 个后端测试全过）
- [x] **T17 节点 lint**：保存前除结构校验外，跑表达式语法、必填 config 字段非空、端口类型匹配（number→boolean 报警）。（2026-10-31：新增 `internal/domain/canvas/lint.py`：`lint_graph(graph)` 三条规则，与 `validate_raw_graph` 串联；9 个新单测 + 3 个旧测试补 required 字段；322 个后端测试全过）
- [x] **T18 多模态**：LLM 节点支持 image_url content part，START 节点 inputs 支持 file 类型，前端上传附件。（2026-10-31：LLM 节点 `_extract_images` 从 inputs["images"]/config["images"] 取 URL 列表，组装 OpenAI multi-modal content parts；START 节点 node_meta 注释支持 image/file 类型；前端试运行弹窗 type=image/file 时渲染 Upload 组件读 dataURL；5 个新单测；327 个后端测试全过）

---

## 六、推进记录（续）

- 2026-10-31：复核发现阶段 1–4 全部为结构层完成，运行时关键 service 未注册。新增 T1–T18 任务清单（见第五节）。
- 2026-10-31：T1 完成。
  - 新增 `internal/engine/services/tool_executor.py::ToolExecutorService`：可 await 的 `(name, args) -> str` 适配器。构造时绑定 tenant_id/user_id/application_id/run_id；lazy 加载租户可见的 enabled 工具列表（PostgresToolRepository.list_page），用 `build_tools` 转 HttpTool/McpTool/EchoTool；内置 echo 工具默认注入方便冒烟测试。`__call__` 内部构造 AgentRunContext 并调 `tool.invoke(args, ctx)`，`ToolExecutionError` 和其他异常一律转成 `[error] ...` 文本回灌 LLM 主循环。
  - `web/deps/graph.py::build_runner`（user chat 路由）注册 tool_executor。
  - `web/admin/routers/apps_admin.py::_register_conversation_services` 顺手注册 tool_executor，admin debug_run_stream / debug_run_stream_resume 两处自动接上。
  - 新增 `tests/test_tool_executor_service.py` 5 例：未知工具列可用清单 / 已知工具透传 args 和 AgentRunContext / ToolExecutionError 转文本 / 其他异常转文本 / 空库时内置 echo 可用。后端 245 个测试全过。
- 2026-10-31：T2 完成。
  - `settings.py` 新增 `vector_store_provider`（memory/pgvector/milvus）+ `milvus_uri` + `milvus_token`。
  - 新增 `internal/engine/services/retrieval_services.py`：`build_embedding_client()`（未配置 api_key 返回 None，节点 handler 自动走 stub）、`build_vector_store()`（按 provider 走已有 factory）、`get_retrieval_bundle()`（进程级单例，threading.Lock 保护）、`register_retrieval_services(services)` 一行注册进 ServiceRegistry。
  - `web/deps/graph.py::build_runner` 与 `web/admin/routers/apps_admin.py::_register_conversation_services` 各加一行 `register_retrieval_services(services)`。Dataset(6) / DatasetWrite(27) handler 本身代码无需改动——它们原本就在等这两个 service。
  - 新增 `tests/test_retrieval_services.py` 7 例：无 api_key 返回 None / 有 api_key 返回 OpenAICompat 客户端 / memory provider 返回 InMemory / 未知 provider 兜底 / embedding=None 时只注册 vector_store / 两者都可用时都注册 / 进程级单例。后端 252 个测试全过。
- 2026-10-31：T3 完成。
  - `internal/infrastructure/sandbox/python_sandbox.py`：
    - 新增 `DEFAULT_ALLOWED_MODULES` 白名单（json/re/math/datetime/collections/itertools/functools/string/decimal/fractions/hashlib/base64/binascii/urllib.parse/random/typing），禁止 os/sys/subprocess/socket/importlib/pathlib。
    - `PythonSandbox.__init__` 新增 `allowed_modules` 参数，默认白名单。
    - `_build_wrapper`：注入受限 `__builtins__.__import__`——非白名单模块抛 `ImportError` 并提示允许列表；`exec(compile(...))` 包 try/except，模块级 import 失败也把 traceback 写到 stdout JSON（`__error__`），而不是只丢到 stderr。
    - `run()`：无论 exit_code 如何都调 `_parse_stdout`，保证 `__error__` 能被 Code 节点 handler 读到。
  - `web/deps/graph.py::build_runner` 与 `web/admin/routers/apps_admin.py::_register_conversation_services` 各加一行 `services.register("sandbox", PythonSandbox())`。
  - 新增 `tests/test_code_node.py` 5 例：白名单模块正常 import / import os 被拒 / import subprocess 被拒 / importlib 动态加载被拒 / 自定义 allowed_modules 扩展白名单。后端 257 个测试全过。
- 2026-10-31：T4 完成。
  - `web/deps/graph.py::build_runner` 在已注册 llm/http/tool_executor/retrieval/sandbox/subgraph_loader 的基础上，当 `current_user_id` 不为 None（user chat 路由场景）时额外注册 `conversation_repo` / `message_repo`：
    - 用 `AsyncConversationRepository` / `AsyncMessageRepository` 包装 sync SQLAlchemy 仓储，绑定当前请求的 tenant_id / user_id / application_id / run_id。
    - admin debug 路由走自己的 `_register_conversation_services`（用 DEBUG_APPLICATION_ID + PlatformAdmin 身份），不冲突。
  - 效果：user 端 `/agents/{id}/workflow/run` 跑含 create_conversation(39) / create_message(55) / query_conversation_list(53) 等节点的工作流时，不再报"service not found"，节点真实读写 conversation/message 表。
  - 后端全量测试全过。
- 2026-10-31：T5 完成（LLM token 流式输出）。
  - `internal/engine/llm.py`：
    - `LLMClient` ABC 新增非抽象 `chat_stream()` 默认实现（退化为一次性 chat，兼容旧 client）。
    - `OpenAICompatLLMClient.chat_stream()`：用 `client.stream("POST", url)` 逐行解析 SSE `data: {...}`，每个 chunk 取 `choices[0].delta.content` 作为增量 yield LLMResponse；流结束时再 yield 一个带 usage 的收尾空 chunk；`stream_options.include_usage=True` 让网关回灌 token 用量。
  - `internal/domain/graph/node_base.py`：`NodeContext` 新增 `emit_event: NodeEventEmitter | None` 字段（frozen dataclass，可选）；导出 `NodeEventEmitter = Callable[[str, dict], Awaitable[None]]`。
  - `internal/domain/graph/compiler.py`：`Compiler.__init__` 新增 `event_emitter` 参数；`_build_node_fn` 闭包内生成绑定 node_id 的 `_emit` 回调并塞进 NodeContext。
  - `internal/engine/runtime.py`：构造 Compiler 时把 `self._on_node_event` 作为 event_emitter 传入，节点内 emit 的 llm_token 事件直接走和 node_start/node_end 同一条 SSE 通道。
  - `internal/domain/graph/nodes/llm.py`：当 `tool_specs` 为空且 `ctx.emit_event` 非 None 时，改走 `_run_streaming()`：逐 chunk emit `llm_token` 事件（`{node_id, delta}`），聚合完整 content 作为 outputs["output"]，usage 从收尾 chunk 回灌。有 tools 时仍走原 ReAct 循环（SSE 流式 + tool_calls 聚合复杂度高，留待后续）。
  - `internal/application/apps/chat_service.py`：当 `tool_specs` 为空（agent_loop 未配置工具）时，第一轮直接走 `client.chat_stream()`，逐 chunk yield `llm_token` SSE 事件；有 tools 时保留原 ReAct 循环。
  - 前端 admin `AppEditPage.tsx`：`nodeDebugMap` 加 `streamingText` 字段；`handleRunEvent` 新增 `llm_token` 分支追加 delta；右侧调试面板在 inputs/outputs 之间渲染蓝色"流式输出"块。
  - 前端 user `ChatPage.tsx` + `agentRun.ts`：AgentStreamEvent 加 `llm_token` 类型；ChatPage 收到 `llm_token` 时直接 setMessages 追加 delta 到 assistant 气泡（打字机效果）。
  - 新增 `tests/test_llm_node_streaming.py` 2 例：流式路径 emit 4 个 token + 聚合 outputs + usage 回灌 / 无 emit_event 时退化为非流式 chat。后端 259 个测试全过。
- 2026-10-31：T6 完成（LLM 记忆开关）。
  - `internal/domain/graph/nodes/llm.py`：
    - 新增配置读取 `needHistory`（bool）+ `historyLimit`（int，默认 10）。
    - 新增 `_load_conversation_history(ctx, history_limit)` 辅助函数：从 `ctx.inputs["conversation_id"]` 或 `ctx.config["conversation_id"]` 取会话 ID，调 `message_repo.list_by_conversation(conv_id, limit)`，过滤掉 system/tool 等非 user/assistant 角色，返回纯历史消息列表。
    - 静默降级：message_repo 未注册 / conversation_id 缺失 / 非合法 UUID / 查询异常时，均返回空列表，不抛错打断主流程。
    - messages 组装顺序：system_prompt（可选）→ 历史 user/assistant → 当前 user prompt。
  - `internal/domain/canvas/node_meta.py`：LLM 节点 config_fields 新增 `needHistory`（boolean 开关，默认 false）+ `historyLimit`（number，默认 10）。
  - 前端 admin `NodeConfigForm` 已有 `boolean` 字段类型渲染（Select 是/否），无需改动——node_meta 下发后自动出现。
  - 新增 `tests/test_llm_node_history.py` 5 例：needHistory=false 不查 repo / needHistory=true 正确拼接历史并过滤 system+tool / conversation_id 缺失时跳过 / 非法 UUID 跳过 / message_repo 未注册时跳过。后端 264 个测试全过。
- 2026-10-31：T7 完成（IF case 可视化编辑器）。
  - `internal/domain/graph/nodes/if_else.py`：
    - 新增 `_OPERATOR_MAP`：eq/ne/gt/gte/lt/lte → Python 比较符；contains/not_contains → `in`/`not in`（左右对调以匹配 coze "left 包含 right" 语义）；is_empty/is_not_empty → 伪操作符。
    - 新增 `_normalize_case_expression(case)`：已有 `expression`/`condition` 字段直接返回；否则按 `left/operator/right` 拼成 Python 表达式字符串。is_empty → `not (left)`；is_not_empty → `not not (left)`（ast 白名单不含 bool()，用双重 not 取真值）；contains 对调为 `right in left`。
    - 新增 `_to_expression_value(raw)`：`{{ref}}` 剥成 inner 引用；数字/bool 字面量；字符串统一 `json.dumps` 加双引号（避免 shlex.quote 对单词不加引号导致被 ast 当 Name 解析）。
    - `_eval_multi_cases`：字符串表达式先判断是否含 `{{`（含则先 `eval_template` 插值），再走 `TemplateEvaluator.eval_expression` 解析 ast 求值；已是 Expr 对象则走 `resolve_config`。
  - 前端 admin `AppEditPage.tsx`：
    - 新增 `CaseListEditor` 组件：每行 左值 Input+RefPickerButton / 操作符 Select（9 种）/ 右值 Input+RefPickerButton（is_empty/is_not_empty 时隐藏）/ 删除按钮；底部"+ 添加条件"按钮。
    - 新增 `parseCasesValue(raw)` 兼容数组 / JSON 字符串两种存储形式。
    - `NodeConfigForm` 对 `field_type === 'case_list'` 走专用渲染，textarea fallback 仅用于未识别类型。
  - 新增 `tests/test_if_else_node.py` 9 例：eq 命中 / ne 落 else / gt / contains 左右对调 / is_empty / is_not_empty / 已有 expression 字段直接使用 / 多 case 第一个为真胜出 / 全假走 else_port。后端 273 个测试全过。
- 2026-10-31：安全修复（AsyncMessageRepository 跨租户 IDOR）。
  - `internal/infrastructure/repository/apps/async_conversation_adapter.py::AsyncMessageRepository.list_by_conversation`：查询消息前先 `get_conversation` 校验归属——会话不存在 / tenant_id 不匹配 / 绑定 user_id 与会话 user_id 不一致 / application_id 不匹配，直接返回空列表，不调用 sync `list_messages_by_conversation`。
  - 触发场景：LLM 节点 needHistory 从 `ctx.config.conversation_id` 取会话 ID，若被填成别人的会话 ID 会造成跨租户读消息。修复同时保护 `QueryConversationHistoryNodeHandler`（type=54）。
  - 新增 `tests/test_async_message_adapter_tenant_scope.py` 5 例：范围匹配返回消息 / 跨租户拒绝 / 跨用户拒绝 / 跨应用拒绝 / 会话不存在返回空。
- 2026-10-31：T8 完成（LLM model picker）。
  - 后端 `internal/application/apps/model_service.py::list_catalog`：
    - 返回字段统一为 `{model_id, display_name, provider_name, capabilities}`，capabilities 自动 `setdefault` `default_temperature` / `default_max_tokens`（兜底取 `settings.llm_temperature`/`llm_max_tokens`），已有自定义值不覆盖。
    - 表为空时（开发态未 seed）回退返回 `[{model_id: settings.llm_model_id, ...}]`，避免前端下拉空空如也。
  - 接口复用现有 `GET /admin/models/catalog/available`（`web/admin/routers/models.py`），无需新增路由。
  - 前端新增 `frontend/admin/src/api/models.ts`：`listAvailableModels()` 调 `/admin/models/catalog/available`，带 `ModelCatalogItem` 类型。
  - 前端 `AppEditPage.tsx` 新增 `ModelPicker` 组件：useEffect 拉模型列表，Select 支持搜索（`showSearch` + `optionFilterProp="label"`），label 格式 `display_name（provider_name）`；onChange 时把 `capabilities.default_temperature` / `default_max_tokens` 一并 patch 进节点 config（`modleName` + `temperature` + `maxTokens`）。
  - `NodeConfigForm` 对 `field_type === 'model_picker'` 走 ModelPicker，原 FieldControl 的 model_picker 分支改为 disabled Input fallback。
  - 新增 `tests/test_model_service_catalog.py` 3 例：空表回退 settings / 非空表补默认 capabilities / 已有自定义 capabilities 不被覆盖。后端 281 个测试全过。
- 2026-10-31：T9 完成（HTTP 节点配置扩展）。
  - `internal/domain/canvas/node_meta.py`：HTTP 节点 config_fields 扩展为 url/method/pathParams/queryParams/headers/authType/authToken/authSecret/bodyType/bodyJson/bodyForm/timeoutMs 共 12 个字段，新增 field_type=key_value_list 用于动态键值对。
  - `internal/domain/graph/nodes/http.py` 重写：
    - 新增 `_to_kv_dict(raw)`：兼容 [{key,value}] 数组 / dict / JSON 字符串三种输入。
    - 新增 `_apply_path_params(url, path_params)`：URL 中 `:param` 形式路径参数替换 + URL 编码（urllib.parse.quote）。
    - 新增 `_build_auth_headers(auth_type, token, secret)`：bearer → `Authorization: Bearer xxx`；basic → `Authorization: Basic base64(user:pass)`。
    - 新增 `_parse_json_body(raw)`：bodyJson 字符串解析成 JSON 对象，解析失败降级为原始字符串。
    - run() 流程：pathParams 替换 URL → queryParams 作 params → headers 合并 auth → bodyType 决定 json_body/form_body；bodyType=none 时保留向后兼容（GET 用 inputs 当 query，POST 用 inputs 当 json body）。
  - `internal/engine/services/http_service.py`：request() 新增 `form_body: dict[str,str] | None` 参数，传 `data=` 给 httpx（与 `json=` 互斥）。
  - 前端 `AppEditPage.tsx`：
    - 新增 `KeyValueListEditor` 组件：每行 Key Input + Value Input（带 RefPickerButton）+ 删除按钮，底部"+ 添加键值对"按钮；支持数组 / dict / JSON 字符串三种输入解析。
    - `NodeConfigForm` 对 `field_type === 'key_value_list'` 走 KeyValueListEditor，原 FieldControl 的 key_value_list fallback 改为 disabled TextArea。
  - 新增 `tests/test_http_node.py` 9 例：kv 字典转换 / 路径参数替换与编码 / bearer+basic 认证头 / GET path+query+headers / POST JSON body + bearer / POST form body / 向后兼容 GET inputs→query / 向后兼容 POST inputs→json / 无 http 服务返回 stub。后端 290 个测试全过。
- 2026-10-31：安全加固（AsyncConversationRepository / AsyncMessageRepository 全方法 IDOR 防护）。
  - 上次只给 `list_by_conversation` 加了范围校验，本次把 `get`/`delete`/`update_title`/`append`/`delete(message_id)`/`clear` 全部补上：
    - `AsyncConversationRepository._assert_in_scope(row)`：会话归属校验（tenant_id + user_id + application_id），不在绑定作用域返回 None。
    - `AsyncConversationRepository.get`：越权会话返回 None；`delete` / `update_title`：越权直接 no-op。
    - `AsyncMessageRepository.append`：若会话已存在，校验作用域，不匹配抛 ValueError；会话不存在（刚创建未落库的事务窗口）放行。
    - `AsyncMessageRepository.delete(message_id)`：先 `get_message` 拿到 conversation_id，校验会话归属后再删。
    - `AsyncMessageRepository.clear(conversation_id)`：先校验会话归属，越权 no-op。
  - `MessageRepository.get_message(message_id)` 新增：按 id 查消息行（含 conversation_id/tenant_id/user_id/application_id），供 adapter 删除前做归属校验。
  - 扩展 `tests/test_async_message_adapter_tenant_scope.py` 至 10 例：list_by_conversation 范围匹配/跨租户拒绝 / append 跨租户拒绝 / append 会话缺失放行 / delete_message 越权拒绝 / delete_message 所有者允许 / clear 跨租户拒绝 / conversation.get 越权返回 None / conversation.delete 越权 no-op / conversation.update_title 越权 no-op。后端 295 个测试全过。
- 2026-10-31：T10 完成（Comment 便签节点）。
  - `internal/domain/graph/nodes/comment.py`：新增 `CommentNodeHandler`，type_name=NodeType.COMMENT.value（"31"），run() 直接返回空 outputs {}，不依赖任何 service。
  - `internal/domain/graph/nodes/__init__.py`：import comment 模块触发注册。
  - `internal/domain/canvas/node_meta.py`：新增 NodeMeta(type_code="31", type_key="comment", color="#ffe58f", category="misc")，无 inputs/outputs 端口，config_fields 只有一个 content textarea。
  - 前端 `AppEditPage.tsx`：
    - `makeNodeRenderer` 对 `meta.type_key === 'comment'` 走专用渲染：黄色便签块（#fff9c4 背景、#5d4037 文字、2px 阴影、左侧 3px #fbc02d 边条），显示 data.content 文本，双击打开配置抽屉。
    - `nodeRegistries` 对 comment 特殊 size={width: 220, height: 100}，defaultPorts 为空（不参与连线）。
  - 新增 `tests/test_comment_node.py` 2 例：handler 已注册且类型正确 / run 返回空 outputs。后端 297 个测试全过。
- 2026-10-31：T11 完成（并发 Loop 的 break/continue）。
  - `internal/domain/graph/nodes/loop.py::_run_parallel` 重写：从 `asyncio.gather` 改为手动 `asyncio.create_task` + `as_completed`，支持运行时取消。
    - break：任一迭代产出 `__break__` 后，置 `break_received=True` 并对所有未完成 task 调 `cancel()`；触发 break 的那次迭代本身不写入结果（与串行语义一致）。
    - continue：产出 `__continue__` 的迭代只跳过输出，其余迭代照常完成。
    - 结果按原数组下标 `sorted(results)` 排序，保证输出顺序与输入顺序对齐。
    - `await fut` 用 `try/except asyncio.CancelledError` 吞掉取消异常；`finally` 块再对残余未完成 task 统一 cancel + `gather(return_exceptions=True)` 兜底。
    - 最大并行度仍走 `asyncio.Semaphore(MAX_PARALLELISM=10)`。
  - 新增 `tests/test_loop_parallel_break_continue.py` 2 例：break 触发后 2/3/4 被取消且只保留已完成的 index 0 / continue 只跳过 index 2 其余按原顺序返回。后端 299 个测试全过。
- 2026-10-31：T12 完成（admin debug 路由接 subgraph_loader）。
  - `web/admin/routers/apps_admin.py`：抽出 `_register_subgraph_loader(services, uow, tenant_id)` helper，内部构造 `ApplicationService(uow)`，定义 async `_loader(child_app_id)`：UUID 解析失败返回 `{}`，调 `app_service.get_runtime_graph(child_uuid, tenant_id)`，异常一律吞掉返回 `{}`。
  - `debug_run_stream` 与 `debug_run_stream_resume` 两处都在 `_register_conversation_services` 之后调用 `_register_subgraph_loader`，避免试运行含 Subworkflow（type=9）节点时走 stub 分支。
  - `internal/domain/graph/nodes/subworkflow.py`：loader 调用改为兼容 sync / async 两种形式——`canvas_json = loader(workflow_id)` 后 `if hasattr(canvas_json, "__await__"): canvas_json = await canvas_json`，与 `web/deps/graph.py` 中 async loader 对齐。
  - 新增 `tests/test_subworkflow_node.py` 4 例：缺 workflowId 返回 error / 未注册 loader 返回 stub / async loader 能被正确 await 并执行子图 END / loader 返回空时返回 error。后端 303 个测试全过。
- 2026-10-31：T13 完成（发布动作 draft → live 快照）。
  - 新增迁移 `migrations/versions/0046_application_published_graph_version.py`：`application.published_graph_version INT NULL`，NULL 表示未发布、运行时回退 latest（向后兼容）。
  - `internal/infrastructure/repository/apps/application_repository.py`：
    - `get_application` SELECT 增加 `published_graph_version` 列。
    - 新增 `set_published_graph_version(application_id, version)`：UPDATE application SET published_graph_version。
  - `internal/application/apps/application_service.py`：
    - `publish_graph(application_id, actor_id, actor_username)`：把 latest 版本号写入 application.published_graph_version；写 `GRAPH_PUBLISH` 审计日志（previous/new published_version + runtime_mode）；commit + 失效缓存。没有 graph 时抛 NotFoundError。
    - `get_runtime_graph` 版本选择顺序改写：①租户 pinned_graph_version → ②application.published_graph_version（NULL 回退 latest）→ ③latest。保证发布后 user chat 读 live，admin 保存新 draft 不影响已发布版本。
  - `web/admin/routers/apps_admin.py`：新增 `POST /{application_id}/publish`，调用 `service.publish_graph`，actor 信息从 PlatformAdmin principal 透传。
  - user chat 路由 `web/deps/graph.py::build_runner` 不变（已调 `get_runtime_graph`），自动切到 live。
  - 新增 `tests/test_publish_graph.py` 4 例：publish 把 published_graph_version 指向 latest / 未发布时 get_runtime_graph 回退 latest / 发布后再保存新 draft，runtime 仍读 published 旧版 / 无 graph 时 publish 抛 NotFoundError。后端 307 个测试全过。
- 2026-10-31：T14 完成（节点 outputs 自定义编辑器）。
  - `frontend/admin/src/pages/apps/AppEditPage.tsx`：
    - 新增 `OutputFieldItem` 类型 `{name, type, description}` + `OUTPUT_TYPE_OPTIONS`（string/number/boolean/object/array/array[string]/array[number]/array[object]）。
    - 新增 `parseOutputsValue(raw)`：兼容 `data.outputs` 数组中缺省字段。
    - 新增 `OutputsEditor` 组件：每行 = 字段名 Input(140px) + 类型 Select(140px) + 描述 Input(flex) + 删除按钮；底部"+ 添加输出字段"按钮；空态文案"暂未定义输出字段"。
    - `NodeConfigForm` 增加 `outputs` / `onOutputsChange` 两个 props；在 config_fields 循环之后追加"输出字段（outputs）"区块，说明文案"自定义本节点产出的字段列表，保存后写入 node.data.outputs"。
    - 页面组件新增 `nodeOutputs` state；双击选中节点时 `setNodeOutputs(parseOutputsValue(nodeData.outputs))` 初始化；新增 `handleOutputsChange(next)`：同步 state + 直接写回 `node.data.outputs = [{name, type, description?}]`（description 空串时省略，保持 JSON 紧凑）。
    - `handleNodeDoubleClick` 的 nodeData 类型补上 `outputs?: unknown[]`。
  - 保存路径已复用现有 `toCozeIR`：`out.data.outputs = (data.outputs || [])`，无需额外改造。`fromCozeIR` 加载时同样保留 outputs 数组。`npx tsc --noEmit` 干净。
- 2026-10-31：T15 完成（运行 trace 面板）。
  - `internal/domain/graph/nodes/agent_loop.py`：
    - 抽出 `_emit(etype, payload)` 闭包：合并 `node_id`，吞异常不影响主流程。
    - `_plan` / `_execute` / `_reflect` 三个阶段都接收 `ctx, emit` 参数：
      - **prompt_text**：每次 LLM 调用前发 `{phase, messages, reflect_round?, tool_round?}`；调用后发 assistant 内容 `{phase, role: "assistant", content, tool_calls?}`。
      - **tool_call_start**：execute 循环里每次 LLM 返回 tool_calls 后，对每个 tc 发 `{name, arguments, reflect_round, tool_round}`。
      - **tool_call_end**：工具执行完成后发 `{name, arguments, observation, ...}`。
    - 新增 `_messages_for_trace(messages)`：长 content 截断到 4000 字符、tool_calls 只保留 name/arguments，避免 SSE 包过大。
  - 前端 `AppEditPage.tsx`：
    - `nodeDebugMap` 每条目新增 `trace: Array<{type, payload}>` 字段。
    - `handleRunEvent` 新增三个分支：`prompt_text` / `tool_call_start` / `tool_call_end` 都 append 到当前 node 的 trace 数组。
    - 新增 `TraceEntry` 组件：按事件类型渲染不同颜色 Tag（prompt=blue / assistant=geekblue / tool_call_start=orange / tool_call_end=green），pre 块展示 messages 列表 / assistant 内容 / tool 入参 / tool observation，phase 标签带 `[phase#round.tool]` 维度。
    - 调试面板 Collapse 每项展开后底部新增"运行 trace（N 条）"区块。
  - 新增 `tests/test_agent_loop_trace_events.py` 1 例：脚本化 LLM + 工具执行器，捕获 emit_event 调用，校验 prompt_text / tool_call_start / tool_call_end 数量与字段。后端 308 个测试全过。
- 2026-10-31：T16 完成（租户模型/插件配置页）。
  - 新增 migration `0047_tenant_settings.py`：`tenant_settings` 表，一行一租户（tenant_id unique），含 `default_model_catalog_id`（FK 到 model_catalog，ON DELETE SET NULL）、`allowed_catalog_ids`（JSONB UUID 列表，空=平台全量可见）、`plugin_whitelist`（JSONB 字符串列表，空=平台全量可见）。
  - 新增 `internal/infrastructure/repository/apps/tenant_settings_repository.py`：`get/upsert/list_all` 原生 SQL。
  - 新增 `internal/application/apps/tenant_settings_service.py`：upsert 前校验 default_model_catalog_id / allowed_catalog_ids 必须存在于 model_catalog，否则 NotFoundError；返回空结构时 `default_model_catalog_id=None / allowed_catalog_ids=[] / plugin_whitelist=[]`。
  - `web/admin/routers/tenants.py` 新增 `TenantSettingsUpdateRequest` schema + `GET /{tenant_id}/settings` + `PUT /{tenant_id}/settings`，权限沿用 `page:tenants` / `button:tenant:update`。
  - 前端新增 `api/tenantSettings.ts`（getTenantSettings / updateTenantSettings）+ `pages/tenants/TenantSettingsPage.tsx`（默认模型 Select + 白名单 Switch + 多模型 Select + 插件 Tag 输入区）；`router.tsx` 加 `/tenants/:id/settings` 路由（platformOnly）；`TenantDetailPage` 头部加"运行时配置"跳转按钮。
  - 新增 `tests/test_tenant_settings.py` 5 例：空结构返回 / upsert 落库 / default_catalog 不存在抛错 / allowed_catalog 不存在抛错 / 覆盖式写。后端 313 个测试全过。
- 2026-10-31：T17 完成（节点 lint）。
  - 新增 `internal/domain/canvas/lint.py`：`lint_graph(graph)` 函数，复用 `validate.ValidationIssue` 数据结构，三条规则：
    1. **表达式语法**：递归遍历 `node.config`，对 `TemplatedString` 实例和含 `{{...}}` 的字符串，每个模板体用 `ast.parse(body, mode="eval")` 校验；if_else 的 `cases[].expression` 是裸表达式，单独走 `_check_bare_expression`。语法错/空表达式 → `error`。
    2. **必填 config 非空**：按 `NodeMeta.config_fields` 里 `required=True` 的字段，检查 `node.config.get(name)` 是否为 None / 空串 / 空 list / 空 dict。空 → `error`。
    3. **端口类型匹配**：每条边查 source 节点 outputs（或 NodeMeta 默认输出）的类型，target 节点 inputs 类型；类型 normalize（int/integer/float/double→number，bool→boolean 等）；string 对任意类型放行；number→boolean / boolean→number / array→object 给 warning。
  - `validate_raw_graph` 串联：`validate_graph(graph) + lint_graph(graph)`，save_graph 已经把 error 级问题抛 `ValidationError`，warning 仅记录不阻塞。
  - 新增 `tests/test_lint_node.py` 9 例：表达式语法错/合法模板/必填缺失/必填填好/端口类型组合/直接构造 CanvasGraph 验证 warning 路径。
  - 顺带修复 `test_graph_object_storage.py` 3 例：原来的 LLM 节点没填 modleName/prompt，被新 lint 拦下；按 T17 规则补 ValueExpressionDTO 结构，并把 `config.prompt` 断言路径改成 `data.inputs.prompt.value.content`。后端 322 个测试全过。
- 2026-10-31：T18 完成（多模态）。
  - 后端 `nodes/llm.py`：新增 `_extract_images(ctx, config)` —— 从 `inputs["images"]` 或 `config["images"]` 取图片列表；支持 list[str] 和逗号分隔 str（前端多图 dataURL 拼接）。新增 `_build_multimodal_content(text, images)` 组装 OpenAI multi-modal parts：`[{type:"text",text:...}, {type:"image_url",image_url:{url:...}}]`。有图片时 user message content 用 parts 数组，无图片时保持原 str 向后兼容。
  - `node_meta.py` START 节点 inputs 描述更新："类型支持 string / number / boolean / file / image"。
  - 前端 `AppEditPage.tsx`：试运行入参弹窗按 START 参数 type 分渲染——`image` / `file` 类型渲染 antd `Upload`（accept=image/*，listType=picture，multiple），`beforeUpload` 里 FileReader.readAsDataURL 读成 base64 dataURL 追加到 `runInputs[name]`（逗号分隔），`onRemove` 清空字段。其他类型保持原 Input。
  - 新增 `tests/test_llm_multimodal.py` 5 例：无图纯文本 / inputs 多图 / config 兜底 / 非字符串元素过滤 / 单字符串拆分。后端 327 个测试全过。
