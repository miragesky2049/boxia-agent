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

---

## 七、2026-10-31 UI/UX 对齐 Coze/Dify 专项（阶段 5）

> 触发：T1–T18 后画布功能已闭环，但视觉与体验仍停留在"demo 级"。
> 参考：Coze 实机（`coze.cn/space/.../project-ide/.../workflow/...`）+ Dify 公开 UI。
> **铁律**：结构以 Coze 为标准；视觉/交互细节可借鉴 Dify 但**严禁复制 Dify 源码**（开源协议）；两者冲突时弹选项让用户选。

### 7.1 现状 UI 问题（对照 Coze 实机截图）

| # | 现状 | Coze 标准 | 差距 |
|---|------|----------|------|
| U1 | 节点 = 纯色圆角块（`background: meta.color`，白字），无图标、无副标题 | 白底卡片 + 左上角 24×24 彩色图标 + 标题 + 一行副标题摘要（关键参数） | 视觉密度低、不专业 |
| U2 | outputs 列表直接渲染在节点色块内部（白字半透明） | 节点卡片右侧圆形端口点，hover 显示字段名+类型 tooltip | 端口不可拖连，体验割裂 |
| U3 | 连线走 Flowgram 默认灰色 | 紫色贝塞尔曲线（#6366f1），端点带箭头 | 连线无方向感 |
| U4 | 节点库在左侧静态面板，按钮堆叠 | 底部浮条"+ 添加节点"按钮 → 弹出分类气泡菜单（带搜索） | 操作路径长 |
| U5 | 试运行按钮在右上角小按钮 | 底部浮条最右侧绿色大按钮"▷ 试运行" | 不醒目 |
| U6 | 无缩放控制、无小地图、无适应画布 | 底部浮条：缩放 % 下拉 / 适应画布 / 网格开关 | 大图导航困难 |
| U7 | 左侧只有节点库 | 左侧资源树：当前工作流 / 设置（变量） | 缺全局导航 |
| ~~U8~~ | ~~顶部面包屑~~ | ~~双 Tab~~ | **砍掉**（我们没有 UI Builder） |
| U9 | 选中节点无高亮边框/阴影 | 选中 = 卡片外圈 2px 蓝色描边 + 轻微投影 | 选中态不明显 |
| U10 | 变量引用 chip 是纯文本 `{{nodeId.output.x}}` | 单行 Input 内渲染蓝色胶囊 chip | 不可读 |
| U11 | 空画布 = 一个 START 节点 | 空态 = 居中欢迎卡片（"从添加第一个节点开始"） | 首次进入体验差 |
| U12 | 配置抽屉从右侧滑出，表单字段堆叠 | 右侧 480px 抽屉，字段分组（基础设置 / 输入 / 输出 / 高级）+ 分割线 | 信息层级不清 |

### 7.2 视觉规范（自研，不抄 Dify）

- **主色**：`#6366f1`（indigo-500），与 Coze 紫色系对齐但不是同一色值。
- **节点卡片**：白底 `#ffffff`、边框 `1px solid #e5e7eb`、圆角 8px、阴影 `0 1px 2px rgba(0,0,0,0.04)`、选中态 `border-color: #6366f1 + box-shadow: 0 0 0 3px rgba(99,102,241,0.15)`。
- **节点图标**：24×24，圆角 6px，背景取 `meta.color` 降饱和 30%（如 `bgcolor: #e0e7ff`、图标 emoji 或 SVG）。
- **连线**：贝塞尔曲线 `stroke: #a5b4fc`、hover `#6366f1`、选中 `#4338ca`、端点箭头 6px。
- **端口**：直径 10px 圆形，未连接灰色 `#d1d5db`，已连接 `#6366f1`，hover 放大到 14px。
- **底部浮条**：白底 + 顶部 1px 边框 `#f3f4f6` + 圆角 12px 阴影，固定在画布底部居中，z-index 10。
- **试运行按钮**：`#10b981`（emerald-500）、白色文字、padding 12px 20px、圆角 8px。

### 7.3 任务清单（阶段 5）— 组件级粒度

> 每个任务拆到：新建/修改文件、组件名、props/state、样式 token、验收标准。
> 全部在 `frontend/admin/` 下，后端不动。

---

#### P0：节点卡片重设计（视觉冲击最大）

##### U-N1 节点卡片组件重写

**现状**：`AppEditPage.tsx:149-181` 的 `makeNodeRenderer` 返回一个纯色 div（`background: meta.color, color: #fff, borderRadius: 8`），outputs 列表用白字半透明渲染在色块内部。

**目标**：白底卡片 + 左上角 24×24 彩色图标 + 标题 + 副标题摘要，参考 Coze `node-header`（白底、圆角 7px、cursor-move）。

**新建文件**：
- `frontend/admin/src/pages/apps/components/NodeCard.tsx`
- `frontend/admin/src/pages/apps/components/NodeIcon.tsx`
- `frontend/admin/src/pages/apps/components/nodeSubtitle.ts`（纯函数，按 typeKey 生成副标题）

**NodeCard props**：
```ts
interface NodeCardProps {
  meta: NodeMeta;           // 来自 /node-meta API
  title: string;            // node.data.title || meta.title
  subtitle: string;          // 由 nodeSubtitle(config) 生成
  status?: 'idle' | 'running' | 'success' | 'error';  // 来自 nodeDebugMap
  selected: boolean;         // Flowgram 选中态
  onDoubleClick: () => void;
  width?: number;           // 默认 240
  children?: React.ReactNode;  // ports 由 Flowgram 注入
}
```

**NodeIcon 映射表**（emoji 图标，底色统一由 `meta.color` 自动降饱和，不硬编码）：
| type_key | emoji | 说明 |
|---|---|---|
| start | ▶️ |  |
| end | ⏹️ |  |
| llm | 🤖 |  |
| http | 🌐 |  |
| if_else | 🔀 |  |
| code | {'</>'} |  |
| dataset | 📚 |  |
| dataset_write | ✍️ |  |
| loop | 🔁 |  |
| batch | 📦 |  |
| subworkflow | 📂 |  |
| variable_set | 🔧 |  |
| text_processor | 📝 |  |
| json_tools | 🧩 |  |
| conversation_* | 💬 | 9 种会话节点共用 |
| human_task | 👤 |  |
| comment | 📌 | 黄色便签，不走白底卡片 |
| api_plugin | 🔌 |  |
| agent_loop | 🧠 |  |

> 底色规则：图标块背景 = `meta.color` 自动取 15% 透明度叠加白底（不用硬编码色值）。
> 例如 `meta.color=#6366f1` → 图标背景 `rgba(99,102,241,0.12)`。

**nodeSubtitle.ts 规则**：
```ts
export function buildSubtitle(typeKey: string, config: Record<string, any>): string {
  switch (typeKey) {
    case 'llm': return `model: ${config.modleName || '未设置'}`;
    case 'http': return `${config.method || 'GET'} ${truncate(config.url || '', 24)}`;
    case 'if_else': return `${config.cases?.length || 0} 个条件`;
    case 'code': return 'Python';
    case 'dataset': return `topK: ${config.topK || 3}`;
    case 'loop': return config.parallel ? '并行' : '串行';
    case 'subworkflow': return config.workflowId ? '已绑定' : '未绑定';
    case 'api_plugin': return config.pluginName || '未设置插件';
    default: return '';
  }
}
```

**样式 token**（NodeCard 内联）：
- 容器：`background: #fff, border: 1px solid #e5e7eb, borderRadius: 8, padding: '10px 12px', minWidth: 200, boxShadow: 0 1px 2px rgba(0,0,0,0.04)`
- 选中：`borderColor: #6366f1, boxShadow: 0 0 0 3px rgba(99,102,241,0.15)`
- 图标块：`width: 24, height: 24, borderRadius: 6, background: meta.color 降饱和, display: flex, alignItems: center, justifyContent: center, fontSize: 14`
- 标题：`fontSize: 14, fontWeight: 600, color: #111827, lineHeight: '20px'`
- 副标题：`fontSize: 12, color: #9ca3af, lineHeight: '16px', marginTop: 2, overflow: hidden, textOverflow: ellipsis, whiteSpace: nowrap`

**验收**：
- [x] 所有 25 种节点在画布上显示为白底卡片（comment 保持黄色便签不变）
- [x] LLM 节点副标题显示 `model: gpt-4o`
- [x] HTTP 节点副标题显示 `GET https://...`（URL 截断到 24 字符）
- [x] 选中节点有蓝色描边 + 光晕
- [x] 双击仍打开配置抽屉

---

##### U-N2 连线样式定制

**现状**：Flowgram 默认灰色连线，无箭头。

**目标**：紫色贝塞尔曲线 + 箭头端点，参考 Coze `stroke: #a5b4fc`。

**修改文件**：`AppEditPage.tsx`（FreeLayoutEditor 的 `defaultLineStyle` 或 CSS 覆盖）

**实现方式**：在 `AppEditPage.tsx` 顶部加 CSS（用 `:global` 或 styled-jsx）：
```css
:global .flow-graph-line {
  stroke: #a5b4fc !important;
  stroke-width: 2;
}
:global .flow-graph-line:hover {
  stroke: #6366f1 !important;
}
:global .flow-graph-line.selected {
  stroke: #4338ca !important;
  stroke-width: 2.5;
}
```

**箭头**：Flowgram 若支持 `markerEnd` 则配置；否则用 SVG `marker` 元素注入 defs。

**验收**：
- [x] 所有连线为淡紫色 `#a5b4fc`
- [x] hover 时变深 `#6366f1`
- [x] 连线端点有箭头

---

##### U-N3 选中态/hover 态端口放大

**现状**：端口是 Flowgram 默认小圆点，无放大效果。

**目标**：未连接灰色 `#d1d5db`、已连接 `#6366f1`、hover 放大到 14px。

**修改文件**：`AppEditPage.tsx` CSS 覆盖 + NodeCard 注入 port 样式。

**CSS**：
```css
:global .flow-graph-port {
  width: 10px; height: 10px;
  background: #d1d5db;
  border: 2px solid #fff;
  transition: all 0.15s;
}
:global .flow-graph-port.connected { background: #6366f1; }
:global .flow-graph-port:hover {
  width: 14px; height: 14px;
  background: #6366f1;
}
```

**验收**：
- [x] 端口为 10px 圆形灰点
- [x] 连线连接后变紫色
- [x] hover 放大到 14px 并变紫色

---

##### U-N4 对齐辅助线

**现状**：拖拽节点时无对齐提示。

**目标**：拖拽时与其他节点水平/垂直对齐时显示虚线辅助线。

**实现**：优先查 Flowgram 是否内置 `snap` / `guide` 插件。若无，**本期不做**（避免自研拖拽引擎）。

**验收**：
- [ ] 拖拽节点时与其他节点水平/垂直居中对齐时出现虚线（或 Flowgram 内置则启用）
  - 状态：**砍掉**（FlowGram free-layout-editor 0.1.x 未暴露 snap/guide API，MVP 不做，避免自研拖拽引擎）

---

##### U-N5 节点运行状态色

**现状**：试运行时节点高亮在 `nodeDebugMap` 里有数据，但画布上无视觉反馈。

**目标**：节点外圈 2px 边框按状态变色。

**修改文件**：`NodeCard.tsx`（已在 U-N1 预留 `status` prop）

**样式**：
- running：`borderColor: #3b82f6` + CSS 呼吸动画 `@keyframes pulse`
- success：`borderColor: #10b981`
- error：`borderColor: #ef4444`
- idle：默认 `#e5e7eb`

**呼吸动画 CSS**：
```css
@keyframes node-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(59,130,246,0.5); }
  50% { box-shadow: 0 0 0 6px rgba(59,130,246,0); }
}
.node-running { animation: node-pulse 1.5s infinite; }
```

**验收**：
- [x] 试运行时正在执行的节点蓝色呼吸
- [x] 成功变绿、失败变红

---

#### P1：底部居中浮条

##### U-B1 CanvasToolbar 组件

**新建文件**：`frontend/admin/src/pages/apps/components/CanvasToolbar.tsx`

**布局**（精简后，砍掉鼠标模式和评论按钮）：
```
[缩放%▾] [▦ 网格] [🗺️ 小地图] [⛶ 适应画布]    │    [+ 添加节点]    │    [▷ 试运行]
←──── 左组 ────→                              ←─中─→   ←── 右组 ──→
```

**位置**：`position: absolute, bottom: 16, left: '50%', transform: 'translateX(-50%)', zIndex: 10`

**容器样式**：
```ts
{
  background: '#fff',
  border: '1px solid #e5e7eb',
  borderRadius: 12,
  padding: '6px 12px',
  boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
  display: 'flex',
  alignItems: 'center',
  gap: 8,
}
```

**子组件**：
| 按钮 | 图标 | 功能 |
|---|---|---|
| 缩放% | 25%▾ | 下拉：25/50/75/100/125/200 |
| 网格 | ▦ | 切换网格背景 |
| 小地图 | 🗺️ | 切换小地图（Flowgram 内置才启用） |
| 适应画布 | ⛶ | 一键缩放到全部节点可见 |
| +添加节点 | + 添加节点 | 紫色按钮（#eef2ff 底 + #4f46e5 字） |
| 试运行 | ▷ 试运行 | 绿色大按钮（#10b981 底 + 白字） |

**props**：
```ts
interface CanvasToolbarProps {
  zoom: number;
  onZoomChange: (z: number) => void;
  onFitView: () => void;
  onToggleGrid: () => void;
  onToggleMinimap: () => void;
  onAddNode: (typeKey: string) => void;  // 由 U-B2 气泡菜单触发
  onRun: () => void;
  running?: boolean;
}
```

**验收**：
- [x] 工具栏固定在画布底部居中浮起
- [x] 缩放%下拉能实际缩放画布
- [x] 试运行按钮点击触发现有 `handleRun`

---

##### U-B2 +添加节点气泡菜单

**新建文件**：`frontend/admin/src/pages/apps/components/AddNodePopover.tsx`

**触发**：U-B1 的"+ 添加节点"按钮点击。

**布局**：Popover 浮在按钮上方，宽 320px。

**结构**：
- 顶部搜索框（Input，placeholder="搜索节点"）
- 分类分组（从 NodeMeta API 拉的 category）：
  - 流程控制（start/end/if_else/loop/batch/break/continue/variable_merge/set_variable/subworkflow/human_task）
  - AI（llm/agent_loop）
  - 逻辑（http/code/json_tools/text_processor/api_plugin）
  - 数据（dataset/dataset_write）
  - 会话（conversation_* 9 种）
  - 其他（comment）
- 每项：24px 图标块 + 节点名 + 一句话描述
- 点击后关闭 Popover，在画布中心位置添加该类型节点

**验收**：
- [x] 点击+添加节点弹出分类列表
- [x] 搜索框能过滤节点
- [x] 点击某项在画布中心添加节点

---

##### U-B3 小地图

**实现策略**：先查 Flowgram 是否内置 `MiniMap` 插件。
- 若有：启用并放在工具栏开关控制显隐
- 若无：**本期不做**，工具栏小地图按钮 disabled + tooltip"暂未支持"

**验收**：
- [x] 工具栏小地图按钮可切换（若 Flowgram 支持）

---

##### U-L3 连线拖拽端口高亮

**现状**：从端口拖出连线时，画布上其他端口无视觉反馈。

**目标**：拖线时，所有可连接的端口（类型兼容）显示蓝色高亮光圈，不可连接的置灰。

**实现**：Flowgram 若有 `onConnectionStart` / `isConnectable` 回调则接入；否则本期不做。

**验收**：
- [x] 从输出端口拖线时，合法输入端口高亮蓝色
- [x] 非法端口置灰

---

##### U-L4 连线点击选中删除

**现状**：连线不能选中，只能通过删除节点间接删边。

**目标**：点击连线选中（紫色加粗 + 端点圆点），按 Delete 删除；点击空白处取消。

**实现**：Flowgram 若有 `lineSelected` 事件则接入；在 U-N2 CSS 里已预留 `.selected` 样式。

**验收**：
- [x] 点击连线变深紫色加粗
- [x] Delete 删除选中连线
- [x] 点击空白取消选中

---

#### P2：左侧资源树

##### U-L1 左侧资源树升级

**现状**：`AppEditPage.tsx` 左侧是节点库按钮列表。

**目标**：改为 Coze 风格资源树，含"工作流/插件/数据/设置"分组。

**新建文件**：`frontend/admin/src/pages/apps/components/ResourceSidebar.tsx`

**结构**（精简后，砍掉插件/数据空壳）：
```
[资源]                                  [<<] 折叠
─────────────────────────
▼ 当前工作流
  📄 {appName}（当前，高亮）
─────────────────────────
▼ 设置
  (x) 变量
  💬 会话管理
```

**props**：
```ts
interface ResourceSidebarProps {
  appName: string;
  onCollapse: () => void;
  onOpenVariables: () => void;   // 触发 U-L2
  onOpenConversation: () => void;
}
```

**注意**：节点库功能迁移到 U-B2 气泡菜单，左侧不再放节点列表。

**验收**：
- [x] 左侧显示资源树结构
- [x] 折叠按钮能收起整个侧边栏
- [x] 点击"变量"打开 U-L2 抽屉

---

##### U-L2 全局变量面板

**新建文件**：`frontend/admin/src/pages/apps/components/VariablesDrawer.tsx`

**数据**：`graph.variables`（T14 后端已支持）

**布局**：右侧 Drawer 480px，标题"全局变量"。

**字段**：name / type（string/number/boolean/object/array）/ default / description

**操作**：新增行 / 删除行 / 编辑行内联。

**验收**：
- [x] 能列出当前 graph.variables
- [x] 新增变量后保存到 graph JSON

---

#### P3：输入体验

##### U-I1 变量引用 chip 胶囊渲染

**现状**：RefPicker 选完后插入纯文本 `{{nodeId.output.x}}`。

**目标**：在**单行 Input** 字段内渲染为蓝色胶囊 chip（#eef2ff 底 + #4f46e5 字），可点击删除。

**重要降级**：textarea / code_editor 字段**不做 chip**（textarea 是纯文本元素，无法内嵌 React 组件；Coze 实际用 contenteditable div，工作量 2-3 天，本期不做）。只在单行 text Input 上做。

**新建文件**：`frontend/admin/src/pages/apps/components/RefChipInput.tsx`

**实现**：
- 用 antd `Input` 的 `prefix` / `suffix` 插槽不够（chip 在文本中间），改用一个简单的"伪 Input"：
  - 外层 div 模拟 Input 外观（边框、圆角、高度 32px）
  - 内部按 `{{...}}` 正则切分文本片段，普通片段渲染为 span，引用片段渲染为 chip
  - chip = `<span style="background:#eef2ff;color:#4f46e5;padding:0 6px;border-radius:4px;margin:0 2px">{inner}<button>×</button></span>`
- 点击 chip 的 × 删除该引用（从字符串中移除对应 `{{...}}` 片段）

**限制**：
- 不支持光标定位编辑（用户只能在文本末尾追加或整体重写）
- 不支持 chip 内光标移动（避免富文本编辑器复杂度）

**验收**：
- [x] 单行 Input 字段（如 url / left / right）输入 `你好 {{start.output.input}}` 时，引用部分显示为蓝色胶囊
- [x] 点击 × 删除该引用
- [x] textarea / code_editor 字段保持纯文本不变

---

##### U-I2 空画布欢迎页

**新建文件**：`frontend/admin/src/pages/apps/components/EmptyCanvasWelcome.tsx`

**触发条件**：`document.nodes.length === 1 && document.edges.length === 0`（只有 START）

**布局**：画布中央绝对定位卡片：
```
┌─────────────────────────┐
│  👋 从添加第一个节点开始  │
│  点击底部 + 添加节点     │
│                         │
│  [＋ 从空白开始]         │
└─────────────────────────┘
```

**验收**：
- [x] 新建应用打开时画布中央显示欢迎卡片
- [x] 添加第一个节点后欢迎卡片消失

---

##### U-I3 配置抽屉分组框架（含 LLM/IF 节点 override）

**现状**：`NodeConfigForm` 把 `config_fields` 平铺渲染。

**目标**：统一的分组框架，按 NodeMeta 字段元数据自动分组；LLM / IF 等复杂节点用专用 override 组件。

**修改文件**：`AppEditPage.tsx` 的 `NodeConfigForm` 组件 + 新增 `NodeConfigSections.tsx`

**分组规则**（在 NodeMeta 的 ConfigFieldMeta 加 `section` 字段）：
- `basic`：title / description / 名称类字段 → "基础设置"
- `input`：url / method / prompt / left / right / 输入变量 → "输入参数"
- `output`：追加现有 OutputsEditor → "输出字段"
- `advanced`：timeout / retry / error_policy / needHistory / historyLimit → "高级"
- 未标注 section 的字段归到 `basic`

**分组渲染**：
```tsx
{sections.map(section => (
  <div key={section.key} style={{ marginBottom: 16 }}>
    <div style={{ fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
      {section.title}
    </div>
    <div style={{ borderTop: '1px solid #f3f4f6', paddingTop: 8 }}>
      {section.fields.map(field => <FieldControl ... />)}
    </div>
  </div>
))}
```

**节点 override 机制**：
- 在 `NodeConfigForm` 里按 `meta.type_key` 查 override 组件：
  - `llm` → 用 `LlmConfigSection`（包含模型选择、技能空态、输入变量 key-value、视觉理解、提示词、高级）
  - `if_else` → 用 `IfElseConfigSection`（包含"如果"卡片列表 + "否则"静态卡片）
  - 其他节点 → 走通用分组渲染

**U-LLM1 / U-LLM2 / U-IF1 合并到本任务**：
- U-LLM1（LLM 抽屉分组重排）= `LlmConfigSection` 组件
- U-LLM2（输入变量 key-value 编辑器）= `LlmConfigSection` 内的子组件
- U-IF1（如果/否则卡片化）= `IfElseConfigSection` 组件

**验收**：
- [x] LLM 节点抽屉显示"模型 / 技能（空态） / 输入变量 / 提示词 / 视觉理解 / 高级"分组
- [x] IF 节点抽屉显示"如果"卡片列表 + "否则"静态卡片
- [x] HTTP 节点抽屉显示"基础 / Headers / Query / Body / 认证 / 高级"分组
- [x] 简单节点（start/end）只有"基础设置"一组

---

#### P4：细节 polish

##### U-P1 快捷键

**修改文件**：`AppEditPage.tsx` 加 `useEffect` 绑定 keydown。

**映射**：
| 快捷键 | 功能 |
|---|---|
| Delete / Backspace | 删除选中节点 |
| Ctrl/Cmd+S | 保存 |
| Space + 拖拽 | 平移画布（Flowgram 内置则启用） |
| Ctrl/Cmd + 滚轮 | 缩放画布 |

**验收**：
- [x] Delete 能删除选中节点
- [x] Ctrl+S 触发保存

---

##### U-P2 节点右键菜单

**新建文件**：`frontend/admin/src/pages/apps/components/NodeContextMenu.tsx`

**菜单项**：复制 / 粘贴 / 重命名 / 删除 / 查看输出

**实现**：antd `Dropdown` + `trigger={['contextMenu']}` 包在 NodeCard 外层。

**验收**：
- [x] 右键节点弹出菜单
- [x] 删除项能删除节点

---

##### U-P5 框选/Shift 多选

**实现**：查 Flowgram 是否内置框选。
- 若有：启用
- 若无：本期不做

**验收**：（依赖 Flowgram 能力）

---

##### U-P6 撤销/重做

**实现策略**：**先查 Flowgram 是否内置 undo/redo**。
- 若内置（查 `@flowgram.ai/free-layout-editor` 文档）：直接启用，绑定 Ctrl+Z/Y
- 若不内置：**本期不做**，避免自研 history 栈与 Flowgram 内部状态冲突

**验收**：
- [x] 若 Flowgram 内置则 Ctrl+Z/Y 可用；否则跳过

---

##### U-P4 窄屏降级

**修改文件**：`AppEditPage.tsx` 用 `useMediaQuery`。

**规则**：< 1024px 时 ResourceSidebar 默认折叠为图标条。

**验收**：
- [x] 缩窄窗口到 800px 时侧边栏自动收起

### 7.4 决策点（执行前需用户拍板）

在动手前，以下 3 个分歧点需要选：

1. **视觉主色**：Coze 紫 `#6366f1` vs Dify 蓝 `#2563eb`？（推荐 Coze 紫，与已有的 indigo 节点色对齐）
2. **底部浮条位置**：底部居中浮起（Coze）vs 底部整条通栏（Dify）？（推荐居中浮起，视觉更轻）
3. **节点卡片副标题**：自动从 config 生成 vs 永远显示固定 meta？（推荐自动生成，信息量更大）

**已确认决策（2026-10-31）**：
- 主色：Coze 紫 `#6366f1`
- 底部浮条：居中浮起
- 副标题：从 config 自动提取
- U8 顶部"业务逻辑/用户界面"双 Tab：**砍掉**（我们没有 UI Builder 概念）
- U-B3 小地图：**Flowgram 内置就用，没有不做**（不自研）
- U-I2 空画布欢迎页：**只做"从空白开始"，砍掉 FAQ 模板**

### 7.5 Coze vs Dify 画布交互全层级对比（2026-10-31 补）

> 按页面层级逐项对比，默认以 Coze 结构为准；Dify 体验更优的吸收；冲突时不抄源码，只学交互思路。

| 层级 | 功能点 | Coze 做法 | Dify 做法 | 最终选用 | 备注 |
|---|---|---|---|---|---|
| **顶部栏** | 应用名 + 保存状态 | 顶部左侧应用名 + 编辑图标 | 顶部左侧应用名 + 部署状态 | ✅ 保留现状 | 我们已有 |
| | 发布按钮 | 顶部右侧"发布"按钮 | 顶部右侧"发布"按钮 | ✅ Coze 位置 | T13 后端已就绪，前端待加 |
| | 双 Tab（业务/UI） | 有 | 无（编排/日志/分析 Tab） | ❌ 砍掉 | 已确认 |
| **左侧面板** | 节点库形态 | 资源树（工作流/插件/数据/设置） | 分类列表（拖拽添加） | ✅ Coze 结构 | 当前阶段只放节点库 + 变量 |
| | 节点搜索 | +添加节点弹窗顶部搜索框 | 左侧面板顶部搜索框 | ✅ Coze 气泡搜索 | 已在 U-B2 |
| | 折叠按钮 | 左侧面板可折叠 | 左侧面板可折叠 | ✅ 都做 | |
| **画布区** | 背景网格 | 浅灰点阵 | 浅灰点阵 | ✅ 一致 | |
| | 拖拽平移 | Space+拖动 / 空白处拖动 | Space+拖动 | ✅ 都做 | U-P1 |
| | 滚轮缩放 | 以鼠标位置为中心 | 以鼠标位置为中心 | ✅ 都做 | |
| | 对齐辅助线 | 拖拽节点时显示网格对齐线 | 拖拽节点时显示对齐线 | ✅ 都做 | **新增 U-N4** |
| | 小地图 | 内置（右下浮窗） | 内置（左下浮窗） | ✅ Flowgram 内置就用 | 已确认 |
| | 适应画布 | 一键缩放到全部节点可见 | 一键缩放到全部节点可见 | ✅ 都做 | U-B1 |
| | 栅格大小切换 | 无 | 无 | ❌ 不做 | |
| **节点卡片** | 卡片样式 | 白底 + 图标 + 标题 + 副标题 | 白底 + 图标 + 标题 + 副标题 | ✅ Coze | 已在 U-N1 |
| | 端口位置 | 输出在右、输入在左 | 输出在右、输入在左 | ✅ Coze | |
| | 选中态 | 蓝色描边 + 阴影 | 蓝色描边 + 阴影 | ✅ 都做 | U-N3 |
| | 运行状态色 | 运行中=蓝色呼吸 / 成功=绿 / 失败=红 / 等待=黄 | 同左 | ✅ 都做 | **新增 U-N5** |
| | 节点大小 | 按内容自适应 | 按内容自适应 | ✅ 都做 | |
| **连线** | 曲线样式 | 紫色贝塞尔 + 箭头 | 深灰贝塞尔 + 箭头 | ✅ Coze 紫 | U-N2 |
| | 连线时高亮 | 拖线时可连接端口高亮 | 同左 | ✅ 都做 | **新增 U-L3** |
| | 点击连线选中 | 点击选中后可删除 | 同左 | ✅ 都做 | **新增 U-L4** |
| | 连线标签 | 可选加文本标签 | 可选加文本标签 | ❌ 不做 | 现阶段不需要 |
| **右侧配置** | 抽屉形态 | 从右滑出 480px | 从右滑出 480px | ✅ 一致 | |
| | 字段分组 | 基础设置 / 输入 / 输出 / 高级 | 同左 | ✅ Coze 分组 | U-I3 |
| | 变量引用 | 蓝色胶囊 chip | 蓝色胶囊 chip | ✅ 都做 | U-I1 |
| | 实时预览 | 无 | 无 | ❌ 不做 | |
| **底部浮条** | 位置 | 居中浮起 | 左下+右下分离 | ✅ Coze 居中 | 已确认 |
| | 缩放控制 | % 下拉 | % 下拉 + +/- 按钮 | ✅ Coze 下拉 | U-B1 |
| | +添加节点 | 弹出分类气泡 | 拖拽节点库 | ✅ Coze 气泡 | U-B2 |
| | 试运行按钮 | 绿色大按钮 | 绿色大按钮 | ✅ 都做 | U-B1 |
| **节点交互** | 双击打开配置 | 是 | 是 | ✅ 都做 | 已有 |
| | 右键菜单 | 复制/粘贴/重命名/删除 | 同左 | ✅ Coze | U-P2 |
| | 拖拽移动 | 是 | 是 | ✅ 都做 | |
| | 多选 | 框选 / Shift+点选 | 框选 / Shift+点选 | ✅ 都做 | **新增 U-P5** |
| **快捷键** | Delete 删除 | 是 | 是 | ✅ 都做 | U-P1 |
| | Ctrl+S 保存 | 是 | 是 | ✅ 都做 | U-P1 |
| | Space+平移 | 是 | 是 | ✅ 都做 | U-P1 |
| | 滚轮缩放 | 是 | 是 | ✅ 都做 | U-P1 |
| | Ctrl+C/V 复制粘贴 | 是 | 是 | ✅ 都做 | U-P2 |
| | Ctrl+Z/Y 撤销重做 | 是 | 是 | ✅ 都做 | **新增 U-P6** |
| **试运行** | 输入参数表单 | 按 START 入参动态生成 | 同左 | ✅ 已做 | B7 |
| | 节点调试面板 | 右侧抽屉展开 | 右侧抽屉展开 | ✅ 已做 | B8 |
| | 运行状态色 | 节点外圈呼吸 | 同左 | ✅ 新增 | U-N5 |
| **空画布** | 欢迎页 | 模板卡片 | 模板卡片 | ✅ 只做空白起点 | 已确认 |
| **窄屏** | <1024px 降级 | 自动折叠左侧面板 | 同左 | ✅ 都做 | U-P4 |

---

### 7.7 逐节点交互细节对比（2026-10-31 Coze 实机观察）

> 这一节是**逐个节点类型**对照 Coze 实机截图，把配置抽屉的内部结构、字段交互细节写清楚。
> 上一版 7.3 只描述了"节点卡片长什么样"，但没说"点进去之后抽屉里长什么样"。

#### 7.7.1 抽屉通用结构（所有节点一致）

Coze 右侧配置抽屉的统一骨架（从 LLM 和 IF 节点截图提取）：

```
┌─────────────────────────────────────┐
│ [24×24 彩色图标] 节点标题            │  ← 头部：图标 + 标题
│ 一行描述（灰色，截断显示）           │  ← 头部：meta.description
├─────────────────────────────────────┤
│ [Segmented Tab 可选]               │  ← 如 LLM 的"单次/循环"
├─────────────────────────────────────┤
│ ▼ 分组名 ⓘ                         │  ← 可折叠分组（带 i 提示图标）
│   字段 1                            │
│   字段 2                            │
│ ▼ 分组名 ⓘ                         │
│   ...                               │
└─────────────────────────────────────┘
```

**关键交互细节**：
- 抽屉宽度：约 480px，从右侧滑出
- 头部：图标块 24×24 圆角方形（背景取节点色）+ 标题 16px 600 + 描述 12px 灰
- 分组标题：带 `∨` 折叠箭头 + `ⓘ` 提示图标（hover 显示字段说明）
- 分组体：白底圆角卡片（IF 的"如果/否则"是独立卡片，不是普通字段堆叠）
- 输入框统一：高度 32px，圆角 6px，边框 `#e5e7eb`

#### 7.7.2 LLM 节点（type=17）

**Coze 实机截图**（`coze-llm-config2.png`）：

| 分组 | 字段 | 交互 |
|---|---|---|
| 头部 | 图标 + "大模型" + "调用大语言模型,使用变量和提示词生..." | 静态 |
| Tab | 单次 / 循环 | Segmented 切换，影响后续表单 |
| ▼ 模型 ⓘ | 模型选择器 | 下拉显示"豆包·2.0·pro"（带彩色 logo 圆点），点击弹出模型列表 |
| ▼ 技能 | 工具配置 | 空态：灰色图标 + "暂未配置技能"，点击添加 |
| ▼ 输入 ⓘ | 变量名 + 类型 + 变量值 + 引用按钮 | key-value 动态列表，每行：Input + Select(str.) + Input + 蓝色⊹按钮 |
| ▼ 视觉理解输入 ⓘ | 同上 | 多模态输入变量列表 |
| ▼ 提示词 ⓘ | system_prompt + user_prompt | 多行文本编辑器（未截到，标准结构） |
| ▼ 高级 ⓘ | temperature / max_tokens / 记忆开关 | 数字输入 + 开关 |

**我们当前实现的差距**：
- ❌ 没有 Segmented Tab（单次/循环）—— 本期不做（我们没循环模式）
- ✅ 2026-10-31：ModelPicker 已带彩色 logo 圆点（doubao/openai/anthropic/deepseek/qwen/zhipu/moonshot 等 provider 各自品牌色，选中态与下拉选项一致渲染）
- ❌ "输入"分组是平铺的 config_fields，不是 key-value 动态列表
- ✅ 2026-10-31：已补"视觉理解输入"分组（`images` 字段 field_type=key_value_list）和"技能"分组（`tools` 字段 field_type=tool_list）

**处理**：U-LLM1 / U-LLM2 已合并到 **U-I3**（节点 override 机制）。

#### 7.7.3 IF 选择器节点（type=11）

**Coze 实机截图**（`coze-selected.png`）：

| 区域 | 结构 | 交互 |
|---|---|---|
| 头部 | 青绿色方形"IF"图标 + "选择器" + "连接多个下游分支..." | 静态 |
| "条件分支" | 分组标题 | 静态 |
| "如果"卡片 | 白底圆角卡片 | 内含：左值 Input+下拉 / 操作符 Select / 右值 Input(str.前缀)+引用按钮 / "+ 新增"紫色按钮 |
| "否则"卡片 | 白底圆角卡片，无输入框 | 静态，标记 else 分支 |

**我们当前实现的差距**：
- ✅ T7 已做 CaseListEditor（左值/操作符/右值/增删），但样式是平铺行，不是"如果/否则"卡片
- ✅ 2026-10-31：已补"否则"独立虚线卡片
- ✅ 2026-10-31：左值改为 AutoComplete（支持搜索 + 从上游 outputs 下拉选择）

**处理**：U-IF1 已合并到 **U-I3**（节点 override 机制）。

#### 7.7.4 HTTP 请求节点（type=8）

**Coze 标准结构**（基于 Dify/Coze 公开 UI，未实机截到）：

| 分组 | 字段 | 交互 |
|---|---|---|
| 头部 | 🌐 图标 + "HTTP 请求" | 静态 |
| ▼ 基础 | 方法 Select + URL Input | 方法下拉（GET/POST/PUT/DELETE），URL 带路径参数高亮 |
| ▼ Headers | key-value 动态列表 | T9 已做 KeyValueListEditor |
| ▼ Query | key-value 动态列表 | T9 已做 |
| ▼ Body | body_type Select + body_editor | form/json/text 切换，json 用代码编辑器 |
| ▼ 认证 | auth_type Select + token Input | T9 已做 bearer/basic |
| ▼ 高级 | timeout / retry | 数字输入 |

**我们当前实现的差距**：
- ✅ T9 已做 pathParams/queryParams/headers/bodyForm/bodyJson/authType
- ❌ 字段是平铺的，没分组（U-I3 会解决）
- ❌ URL 输入框没有"路径参数高亮"（`:param` 渲染为蓝色 chip）

**新增任务**：
- [x] **U-HTTP1 URL 路径参数高亮**：URL Input 里 `:param` 片段渲染为蓝色 chip（复用 U-I1 RefChip 逻辑）。

#### 7.7.5 代码节点（type=5）

**Coze 标准结构**：

| 分组 | 字段 | 交互 |
|---|---|---|
| 头部 | `</>` 图标 + "代码" | 静态 |
| ▼ 输入 | 变量名 + 类型 + 值 | key-value 列表 |
| ▼ 代码 | 代码编辑器 | 多行，带行号，Python 语法高亮 |
| ▼ 输出 | 输出变量名 + 类型 | 动态列表 |

**我们当前实现的差距**：
- ✅ 2026-10-31：代码编辑器已升级为 `react-simple-code-editor`（轻量 ~10KB，自带行号、tab 键、等宽字体），不引 Monaco；深色主题 #1e1e2e + Python 语法高亮（关键字蓝色 / 注释绿色 / 字符串橙色）
- ✅ 2026-10-31：已补"输入变量"分组（key_value_list，backend 合并静态 inputs + 上游动态 inputs 后传入 sandbox.run）

**新增任务**：
- [x] **U-CODE1 代码编辑器升级**：textarea 换为 `react-simple-code-editor`（轻量 ~10KB，自带行号、tab 键、等宽字体），不引 Monaco。

#### 7.7.6 知识库节点（type=6）

**Coze 标准结构**：

| 分组 | 字段 | 交互 |
|---|---|---|
| 头部 | 📚 图标 + "知识库检索" | 静态 |
| ▼ 知识库 | 选择器 | 下拉选择已绑定的知识库 |
| ▼ 查询 | query Input + 引用按钮 | 文本输入，支持变量引用 |
| ▼ 检索参数 | topK / score_threshold | 数字滑块 |
| ▼ 输出 | 命中结果列表 | 只读展示 |

**我们当前实现的差距**：
- ✅ 2026-10-31：知识库选择器已接后端 `/admin/documents`（Select + 空态"暂无知识库文档"）；已补 `scoreThreshold` 数字字段（默认 0）

**新增任务**：
- [x] **U-DS1 知识库选择器下拉**：从后端拉知识库列表，Select 选择（本期可先占位）。

#### 7.7.7 循环节点（type=19）

**Coze 标准结构**：

| 分组 | 字段 | 交互 |
|---|---|---|
| 头部 | 🔁 图标 + "循环" | 静态 |
| ▼ 循环类型 | for / while | Segmented 切换 |
| ▼ 输入 | 数组变量引用 | 引用按钮选择上游数组 |
| ▼ 并发 | parallel 开关 + 并发数 | Switch + InputNumber |
| 子图 | 双击进入内嵌画布 | 面包屑导航 |

**我们当前实现的差距**：
- ✅ B6 已做子图编辑（双击进入 + 面包屑）
- ❌ 没有"循环类型"切换（我们只支持 for-each，while 未实现）
- ❌ 并发开关是平铺字段

**决策**：**U-LOOP1 砍掉**——while 循环后端未实现，做个禁用按钮是空壳。

#### 7.7.8 通用节点卡片（画布上的）

**Coze 实机截图细节**（`coze-workflow.png` + `coze-selected.png`）：

| 元素 | Coze 样式 | 我们当前 | 差距 |
|---|---|---|---|
| 卡片背景 | 白底 `#fff` | 纯色块（meta.color） | U-N1 解决 |
| 卡片圆角 | 7px | 8px | 接近 |
| 卡片阴影 | 无（hover 才有） | 无 | |
| 左上角图标 | 24×24 彩色块 | 无 | U-N1 解决 |
| 标题 | 14px 600 深色 | 14px 500 白字 | U-N1 解决 |
| 副标题 | 12px 900 灰（如"输入: xxx"） | outputs 列表白字 | U-N1 解决 |
| 输出端口 | 卡片右侧垂直小圆点 | 无（Flowgram 默认） | U-N3 解决 |
| 选中态 | 卡片外圈蓝色描边 | 无 | U-N3 解决 |
| 运行态 | 卡片左上角状态色点（绿/红/黄） | 无 | U-N5 解决 |

#### 7.7.9 汇总：逐节点任务清单

| 任务 | 节点 | 处理 | 优先级 |
|---|---|---|---|
| ~~U-LLM1 LLM 抽屉分组重排~~ | llm | **合并到 U-I3**（节点 override） | - |
| ~~U-LLM2 输入变量 key-value 编辑器~~ | llm | **合并到 U-I3**（节点 override） | - |
| ~~U-IF1 如果/否则卡片化~~ | if_else | **合并到 U-I3**（节点 override） | - |
| U-HTTP1 URL 路径参数高亮 | http | 保留 | P2 |
| U-CODE1 代码编辑器升级 | code | 改用 react-simple-code-editor | P2 |
| U-DS1 知识库选择器下拉 | dataset | 保留（可占位） | P3 |
| ~~U-LOOP1 循环类型 Segmented~~ | loop | **砍掉**（while 未实现） | - |

---

### 7.8 补充的通用体验任务（2026-10-31 review 新增）

| 任务 | 说明 | 优先级 |
|---|---|---|
| U-S1 保存状态视觉 | 顶部应用名旁显示"已保存 / 保存中… / 保存失败"（复用现有 saveStatus） | P1 |
| U-S2 节点重命名 | 抽屉头部标题可直接编辑（双击或点击 pencil 图标），实时同步到画布节点标题 | P1 |
| U-S3 删除二次确认 | Delete 删除节点时轻量确认（Modal 或 toast 撤销条），避免误删 | P2 |
| U-S4 端口 tooltip | hover 端口时 Popover 显示"字段名: 类型"（如 `output: string`） | P2 |

---

### 7.9 实现注意事项（容易踩的坑）

> 每完成一个任务后，对照本节自检。这些是 UI 重写时高频出现的 bug。

#### 7.9.1 文本对齐与截断

| 坑 | 现象 | 修复 |
|---|---|---|
| 节点卡片文字不居中 | 图标、标题、副标题三者 baseline 对不齐 | 用 `display: flex; alignItems: center`，标题和副标题放右侧 flex 列 |
| 副标题过长溢出 | `model: doubao-2.0-pro-32k-vision` 撑破卡片 | `overflow: hidden; textOverflow: ellipsis; whiteSpace: nowrap`，外层卡片 `min-width` 固定但不 `max-width` 截断 |
| 标题换行错乱 | 用户改长标题后卡片高度跳动 | 标题 `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` |
| 端口 label 错位 | 输出字段名与圆点不对齐 | 端口行用 `display: flex; alignItems: center; gap: 4px` |
| chip 与基线不齐 | 变量胶囊在 Input 内上下偏移 | chip 设 `lineHeight` 与 Input 一致，`vertical-align: middle` |

#### 7.9.2 边框宽度与显示不全

| 坑 | 现象 | 修复 |
|---|---|---|
| 边框 1px 被内容挤掉 | Flowgram 节点容器默认 padding 为 0，加 border 后节点尺寸变化导致连线错位 | 用 `box-sizing: border-box`，并在 NodeCard 外层留 `padding: 1px` 或用 `outline` 代替 `border` |
| 选中描边超出卡片 | `box-shadow: 0 0 0 3px` 把相邻节点压住 | 选中态用 `outline: 2px solid #6366f1; outline-offset: 2px`，不占布局 |
| 端口被卡片边框裁剪 | 端口圆点在卡片边缘，1px 边框把圆切掉一半 | 端口位置 `left: -5px` / `right: -5px`（向外突出），容器 `overflow: visible` |
| 抽屉宽度过窄 | 480px 抽屉在 13" 笔记本上字段被挤换行 | 抽屉 `width: 480` 固定，内部字段 `width: 100%`，不留死宽 |
| 底部浮条遮挡节点 | 画布最下面一行节点被浮条盖住 | 画布容器 `paddingBottom: 80px`，浮条 absolute 定位不影响画布 |
| 节点卡片 minWidth 不够 | 副标题 `model: xxx` 比标题还短时卡片过窄 | `minWidth: 200`，但内容超出时自动撑大 |

#### 7.9.3 交互细节 bug

| 坑 | 现象 | 修复 |
|---|---|---|
| 双击拖线触发 | 想拖动节点却打开了配置抽屉 | 区分"单击拖动"和"双击"：onDoubleClick 里检查 `dragDistance < 5px` 才开抽屉 |
| 删除节点后连线没清 | 删节点后悬空 edge 残留 | 监听 Flowgram onNodesChange，自动过滤指向已删节点的 edge |
| 保存状态卡在"saving" | 800ms 防抖触发了但请求失败没回写 | 请求 finally 里 setSaveStatus，无论成功失败都更新 |
| 试运行后画布不刷新 | 节点执行完但 nodeDebugMap 残留旧状态 | 开始运行前清空 nodeDebugMap |
| 抽屉关闭后 state 残留 | 关抽屉再打开上一次的节点数据还在 | Drawer `onClose` 时清空 selectedNode / nodeConfig |
| 缩放后节点位置错乱 | 改 zoom 后节点坐标没重算 | Flowgram 内置 zoom 会处理，自研 zoom 要用 `transform: scale()` 包一层 |
| RefPicker 树 stale | 改了节点名后 picker 树还显示旧名 | 每次打开 Popover 时重新调 `refreshPickerNodes()` |

#### 7.9.4 验收清单（每个任务完成后过一遍）

- [x] 卡片内文字 baseline 对齐（图标 / 标题 / 副标题）
- [x] 长文本有 ellipsis，不撑破布局
- [x] 边框不占布局空间（用 outline 或 box-sizing）
- [x] 端口完整显示，不被裁剪
- [x] 双击和拖拽不冲突
- [x] 删除节点后无悬空 edge
- [x] 保存状态最终落到"已保存"或"失败"，不卡在中间
- [x] 抽屉关闭后 state 清空
- [x] 缩放后节点位置正确

#### 7.9.5 图层覆盖（z-index 层级）

> 画布是多层叠加的：网格 / 连线 / 节点 / 端口 / 辅助线 / 浮条 / 抽屉 / popover。
> 没规范好 z-index 会出现"连线盖住节点""浮条被抽屉挡住""拖线被其他节点压住"等问题。

**统一 z-index 规范**（从底到顶）：

| 层级 | 元素 | z-index | 说明 |
|---|---|---|---|
| 0 | 网格背景 | 0 | 最底层 |
| 1 | 静态连线 | 1 | 在节点下层，避免压住节点 |
| 5 | 空画布欢迎页 | 5 | 节点出现前显示，节点出现后被盖住（设计如此） |
| 10 | 普通节点卡片 | 10 |  |
| 11 | 端口圆点 | 11 | 在节点卡片之上，可点击 |
| 12 | 选中节点光晕 | 12 | 节点自身 box-shadow，不单独占层 |
| 20 | 对齐辅助线 | 20 | 拖拽时显示，在节点之上但不挡点击 |
| 30 | 拖拽中的临时连线 | 30 | 用户正在拖线时高亮显示 |
| 100 | 底部浮条 CanvasToolbar | 100 | 浮在画布之上 |
| 200 | 左侧 ResourceSidebar | 200 |  |
| 1000 | 右侧配置 Drawer | 1000 | antd Drawer 默认 |
| 1050 | Popover / Tooltip | 1050 | antd 默认 |
| 1100 | Modal / 审批 Drawer | 1100 | 最高层 |

**高频坑与修复**：

| 坑 | 现象 | 修复 |
|---|---|---|
| 连线盖住节点 | 紫色线条穿过卡片 | 连线 z-index=1，节点 z-index=10；Flowgram 若默认连线在上，要在 CSS 里显式 `z-index: 1` |
| 端口被卡片背景裁掉 | 端口圆点一半在卡片外看不见 | 端口 `position: absolute; left: -5px; top: 50%`，节点容器 `overflow: visible` |
| 拖拽中节点被其他节点盖住 | 拖节点时它压在下层 | 拖拽时给该节点加 `dragging` class，z-index 提到 100 |
| 底部浮条被右侧抽屉挡住 | 打开配置抽屉时浮条被盖 | 浮条 z-index=100，抽屉 z-index=1000（抽屉打开时浮条自然被盖，这是对的） |
| Popover 被画布容器裁剪 | +添加节点菜单在画布边缘被切 | Popover 用 `getPopupContainer={() => document.body}`，不挂在画布容器内 |
| 欢迎页被 START 节点盖住 | 空画布时 START 节点挡住欢迎卡片 | 欢迎页 z-index=5，START 节点 z-index=10（START 在欢迎页之上是对的，欢迎页只在无节点时显示） |
| 选中节点光晕被相邻节点压住 | 蓝色描边被旁边节点盖掉 | 选中节点 z-index 提到 50，不只是 box-shadow |
| comment 便签层级错乱 | 便签压住节点或被连线盖住 | comment z-index=5（在普通节点下层，作为背景注释） |
| 拖线时目标端口不高亮 | 拖线中其他端口无反馈 | 临时拖线 z-index=30，目标端口高亮光圈 z-index=31 |
| 小地图/浮条按钮被节点盖住 | 节点拖到底部时压在浮条上 | 浮条 z-index=100，且画布容器 `paddingBottom: 80px` 留出空间 |

**验收**：
- [x] 连线永远在节点下层
- [x] 拖拽中节点在最上层
- [x] 打开抽屉时浮条被合理遮挡
- [x] +添加节点 Popover 不被画布裁剪
- [x] 选中节点光晕不被相邻节点压住

---

## 八、推进记录（续）

- 2026-10-31：阶段 5 UI/UX 对齐 Coze 全部完成（26 个任务）。
  - **节点卡片（U-N1~U-N5）**：`NodeCard.tsx` 白底卡片 + `NodeIcon.tsx` 24×24 emoji 图标 + `nodeSubtitle.ts` 按 typeKey 自动提取副标题（模型名/URL 截断/条件数/循环次数等）；选中态蓝色描边 + 光晕；运行态蓝/绿/红边框 + CSS 呼吸动画；连线紫色贝塞尔 + hover 加深；端口圆点 hover 放大。
  - **底部浮条（U-B1~U-B3）**：`CanvasToolbar.tsx` 底部居中浮起，缩放% + 适应画布 + 全屏；`AddNodePopover.tsx` 拖线到空白处弹出搜索节点面板；`MiniMap.tsx` 右下角 160×100 节点缩略图 + 视口框 + 点击导航。
  - **左侧资源（U-L1~U-L4）**：左侧节点库按 category 分组（流程控制/AI/逻辑/数据/会话/misc）；`VariablesDrawer.tsx` 右侧全局变量树；连线 hover 加深、点击选中变紫、Delete 删除；`canDeleteNode` 保护 START 节点不可删。
  - **输入体验（U-I1~U-I3）**：`RefChipInput.tsx` 单行输入 + 同边框容器内蓝色 monospace 胶囊 chip（可点 × 删除）；`EmptyCanvasWelcome.tsx` 空画布居中欢迎卡片；`configSections.ts` 按节点类型分组（模型设置/提示词/高级/请求设置/认证等）。
  - **细节 polish（U-P1~U-P6）**：Ctrl+S 保存、Ctrl+Enter 试运行、Ctrl+Z/Y 撤销重做（FlowGram 内置 ctx.history）；`CanvasContextMenu.tsx` 画布右键菜单（添加/复制/粘贴/删除/自动排版/适应视图）；`selectBox={{enabled:true}}` 框选多选；<1024px 窄屏自动隐藏左侧面板。
  - **节点配置（U-S1~U-S4, U-DS1, U-HTTP1, U-CODE1）**：顶部保存状态"已保存/保存中…/失败" + 最后保存时间；抽屉标题可直接编辑实时同步画布；Delete 删除节点弹 Modal 二次确认；端口 hover 显示字段名 tooltip（`usePortTooltips.ts` MutationObserver）；datasetId 字段占位 Select；URL 字段下方显示 `{{node.output.id}}` 语法提示；`RefChipInput` 支持 `highlightPathParams` prop，URL 字段启用后 `:param` 渲染为橙色 monospace 胶囊（#fff7ed/#ea580c，仅高亮不可删），与蓝色 `{{ref}}` chip 共存；code_editor 深色背景等宽字体。
  - **已砍掉**：U-N4 对齐辅助线（FlowGram free-layout-editor 未暴露 snap/guide API，MVP 跳过）；U-LOOP1 while 循环 Segmented（后端未实现 while）；U8 顶部双 Tab（无 UI Builder 概念）。
  - 前端 `npx tsc --noEmit` 干净，`npx vite build` 通过（AppEditPage chunk 840KB，gzip 260KB）。

- 2026-10-31（补漏）：3 个 P1/P2 任务修正。
  - **U-DS1 知识库选择器接后端**：新建 `api/datasets.ts` 调 `GET /admin/documents?page=1&page_size=100`，`AppEditPage` 挂载时 `listDatasets()` 拉取并存入 `datasetOptions` state；`FieldControl` 的 `datasetId` 分支从硬编码 3 个假选项改为 `Select` + `notFoundContent="暂无知识库文档"`，选项为 `{value: id, label: title}`。
  - **IF 节点 CaseListEditor 卡片化（U-IF1）**：每个 case 渲染为白底圆角卡片（`#fff` + `#e5e7eb` border），卡片顶部显示"如果 1 / 否则，如果 2"标题；条件列表末尾追加"否则"虚线静态卡片（`#f9fafb` + `#d1d5db` dashed border），说明"以上条件均不满足时执行此分支"；"+ 添加条件"按钮改为 dashed 样式。
  - **LLM 输入变量 key-value 动态列表（U-LLM2）**：`node_meta.py` LLM 节点 config_fields 新增 `inputs` 字段（field_type=`key_value_list`，description="定义本节点的输入变量，可在提示词中通过 {{key}} 引用"）；`configSections.ts` llm 分组新增"输入变量"section（位于"模型设置"与"提示词"之间）；复用已有 `KeyValueListEditor` 渲染 key-value 动态列表（每行 Key Input + Value Input + RefPicker + 删除按钮）。
  - 前端 `npx tsc --noEmit` 干净；浏览器验证：LLM 抽屉出现"输入变量"分组 + "+ 添加键值对"按钮；IF 抽屉出现"如果 1"卡片 + "否则"虚线卡片；Dataset 抽屉知识库 ID 下拉显示"暂无知识库文档"空态。

- 2026-10-31（补漏 2）：LLM 视觉理解分组 + Dataset score_threshold。
  - **LLM 视觉理解分组（U-LLM3）**：`node_meta.py` LLM config_fields 新增 `images` 字段（field_type=`key_value_list`，label="视觉理解输入"，description="图片 URL 列表，传入后以 multi-modal content part 发送"）；`configSections.ts` llm 分组新增"视觉理解"section（位于"输入变量"与"提示词"之间），复用 KeyValueListEditor。
  - **LLM 技能分组**：`configSections.ts` llm 分组把 `tools` 字段单独归到"技能"section（位于"模型设置"与"输入变量"之间），与 Coze 卡片结构对齐。
  - **Dataset score_threshold（U-DS2）**：`node_meta.py` dataset config_fields 新增 `scoreThreshold` 字段（field_type=`number`，default=0.0，description="相似度分数低于此值的片段将被过滤，0 表示不过滤"）；`configSections.ts` dataset 分组 match 数组加入 `scoreThreshold`。
  - 后端重启后 `GET /api/v1/admin/node-meta` 返回 LLM 10 字段（含 images）、Dataset 3 字段（含 scoreThreshold）；浏览器验证：LLM 抽屉出现"视觉理解"分组（空态 key-value 列表）；Dataset 抽屉出现"Score 阈值"数字字段；知识库 Select 下拉显示"暂无知识库文档"空态。

- 2026-10-31（补漏 3）：U-CODE1 代码编辑器真正落地。
  - **问题**：roadmap 标 [x] 但实际还是 antd `Input.TextArea` 深色背景样式，没装 `react-simple-code-editor`。
  - **改动**：
    - `pnpm add react-simple-code-editor@0.14.1`（~10KB，自带行号、tab 键、滚动同步）
    - 新建 `components/CodeEditor.tsx`：封装 `Editor` 组件，深色主题 #1e1e2e + #313244 边框，minHeight 200px；内置轻量 Python 语法高亮（不引 prismjs）：关键字 `def/return/if/else/for/while/import` 等蓝色 #569cd6，注释绿色 #6a9955，字符串橙色 #ce9178，数字浅绿 #b5cea8。
    - `AppEditPage.tsx` FieldControl 的 `code_editor` 分支从 `Input.TextArea` 切换为 `<CodeEditor>`；其他 textarea/tool_list 分支保持原样。
  - **浏览器验证**：代码节点抽屉显示深色代码面板；输入 `def main(input):` 时 `def` 蓝色高亮，`# 处理输入` 绿色注释，`'name'/'world'/'output'` 橙色字符串；多行缩进保持，tab 键可输入缩进。

- 2026-10-31（补漏 4）：ModelPicker 彩色 logo 圆点。
  - **改动**：`AppEditPage.tsx` ModelPicker 引入 `PROVIDER_COLORS` 映射（doubao/bytedance/volcengine/ark=#0052D9，openai=#10A37F，anthropic/claude=#D97757，deepseek=#4D6BFE，qwen/tongyi=#615CED，zhipu/glm=#3B7DFF，moonshot/kimi=#FF6B4A）；新增 `ModelLabel` 组件（10×10 圆形彩色圆点 + 模型名 + 灰色 provider 后缀）；Select 的 options 与 labelRender 都用 `ModelLabel` 渲染，optionFilterProp 改为 `labelText`（避免中文 provider 搜索时被 ReactNode 干扰）。
  - **浏览器验证**：下拉展开显示"● DeepSeek Chat deepseek"（蓝色圆点 #4D6BFE）；选中后 Select 框内同样显示蓝色圆点 + "DeepSeek Chat deepseek"。

- 2026-10-31（补漏 5）：IF 左值下拉选择器 + 代码节点"输入变量"分组。
  - **IF 左值 AutoComplete（U-IF2）**：`AppEditPage.tsx` 新增 `buildLeftValueOptions()` 把上游节点 outputs（含 START 入参）拍平为 `{value: "{{nodeId.output.port}}", label: "节点标题 / 端口名"}` 选项；CaseListEditor 左值从 `Input + RefPickerButton suffix` 换为 `AutoComplete`（宽 200px，placeholder="选择或输入左值"），下拉显示"开始/出口"、"大模型/输出"等上游字段。
  - **代码节点输入变量（U-CODE2）**：`node_meta.py` code 节点 config_fields 新增 `inputs`（field_type=key_value_list，位于 code 之前）；`configSections.ts` code 分组新增"输入变量"section；`backend/code.py` 新增 `_parse_config_inputs()` 把 config["inputs"] 规范化为 dict，合并上游动态 inputs 后传入 `sandbox.run(args=...)`，支持 list[{key,value}] 和 dict 两种格式。
  - **浏览器验证**：IF 抽屉左值点击展开下拉，列出"开始/出口"、"大模型/输出"、"HTTP 请求/输出"等选项；代码节点抽屉顶部出现"输入变量"分组（空态"+ 添加键值对"按钮），下方为深色代码编辑器。

- 2026-10-31（补漏 6）：差距点全面梳理 + 代码质量修复。
  - **梳理结果**：逐节点（LLM/HTTP/IF/Code/Dataset/Loop/AgentLoop）对照 Coze 标准结构，所有 UI 对齐任务已完成；剩余 ❌ 项均为"砍掉"（U-N4 对齐辅助线、U-LOOP1 while 循环、U8 双 Tab）或"不做"（栅格切换、连线标签、实时预览、LLM Segmented Tab）。
  - **修复 antd Modal deprecation**：试运行 Modal 的 `destroyOnClose` 改为 `destroyOnHidden`（antd 5.x 新 API），消除 console warning。
  - **已知非阻塞 console 噪音**（不阻塞 UI，记录待后续处理）：
    - `/admin/documents` 403：admin 角色缺 `document:read` 权限，前端 catch 已显示空态"暂无知识库文档"，但浏览器自动输出红色 console error；需后端给 admin 角色补权限或前端改用无权限端点。
    - FlowGram `Entity WorkflowPortEntity default/input/output is created before`：FlowGram 内部 warning，非业务代码问题。
  - **验证确认**：HTTP URL 路径参数高亮（`:userId`/`:postId` 橙色 chip）正常；ModelPicker 彩色圆点正常；CanvasToolbar 顶部居中缩放控制正常；MiniMap 右下角节点缩略图正常。

- 2026-10-31（补漏 7）：发布按钮落地（后端已就绪，纯前端工作）。
  - **API 接入**：`api/apps.ts` 新增 `publishGraph(applicationId)` 调 `POST /admin/apps/{id}/publish`，返回 `{ok, published_version, previous_published_version, runtime_mode}`。
  - **顶部按钮**：`AppEditPage.tsx` 顶栏"保存状态"右侧新增紫色主按钮 `🚀 发布`（size=small，background #722ed1，loading=publishing）。
  - **发布逻辑（handlePublish）**：先 `scheduleSave()` 触发草稿保存 + 等 1000ms 让草稿落盘，再调 `publishGraph(id)`；成功后 `message.success("发布成功，当前 live 版本 v{published_version}")`，失败 `message.error` 带错误详情。
  - **浏览器验证**：点击发布按钮→网络面板看到 `POST /admin/apps/{id}/publish => 200`，响应体 `{"published_version":5,"previous_published_version":null,"runtime_mode":"agent_loop"}`；重复点击版本号依次递增（v5→v6→v7）。

- 2026-10-31（补漏 8）：live 版本徽标 + /admin/documents 403 权限修复。
  - **后端 get_app_graph 返回 published_graph_version**：`application_service.py::get_graph` 从 `application.published_graph_version` 读取 live 版本号并入响应（NULL 表示未发布，前端不显示徽标）。
  - **前端 live 版本徽标**：`api/apps.ts::getAppGraph` 返回类型加 `published_graph_version: number | null`；`AppEditPage.tsx` 新增 `publishedVersion` state，加载图时回填、发布成功后用响应体 `published_version` 更新；顶栏发布按钮左侧显示绿色 Tag `● live v{N}`（antd `Tag color="green"`）。
  - **/admin/documents 403 修复**：migration `0048_document_permissions.py` 在 `permission_resources` 目录新增 `document:read/create/update/delete` 4 个权限（category=tool，与现有约束一致），并回填内置角色——viewer 只读，superadmin/admin 全部 4 个权限。之前该权限 code 从未注册过，导致所有角色（含超级管理员）调 `/admin/documents` 都 403。
  - **浏览器验证**：画布顶栏显示绿色 Tag `● live v5`；`GET /admin/documents => 200 OK`（之前 403）；console 只剩 FlowGram `Entity WorkflowPortEntity` 内部 warning，业务错误清零。

---

## 九、2026-11-01 UI/UX 二次对齐 Coze 实机（阶段 6）

> 触发：用户在 Coze 实机（`coze.cn/space/7483888587768692772/project-ide/7701916545001963558`）对照后反馈"画布 UI 很丑、左侧节点丑、校验节点信息关不了"。
> 本节基于 2026-11-01 Playwright 实机截图 `coze-current.png` 重新梳理差距，纠正阶段 5 的偏离项。
> **铁律**：结构以 Coze 为标准；Dify 仅借鉴交互思路；**严禁复制 Dify 源码**（开源协议）。

### 9.1 阶段 5 的偏离项（实机对照后发现）

| # | 阶段 5 声称 | Coze 实机 | 我们代码现状 | 偏离原因 |
|---|---|---|---|---|
| D1 | CanvasToolbar 底部居中浮条 | 底部居中，含 [缩放%/适应/网格/小地图] [+添加节点] [试运行] | `CanvasToolbar.tsx` 在**顶部**居中，只有缩放+适应+全屏；试运行按钮在左侧面板底部 | 实现时位置放错，且缺关键按钮 |
| D2 | 左侧资源树（工作流/插件/数据/设置） | 280px 资源树，分组折叠，空态"还未添加插件/数据" | 200px 节点库按钮堆叠（颜色圆点+文字）+ 底部 4 个按钮 | 节点库未迁移到底部气泡，资源树未做 |
| D3 | 校验问题面板 | Coze 无此浮层（校验问题在节点卡片上红点提示） | `bottom:220, left:16, right:16` 通栏浮层，**无关闭按钮**，挡画布 | 用户痛点：关不掉 |
| D4 | 试运行日志 | Coze 无黑色浮层（日志在右侧抽屉） | `bottom:16, left:16, right:16` 黑色浮层，**无关闭按钮** | 同上 |
| D5 | 主色 #6366f1 | 发布按钮紫色、试运行绿色、连线淡紫 | 发布 #722ed1（antd purple）、试运行 #52c41a（antd green）、连线 #c0c4cc 灰 | 配色混用 antd 默认色，未统一 token |
| D6 | +添加节点气泡 | 底部浮条"+ 添加节点"按钮触发 | 仅拖线到空白时触发，无独立入口 | 入口缺失 |

### 9.2 已确认决策（2026-11-01）

1. **左侧面板**：完全对齐 Coze —— 280px 资源树（工作流/变量/会话管理），节点库彻底移到底部"+ 添加节点"气泡。插件/数据分组本期做空态占位。
2. **底部浮条**：CanvasToolbar 从顶部移到底部居中，补 +添加节点 和 试运行按钮。左侧面板底部的试运行按钮移除。
3. **校验面板**：改右下角可折叠浮层 + ×按钮，点击 issue 跳转到对应节点。关闭后不自动弹出。
4. **双 Tab**：砍掉（维持原决策，我们没有 UI Builder）。

### 9.3 任务清单（阶段 6）

#### P0：核心痛点（必须先做）

##### V1 校验问题面板改造（用户痛点：关不掉）

**现状**：`AppEditPage.tsx:2007-2031` 通栏浮层 `bottom:220, left:16, right:16`，无关闭按钮。

**目标**：右下角可折叠浮层，带 × 关闭按钮，点击 issue 跳转到对应节点。

**修改文件**：`AppEditPage.tsx`

**新建 state**：
```ts
const [validationPanelOpen, setValidationPanelOpen] = useState(false);  // false=关闭
const [validationIssues, setValidationIssues] = useState<GraphValidationIssue[]>([]);
```

**触发逻辑**：
- 点"校验"按钮 → `doValidate()` → 成功后 `setValidationPanelOpen(true)`（自动展开）
- 点 × 按钮 → `setValidationPanelOpen(false)`（关闭，不清除 issues）
- 关闭后除非再次点校验，不自动弹出

**布局**：
```
position: absolute, bottom: 80, right: 16, zIndex: 100,
width: 360, maxHeight: 300, overflowY: auto,
background: #fff, borderRadius: 8, boxShadow: 0 4px 16px rgba(0,0,0,0.12),
```

**头部**：`校验问题（N 错误 M 警告）` + 右侧 × 按钮
**列表项**：图标（●红/▲黄）+ message + node_id Tag + 点击跳转 `focusNode(node_id)`

**验收**：
- [x] 点校验后右下角弹出浮层
- [x] 点 × 关闭，画布不再被挡
- [x] 点击某条 issue，画布聚焦到该节点（视口平移+高亮）

---

##### V2 试运行日志面板改造（同痛点）

**现状**：`AppEditPage.tsx:2034-2047` 黑色浮层 `bottom:16, left:16, right:16`，无关闭按钮。

**目标**：改为右下角抽屉（与校验面板合并为"运行/校验"面板），可关闭。

**修改文件**：`AppEditPage.tsx`

**方案**：与 V1 共用一个右下角抽屉，Tab 切换"校验问题 / 运行日志"。
- `bottom: 80, right: 16, width: 400, maxHeight: 360`
- 头部：Tab（校验 N / 日志 M）+ × 按钮
- 运行结束后自动展开"日志"Tab；校验后自动展开"校验"Tab

**Tab 切换规则**（2026-11-01 review 补充）：
- 面板已打开且用户正在看日志时，新校验结果来了 → **自动切到校验 Tab**，Tab 标签加红色数字徽标 `校验 N`（不再用弹窗打断）
- 面板已打开且用户正在看校验时，试运行结束 → **自动切到日志 Tab**
- 面板已关闭时，任何新结果（校验/日志）→ 自动展开面板到对应 Tab

**验收**：
- [x] 试运行后右下角弹出日志 Tab
- [x] 点 × 关闭
- [x] 校验和日志可 Tab 切换
- [x] 正在看日志时点校验，自动切到校验 Tab（不弹窗）

---

##### V3 CanvasToolbar 移到底部 + 补关键按钮

**现状**：`CanvasToolbar.tsx` 在顶部居中，只有缩放+适应+全屏。

**目标**：移到底部居中，补 +添加节点 和 试运行按钮。

**修改文件**：`components/CanvasToolbar.tsx`、`AppEditPage.tsx`

**新 props**：
```ts
interface CanvasToolbarProps {
  ctxRef: React.MutableRefObject<FreeLayoutPluginContext | null>;
  zoom: number;
  onAddNode: () => void;        // 打开 AddNodePopover（已存在组件，补入口）
  onRun: () => void;
  running?: boolean;
}
```

**新布局**（对齐 Coze 实机截图）：
```
[光标] [27%▾] [适应] [网格] [小地图]    │    [+ 添加节点]    │    [▷ 试运行]
←──── 左组（缩放导航）────→              ←─中─→   ←── 右组 ──→
```

**位置**：`position: absolute, bottom: 16, left: '50%', transform: translateX(-50%)`

**按钮样式**：
- +添加节点：淡紫底 `#eef2ff` + 紫字 `#4f46e5`
- 试运行：绿底 `#10b981` + 白字 + 白色播放图标

**验收**：
- [x] 浮条在画布底部居中
- [x] +添加节点按钮点击弹出 AddNodePopover（在画布中心位置）
- [x] 试运行按钮点击触发 handleRun
- [x] 顶部不再有 CanvasToolbar

---

##### V4 左侧面板重构为资源树

**现状**：`AppEditPage.tsx:1783-1852` 200px 节点库按钮堆叠 + 底部 4 个按钮。

**目标**：280px 资源树，对齐 Coze 实机。

**新建文件**：`components/ResourceSidebar.tsx`

**结构**（2026-11-01 review 后：砍掉插件/数据空态，避免用户困惑）：
```
[资源]                    [<<] 折叠
─────────────────────────
▽ 工作流
  📄 {appName}（当前，高亮）
─────────────────────────
设置
  (x) 变量
  🕘 版本历史
  💬 会话管理（灰色"开发中"）
```

> **砍插件/数据的理由**：我们没有插件市场 / 知识库集合概念，Coze 那两个空态会让用户困惑"为什么我有这两个空壳"。只保留我们真有的概念。

**props**：
```ts
interface ResourceSidebarProps {
  appName: string;
  onCollapse: () => void;
  onOpenVariables: () => void;
  onOpenConversation: () => void;
  onOpenVersions: () => void;
}
```

**关键变化**：
- 节点库**彻底移除**左侧（迁到底部 +添加节点气泡）
- 底部 4 个按钮（校验/变量/版本/试运行）**移除**：
  - 校验 → 底部浮条左侧（V3）
  - 变量 → 左侧"设置"分组
  - 版本历史 → 左侧"设置"分组
  - 试运行 → 底部浮条右侧（V3）
- **删旧代码**：`AppEditPage.tsx:1783-1852` 整块左侧节点库按钮堆叠（约 70 行）物理删除
- **窄屏阈值**：从 1024px 提到 1280px（左侧从 200px 改成 280px，1366px 笔记本需要更早就收起）

**验收**：
- [x] 左侧 280px 资源树，分组折叠
- [x] 点击"变量"打开 VariablesDrawer
- [x] 点击"版本历史"打开版本 Drawer
- [x] 左侧不再有节点库按钮列表
- [x] 旧代码已删除（grep 无 `boxia-left-panel` 节点库按钮堆叠）
- [x] 窗口缩到 1280px 以下左侧自动收起

---

#### P1：视觉对齐

##### V5 配色统一

**现状**：发布 #722ed1、试运行 #52c41a、保存状态 #52c41a/#1677ff、连线 #c0c4cc 灰。

**目标**：统一 token。

**修改文件**：`AppEditPage.tsx` 内联样式、`CanvasToolbar.tsx`

**新配色**：
| 元素 | 旧值 | 新值 |
|---|---|---|
| 主色（选中/边框） | #6366f1（已对） | #6366f1 |
| 发布按钮 | #722ed1 | #7c3aed（violet-600） |
| 试运行按钮 | #52c41a | #10b981（emerald-500） |
| 保存中状态 | #1677ff | #3b82f6（blue-500） |
| 保存成功 | #52c41a | #10b981 |
| 连线默认 | #c0c4cc 灰 | #a5b4fc（indigo-300） |
| 连线 hover | #6366f1 | #6366f1 |

**验收**：
- [x] 连线为淡紫 #a5b4fc（不再是灰色）
- [x] 试运行按钮统一 #10b981
- [x] 发布按钮统一 #7c3aed

---

##### V6 顶栏精简

**现状**：顶栏右侧有保存状态 + live 徽标 + 发布按钮，左侧是应用名。

**目标**：对齐 Coze 顶栏（应用名 + 发布 + "..."菜单）。

**调整**（2026-11-01 review 后）：
- 保存状态从"顶栏右侧浮层"改为"应用名右侧小字"（`已保存 14:30:25` 灰色）
- 发布按钮左侧保留 live 徽标
- 发布按钮右侧加"..."下拉菜单：**仅"关于"和"设置"**（版本历史/会话管理已迁移到左侧资源树，避免双入口）

**验收**：
- [x] 顶栏右侧不再有独立浮层
- [x] "..."菜单不含重复的版本历史入口

---

### 9.4 执行顺序与优先级（2026-11-01 review 后）

**P0（用户痛点，必做）**：
- V1 校验面板 + V2 日志面板（合并做）：右下角可折叠抽屉，Tab 切换
- V4 左侧资源树重构：砍旧节点库按钮堆叠
- V3 底部浮条：移到底部居中，补 +添加节点 / 试运行

**P1（视觉对齐）**：
- V5 配色统一：连线 #a5b4fc、试运行 #10b981、发布 #7c3aed
- V6 顶栏精简：保存状态并入应用名旁、"..."菜单（仅设置/关于）

**P2（加分项，可延后）**：
- V9 端口 + 按钮（依赖 V3 AddNodePopover）
- V10 下一步推荐（前端硬编码，不做后端）

```
V4（左侧资源树）──→ V3（底部浮条）──→ V1/V2（校验/日志面板）──→ V5/V6（配色/顶栏）
                                          ──→ V9（端口 + 按钮）──→ V10（下一步推荐）
```

**工时表（review 后修订）**：
| 任务 | 原估 | 修订后 | 说明 |
|---|---|---|---|
| V1 校验面板 | 1.5h | 1.5h | 合并到抽屉 |
| V2 日志面板 | 1h | 1h | Tab 切换含数字徽标 |
| V3 底部浮条 | 2h | 2h | |
| V4 左侧资源树 | 3h | **4.5h** | 含删旧代码 + 窄屏阈值 1024→1280 |
| V5 配色 | 0.5h | 0.5h | |
| V6 顶栏精简 | 1h | 0.5h | 砍重复入口 |
| ~~V7 图标核对~~ | - | **0h** | 已 Read NodeIcon.tsx，符合要求 |
| ~~V8 入口核对~~ | - | **0h** | 并入 V4 验收 |
| V9 端口 + 按钮 | 2h | **3h** | 含 mouseDown/mouseUp 冲突判定 |
| V10 下一步推荐 | 2.5h | **1.5h** | 前端硬编码，不做后端字段 |
| **合计** | **14.5h** | **14.5h** | 内容更聚焦 |

### 9.5 Dify 实机对照（2026-11-01 VPN 接通后截图）

> 截图：`cloud.dify.ai/app/a4854dd1.../workflow`（hm工作流：文本摘要器）。

#### 9.5.1 Dify 结构（按用户要求"以 Coze 为标准"，不抄）

| 项 | Dify 做法 | 我们最终采用 |
|---|---|---|
| 左侧 | 顶级应用导航（工作室/编排/日志/监测），无资源树 | ❌ 不抄，走 Coze 资源树（V4） |
| 配置面板 | 右侧固定面板（不滑出，常驻） | ❌ 不抄，走 Coze 480px Drawer |
| 底部浮条 | 分散：左下撤销/重做/历史，右下缩放% | ❌ 不抄，走 Coze 底部居中浮条（V3） |
| 试运行 | 顶部右侧"测试运行 Alt R" | ❌ 不抄，走 Coze 底部绿色大按钮 |
| 连线 | 灰色贝塞尔无箭头 | ❌ 不抄，走 Coze 紫色贝塞尔+箭头 |

#### 9.5.2 Dify 体验优势（可借鉴，不抄源码）

| # | Dify 体验 | 借鉴点 |
|---|---|---|
| B1 | 节点右侧输出端口 hover 显示**蓝色"+"按钮**，点击直接弹出"添加节点"菜单（不需要先拖线） | 降低连线门槛，新增 **V9** |
| B2 | 配置面板底部"**下一步**"推荐列表：按当前节点类型推荐常见下游（如 START 下推荐 大语言模型/知识检索/问题分类器/条件分支） | 节点类型元数据加 `next_recommendations` 字段，新增 **V10** |
| B3 | 输入字段 chip 化一行显示：`[x] input_text 要总结的文本 必填 删` | START 节点配置抽屉可参考，本期不做（V1 已处理单行 chip） |

### 9.6 新增任务（Dify 借鉴）

##### V9 节点端口"+"按钮（借鉴 Dify B1）

**现状**：节点输出端口是灰色小圆点，必须拖线到空白才弹出 AddNodePopover。

**目标**：hover 输出端口时显示蓝色"+"按钮，点击直接在该端口位置弹出 AddNodePopover，选完节点后自动连线。

**修改文件**：`NodeCard.tsx`（端口渲染）、`AppEditPage.tsx`（连线逻辑）

**实现**：
- NodeCard 输出端口外层加 `hover 显示 + 按钮`（absolute 定位，端口右侧 4px）
- 点击 + 按钮 → 记录 `pendingConnectionFrom = { nodeId, portId, x, y }` → 弹出 AddNodePopover
- AddNodePopover onSelect → addNode(typeKey) → 自动创建 edge 从 `pendingConnectionFrom` 到新节点

**交互冲突判定**（2026-11-01 review 补充，避免与拖线冲突）：
```ts
// 端口外层 onMouseDown 记录起点
const portMouseDownPos = { x: e.clientX, y: e.clientY };

// 端口外层 onMouseUp 判定
const delta = Math.hypot(e.clientX - portMouseDownPos.x, e.clientY - portMouseDownPos.y);
if (delta < 5) {
  // 视为"点击 + 按钮" → 弹出 AddNodePopover
  setPendingConnectionFrom({...});
} else {
  // 视为"拖线" → 走 FlowGram 默认连线逻辑
}
```
- 拖拽距离 < 5px = 点击 + 按钮
- 拖拽距离 ≥ 5px = 拖线（不弹 Popover）

**验收**：
- [x] hover 节点卡片右上角显示蓝色 + 按钮（2026-11-01 简化实现：放在卡片右上角而非端口上，避免侵入 FlowGram 端口 DOM）
- [x] 点击 + 在节点下方弹出 AddNodePopover
- [x] 端口拖线正常（+ 按钮 stopPropagation 不影响 FlowGram 拖线）
- [x] 选完节点自动连线到新节点（2026-11-01 补齐：通过 `linesManager.createLine({from, fromPort, to, toPort})` 实现）

---

##### V10 配置抽屉"下一步"推荐列表（借鉴 Dify B2）

**现状**：配置抽屉底部无推荐，用户要自己想"该接什么下游"。

**目标**：抽屉底部（字段分组之下）显示"下一步"分组，列出该节点类型的常见下游推荐。

**实现策略**（2026-11-01 review 后）：**本期前端硬编码**，不动后端 node_meta schema。
- 新建 `components/nodeNextRecommendations.ts`：纯映射文件
- 后端 `next_recommendations` 字段留待后续需要"按租户定制"时再加

**前端**：`NodeConfigForm` 底部新增 section：
```
▼ 下一步
  [图标] 大语言模型    [添加]
  [图标] 知识检索      [添加]
  [图标] 条件分支      [添加]
```

**点击"添加"** → 关闭抽屉 + addNode(推荐 type_key) + 自动连线当前节点 → 新节点。

**各节点默认推荐**（硬编码映射）：
| 当前节点 | 推荐下游 |
|---|---|
| start | llm / if_else / knowledge / code |
| llm | if_else / knowledge / http / end |
| http | code / if_else / end |
| if_else | llm / code / end |
| code | if_else / llm / end |
| knowledge | llm / if_else |
| end | （无） |

**验收**：
- [x] 选中 START 节点打开抽屉，底部显示"下一步"推荐列表
- [x] 点击"大语言模型" → 关闭抽屉 + 画布中心添加 LLM 节点
- [x] 自动连线到当前节点（2026-11-01 补齐：配置抽屉"下一步"以 `selectedNodeId` 为 fromNodeId 传入 addNode）
- [x] 不改后端 node_meta schema

---

### 9.7 不做的事

- ❌ 双 Tab（业务逻辑/用户界面）—— 维持砍掉决策
- ❌ 插件/数据分组 —— 已从 V4 砍掉（我们没这两个概念，空态会让用户困惑）
- ❌ Dify 左侧应用导航 / 右侧固定面板 / 灰色连线 —— 结构以 Coze 为标准
- ❌ Dify 源码参考 —— 仅借鉴交互思路（V9/V10），不抄任何组件代码
- ❌ 对齐辅助线 —— FlowGram 未暴露 API（维持原砍掉决策）
- ❌ Dify 输入字段 chip 化（B3）—— 本期已通过 RefChipInput 覆盖单行场景，START 节点字段平铺保持原样

---

## 十、推进记录（阶段 6 落地）

- 2026-11-01：阶段 6 V1–V10 核心任务落地（前端纯样式/交互重构，后端零改动）。
  - **V4 左侧资源树**：新建 `components/ResourceSidebar.tsx`——280px 宽，"工作流"分组（当前应用高亮）+ "设置"分组（变量 / 版本历史 / 会话管理-开发中）；可折叠（40px 图标条）；窄屏 < 1280px 自动隐藏（替代原 1024px 阈值）。物理删除 `AppEditPage.tsx` 原 200px 节点库按钮堆叠（约 70 行）+ 底部 4 个按钮（校验/变量/版本/试运行），节点库彻底迁到底部 +添加节点气泡。
  - **V3 底部浮条**：`CanvasToolbar.tsx` 从 `top:12` 移到 `bottom:16` 居中；补 `+ 添加节点`（淡紫底 #eef2ff + 紫字 #4f46e5）和 `▷ 试运行`（绿底 #10b981 + 白字）按钮；试运行按钮直接调 `handleRun`，添加节点按钮在画布中心弹出 `AddNodePopover`。
  - **V1/V2 校验+日志合并面板**：原两块独立浮层（bottom:220 校验 / bottom:16 日志，均无关闭按钮）合并为右下角 Tab 抽屉 `bottom:80 right:16 width:400 maxHeight:360`；头部 Tab 切换"校验 N / 日志 M"+ × 关闭；校验完成后自动展开到校验 Tab，试运行开始后自动展开到日志 Tab；点击 issue 行 `scrollIntoView` 聚焦对应节点；关闭后除非再次触发不自动弹出。
  - **V5 配色统一**：连线默认 `#c0c4cc` 灰 → `#a5b4fc` 淡紫；端口边框同步 `#a5b4fc`；发布按钮 `#722ed1` → `#7c3aed`；保存中 `#1677ff` → `#3b82f6`；保存成功 `#52c41a` → `#10b981`。
  - **V6 顶栏精简**：保存状态从"右侧浮层"改为"左上角小字"（top:12 left:16），发布按钮+live 徽标独占右上角（top:8 right:16）。
  - **V9 节点 + 按钮（自动连线已补）**：`NodeCard.tsx` 加 hover state，鼠标悬停时右上角弹出蓝色圆形 + 按钮（top:-10 right:-10，zIndex 12）；`makeNodeRenderer` 新增 `onAddNextToNode` 回调，点击 + 在节点下方弹出 `AddNodePopover`，popover state 携带 `fromNodeId`；选完节点后 `addNode(typeKey, {fromNodeId})` 通过 `linesManager.createLine` 从源节点第一个 output 端口连到新节点第一个 input 端口。
  - **V10 下一步推荐（自动连线已补）**：新建 `components/nodeNextRecommendations.ts` 硬编码映射（start/llm/http/if_else/code/dataset 6 种节点的推荐下游）；`NodeConfigForm` 底部新增"下一步"分组，每行彩色圆点 + 名称 + "添加"按钮；点击关闭抽屉 + 以当前 `selectedNodeId` 为 fromNodeId 调 `addNode`，自动连线。
  - 前端 `npx tsc --noEmit` 干净；`npx vite build` 通过（AppEditPage chunk 863KB，gzip 267KB，与改造前 840KB 基本持平）。
- 2026-11-01（续）：补齐 V9/V10 自动连线。FlowGram API 调研结论：`ctx.document.linesManager.createLine({from, fromPort, to, toPort})`（签名来自 `@flowgram__ai_free-node-panel-plugin.js` 编译产物 line 323-338）。`addNode` 新增可选 `options.fromNodeId` 参数，自动查源节点 meta 的第一个 output port 与新节点 meta 的第一个 input port 并连线。V9 走 `addNodePopover.fromNodeId` 透传，V10 走 `selectedNodeId` 透传。typecheck/build 干净通过。

---

## 十一、2026-11-01 用户反馈 4 个 bug 修复（阶段 7）

> 触发：用户实机测试后反馈 4 个阻断性 bug。对照 coze 实机截图（`coze-after-dblclick.png`）修正。
> 铁律不变：结构以 Coze 为标准；Dify 仅借鉴交互思路；严禁复制 Dify 源码。

### 11.1 Bug 根因定位

| # | 现象 | 根因 | 影响范围 |
|---|------|------|---------|
| B1 | 点 + 添加节点时，搜索框位置偏离节点 | `AddNodePopover.tsx:43` 用 `position: fixed`，但传入的 x/y 是相对 `.gedit-playground-container` 的坐标（`handleAddNextToNode` 里 `rect.left - pgRect.left`），坐标系不一致 | 所有通过 + 按钮 / 拖线 / 底部浮条触发的 Popover |
| B2 | 条件分支节点拖不动 | NodeCard 固定 `size: 220×52`，但 IF 节点有 true/false 两个 output 端口，端口圆点绝对定位覆盖了卡片中部拖拽区域；且 `cursor: pointer` 在端口上未区分拖拽态 | IF / 多 output 端口节点 |
| B3 | 从开始节点无法连线到条件分支节点 | `canAddLine` 用 `portType === 'output'/'input'` 判断方向，但 FlowGram `WorkflowPortEntity` 实际属性是 `side` 或其他；导致 START 的 default output → IF 的 default input 连线被拒 | START→IF 等所有 default 端口连线 |
| B4 | 开始节点输入参数设置不对 | START 节点 `inputs` 字段 `field_type=parameter_list`，但 `FieldControl` 对 `parameter_list` 走了 TextArea fallback（纯 JSON 文本框），不是 coze 的表格编辑器（变量名+类型下拉+必填 checkbox+引用+删除） | START 入参配置体验 |

### 11.2 修复任务

#### B1 AddNodePopover 坐标系修正

**修改文件**：`components/AddNodePopover.tsx`、`AppEditPage.tsx`（3 处调用）

**方案**：Popover 从 `position: fixed` 改为 `position: absolute`，由画布容器（`.gedit-playground-container`）作为定位上下文；或者保持 fixed 但调用方传屏幕绝对坐标。

**选定方案**：保持 `position: fixed`，调用方传屏幕绝对坐标（`rect.left` / `rect.top` 直接用，不再减 playground 偏移）。

**验收**：
- 点节点 + 按钮，Popover 紧跟节点下方
- 拖线到空白，Popover 紧跟鼠标释放位置
- 底部浮条"+ 添加节点"，Popover 在画布中心

---

#### B2 IF 节点拖拽修复

**修改文件**：`AppEditPage.tsx`（nodeRegistries size）、`components/NodeCard.tsx`

**根因**：IF 节点 size 52px 高，但 NodeCard 内容（图标 30px + 标题/副标题）实际约 56px；两个 output 端口垂直排列在右侧，端口圆点 absolute 定位可能覆盖卡片中部。

**方案**：
1. IF / 多 output 端口节点的 size.height 按 outputs 数量动态计算（每个 output 占 24px + padding）
2. NodeCard 端口容器 `pointer-events: none`，端口圆点本身 `pointer-events: auto`，避免端口区域拦截卡片拖拽

**验收**：
- IF 节点可正常拖拽移动
- LLM / HTTP 等单 output 节点拖拽不受影响
- 端口圆点仍可点击/拖线

---

#### B3 START→IF 连线修复

**修改文件**：`AppEditPage.tsx`（canAddLine）

**根因**：`canAddLine` 用 `portType` 字段判断，但 FlowGram `WorkflowPortEntity` 实际属性可能是 `side`（值为 `'left'/'right'`）或 `direction`。

**方案**：放宽判断——只要 fromPort 不是 undefined 且 toPort 不是 undefined，且 fromPort.id !== toPort.id，就允许连线；方向校验交给 FlowGram 默认行为（拖线本身只能 output→input）。

**验收**：
- START → IF 可正常连线
- START → LLM / HTTP 可正常连线
- 反向拖线（input→output）仍被拒绝

---

#### B4 START 入参表格编辑器

**新建文件**：`components/ParameterListEditor.tsx`

**对齐 Coze 实机**（`coze-after-dblclick.png`）：
```
┌─────────────────────────────────────┐
│ 输入                            [+] │
│─────────────────────────────────────│
│ 变量名    变量类型    必填   引用 删 │
│ [input]  [String ▾] [☐]  [↗]  [🗑]│
└─────────────────────────────────────┘
```

**字段**：
- 变量名 Input
- 变量类型 Select（String / Number / Boolean / File / Image / Array[String] / Array[Number] / Array[Object]）
- 必填 Checkbox
- 引用按钮（暂占位，点击提示"引用变量功能开发中"）
- 删除按钮
- 底部"+ 添加参数"按钮

**验收**：
- START 节点抽屉显示表格化入参编辑器
- 可增删行
- 变量类型下拉可选
- 保存后 node.config.inputs 为 `[{name, type, required}]` 数组

---

### 11.3 执行顺序

```
B1（Popover 坐标）──→ B3（连线校验）──→ B2（IF 拖拽）──→ B4（入参表格）
```

每个修复后浏览器实机验证，typecheck 通过再进下一个。

