# 用户端对话流 Chat UI 体系化优化方案与执行计划

> 状态：**v3.2 —— 推翻旧 UI 全新重建口径；P0/P1 完成并经风格闸门确认，P2 协议接线完成，P3/P4 打磨进行中（进度见 §8）**
> 日期：2026-11-04（v1 初版 → v2 补实机截图逐区块明细 → v3 改为全新重建策略，均同日）
> 目标页面：`http://<租户>.localhost:5174/agents/:agentId/chat`（实机验证租户：anan / 智能体：测试智能体 01a18808-…）
> 截图证据：`docs/assets/chatflow/chat-current-*.png` + 用户提供的 2844x1438 实机截图（欢迎态全貌，问题明细见 §2.2）

---

## 1. 背景与目标

当前用户端 Chat 页"比较丑，且布局有问题"。目标是做一次**偏 C 端、体验优先**的完整 UI/交互重设计，并保证对话流功能（流式、工具轨迹、问答中断、会话历史）完整可用。

设计对标：coze / doubao 风格的用户端对话页 —— 清爽留白、品牌色克制使用、消息气泡舒适、流式反馈细腻、空状态有引导。

**设计原则（v3 修订）**
1. 体验优先：所有状态（加载/流式/出错/中断/空）都有明确、好看的反馈。
2. 不破坏协议：SSE 两类事件流（Agent 事件、Chatflow 事件含 question/resume 中断）、会话/历史接口、认证机制是**唯一必须保留的层**。
3. **全新重建（v3 裁决）**：推翻现有外观与布局结构，按全新设计语言重做整个 Chat UI；不在旧 `chat-*` 样式上打补丁，旧样式块在验收通过后一次性物理删除，不留兼容层。
4. 不引入新技术栈：沿用 React18 + antd5 + react-markdown + Vite，仅按需加极小依赖（代码高亮）。
5. 每阶段人工闸门兜底：全新重建面大，用"阶段验收 + 欢迎态样板闸门 + 四态截图回归"控制风险。

---

## 2. 现状问题清单（实机截图 + 代码取证）

### 2.1 布局硬伤（截图实证，最严重）
| # | 问题 | 证据 |
|---|------|------|
| L1 | 会话侧栏未撑满全高，仅 186px 塌在左上角，下方大片空白；header 被顶到 y=186 占满 1440 全宽 —— 整体呈纵向堆叠而非左右分栏 | 根因已复核（index.css:353-358、962-967）：`.chat-page` 为 `flex-direction:column`，aside/header/scroll/input 是 4 个直接子元素**纵向堆叠**；桌面 ≥900px 媒体查询只是把侧栏从"绝对定位抽屉"改成 `position:relative`，从未形成行布局。**移动端抽屉形态其实是正常的**，塌的是桌面端 |
| L2 | 消息区高度被压到 534px，底部输入区悬浮脱节，与消息列宽(820)不对齐 | `div.chat-scroll [1440x534]` vs `chat-input-wrapper [820x62 @310,797]` |
| L3 | 信息重复：侧栏"新会话/历史会话"、header"会话/新会话"、欢迎区再展示一次 agent 名与简介，同屏三处入口冗余 | chat-current-1.png |
| L4 | 错误消息直接渲染红色裸提示条，无重试入口、无友好文案 | chat-current-3-done.png（psycopg 报错原文糊在气泡里） |

### 2.2 当前 UI 区块明细（视觉层，基于用户实机截图逐区块核对）

> 截图为欢迎（空会话）态，视口约 1422x719 逻辑像素（DPR 2）。以下按区块列出"看到什么 → 问题 → 改法方向"。

| 区块 | 现状观察 | 问题诊断 | 改法方向（对应 §3） |
|------|----------|----------|----------------------|
| 页面背景 | 上半屏一条淡紫渐变 wash（自侧栏后方向右铺满，约 y0–350），下半屏转浅灰，wash 与浅灰之间有肉眼可见分界 | 渐变带与内容无关、随布局破坏而"漂移"；深浅分界生硬 | 统一为纯浅底 `--bg-layout`；欢迎态允许极淡径向光斑点缀，消息态全纯色（§3.2） |
| 左侧栏 | 白底卡片只覆盖左上角（高约 186px），头行"历史会话 / 新会话"，下方"暂无历史会话"空态后即截断，右侧一条边框线突兀结束 | 布局硬伤 L1 的视觉表现；空态无引导（没有"开始第一次对话"暗示） | 侧栏满高；空态插画/文案引导；边框线改为满高分隔（§3.1） |
| Header 行 | 位于 wash 下方，独占全宽：← 返回 · 🕐 会话 · 蓝紫头像 + "测试智能体" + "在线·随时为你服务"，最右一个灰色置灰的"新会话" | 与侧栏入口三处重复（L3）；置灰"新会话"对比度过低近似不可点；"在线·随时为你服务"文案偏营销腔 | 去重后仅侧栏保留新会话；header 只留头像+名称+状态点（绿点+"在线"，流式时切换"思考中…"）；置灰态统一降透明度而非换灰字（§3.1/§3.2） |
| 欢迎 Hero | 64px 紫渐变圆角头像，右下角叠一个绿色"认证"圆徽；黑色大标题"测试智能体"；灰副标题 | 绿徽是多余装饰（agent 并非认证语义），C 端显廉价；紫渐变大色块与整体浅色系冲突；标题层级过强、与 header 重复展示名称 | 去绿徽；头像改品牌色纯底/柔和渐变小尺寸；欢迎态不再重复大标题名称（副标题一句引导即可）（§3.2） |
| 建议提示词 | 3 个白底细灰边胶囊按钮，宽度贴合文字长短不一，无图标无层级 | 像"标签"不像"可点的卡片"；无 hover 态差异；长短不齐显得散 | 改等宽三卡（网格，≤3 条自动均分；>3 条纵向列表）：图标+文案+hover 品牌色描边/轻投影，点击直接发送（§3.2/§3.3） |
| Composer | 白胶囊输入框宽约 820px（比消息列宽且未对齐）；placeholder 淡灰；右侧小号浅紫渐变发送钮 | 与消息列不对齐（L2）；disabled 发送钮浅紫几乎看不清；输入框内边距/焦点态缺失 | 列宽统一 760 居中；发送钮 enabled=品牌色实心、disabled=灰底白字降透；focus 品牌色 2px 光环；Enter/Shift+Enter 说明移入 hover 或底部弱化（§3.1/§3.2） |
| 底部声明 | "由 测试智能体 驱动 · 内容由智能体生成，请谨慎甄别" 淡灰小字居中 | 基本合格，字号偏小、"测试智能体"链接色与正文混杂 | 保留，统一 `--text-tertiary`，智能体名去链接化（欢迎态已在 header 展示） |
| 消息态（参考流式截图） | user 高饱和蓝紫渐变大气泡；错误为红色裸条直出后端报错原文 | 渐变大块气泡压迫感强、长文本对比疲劳；错误不可读不可重试（L4） | user 浅蓝底深蓝字小圆角泡、限宽 70%；assistant 无框化直排+头像；错误改错误卡+重试（§3.2/§3.3） |

### 2.3 运行环境问题（阻塞验收）
| # | 问题 | 证据 |
|---|------|------|
| R1 | 后端以 `uvicorn web.app_user:app --port 8001`（不带 --reload）启动时，psycopg async 在 Windows ProactorEventLoop 下报错，对话直接失败。**已复核解法**：标准启动 = `uv run python -m web.app_user`（`__main__` 入口 reload=True，即 selector loop），报错文案本身即指向此方式 | 截图报错文案；`backend/web/app_user.py:8-11` |
| R2 | 本地无用户端默认账号；已为 staff001（anan/viewer）插入探针 refresh token（7 天过期，`user_refresh_tokens` 表）用于自动化截图验收 | 本次调研 SQL 插入记录 |

### 2.4 代码欠债（影响可维护性与体验迭代）
| # | 问题 | 位置 |
|---|------|------|
| C1 | 744 行单体组件，气泡/列表/输入/工具轨迹/欢迎页全部内联，无子组件 | `frontend/user/src/pages/ChatPage.tsx` |
| C2 | 无状态层：流式、会话、工具轨迹全在组件 setState，token 逐字追加触发全组件重渲染（流式卡顿根源） | ChatPage.tsx:192-412 |
| C3 | 无设计 token：971 行 index.css 散落硬编码色值；antd theme 与 CSS 双处维护、互相不同步；无 dark 模式 | `src/index.css`、`src/main.tsx:17-34` |
| C4 | markdown 代码块无高亮、无复制按钮；user 消息纯文本；无消息操作（复制/重试/时间） | ChatPage.tsx:671-674 |
| C5 | Chat 零测试（现有 vitest 仅 auth/tenant 两处） | `src/**/*.test.tsx` |
| C6 | 历史消息加载后丢弃 toolTraces，会话切换无加载骨架屏 | ChatPage.tsx:135-141 |

---

## 3. 总体设计方案

### 3.1 信息架构（三栏定高布局，视口不滚动，仅消息流内滚）

```
┌────────────┬──────────────────────────────────────────┐
│ 侧栏 264px  │ Header 64px：头像+agent名+状态点  [新会话][…] │
│ (可折叠)     ├──────────────────────────────────────────┤
│ ▸ 新会话     │            消息流（居中列 max-width 760）     │
│ ▸ 历史会话   │   user 右侧气泡 / assistant 左侧无框排版       │
│   列表项     │   工具轨迹=可折叠"步骤卡"  question=问答卡片    │
│   (悬停重命名 │            …… 底部渐变遮罩 + [↓回到底部]        │
│    /删除)    ├──────────────────────────────────────────┤
│ 底部: 返回   │ Composer：自动增高输入框 + 发送/停止 按钮       │
│     用户菜单 │ 提示行(快捷键/免责声明)                        │
└────────────┴──────────────────────────────────────────┘
```

要点：
- 删除 header 中与侧栏重复的"会话/新会话"入口；欢迎态时隐藏 header 的会话信息行，居中展示 hero。
- 侧栏可折叠（图标态 64px），当前会话高亮；会话项 hover 操作（重命名/删除）**待裁决点 E**——当前前后端均无该能力，未批准则不设计假入口。
- 移动端（<768px）：侧栏变抽屉，Header 保留；Composer 吸底适配安全区。

### 3.2 视觉设计系统

**设计语言定义 ——「留白 · Light Chat」**（v3 全新，与旧视觉彻底切割）：
- 关键词：大留白、单一品牌蓝点缀、大圆角、细线、柔影、克制动效。参考气质：coze 用户端 / doubao 对话页。
- **明确不继承**：旧紫色渐变 wash 带、高饱和渐变气泡、绿色认证徽、紫渐变发送钮、三处重复入口——以上全部废弃，新 UI 不保留任何旧 `chat-*` 视觉资产。
- §2.2 逐区块问题清单在新建中作为**反向约束**（每条都是新设计必须避免的坑）。

**具体规范**：
- **Token 化**：新建 `src/styles/tokens.css`，CSS 变量定义 `--brand-*、--bg-*、--text-*、--border-*、--radius-*(8/12/16/999)、--space-*、--shadow-*、--font-*`；`main.tsx` antd ConfigProvider 从同一处 JS token 派生，单一事实源。
- **配色**：品牌主色保留 #2f6bff 系；页面背景统一浅底（去掉横贯上半屏的紫色 wash 渐变带，欢迎态仅允许极淡径向光斑，消息态纯色，消除分界线）；user 气泡浅蓝底深蓝字、限宽 70%（弃高饱和渐变）；assistant 无框直排 + 小头像（弃卡片大边框）；gradient 仅保留在头像与品牌点缀，且降饱和。
- **组件级落点（对应 §2.2 逐区块）**：
  - Hero：去绿色认证徽；头像 56px 圆角柔光底；不再重复大标题 agent 名，副标题一句引导。
  - 建议提示词：等宽卡片网格（≤3 条均分、>3 条纵列），图标+文案，hover 品牌描边+轻投影，点击即发送。
  - Composer：列宽与消息列对齐（760px 居中）；发送钮 enabled 品牌实心 / disabled 灰底降透；focus 品牌 2px 光环；placeholder 提高一级灰度保证可读。
  - Header：仅头像+名称+状态点（绿点在线 / 流式"思考中…"），其余入口去重；置灰元素统一 opacity 0.45 而非灰字。
  - 底部声明：`--text-tertiary` 统一，agent 名去链接化。
- **字体**：系统栈；正文 15px/1.7；消息列 760px；行高、段距按阅读舒适度调校。
- **动效**：流式光标（▍闪烁）、消息入场 120ms fade+rise、步骤卡展开 150ms、toast；全部 prefers-reduced-motion 可降级。
- **Dark 模式**：本期只做 token 预留（变量双份），实现放收尾阶段可选。

### 3.3 交互清单（体验优先的差异化点）
| 场景 | 设计 |
|------|------|
| 发送 | Enter 发送 / Shift+Enter 换行；发送即清空并保持焦点；发送后输入框不禁用（可预编辑下一条，排队提示） |
| 流式中 | 打字机 + 光标；Header 状态点变"思考中…"；Composer 发送按钮变"停止生成"(可中断，复用现有 abort 逻辑，补 run 中断确认) |
| 出错 | 气泡下方 inline 错误卡：友好文案 + [重试]（重发上一条 user 消息）；技术细节折叠供排查 |
| 工具调用 | 折叠"步骤卡"：⚙️ 正在调用 xxx… → 完成 ✓ 耗时；点开看参数/结果（保留 Collapse，视觉重做） |
| Chatflow question 中断 | 渲染为问答卡片：可点选项/自定义输入 → resume（现有协议保留） |
| 消息操作 | assistant：复制全文 / 重新生成（最后一条）；hover 时间戳（user 编辑重发列入范围外） |
| 滚动 | 流式自动吸底；用户上滚即停止吸底并显示 [回到底部↓] 浮动按钮 |
| 空状态 | Hero 头像+欢迎语+建议提示词卡片（现为前端硬编码 3 条 `SUGGESTED_PROMPTS`，ChatPage.tsx:44-48，非 agent 配置下发；本期沿用硬编码仅重做样式，"按 agent 配置"列入范围外） |
| 会话切换 | 骨架屏加载历史；保留 toolTraces（后端已返回则渲染，未返回则不显示） |

### 3.4 组件与技术架构（v3：全新重建，以下组件均新写而非从旧代码拆出）

```
src/
  features/chat/
    ChatPage.tsx                    // 路由薄壳，仅渲染 ChatWorkbench（目标 <30 行）
    hooks/useChatSession.ts         // 会话+消息+流式状态收敛（useReducer；持有 AbortController 接 agentRun 已有的 signal 参数）
    hooks/useAutoScroll.ts          // 吸底/上滚脱离/回到底部
    state/chatReducer.ts            // SSE 事件 → UI 状态映射（含 token 批量节流：requestAnimationFrame 合批，解决卡顿）
    components/
      ChatSidebar.tsx               // 会话列表（折叠/重命名/删除）
      ChatHeader.tsx                // 顶栏+状态点
      MessageList.tsx               // 虚拟不需要（历史限20条+分页后续再说）
      MessageBubble.tsx             // user/assistant 两态
      AssistantContent.tsx          // markdown 渲染 + 代码高亮 + 复制
      ToolTraceCard.tsx             // 工具轨迹步骤卡
      QuestionCard.tsx              // chatflow 问答中断卡
      NoticeCard.tsx                // interrupted 审批等待提示（旧 ChatPage.tsx:288-294 已有此消息态）
      Composer.tsx                  // 输入区（自动增高/停止/发送）
      WelcomeHero.tsx               // 空状态
      ErrorNotice.tsx               // 错误卡+重试
    api/（沿用 src/api/agentRun.ts、conversations.ts，事件协议不动）
```
- 新增唯一小依赖：`highlight.js` + 自封装 CodeBlock（是否引入由裁决点 B 定，最迟在 P1.4 闸门前拍板）。
- vitest：为 chatReducer（事件→状态）、useAutoScroll、QuestionCard resume 流程补单测；Playwright 截图脚本扩展为"改造前后对比"验收。

---

## 4. 执行计划（v3：**全新重建**策略，推翻旧 UI）

> **重建策略**：从零实现全新的 `features/chat/**`（新设计语言「留白 · Light Chat」、新组件、新样式文件 `chat.css`，类名统一 `lc-*` 前缀），**不修改、不兼容、不借用**旧 ChatPage 外观与 index.css `chat-*` 样式；唯一复用的是协议层（`src/api/agentRun.ts`、`conversations.ts`、auth/租户机制）。路由 `pages/ChatPage.tsx` 改为薄壳直接渲染新 `ChatWorkbench`，旧视觉代码与旧样式块在 P5 一次性物理删除，不留兼容层。
>
> **依赖链**：P0 基建 → P1 全新 UI 静态版（mock 数据）→ 风格闸门 → P2 协议接线 → P3 视觉动效打磨 → P4 交互深化 → P5 切换与清理
>
> **v3 关键差异**：风格人工闸门从"改到一半"（v2 的 P3.0）前移到 **P1 结束时**——全新重建时最贵的错误是"方向错了整体返工"，所以在接协议之前先用 mock 数据把全部视觉状态截图定版。
>
> **统一 DoD（每阶段必须全绿）**：
> - `pnpm --filter boxia-user typecheck` + `pnpm --filter boxia-user test` 通过；
> - Playwright 截图归档至 `docs/assets/chatflow/acceptance/pX-*.png`（欢迎态/流式中/完成态/错误态四态齐全；P1 允许 mock 态截图）；
> - 浏览器 console 无新增 error；
> - 协议零改动：`src/api/agentRun.ts` 事件语义 diff 为空（P2 起）。

### P0 基建：环境 + 验收工具 + token 骨架（0.5 天）
| 任务 | 文件 | 说明/验收 |
|------|------|------|
| 0.1 后端标准启动方式落地：用户端一律 `uv run python -m web.app_user`（reload=True 入口，selector loop），写入 `docs/development.md` 排错条目（CLI 不带 --reload 必报 psycopg Proactor 错，R1 已复核） | docs | 实机发"你好"能收到流式回复（全部验收的前提） |
| 0.2 固化截图验收工具：`probe-chat-ui.js` 改造为 `acceptance.js`（参数化视口/登录注入/发消息/mock 开关/四态输出） | docs/assets/chatflow/ | 一条命令产出四态图 |
| 0.3 新建 `src/styles/tokens.css`（明色一套 + dark 空槽）与 `src/theme/tokens.ts` JS 单源；`main.tsx` antd ConfigProvider 从 tokens.ts 派生 | 新文件 ×2 + main.tsx | 新 UI 只引用变量；antd 主色与 CSS 一致 |
| 0.4 采集现状基线截图留档（旧 UI 丑图作对照组，P5 删除旧码前最后留证） | acceptance/p0-baseline-*.png | — |

### P1 全新 UI 静态版（1 天，mock 数据，先骨架后皮肤）
| 任务 | 文件 | 说明/验收 |
|------|------|------|
| 1.1 新样式入口 + 三栏定高骨架：`.lc-page` 100dvh flex；侧栏（满高/可折叠）、header（头像+名称+状态点）、消息列 760 居中、Composer 吸底 | features/chat/ChatWorkbench.tsx + chat.css | 截图：§2.2 每一条布局问题在新 UI 上不存在 |
| 1.2 欢迎态：WelcomeHero（无绿徽、不重复大标题）+ 建议提示词等宽卡片网格（mock 数据） | components/WelcomeHero.tsx | 截图评审 |
| 1.3 消息态全套静态样式（fixture 驱动）：user 浅蓝泡/assistant 无框+头像/markdown 排版/代码块/步骤卡三态/错误卡/QuestionCard/NoticeCard(审批提示)/流式光标 | components/（静态 props） | mock 页 `?lcMock=1`（仅 dev 构建注入）五态截图 |
| 1.4 **风格闸门（人工）**：P1 四态截图 + 新旧对照交人工评审，通过才进 P2；驳回则在 P1 内迭代样式，不接协议 | — | 人工确认记录 |

### P2 协议接线：真实对话流跑通（1.5 天）
| 任务 | 文件 | 说明/验收 |
|------|------|------|
| 2.1 `useChatSession` + `chatReducer`：SSE（Agent/Chatflow 两事件流）→ reducer 状态；llm_token rAF 合批，消除逐 token 全组件重渲染（修 C2）；**必须保留旧实现的幂等覆盖语义**：llm_end 的 `usage_streamed` 回退分支与 result 事件对 content/tool_traces 的整体覆盖（ChatPage.tsx:369-376/411-422） | hooks/ + state/ | 长回答流式无掉帧；reducer 单测覆盖上述两种覆盖时序 |
| 2.2 会话能力接线：会话列表/新建/切换/历史加载（保留 toolTraces，修 C6）。**复核更正**：前后端均无会话重命名/删除端点（conversations.ts 与 chat.py 只有两个 GET），本期不做，除非裁决点 E 批准新增后端 | useChatSession | 多会话实测截图 |
| 2.3 中断与错误：停止生成按钮——**两端管道已存在只需 UI 接线**：前端 agentRun.ts `StreamOptions.signal` 早已支持，后端 run/stream `event_stream finally → task.cancel()` 断连即取消 producer（chat.py:137-145）；error 事件 → 错误卡 + 重试（重发上一条 user）；question → resume 真实往返（当前测试智能体 01a18808 即 chatflow，可直接实测） | components | 故意断后端 + 当前 agent 实测 question/resume |
| 2.4 移除 `?lcMock=1` 依赖路径（保留 reducer fixture 供单测） | — | 真实链路四态截图 |

### P3 视觉与动效打磨（1 天）
| 任务 | 文件 | 说明/验收 |
|------|------|------|
| 3.1 动效落地：消息入场 120ms、流式光标、步骤卡展开 150ms、状态点"思考中…"切换；prefers-reduced-motion 降级 | components | 流式中截图含光标 |
| 3.2 细节规范铺面：focus 光环、hover 态、置灰 opacity 0.45、底部声明、空态文案；`chat.css` 全量 token 化（无裸 hex） | chat.css | 抽查样式文件 |
| 3.3 消息操作：复制、最后一条"重新生成"、hover 时间戳 | MessageBubble 等 | 实测截图 |

### P4 交互深化（1 天）
| 任务 | 文件 | 说明/验收 |
|------|------|------|
| 4.1 useAutoScroll：吸底/上滚脱离/「回到底部」浮标（**取代**旧实现"每次 messages 变化无条件 smooth scrollTo"，ChatPage.tsx:193-198，该写法流式中会反复强制拉回） | hooks/useAutoScroll.ts | 流式中上滚不被拉回 |
| 4.2 Composer：自动增高(max 6 行)、IME 组合回车不误发（回归现有 `isComposing` 判定，ChatPage.tsx:443）、字数上限、发送保持焦点、禁用态清晰 | Composer.tsx | 中文输入法实测 |
| 4.3 侧栏体验：当前会话高亮、切换骨架屏、hover 操作位（接线与否随裁决点 E） | ChatSidebar.tsx | 多会话实测 |
| 4.4 建议提示词点击即发送；发送后 header/hero 平滑过渡到消息态 | WelcomeHero | 新会话实测 |

### P5 切换与清理 + 收尾（1 天，收尾可选项见裁决点 C）
| 任务 | 说明/验收 |
|------|------|
| 5.1 **旧代码物理删除**：ChatPage.tsx 旧渲染逻辑、index.css `chat-*` 样式块、相关死代码全部移除；路由薄壳化 | 全局搜索无 chat-* 残留；包体积对比 |
| 5.2 vitest：chatReducer 事件映射、QuestionCard resume、Composer IME、错误卡重试四组用例 | 测试全绿 |
| 5.3 移动端抽屉重做与打磨（旧版 <900px `absolute+translateX(-100%)+mask` 形态本就正常，v3 按 lc-* 重建并补齐 Composer 吸底安全区） | 375px 五态截图 |
| 5.4 dark 模式填充（P0.3 已留槽位）+ a11y 抽查（焦点环/aria-live/对比度） | 明暗切换截图 + axe 报告 |
| 5.5 探针 refresh token revoke 清理（user_refresh_tokens，§2.3 R2） | 记录 |

**工作量汇总**：P0-P5 核心 ≈ **6 天**（风格闸门在 P1.4，接协议前定版可避免最大返工项）；其中 5.3/5.4 可按裁决点 C 裁剪（约 -1 天）。

---

## 5. 风险与约束

1. **全新重建的最大风险是功能回归**：旧 UI 里散落的边界行为（历史 20 条截断、Web Locks 单发保护、401 单飞刷新配合、租户头透传、abort/resume 时序）都可能在新实现中丢失。对策：协议层文件（agentRun.ts / conversations.ts / client.ts）零改动；P1.4 风格闸门在接协议前定版；P2 起每阶段 DoD 含"真实链路四态截图 + 控制台无错"；旧代码保留至 P5.1 才物理删除，期间可随时 diff 行为。
2. **SSE 协议兼容**：Agent/Chatflow 两类事件 + question/interrupted/resume 是硬约束，P2 只做事件→reducer 映射不改协议。**复核结论**：当前测试智能体 01a18808 即 chatflow 型（application.flow_type='chatflow'），2.3 问答中断可直接实测，无需另建 agent；但 ReAct run/stream 分支在 UI 上需非 chatflow agent 才可达（且现行实现把 workflow 型也送进 run/stream，`/workflow/run` 端点用户端未使用）——新 UI 保持与旧实现相同分流（`flow_type==='chatflow'` 二分），不顺手改语义，workflow 分流问题另立工单。
3. **Windows 后端事件循环**（R1）：解法已复核——`uv run python -m web.app_user`；P0.1 前置为文档化+验证。
4. **antd 与自绘样式混合**：新 UI 中 Composer/气泡/卡片全部自绘 + CSS 变量，antd 仅用于 Collapse/Modal/Dropdown/message 等少数交互件，避免双体系打架。
5. ~~viewer 角色权限~~ **已闭环**：run/stream 等端点无角色级依赖，报错截图证明 staff001(viewer) 已通过认证并进入流程执行（错误发生在 psycopg，即认证之后）。
6. **旧代码删除时机**：仅当新旧行为对照清单（P2 验收时整理）全部勾完才执行 5.1，防止"删早了没得比"。
7. **会话重命名/删除无后端能力**：前后端均无端点。本期侧栏**不提供假动作入口**（不摆只弹 toast 的菜单）；是否补两个小后端端点见裁决点 E，批准则 2.2/4.3 追加。
8. 范围外（本期不做）：消息编辑重发、多模态附件上传、会话分页游标、消息搜索、TTS、建议提示词按 agent 配置下发。

## 6. 确认点（需要人工裁决后再开工）

> v3 已裁决项：是否推翻旧 UI → **是，全新重建**（本轮用户明确）。

- [ ] A. 设计语言按 §3.2「留白 · Light Chat」推进即可，或指定参照站（coze/doubao/其它）由我用浏览器实机对照后再定；P1.4 仍设风格闸门兜底。
- [ ] B. 是否引入代码高亮小依赖（highlight.js）；不引入则代码块仅等宽+复制。
- [ ] C. P5 中 5.3 移动端 / 5.4 dark+a11y / 5.2 单测的取舍。
- [ ] D. 执行节奏：默认"P0→P1→闸门→P2→P3→P4→P5"逐阶段确认；可选"P1.4 风格定版后，P2→P4 连续执行、P5 前统一验收"。
- [ ] E.（review 新增）会话重命名/删除：当前前后端均无端点。选项①本期不做（默认，UI 不摆假入口）；②补后端 PATCH/DELETE 两个小端点 + 前端接线（约 +0.5 天，超出纯前端范围）。

## 7. Review 记录（2026-11-04，对照真实代码逐条复核）

| # | 方案原论断 | 复核结果 | 处置 |
|---|-----------|----------|------|
| V1 | L1 根因"flex 未生效" | `.chat-page` 本就是 `flex-direction:column`，四段纵向堆叠；≥900px 媒体只改 position，从未有行布局；移动端抽屉正常（index.css:353/962） | §2.1 更正 |
| V2 | "复用现有 abort 逻辑" | 前端 `StreamOptions.signal` 早已存在但 UI 从未传入；后端断连 `task.cancel()` 已实现（chat.py:137-145）→ 成本更低，属"接线"非"新建" | P2.3 更正 |
| V3 | P2.2 "重命名/删除，复用 conversations.ts" | 前端无函数、后端无端点（chat.py 会话侧仅 2 个 GET） | 移出默认范围，新增裁决点 E |
| V4 | 风险"本地可能无 chatflow agent 需创建" | 目标 agent 01a18808 即 chatflow（DB 查证）；2.3 直接可测 | 风险 2 更正 |
| V5 | 风险"viewer 可能无 run 权限" | 端点无角色依赖；报错截图证明已过认证进入执行 | 风险 5 闭环 |
| V6 | P0.1 "selector loop 或 app 入口"待摸索 | `web/app_user.py:8-11` `__main__` reload=True 入口即解法 | P0.1 定稿 |
| V7 | §3.3 "沿用现有 suggestion" | 是前端硬编码 3 条（ChatPage.tsx:44-48），无 agent 配置下发 | §3.3/范围外更正 |
| V8 | P4.2 "IME 组合回车不误发"当作新特性 | 旧代码已实现 `isComposing`（ChatPage.tsx:443）→ 改"回归" | P4.2 更正 |
| V9 | P4.1 未提现状 | 旧实现每次 messages 变化无条件 smooth scrollTo（193-198）→ 明确"取代" | P4.1 更正 |
| V10 | P5.3 "移动端做侧栏抽屉" | 旧抽屉形态本已正常（<900px absolute+mask）→ 改"重做与打磨" | P5.3 更正 |
| V11 | 组件清单缺态 | 旧 UI 有 interrupted→notice 审批提示态（ChatPage.tsx:288-294） | 加 NoticeCard，P1.3 五态 |
| V12 | reducer 映射遗漏时序 | llm_end `usage_streamed` 回退 + result 覆盖 content/tool_traces 的幂等语义必须保留（369-376/411-422） | P2.1 补充验收点 |
| V13 | 分流语义 | ChatPage 把非 chatflow（含 workflow）全送 run/stream，`/workflow/run` 未用——新 UI 保持同分流不改语义 | 风险 2 补充 |

## 8. 执行进度（2026-11-04）

> 裁决结果：A 留白 · Light Chat 通过 P1.4 风格闸门；B 引入 highlight.js；E 本期不做会话重命名/删除。

| 阶段 | 状态 | 证据/说明 |
|------|------|-----------|
| P0 基建 | ✅ | 后端 `uv run python -m web.app_user` 流式实机通过；`acceptance.js` 固化；tokens.css/tokens.ts 单源；`acceptance/p0-baseline-*.png` 旧 UI 基线 |
| P1 全新 UI 静态版 | ✅ | `features/chat/**` 全量 `lc-*` 组件 + chat.css；六态截图 `acceptance/p1-*.png`；人工闸门通过 |
| P2 协议接线 | ✅ | reducer + useChatSession + ConnectedChat 接线；真实链路 `acceptance/p2-real-*.png` / `p2-live-*.png`；交互 `p2-interaction-*`（切会话=2 条历史、新建回欢迎态、停止生成生效）；console 零报错 |
| P3 视觉/动效 | ✅ | 对话流等待态思考气泡、停止后「已停止生成」轻提示、消息入场 120ms、侧栏会话点对齐、focus-visible 光环；`p3-*.png` |
| P4 交互深化 | ✅ | 粘性自动滚动（流式中上滚不被打断 + 「回到底部」浮标）、移动端抽屉、等待态占位；IME 回归沿用 `isComposing`；`p3-mobile-*.png` |
| P5 清理/收尾 | 🟡 | 已完成：旧 ChatPage 渲染逻辑删除（薄壳 6 行）、index.css 旧 `chat-*` 样式块物理删除、未用的 mock fixtures 删除、错误态友好文案 + 技术细节折叠（`p5-error.png`）、aria-live/role=log；未做：dark 模式实装（仅 token 槽位）、axe 自动扫描 |

**测试水位**：`pnpm --filter boxia-user typecheck` 通过；vitest **19 passed**（chatReducer 10 + useChatSession 3 + tenant 4 + auth 2）。

**偏差更正（P2.3）**：目标智能体 01a18808 虽是 chatflow，但其发布图 `start → llm → if_else → output` **没有 question 节点**，无法真实触发问答中断；`question/resume` 链路改为 `useChatSession.test.tsx` 单测覆盖（question 登记 → resume 携带 `{answer}` 且 `message=''` → 结果续写），如需真实往返验收，需在画布中加 question 节点后再跑一次。

**探针 token**：`user_refresh_tokens` 每次验收都会新增行（refresh 一次性轮换），属临时数据；P5.5 统一清理。
