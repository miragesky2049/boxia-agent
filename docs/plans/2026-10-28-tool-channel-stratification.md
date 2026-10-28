# 跨网工具调用分层与租户级 Agent 运行平台演进 Plan

> 日期：2026-10-28
> 范围：backend/engine、backend/web、frontend/admin、frontend/user、ops
> 目标范式：对齐 Dify「租户级 Agent 运行平台」——租户可自助创建 Agent、注册工具/技能/知识库，平台只提供运行时与编排能力。

---

## 一、背景与现状

### 1.1 已有能力

| 模块 | 现状 | 位置 |
|---|---|---|
| Agent 运行主循环 | Function Calling while 循环，max_iterations=6，事件外抛已预留 | `backend/internal/engine/runner.py` |
| 消息模型 | OpenAI Chat Completions 兼容（system/user/assistant/tool） | `backend/internal/engine/messages.py` |
| LLM 客户端 | OpenAI 兼容（DeepSeek/Qwen/网关） | `backend/internal/engine/llm.py` |
| 工具抽象 | `Tool` ABC，已实现 `EchoTool` / `HttpTool` / `McpTool` | `backend/internal/engine/tools.py` |
| MCP 协议 | fastmcp client，支持 `list_tools` / `call_tool` | `backend/internal/engine/mcp_client.py` |
| MCP 同步 | 从外部 MCP server 拉工具 upsert 到 tools 表 | `backend/internal/application/mcp_sync_service.py` |
| 短期记忆 | Redis，按 `tenant/agent/conversation` 维度，滑动 TTL | `backend/internal/engine/memory.py` |
| RAG | query rewrite → 多 query 召回 → rerank 精排 | `backend/internal/application/retrieval_service.py` |
| 多租户 | Tool/Agent/Skill/Prompt 实体均带 `tenant_id`，产品级租户 = 全零 UUID | `backend/internal/domain/entity/resource.py` |
| 前端 admin | 已有 agents/skills/tenants/users/grants 等页面 | `frontend/admin/src/pages/` |

### 1.2 缺口（本次要解决的）

1. **跨网工具调用无分层**：租户工具可能部署在公网、租户内网 MCP、租户内网且不愿开端口，目前只有 HttpTool 和 McpTool 两条路径，第三种完全缺失。
2. **服务端到服务端调用不工程化**：HttpTool 没有鉴权策略、重试、超时分级、审计落库、SSRF 防护。
3. **租户接入成本高**：注册工具要手填 JSON config，没有向导、没有连通性测试、没有 schema 自动提取。
4. **前端图形化不足**：Agent 编排、工具配置、Connector 状态都没有可视化界面。
5. **产品级管理员视角缺失**：平台公共工具市场、Connector 全局看板、租户配额管理均未实现。

---

## 二、跨网工具调用三层模型（核心）

### 2.0 网络方向对比（关键认知）

| 通道 | 网络方向 | 谁主动连谁 | 租户要做什么网络配置 | 适用租户场景 |
|---|---|---|---|---|
| L1 HttpTool | 平台 outbound → 租户公网 API | **平台主动** | 租户必须把工具服务暴露公网，或专线打通到平台 | 工具已上云 / 有公网域名 |
| L2 McpTool | 平台 outbound → 租户 MCP Server | **平台主动** | 同 L1，平台要能 reach 到 MCP Server URL | 租户在内网跑了 MCP Server，且有专线/SD-WAN 打通 |
| L3 Connector | 租户 Connector outbound → 平台 WS 端点 | **租户主动** | **零端口暴露、零公网 IP、零网络打通** | 工具完全在租户内网，什么都不愿暴露 |

> **核心结论**：L1 和 L2 是同一种网络方向（平台主动调租户），区别只是协议。真正"零网络配置"的只有 L3，因为它把连接方向反转为租户出站（租户防火墙默认允许 outbound HTTPS/WSS）。

### 2.1 整体拓扑

```
┌──────────────────────────────────────────────────────────────┐
│  boxia-agent 运行平台（公网 / 平台节点）                       │
│                                                              │
│   Agent ──► Tool Dispatcher ──►┬── L1 HttpTool（公网直连）     │
│                                 ├── L2 McpTool（内网 MCP Server）│
│                                 └── L3 ConnectorTool（WS 反向）  │
└──────────────────────────────────────────────────────────────┘
        ▲                            ▲                │
        │ 平台 outbound              │ 平台 outbound  │ 租户 outbound（方向反转）
        │ （要求租户暴露）            │ （要求租户暴露）│ （租户零配置）
        ▼                            ▼                │
┌─────────────────────────┐  ┌─────────────────────┐ │
│ 租户公网 API             │  │ 租户内网 MCP Server  │ │
│ (租户主动暴露)           │  │ (租户主动暴露+专线)  │ │
└─────────────────────────┘  └─────────────────────┘ │
┌─────────────────────────────────────────────────────┘
│ 租户内网（完全封闭）
│   ┌─────────────┐    ┌──────────────┐
│   │ 内部业务    │◄──│ Connector    │
│   │ 服务 API   │   │ Agent（轻量）│
│   └─────────────┘    └──────────────┘
└─────────────────────────────────────────────────────
```

### 2.1 L1 — HttpTool（公网可达）

**适用**：租户工具服务已暴露公网 URL，或通过专线/SD-WAN 打通到平台节点。

**⚠️ 租户必须自行解决网络可达性**：平台不负责打通租户内网。如果租户工具没有公网 URL 也没有专线，请改用 L3 Connector。前端向导在租户选 L1 时要明确提示这一点。

**已有，需工程化加固**：

| 能力 | 现状 | 加固项 |
|---|---|---|
| URL 模板渲染 | `{{var}}` 已支持 | 增加变量白名单校验 |
| 鉴权 | 无 | 新增 `auth_strategy`：none / bearer_static / api_key_header / oauth2_client_credentials |
| 超时 | connect=10s / total=30s | 可配置分级（connect / read / total） |
| 重试 | 无 | 429/5xx 指数退避，最多 3 次，幂等 key 头 |
| 审计 | 仅日志 | 落 `tool_call_audit` 表（入参 hash、出参长度、耗时、状态码） |
| SSRF 防护 | 无 | URL 黑名单（内网网段 10/8、172.16/12、192.168/16、169.254/16、localhost）+ 租户级白名单 |
| 入参 schema | 手填 | 支持从 OpenAPI/Swagger JSON 自动导入 |

### 2.2 L2 — McpTool（内网但愿意跑 MCP Server）

**适用**：租户在内网跑了 MCP Server，平台节点能通过某种隧道（如专线/SD-WAN）访问到。

**已有雏形，需加固**：

| 能力 | 现状 | 加固项 |
|---|---|---|
| 协议 | fastmcp remote（HTTP/SSE） | 增加 stdio 模式（平台侧直接 spawn 子进程，仅限同机） |
| 同步 | `McpSyncService` 手动触发 | 增加定时增量同步 + schema 变更告警 |
| 鉴权 | 无 | MCP Server 支持 Bearer Token / mTLS |
| 超时 | 复用 httpx 默认 | 独立 timeout 配置 |
| 审计 | 仅日志 | 同 L1 落库 |

### 2.3 L3 — ConnectorTool（内网且不愿暴露端口）—— **本次新增**

**适用**：租户工具服务完全在内网，没有公网入口，也不愿跑 MCP Server。

**架构**：

```
租户内网节点                          平台节点
─────────                          ─────────
                                    ┌─ Tool Dispatcher
                                    │     │
                                    │     ▼
┌──────────────┐   WS 出站连接      │  ┌────────────────┐
│ Connector    │ ◄─────────────────┼──┤ Connector GW   │
│ Agent        │   wss://.../ws     │  │ (FastAPI WS)   │
│ (轻量二进制)  │   每租户一个       │  └────────────────┘
│              │   心跳 30s         │         │
│ 上报工具清单  │ ◄─────────────────┘         ▼
│ 接收 invoke  │                    ┌────────────────┐
│ 调本地 HTTP  │ ──────────────────►│ connector_registry
│ 回传结果     │                    │ (Redis 路由表)  │
└──────────────┘                    └────────────────┘
```

**核心组件**：

1. **Connector GW（平台侧）**：FastAPI WebSocket 端点 `wss://<platform>/api/v1/connector/ws`
   - **生产部署**：走 443 经 Nginx/Ingress，必须透传 `Upgrade: websocket` / `Connection: Upgrade` header；Nginx 配置 `proxy_read_timeout 3600s` 防 WS 被中间层切断
   - **鉴权（平台签发，不是租户签发）**：
     - 租户管理员在平台端「新建 Connector」时，平台用 `MASTER_KEY` 签发 short-lived JWT（`exp=24h`），payload 含 `connector_id` / `tenant_id` / `version`
     - Connector Agent 启动时把 JWT 放在 `Authorization: Bearer <jwt>` header 里做 WS 握手
     - 平台用同一 `MASTER_KEY` 验签，提取 `connector_id` / `tenant_id`
     - 租户吊销：平台把 `connector_id` 写入 Redis 短期黑名单（key=`connector:revoked:<id>`，TTL=7 天），下次握手拒绝
   - **连接路由**：`connector_id -> WebSocket`，初期单实例内存 dict（按 D2 决策）；抽象 `ConnectorRouteResolver` 接口，后续可切 Redis pub/sub
   - **心跳**：server 30s ping，client pong；60s 无 pong 判定离线，触发状态机迁移 online -> offline
   - **离线 invoke 行为**：平台要调 offline Connector 的工具时，**立即返回错误**（"工具暂不可用，请稍后重试"），不排队等待；LLM 拿到错误后自己决定重试或换工具
   - **大结果集限制**：单条 WS 消息 ≤ 256KB；超过时 Connector Agent 走"分块传输"（`type=result_chunk`，带 `call_id` / `offset` / `total` / `is_last`），平台侧拼装完整内容
   - **多 Connector 同租户路由**：工具注册时绑定 `connector_id`（一个工具只能挂在一个 Connector 上）；invoke 时按 `tool.config.connector_id` 找到对应 WS，不做模糊匹配
   - **版本升级感知**：register 消息带 `version` 字段，平台记录到 `connectors.version`，前端展示版本号，过旧时提示租户升级二进制
   - 消息协议（JSON）：
     ```json
     // client -> server 启动上报（含版本）
     {"type": "register", "connector_id": "...", "version": "1.0.0",
      "tools": [{"name": "...", "description": "...", "input_schema": {...}}]}
     // server -> client 调用
     {"type": "invoke", "call_id": "...", "tool_name": "...", "arguments": {...}, "timeout_ms": 5000}
     // client -> server 回包（小结果）
     {"type": "result", "call_id": "...", "ok": true, "content": "..."}
     {"type": "result", "call_id": "...", "ok": false, "error": "..."}
     // client -> server 回包（大结果分片）
     {"type": "result_chunk", "call_id": "...", "offset": 0, "total": 1024000, "is_last": false, "chunk": "..."}
     {"type": "result_chunk", "call_id": "...", "offset": 262144, "total": 1024000, "is_last": true, "chunk": "..."}
     ```

2. **Connector Agent（租户侧）**：单二进制（Python 打包为 PyInstaller / Go 重写）
   - 启动参数：`--platform-url wss://boxia.example.com --token <jwt>`
   - 自动重连：指数退避 1s/2s/4s/.../60s 封顶
   - 工具定义：YAML 配置文件声明本地 HTTP 调用映射
     ```yaml
     tools:
       - name: create_hr_ticket
         description: 在 HR 系统创建工单
         input_schema: { ... }
         endpoint: http://127.0.0.1:8080/api/tickets
         method: POST
         timeout_ms: 5000
     ```
   - 安全：工具 endpoint 只允许 `127.0.0.1` / 内网网段，禁止公网跳转

3. **Connector Registry（平台侧）**：
   - 表 `connectors`：id、tenant_id、name、status(online/offline)、last_heartbeat_at、version
   - 表 `connector_tools`：从 register 消息 upsert，自动在 `tools` 表生成 `type=connector` 记录
   - 租户级 Connector 管理页：签发 token、吊销、查看在线状态

---

## 三、Tool 实体与配置 schema 扩展

### 3.1 `Tool.type` 枚举

| type | 说明 | 通道 |
|---|---|---|
| `echo` | 内置调试 | — |
| `http` | 公网 HTTP | L1 |
| `mcp` | 外部 MCP Server | L2 |
| `connector` | 内网反向隧道 | L3（新增） |

### 3.2 `Tool.config` schema 扩展

```jsonc
// http
{
  "url": "https://api.tenant.com/xxx/{{id}}",
  "method": "POST",
  "headers": { "Content-Type": "application/json" },
  "auth_strategy": "bearer_static",      // 新增
  "auth_secret_ref": "sec_xxx",          // 新增，引用加密存储
  "timeout_connect_ms": 5000,            // 新增
  "timeout_total_ms": 15000,             // 新增
  "retry": { "max_attempts": 3, "backoff_ms": 500 },  // 新增
  "ssrf_allow_private": false            // 新增，默认 false
}

// mcp
{
  "server_url": "https://mcp.tenant.com",
  "tool_name": "get_user",
  "input_schema": { ... },
  "auth_strategy": "bearer_static",      // 新增
  "auth_secret_ref": "sec_xxx",
  "timeout_ms": 15000
}

// connector（新增）
{
  "connector_id": "conn_xxx",
  "tool_name": "create_hr_ticket",
  "input_schema": { ... },
  "timeout_ms": 10000
}
```

### 3.3 新增表

| 表 | 用途 |
|---|---|
| `tool_secrets` | 加密存储 api_key/bearer_token/oauth 凭据（KMS 或对称加密） |
| `connectors` | Connector Agent 注册表 |
| `tool_call_audit` | 每次工具调用审计（tenant_id、tool_id、call_id、耗时、状态、入参 hash、出参长度） |

---

## 四、Tool Dispatcher（运行时统一入口）

当前 `runner.py` 直接 `self._tools[name].invoke()`。新增统一 Dispatcher：

```
Tool.invoke(arguments, context)
  ├── RateLimitInterceptor    租户级限流（每分钟 N 次，Redis 计数）
  ├── CircuitBreaker           熔断：连续失败 5 次，5 分钟内直接返回"暂不可用"
  ├── AuthInterceptor         按 auth_strategy 注入凭据（bearer/api_key/oauth2）
  ├── TimeoutInterceptor      分级超时
  │     L1: connect / read / total
  │     L2: connect / total
  │     L3: WS invoke 等待 result 超时（独立配置，不等同于 HTTP timeout）
  ├── RetryInterceptor         429/5xx 重试（仅幂等方法 GET/HEAD/OPTIONS）
  ├── Router
  │     ├── HttpToolExecutor        L1
  │     ├── McpToolExecutor         L2
  │     └── ConnectorExecutor       L3（按 tool.config.connector_id 路由到 WS）
  ├── AuditInterceptor         落 tool_call_audit（入参 hash、出参长度、耗时、状态）
  └── MetricsInterceptor       Prometheus 指标（qps、latency、error_rate）
```

**熔断状态机**（每 tool 独立）：
- `closed`（正常）-> 连续失败 5 次 -> `open`（5 分钟内直接拒绝）
- `open` -> 5 分钟后 -> `half_open`（放 1 个探测请求）
- `half_open` 成功 -> `closed`；失败 -> `open`（重新计时）

**租户级限流**：
- 按 `tenant_id` 维度，每分钟默认 60 次工具调用（可在租户配置里调整）
- 超过时返回 `ToolExecutionError("调用频率超限，请稍后重试")`，不消耗 LLM 调用次数

**位置**：`backend/internal/engine/tools.py` 重构为包结构：

```
engine/tools/
  ├── base.py            Tool ABC + ToolExecutionError
  ├── dispatcher.py      统一入口 + 拦截器链
  ├── http.py             L1
  ├── mcp.py              L2
  ├── connector.py        L3
  ├── echo.py
  └── factory.py          build_tools(entities) -> Tool 实例
```

---

## 五、租户接入低成本流程

### 5.1 新建工具向导（三步）

1. **选通道**：「我的工具服务在哪？」
   - 🌐 公网可访问 → L1 HttpTool
   - 🔗 内网跑了 MCP Server → L2 McpTool
   - 🔒 内网且无公网入口 → L3 ConnectorTool
2. **填配置**：按通道类型动态渲染表单
   - L1：URL、方法、Header、鉴权方式、超时、重试
   - L2：MCP Server URL、Token、「拉取工具列表」按钮
   - L3：选择已有 Connector 或新建（生成下载链接 + token）
3. **测试连通**：平台模拟一次调用，展示请求/响应/耗时

### 5.2 Connector 接入五步走

1. 租户管理员在 admin 端「Connector 管理」点「新建」
2. 平台生成 `connector_id` + 一次性 JWT token（24h 有效）
3. 下载 `connector` 二进制（Linux/Windows/macOS）
4. 租户在自己服务器跑：
   ```bash
   ./connector --platform-url wss://boxia.example.com --token <jwt> --config tools.yaml
   ```
5. 平台端实时看到 Connector 上线，自动上报工具清单，租户一键绑定到 Agent

### 5.3 Agent 编排页

- 拖拽式：左侧工具/技能/知识库列表，右侧 Agent 画布
- Prompt 可视化编辑器：变量高亮、历史版本、调试预览
- 试运行：右侧聊天窗，实时展示 tool 调用轨迹

---

## 六、前端图形化配置范围

### 6.1 租户端（`frontend/admin`）

| 页面 | 现状 | 新增/改造 |
|---|---|---|
| 工具管理 | 列表 + JSON 编辑 | **向导式新建**、连通性测试、按通道分组 tab |
| Connector 管理 | 无 | **新建**：列表（在线/离线）、签发 token、吊销、下载二进制 |
| Agent 编排 | 表单页 | **拖拽画布**：工具/技能/知识库绑定、Prompt 编辑器、试运行 |
| 技能管理 | 列表 + 编辑器 | 渐进式披露开关、依赖工具提示 |
| 知识库 | 上传 + 列表 | 切分预览、召回测试（query → chunks 打分） |
| 审计日志 | 无 | **新建**：按时间/工具/Agent 查询 |

### 6.2 产品级管理员端（平台视角）

| 页面 | 说明 |
|---|---|
| 租户管理 | 已有，增加工具配额、Connector 数量配额 |
| 平台公共工具市场 | 产品级注册工具，所有租户可一键安装 |
| Connector 全局看板 | 在线 Connector 数、按租户分布、调用 QPS |
| 平台审计 | 跨租户审计查询 |
| LLM 网关配置 | 模型、API Key、限流 |

---

## 七、分阶段实施计划

| Phase | 周期 | 内容 | 交付物 |
|---|---|---|---|
| **P1 工程化加固** | 2 周 | Tool 实体扩展、tool_secrets 表、Tool Dispatcher 拦截器链（auth/timeout/retry/audit）、SSRF 防护 | 后端可跑，L1 通道生产可用 |
| **P2 Connector 后端** | 2 周 | Connector GW（WS）、Registry、Redis 路由表、ConnectorExecutor、消息协议 | 平台侧能接收 connector 连接 |
| **P3 Connector 客户端** | 1 周 | Python 单二进制、YAML 工具声明、自动重连、启动脚本 | 租户可下载运行 |
| **P4 前端工具/Connector** | 2 周 | 工具向导、Connector 管理页、连通性测试 | 租户能自助注册工具 |
| **P5 Agent 编排页** | 2 周 | 拖拽画布、Prompt 编辑器、试运行聊天窗 | 租户能自助编排 Agent |
| **P6 联调 + 文档** | 1 周 | 端到端联调、租户接入手册、Connector 部署文档 | 上线 |

---

## 八、关键风险与对策

| 风险 | 对策 |
|---|---|
| WS 网关水平扩展多实例 | 路由表存 Redis + pub/sub，invoke 消息通过 Redis 广播到 connector 所在实例 |
| Connector 二进制跨平台分发 | 先 PyInstaller 三平台打包，后续视性能 Go 重写 |
| 内网工具被滥用 | connector token 短时效 + 租户可吊销 + 调用审计全量落库 |
| 工具入参 schema 漂移 | MCP/Connector 启动上报时 diff 检测，前端提示 schema 变更 |
| 长连接占资源 | 每连接独立 asyncio task，上限可配，超限时拒绝新连接 |
| 鉴权凭据泄露 | tool_secrets 加密存储，前端只显示 secret_ref，不回显明文 |

---

## 九、与 Dify 的对标差异

| 维度 | Dify | 本平台 |
|---|---|---|
| 工具通道 | HTTP / Plugin / MCP | HTTP / MCP / **Connector（WS 反向）** |
| 多租户 | SaaS 多租户 | 私有部署多租户（产品级租户 = 全零 UUID） |
| 编排 | 拖拽工作流 | 初期：表单 + 工具绑定；后续：工作流画布 |
| 接入 | Plugin SDK | Connector 二进制 + YAML 声明（更低成本） |

---

## 十、已确认决策（2026-10-28）

| # | 事项 | 决策 | 影响 |
|---|---|---|---|
| D1 | Connector 客户端语言 | **Python + PyInstaller** | P3 按 Python 单二进制交付，三平台打包；后续视性能数据决定是否 Go 重写 |
| D2 | WS 网关多实例 | **初期单实例，预留 Redis 路由接口** | ConnectorRegistry 抽象为接口（`ConnectorRouteResolver`），初期实现单实例内存路由；后续加 Redis pub/sub 实现时不改业务代码 |
| D3 | tool_secrets 加密 | **对称加密（env 注入 MASTER_KEY）** | AES-256-GCM，MASTER_KEY 从环境变量读取；SecretCipher 抽象预留 KMS 切换 |
| D4 | Agent 编排页形态 | **直接上拖拽画布** | P5 采用 React Flow / Antv X6，开发周期从 2 周调整为 3 周 |
| D5 | 产品级公共工具市场 | 待 P5 完成后单独评估 | 不阻塞当前 Phase |

### 10.1 实施计划调整

| Phase | 原周期 | 调整后 | 调整原因 |
|---|---|---|---|
| P1 工程化加固 | 2 周 | 2 周 | 不变 |
| P2 Connector 后端 | 2 周 | 2 周 | 单实例路由 + Redis 接口预留，不增加开发量 |
| P3 Connector 客户端 | 1 周 | 1 周 | Python + PyInstaller 三平台打包 |
| P4 前端工具/Connector | 2 周 | 2 周 | 不变 |
| P5 Agent 编排页 | 2 周 | **3 周** | 拖拽画布（React Flow）开发量 +1 周 |
| P6 联调 + 文档 | 1 周 | 1 周 | 不变 |
| **合计** | **10 周** | **11 周** | |
