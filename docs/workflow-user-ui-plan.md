# 用户端 Workflow 类型应用 —— 执行计划

> 状态：**待确认（2026-11-05）**
> 目标：用户端完整支持 workflow（工作流）类型应用：动态入参表单 → 运行轨迹实时反馈 → 结果/审批/错误呈现 → 我的运行历史，交互对标 coze 工作流应用。
> 参考截图：`docs/assets/workflow/coze-*.png`

---

## 1. 背景与目标

当前用户端只有对话形态：所有应用点进去都是 `/agents/:id/chat`。flow_type=workflow 的应用被当作聊天应用送进 run/stream（语义错误，见 chat-ui-redesign-plan.md 风险 2），后端已有的 `/workflow/run` 非流式端点用户端从未使用。

本期交付 workflow 应用的**用户端工作台**：

1. 入口按 flow_type 分流：对话流进聊天页，工作流进工作台。
2. 工作台根据 START 节点定义的入参自动渲染表单（含 string/number/boolean/image/file/object/array）。
3. 点击运行：SSE 实时展示节点执行轨迹（对齐 coze 试运行的节点时间线 + LLM token 流式）。
4. 运行结束展示 END 输出结果卡；人审中断展示审批卡（有权限直接批准/拒绝，续跑实时轨迹）；出错展示错误卡 + 重试；支持中途停止。
5. 我的运行历史：列表 + 详情（入参/出参/节点执行记录），仅能看本人发起的记录；另设「待我审批」分组供审批人处理他人发起的中断运行。

**设计原则**

- 沿用 chat 改版已定版的「留白 · Light Chat」设计语言（`styles/tokens.css` 单源、lc/wf 前缀、克制品牌色），不另起视觉体系。
- 协议层零破坏：现有 chat/chatflow 接口与前端 `api/*` 不改语义，只新增 workflow 通道。
- 不做 coze 新版那套低代码 UI Builder（截图 `coze-wf-ui-builder.png`）——那是页面搭建平台，本期不做；本期形态对标 coze 经典工作流"表单 + 运行 + 轨迹 + 结果"。
- 每阶段 DoD 全绿：后端 pytest、前端 typecheck + vitest、Playwright 截图四态、console 无新 error。

## 2. 现状盘点（已代码/数据库取证）

### 2.1 后端已有能力（复用）

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 非流式运行 | `POST /user/agents/{id}/workflow/run`（chat.py:236） | 返回 `{status: success/waiting_approval, output, thread_id, run_id, approval?}`；校验可见性、拒绝 chatflow、拒绝问答节点（type=18） |
| 运行引擎节点事件 | `GraphRuntime`（runtime.py:544-589） | runner 已支持 `on_node_event` 回调，产出 `node_start/node_end`（含 inputs/outputs/duration_ms/error）；LLM 节点另有 `llm_token`、agent_loop 有 `prompt_text/tool_call_start/tool_call_end` |
| run 落库 | runtime.ensure_run（runtime.py:201） | invoke 前自动 insert run，结束 update success/error/interrupted；节点执行落 `run_node_execution` |
| 运行时图 | `ApplicationService.get_runtime_graph` | 按发布版本/租户 pin 取画布 JSON |
| 人审中断 | `GraphInterrupted` | 非流式端点已捕获并返回 waiting_approval |
| SSE 骨架 | chat.py run_chatflow_stream | queue+producer+断连 task.cancel 模式可直接仿照 |

### 2.2 缺口（本期新建）

| # | 缺口 | 影响 |
| --- | --- | --- |
| G1 | run 表**无 user_id 列**（0031 建表起就没有），且中断 payload 只在 checkpointer | 用户端无法查"我的运行"，待审批列表无法用 SQL 直接取 |
| G2 | 无用户端获取 START 入参 schema 的通道 | 表单无法动态渲染（用户端拿不到画布 JSON） |
| G3 | 无 workflow SSE 端点（invoke/resume 都只有 admin 非流式） | 运行过程无实时轨迹，审批后续跑也无法继续看轨迹 |
| G4 | 无用户端 run 列表/详情/审批端点（admin 端点不做用户归属校验） | 运行历史、用户端审批无数据来源 |
| G5 | 前端无 workflow 页面/组件/路由；列表卡、详情页按钮全部硬编码进 `/chat` | 用户无法使用 workflow 应用 |

### 2.3 START 入参数据模型（已核对管理端）

- 画布中 START 节点 `data.config.inputs`（coze IR 中同构）：`[{name, type, required}]`。
- type 集合（chatflowStart.ts）：`string / number / boolean / object / file / image / array[string] / array[number] / array[object]`。
- chatflow 内置参数 `USER_INPUT / CONVERSATION_NAME` 在 workflow 形态必须过滤。
- 管理端试运行弹窗 `RunInputsModal.tsx` 已实现 image/file → dataURL 上传，前端直接借鉴。

### 2.4 本地环境

- 唯一 workflow 应用「AI智能创建剧本」无任何 graph 版本（空壳）；验收前需在管理端新建一个 `start(input) → llm → end` 测试工作流并发布。
- 后端标准启动：`uv run python -m web.app_user`。

## 3. 设计方案

### 3.1 信息架构与页面布局

```
┌────────────────────────────────────────────────────────┐
│ ← 返回   [头像] 应用名 · 工作流        [运行历史] [新运行] │  Header 56px
├──────────────────┬─────────────────────────────────────┤
│ 入参面板 380px     │ 运行区（居中列 max-width 720）         │
│ 应用简介           │  空态：插画 + "填写左侧参数后开始运行"    │
│ ─────────         │  运行中：节点轨迹时间线 + token 流式     │
│ 字段1 * [____]    │  成功：结果卡（markdown/JSON + 复制）   │
│ 字段2   [____]    │  审批：审批卡（说明/快照/备注/批准·拒绝） │
│ 图片3   [上传]    │  失败：错误卡 + [重试] [查看技术详情]    │
│ ...               │                                     │
│ [   开始运行   ]   │                                     │
└──────────────────┴─────────────────────────────────────┘
运行历史：右侧抽屉，两个 Tab：「我的运行」（本人发起）/「待我审批」（interrupted 且审批角色匹配）
移动端（<768px）：上下堆叠，历史全屏抽屉
```

- 入口分流：
  - `AgentListPage` 卡片：chatflow → "发起对话"（`/chat`）；workflow → "开始运行"（`/workflow`），标签已有（对话流/工作流）。
  - `AgentDetailPage` 主按钮同上。
  - `ChatPage` 检测到 workflow 型直接 `<Navigate>` 到工作台（兼容旧链接/收藏）。
- 路由新增：`/agents/:agentId/workflow` → `pages/WorkflowPage.tsx`（薄壳 < 30 行）→ `features/workflow/WorkflowWorkbench.tsx`。

### 3.2 前端组件结构

```
src/
  api/workflow.ts                    // runWorkflowStream / getWorkflowSchema / listMyRuns / getMyRun
  pages/WorkflowPage.tsx             // 路由薄壳
  features/workflow/
    WorkflowWorkbench.tsx            // 三栏布局 + 状态编排
    workflow.css                     // wf-* 类名，全部引用 tokens.css 变量
    types.ts
    state/workflowReducer.ts         // SSE 事件 → 运行状态（节点 map、输出、错误）
    hooks/useWorkflowRun.ts          // 发起运行/abort/重试，持有 AbortController
    hooks/useWorkflowHistory.ts      // 我的运行列表/详情
    components/
      WorkflowHeader.tsx
      StartInputForm.tsx             // 动态表单 + required/JSON 校验
      TraceTimeline.tsx              // 节点时间线（running/success/error + 耗时）
      TraceNodeCard.tsx              // 折叠查看节点 inputs/outputs，LLM token 实时文本
      ResultCard.tsx                 // END 输出：文本走 markdown，对象走 JSON 美化，复制
      ApprovalNotice.tsx             // 审批卡：instructions/snapshot 只读 + 备注 + 批准/拒绝（无角色时降级为纯等待+刷新）
      WorkflowErrorCard.tsx          // 错误卡 + 重试 + 技术详情折叠
      RunHistoryDrawer.tsx           // Tab「我的运行」/「待我审批」，只读回看 + 审批操作入口
      EmptyRunState.tsx
```

- 表单类型映射：

  | START type | 控件 | 校验 |
  | --- | --- | --- |
  | string | Input（名称含 desc/多行语义时给 TextArea，默认单行） | required |
  | number | InputNumber | required + 数字 |
  | boolean | Switch | — |
  | image | Upload 多选 → dataURL 逗号拼接（沿用 RunInputsModal） | required |
  | file | Upload → dataURL | required |
  | object / array[*] | JSON 文本域 | required + JSON.parse 合法性 |

- 状态机：`idle → running → success | error | interrupted`；running 中可"停止"（abort SSE，后端断连 cancel）；任何终态可"再次运行/重试"（保留上次入参）。
- 视觉：沿用 token（品牌蓝 #2f6bff、圆角、柔影、120ms 入场），轨迹节点参考管理端 RunHistoryPanel 但做时间线竖轴 + 实时 spinner。

### 3.3 后端接口设计（全部新增，不动旧接口）

**(1) GET `/user/agents/{id}/workflow/schema`**

返回：
```json
{
  "agent_id": "...",
  "name": "...",
  "description": "...",
  "flow_type": "workflow",
  "start_inputs": [
    {"name": "topic", "type": "string", "required": true},
    {"name": "images", "type": "image", "required": false}
  ]
}
```
- 服务方法 `ChatService.get_workflow_schema`：可见性校验 → get_runtime_graph → 找 `type=='start'` 节点 → 从 `config.inputs`（兼容 `outputs`）提取 → 过滤内置参数。
- 非 workflow 应用调用返回 400（提示该应用不是工作流）。

**(2) POST `/user/agents/{id}/workflow/run/stream`**（SSE）

请求：`{"inputs": {...}, "thread_id": "...可选，历史续跑同一线程"}`

预检在 StreamingResponse 之前（4xx 走 JSON）：可见性、flow_type=workflow、无问答节点、START required 字段非空（按 schema 校验）。

事件序列（复用 postSseStream 解析）：

| event | data | 时机 |
| --- | --- | --- |
| run_start | `{run_id, thread_id}` | producer 启动 |
| node_start | `{node_id, node_type, inputs}` | 节点开始（runtime 原生） |
| node_end | `{node_id, status, outputs, duration_ms, error?}` | 节点结束（runtime 原生） |
| llm_token | `{node_id, delta}` | LLM 节点流式 token（runtime 原生） |
| tool_call_start / tool_call_end / prompt_text | 透传 | agent_loop 节点 trace |
| result | `{status:'success', output, run_id, thread_id}` | invoke 正常返回 |
| interrupted | `{status:'waiting_approval', approval, run_id, thread_id}` | GraphInterrupted |
| error | `{message, code}` | 异常 |
| final | `{}` | 结束哨兵 |

- 实现仿 run_chatflow_stream：queue + producer + 断连 `task.cancel()`；runner 用 `build_runner(..., on_node_event=emitter)`。
- commit 语义与非流式版一致（success/interrupted 均 commit）。
- 捕获 GraphInterrupted 时除推 interrupted 事件外，同时把 interrupt payload 写入 `run.interrupt_payload`（见 §3.4），供待审批列表 SQL 直取。
- 非流式 `/workflow/run` 保留（API 兼容）。

**(3) POST `/user/agents/{id}/workflow/runs/{thread_id}/resume/stream`**（SSE）

请求：`{"approved": true, "comment": "备注"}`。

- 预检（流外，4xx JSON）：run 存在且属于该租户/应用且状态 interrupted（`get_running_by_thread`，复用 run_id）→ build runner（thread_id + run_id）→ `get_interrupt_state()` 读 assignee_role，fail-closed（读不到/未配置 → 403）；当前用户 role_code 匹配 assignee_role 才放行（与 admin resume_application 同规则；不要求是发起人本人——审批人通常是发起人的主管）。
- producer 调 `runner.resume({"approved","comment","approver": username})`，事件序列与 (2) 相同（node_*/result/interrupted/error/final），可继续遇到下一个人审节点。
- 审批拒绝：human_task 节点抛 RuntimeError，流程按 error 事件结束（现有节点语义，不改）。

**(4) GET `/user/agents/{id}/runs?limit=20&offset=0` / GET `/user/runs/{run_id}`**

- 列表返回**当前用户发起**的 run（按 user_id 强制过滤；状态、时间、耗时、input 摘要；interrupted 项附审批角色与本人是否可审）。
- 详情返回 run（含 interrupt_payload）+ node_executions；归属校验：本人发起的可看全部；非本人但 run 处于 interrupted 且本人角色匹配 assignee_role 时，允许只读详情（审批人要先看 snapshot）；其余 404。

**(5) GET `/user/agents/{id}/approvals`**

- 待我审批列表：该应用下 `execute_status='interrupted'` 的 run，按 `interrupt_payload->>assignee_role = 当前用户 role_code` 过滤（应用可见性校验照旧；superadmin 角色可看全部，与端点 3 的放行规则一致）。
- 返回 run_id/thread_id/发起人/input 摘要/节点标题/instructions/发起时间，供抽屉列表渲染。

### 3.4 数据模型变更

迁移 `0066_run_user_id.py`：

```sql
ALTER TABLE run ADD COLUMN user_id UUID NULL;
ALTER TABLE run ADD COLUMN interrupt_payload JSONB NULL;
CREATE INDEX ix_run_tenant_app_user_started
  ON run (tenant_id, workflow_id, user_id, started_at DESC);
-- 待审批列表：租户+应用+中断状态，角色过滤在 SQL 外或用 ->> 过滤（角色值简短，量级小可接受）
CREATE INDEX ix_run_tenant_app_interrupted
  ON run (tenant_id, workflow_id) WHERE execute_status = 'interrupted';
```

- 历史数据两列均为 NULL（管理端旧记录、fork 记录不受影响）。
- `RunRepository.insert_run` 增加 `user_id: UUID | None`；`runtime.ensure_run` 传 `self.user_id`。
- `RunRepository.update_run_interrupt(run_id, payload)`：中断时写 payload；`update_run_status` 流转到 success/error 时清空（置 NULL）。
- `list_runs` 增加可选 user_id 过滤；用户端查询强制传 user_id；新增 `list_interrupted(tenant_id, app_id)` + `list_interrupted_for_role(..., role_code)`。

### 3.5 范围边界

- **不做**：coze 式 UI Builder 拖拽搭页；workflow 会话/消息（工作流是一次性任务，不产生聊天会话）；结果产物富渲染（图表/PPT 等，仅 markdown + JSON + 图片 dataURL 原样展示）；多模态结果文件下载；运行结果分享；审批催办/审批意见流转通知（后端无通知通道）；管理端既有审批入口保持不变（双端都可审，以 run 状态为准天然互斥）。
- question 问答节点：workflow 运行前即被后端拒绝（现有规则不变，错误信息引导联系发布者改用对话流）。

## 4. 执行计划

> 统一 DoD：`uv run pytest` 全绿（后端）；`pnpm --filter boxia-user typecheck && test` 全绿；Playwright 截图归档 `docs/assets/workflow/acceptance/pX-*.png`；浏览器 console 无新增 error。

### P0 数据模型与后端基建（0.5 天）

| 任务 | 说明/验收 |
| --- | --- |
| 0.1 迁移 0066：run.user_id + run.interrupt_payload + 两个索引；alembic upgrade/downgrade 本地通过 | 回滚验证 |
| 0.2 RunRepository：insert_run 带 user_id；update_run_interrupt / 状态流转清 payload；list_runs 支持 user_id；list_interrupted(_for_role)；runtime.ensure_run 传 self.user_id；admin fork 调用点传 None 保持旧行为 | 既有 run 相关测试全绿 |
| 0.3 测试 fixture：构造最小 workflow 图（start→end 直出、start→llm→end、start→human_task→end 各一份）的 pytest 工厂 | 后续端点测试复用 |

### P1 后端五个端点 + 测试（1.5 天）

| 任务 | 说明/验收 |
| --- | --- |
| 1.1 `GET workflow/schema`：service 提取 START 参数（过滤内置、兼容 config.inputs/outputs） | pytest：参数提取、非 workflow 400、不可见应用 404 |
| 1.2 `POST workflow/run/stream`：预检 4xx、SSE 事件序列、中断写 payload、异常、断连 cancel | pytest：直出图事件顺序（run_start/node_start/node_end/result/final）；llm 图 mock LLMService 断 token；human_task 图断言 interrupted 事件 + run.interrupt_payload 落库 |
| 1.3 `POST workflow/runs/{thread_id}/resume/stream`：interrupted 预检、assignee_role fail-closed 403、批准续跑事件流、拒绝走 error、二次中断 | pytest：角色匹配放行/不匹配 403、批准成功 output、拒绝 error、非中断 run 404 |
| 1.4 `GET agents/{id}/runs` + `GET runs/{id}` + `GET agents/{id}/approvals`：本人过滤、审批人只读放行、跨租户 404、待审批角色过滤 | pytest IDOR + 角色用例 |
| 1.5 非流式 `/workflow/run` 回归（user_id 自动获得 + interrupt_payload 写入） | 现有测试绿 |

### P2 前端静态版 + 风格闸门（0.5 天，mock 数据）

| 任务 | 说明/验收 |
| --- | --- |
| 2.1 路由 + WorkflowPage 薄壳 + WorkflowWorkbench 三栏骨架 + workflow.css（wf-* token 化） | 空态截图 |
| 2.2 StartInputForm 全类型控件（mock schema 覆盖 8 种 type）+ 校验态 | 表单截图 |
| 2.3 TraceTimeline / ResultCard / ApprovalNotice（含可审批/纯等待两态）/ WorkflowErrorCard / RunHistoryDrawer（两个 Tab）静态 props 五态 | `?wfMock=1`（仅 dev）五态截图 |
| 2.4 **风格闸门（人工）**：截图对照 chat 定版风格与 coze 参考，通过才进 P3 | 人工确认 |

### P3 真实接线（2 天）

| 任务 | 说明/验收 |
| --- | --- |
| 3.1 api/workflow.ts + workflowReducer + useWorkflowRun：真实 SSE、节点 map 增量更新、llm_token rAF 合批、abort 停止、重试（带上次入参） | 真机运行截图 |
| 3.2 进页面拉 schema 动态渲染表单；required/JSON 校验；image/file dataURL 上传 | 真机提交 |
| 3.3 审批接线：ApprovalNotice 备注+批准/拒绝 → resume SSE 续跑并入时间线（含二次中断）；无角色时纯等待+刷新；待审批 Tab 列表/详情/审批操作 | 双账号实测（发起人 + 审批角色人） |
| 3.4 useWorkflowHistory + RunHistoryDrawer 真实数据；历史详情"结果回看"（只读态）；从待审批项进入审批视图 | 多 run 截图 |
| 3.5 入口分流：列表卡/详情页按钮按 flow_type；ChatPage 对 workflow 重定向；移除 `?wfMock=1` | 两个应用两种入口实测 |

### P4 打磨、验收、review（1 天）

| 任务 | 说明/验收 |
| --- | --- |
| 4.1 动效与细节：节点 spinner → ✓ 150ms 切换、结果卡入场、focus 光环、空态、置灰 opacity；prefers-reduced-motion 降级 | 录屏/截图 |
| 4.2 移动端 375px：表单与运行区上下堆叠、历史全屏抽屉 | 移动端五态截图 |
| 4.3 vitest：workflowReducer 事件映射（含 interrupted/resume/abort）、表单校验、审批角色判定三组 | 测试全绿（现有 19 个不回归） |
| 4.4 本地建测试工作流（含 start(input)→llm→end 与 start→human_task→end 两幅）并发布；Playwright 六态：待运行/运行中轨迹/成功结果/审批等待/审批后续跑/错误；console 零报错 | acceptance/p4-*.png |
| 4.5 自审 + 提交 review：后端 pytest 全量、ruff/mypy 新文件零新增问题；前端 typecheck；对照本计划逐项勾验收 | review 记录写入本文档 §6 |

**工作量合计：约 5.5 人天。**

## 5. 风险与约束

1. **SSE 与 commit 时序**：workflow 运行中节点写库、消息节点写会话，必须在 result/interrupted 后 commit，error 时不产生半成品 run 状态——沿用 runtime 现有状态更新逻辑，端点层只加事件转发，不重写事务边界。
2. **双端并发审批**：用户端与管理端都可审批同一 interrupted run，状态以 run 表为准天然互斥（第二个 resume 请求会因 run 已非 interrupted 而 404）；前端对 404 提示"该运行已被处理"并刷新列表，不做分布式锁。
3. **审批角色 fail-closed**：resume 前必须从 checkpointer 读到 assignee_role 且与当前 role_code 匹配；读不到一律 403（沿用管理端既定规则，不放宽）。
3. **大 input（图片 dataURL）**：与 chat 端一致走 JSON SSE POST body；多图 base64 可能超体，表单层限制单图 10MB / 最多 6 张（与管理端一致），超限前端拦截。
4. **历史数据无 user_id**：用户端历史只展示上线后的新 run；管理端列表不受影响。
5. **运行中节点输入输出敏感信息**：节点 inputs/outputs 在用户端可见是预期（使用者本人发起的运行）；但 tool_call trace 可能含密钥类回显，沿用管理端 RunHistoryPanel 同等级别展示，不做额外脱敏（与现有用户端 tool trace 策略一致）。
6. **唯一 workflow 测试应用是空壳**：P4.4 前必须先建图发布，否则无法真机验收。

## 6. Review 记录

> 2026-11-05 实现完成后填写。验收截图：`docs/assets/workflow/acceptance/`（p2-* 为风格闸门定稿，p3-* 为真实接线实测）。

### 6.1 逐阶段验收结论

| 阶段 | 结论 | 证据 |
| --- | --- | --- |
| P0-P1（后端端点+契约） | 通过（前一 session 完成） | `tests/test_user_workflow_api.py` 10 passed |
| P2 静态版 + 风格闸门 | 通过（人工确认） | p2-01~08 截图，用户答复"通过，继续 P3+P4" |
| P3.1-P3.4 真实接线 | 通过 | schema/run/resume/history/审批分流全走真实 API；typecheck 0 错 |
| P3.5 双账号实测 | 通过 | wf-owner 发起直出/人审（等待态）；wf-leader 抽屉角标→去审批→批准→resuming 续跑并入轨迹；p3-02~06 |
| P4.1 结果卡打磨 | 通过 | 复用 chat `AssistantContent` markdown 渲染；单 `output` 键解包；null→"本次运行无输出"；p3-10 |
| P4.2 单测 | 通过 | workflowReducer 6 + StartInputForm 4 + useWorkflowRun 4，共 14 用例；全量 vitest 33/33 |
| P4.3 移动端 | 通过 | 375px 表单/运行区上下堆叠，抽屉全屏；p3-11 |
| P4.4 真机六态 | 通过 | idle p3-07 / running p3-08 / success p3-02 / approval p3-05 / waiting p3-03 / error p3-09；console 无新增报错 |

### 6.2 测试水位

- 前端：`tsc --noEmit` 0 错；`vitest run` 7 文件 33 passed（新增 3 文件 14 用例，原 19 用例不回归）；oxlint 新增告警与 chat 基线同类（set-state-in-effect / refs），无新规则命中。
- 后端：全量 pytest 通过（含 workflow API 10 用例）；新增文件 `scripts/seed_workflow_demo.py`、`web/app_user.py` ruff 通过、mypy 自身 0 错误（93 个为 import 链存量基线）。

### 6.3 偏差与处置

1. **`?wfMock=` 静态通道未移除**（原 3.5 计划移除）：保留为 dev-only（生产构建 `import.meta.env.DEV` 分支 tree-shake，且 URL 不带参即走真实视图）。理由：P2 风格截图与后续样式回归依赖六态确定性复现。
2. **StartInputForm 提交门死锁 bug**：`notice` 写入空串键导致 `Object.keys(errors).length` 恒 >0，实测点击"开始运行"无请求后修复为仅收集非空错误。
3. **reducer error 闩**：后端失败时仍补发 `result(output=null)`，`result` 分支对 `phase==='error'` 忽略，错误态不被覆盖（错误链实测 p3-09）。
4. **`web/app_user.py` 补 win32 SelectorEventLoopPolicy**：原仅 app_admin 有，直接 `uvicorn web.app_user:app` 时 psycopg async 抛 ProactorEventLoop 错（P1 端点测试走 conftest 策略未暴露）。
5. **演示 LLM 工作流 model=test-model 未配置**：真机运行落入真实错误态（正好补足 error 截图）；如需跑通 LLM 链路，管理端换真实模型即可，不影响验收。
6. **dev 库 admin 口令漂移**：`.env` 与库中 hash 不一致（AUTO_INIT 只建不改），已按 .env 重置，seed 脚本 `scripts/seed_workflow_demo.py` 幂等可重跑。
