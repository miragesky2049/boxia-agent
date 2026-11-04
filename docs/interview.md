> 返回 [项目手册](../README.md)

## 13. 面试讲解指南

这一章不是功能文档，而是帮你把项目讲清楚。建议先自己运行一遍，再按下面的顺序准备。

### 13.1 30 秒介绍模板

> 这是一个企业内部的 AI 应用编排与运营平台。管理员在可视化画布上组合模型、提示词、工具与知识库，编排成应用后发布到市场，再按租户和角色授权给最终用户使用。后端是 FastAPI 双站点，运行引擎用 LangGraph 执行画布 DAG，RAG 链路走 bge 向量召回 + cross-encoder 精排，工具调用统一经过治理网关。项目重点在工程化：多租户隔离、RBAC、审计、可撤销会话、数据库迁移、可观测性、容器化部署和 CI 质量门禁。

### 13.2 2 分钟介绍模板

1. **背景和目标**：企业想把“模型 + 提示词 + 工具 + 知识”组合成可复用的 AI 应用，但配置分散、权限复杂，需要一个统一的编排、发布和运营平台。
2. **系统组成**：管理端（React 19 + ReactFlow 画布）、用户端、后端 FastAPI 双站点（admin 8000 / user 8001）、PostgreSQL + Redis + Celery，Nginx 统一反代。
3. **核心流程**：管理员登录 → 创建应用 → 画布编排（LLM / HTTP / 代码 / 知识检索 / 循环 / 子流程等节点）→ 调试运行 → 发布生成不可变图版本 → 上架市场 → 租户开通实例（钉版本、配额、有效期）→ 终端用户对话或运行。
4. **工程重点**：短 Access + 可撤销 Refresh 会话、RBAC 与资源授权、审计日志、统一错误模型、Alembic 迁移与就绪检查、结构化日志与指标、容器安全加固。
5. **个人贡献/亮点**：选 1–2 个最熟的点展开，比如“画布 DAG 的运行时与断点续跑”“刷新令牌轮换与重放检测”“工具治理网关的 SSRF 与熔断”“RAG 召回 + 精排链路”。

### 13.3 架构怎么讲

```text
┌────────────────────────────────────────────┐
│  管理端 React 5173     用户端 React 5174    │
│  画布编排 / 市场 / 资源   我的应用 / 对话     │
└───────────────┬────────────────────────────┘
                │ HTTPS + /api/v1/{admin,user}
┌───────────────▼────────────────────────────┐
│  FastAPI 双站点（admin 8000 / user 8001）   │
│  web → application → domain → infrastructure│
│  GraphRuntime（LangGraph DAG）              │
│  ChatService（ReAct 对话循环）              │
│  RetrievalService / ToolGateway             │
└──────┬──────────────┬───────────────┬──────┘
       │              │               │
┌──────▼─────┐ ┌──────▼─────┐  ┌──────▼────────┐
│ PostgreSQL │ │   Redis    │  │ Celery (RAG)  │
│ + pgvector │ │ 记忆 / 缓存 │  │ 文档切分/向量化 │
└────────────┘ └────────────┘  └──────┬────────┘
                                      │
                              ┌───────▼────────┐
                              │ 外部 HTTP/MCP  │
                              │ 工具（经网关）  │
                              └────────────────┘
```

讲解时强调四点：

1. **应用是唯一模型**：`application` 存应用，`application_graph` 存草稿图，发布时写不可变的 `application_graph_version`，市场开通后 `tenant_application_instance` 钉住版本。
2. **运行时与业务层解耦**：`internal/domain/graph` 只负责画布编译与节点执行，鉴权、可见性、事务提交由 `web` 与 `internal/application` 负责。
3. **前后端完全分离**：开发时 Vite 代理 `/api`，生产时 Nginx 反代，前端不直接连数据库。
4. **事务边界**：仓储只 `flush`，应用服务统一 `commit`，审计与业务同事务。

### 13.4 技术选型与理由

| 选择 | 理由 | 代价/替代方案 |
| --- | --- | --- |
| FastAPI | 类型提示 + Pydantic 自动校验、自动生成 OpenAPI、开发效率高 | 同步 ORM 需要线程池；纯高并发 IO 场景可换 async 或 Go |
| PostgreSQL + pgvector | JSONB 存画布图，事务、索引、`pg_trgm` 模糊搜索成熟，向量检索与业务数据同库 | 向量规模很大时可切 Milvus（代码已做 `VECTOR_STORE_PROVIDER` 抽象） |
| LangGraph | 图状态、检查点、中断与断点续跑开箱即用，适合画布 DAG | 需要理解图状态与检查点模型 |
| SQLAlchemy 2.0 | 成熟、类型友好、迁移生态完善 | 同步模型在极高并发下需要调连接池 |
| DDD 分层 | 业务规则与 HTTP/ORM 解耦，便于测试和演进 | 文件数量增加，小项目可能显得重 |
| 短 Access + 可撤销 Refresh | 兼顾性能和可撤销性；Access 不落 localStorage，降低 XSS 风险 | Refresh 仍存 localStorage，需要 CSP、轮换和重放检测兜底 |
| Nginx 做前端与反代 | 静态资源、SPA 回退、限流、安全头一次解决 | 多一层需要维护 |
| 多租户：共享库 + `tenant_id` 行级隔离 | 一套代码、一套数据库，迁移和升级只做一次，运维成本低 | 查询必须始终带作用域条件；强合规或超大租户可演进为独立 Schema/独立库 |
| Celery + Redis | 文档切分与向量化耗时长，异步化后接口快速返回 | 需要维护 worker 与队列 |
| Docker Compose | 小团队部署成本低，服务边界清晰 | 大规模编排可迁移到 Kubernetes |

### 13.5 可讲的亮点

1. **会话安全**
   - Access Token 只存内存，Refresh Token 数据库只存 SHA-256 哈希。
   - 单次轮换 + 重放检测：旧 refresh 再次使用会撤销整族会话。
   - `token_version` 让登出、改密、禁用、删除立即失效。
   - 多标签页用 Web Locks 单飞刷新，避免并发刷新导致令牌互相失效。

2. **画布运行时**
   - 画布 JSON 由 `internal/domain/canvas` 转换、校验、lint，再由 `internal/domain/graph` 编译成图执行。
   - 检查点落库并按租户隔离，支持断点续跑、单节点调试和人审中断（`waiting_approval`）。
   - 子流程节点可加载子应用图；变量系统支持 `{{query}}`、`{{llm_1.output}}` 这类引用。

3. **RAG 链路**
   - 文档异步切分 + 向量化，embedding 用 bge-large-zh，召回后 cross-encoder 精排。
   - 查询改写、召回、rerank、prompt 注入分阶段可观测，向量库可切 pgvector / Milvus。

4. **工具治理网关**
   - SSRF 防护、熔断、限流、重试、连接池、响应截断统一收口。
   - HTTP 与 MCP 双协议共用同一套治理，租户工具与平台工具走同一入口。

5. **事务与审计一致性**
   - 仓储不提交事务，应用服务统一提交；审计日志与业务写入同事务。
   - 认证失败使用独立短事务记录，避免影响主流程。

6. **数据库工程化**
   - Alembic 版本化迁移，CI 中执行 `alembic check` 防止模型和迁移漂移。
   - 迁移前加 advisory lock，避免多个实例并发迁移。
   - 就绪检查同时验证数据库连通性和迁移版本，部署时能快速发现“代码新、库旧”。

7. **可观测性与交付**
   - 每个请求有 `request_id`，并支持 W3C `traceparent` 传播。
   - 结构化日志、OpenTelemetry 链路、Prometheus 指标。
   - 容器非 root、只读根文件系统、`cap_drop: ALL`，CI 中用 Trivy 扫描镜像漏洞。

8. **多租户作用域隔离**
   - 同一套代码按二级域名区分产品级与租户级，不需要为每个租户部署一套服务。
   - 作用域在请求入口解析一次，贯穿认证、RBAC、仓储三层校验，令牌跨作用域直接拒绝。
   - 应用通过市场开通生成租户实例（含配额、有效期、钉住的图版本），资源通过 `resource_grant` 开放给租户，管理单元决定数据可见范围。
   - 仅本地回环主机保留请求头切换作为调试逃生口；开发/测试/线上只认域名，配置错误启动即失败。

### 13.6 难点与取舍

| 难点 | 做法 | 取舍 |
| --- | --- | --- |
| 画布既要可编辑又要可回滚 | 草稿图与发布版本分离，实例钉住版本 | 多一套版本表与缓存失效逻辑 |
| 令牌既要安全又要无感刷新 | 短 Access + 轮换 Refresh + 请求排队重放 | 实现复杂，前端需要处理并发刷新 |
| 租户既要用平台应用又要能配置 | 平台应用 + 租户实例 + 租户级配置覆盖 | 运行时配置解析多一层合并 |
| 工具调用既要灵活又要安全 | 统一网关做 SSRF、熔断、限流、截断 | 网关成为关键路径，需要独立测试与监控 |
| 迁移安全 | advisory lock + 就绪检查 + CI 漂移检查 | 上线流程要求先迁移后启动 |
| 权限实时生效 | 每次请求查数据库校验角色/状态 | 每个请求多一次查询，用索引和连接池控制成本 |

### 13.7 高频面试问答

**Q1：为什么用 FastAPI，不用 Django/Spring？**

FastAPI 类型提示友好、Pydantic 校验和 OpenAPI 文档开箱即用，适合以 API 为主的项目；团队是 Python 技术栈。Django 更适合全家桶式业务，Spring 更重但生态成熟。选型主要看团队和交付速度。

**Q2：为什么做 DDD 分层，会不会过度设计？**

这个项目除了 CRUD，还有画布编译、图运行时、RAG、工具治理、多租户、RBAC、审计等规则，放一起会很快失控。分层让业务规则可测试、可替换；代价是文件多。如果只是纯 CRUD 小工具，确实可以更简单。

**Q3：应用的发布和回滚怎么设计？**

草稿存 `application_graph`，发布时生成不可变的 `application_graph_version`。租户开通后生成 `tenant_application_instance` 并钉住版本，回滚就是切换实例指向的版本，不需要改草稿图。

**Q4：Access Token 和 Refresh Token 怎么设计？**

Access 用 JWT（HS256），默认 30 分钟，前端只存内存；Refresh 是随机串，数据库只存 SHA-256 哈希，默认 14 天。刷新时轮换，旧令牌立即失效；检测到旧令牌重放就撤销整条会话链。

**Q5：为什么 Refresh Token 存数据库？**

为了可撤销。JWT 本身无状态，签发后无法主动失效；把 refresh 存库并维护会话状态，才能在登出、改密、禁用时立即让会话失效。

**Q6：怎么防暴力破解和用户名枚举？**

未知用户名也做一次固定 bcrypt 校验，避免响应时间差；连续失败锁定 15 分钟；Nginx 对登录接口限流；错误文案统一，不区分“用户不存在”和“密码错误”。

**Q7：RBAC 怎么实现？**

角色存数据库，每次请求解析令牌后查实时账号、角色与功能权限编码；权限分系统 / 菜单 / 页面 / 按钮 / 工具几类。管理端路由统一挂管理员鉴权，应用管理仅产品级平台可写；租户只能使用已开通的应用和被授权的资源。不信任令牌里的角色快照，避免改角色后旧令牌继续生效。

**Q8：多租户数据怎么隔离？**

请求入口解析域名得到作用域，JWT 带 `tid`，鉴权时校验令牌、账号、作用域三者一致；仓储层再按 `tenant_id` 过滤一次。平台只读写产品级数据，租户能“看到本租户 + 产品级”，但只能写本租户。即使上层校验漏了，SQL 层也不会跨租户。

**Q9：LangGraph 在项目里怎么用？**

把画布 JSON 编译成图，节点是执行单元，检查点落库。这样断点续跑、单节点调试、人审中断都能复用图状态；执行器与业务层解耦，`GraphRuntime` 不需要知道权限和事务。

**Q10：RAG 怎么做的？**

文档异步切分后写向量库（pgvector 或 Milvus），查询时先改写再召回，cross-encoder 精排后注入 prompt。embedding 与 rerank 模型都可配置，Celery 负责耗时的建档任务。

**Q11：工具调用怎么保证安全？**

所有工具调用经过治理网关：先做 SSRF 校验，再走熔断、限流、重试和连接池，响应超长会截断。HTTP 和 MCP 共用这套治理，避免每个工具各写一份。

**Q12：审计日志怎么保证不丢？**

业务审计和业务写入在同一个数据库事务里提交；登录失败这类没有业务事务的场景，用独立短事务写入，避免影响主流程。

**Q13：数据库迁移怎么保证安全？**

用 Alembic 版本化；迁移脚本进入代码评审；CI 跑 `alembic check` 检查模型漂移；迁移时加 advisory lock 防止并发；就绪检查校验迁移版本；生产由一次性 `migrate` 服务先执行，后端等成功后再启动。

**Q14：为什么测试用真实 PostgreSQL，不用 mock？**

迁移、JSONB、唯一索引、pgvector、检查点这些行为 mock 不出来；用真实数据库能验证迁移和 SQL 是否正确。代价是测试环境依赖数据库，CI 用 service 容器解决。

**Q15：如果继续演进，你会做什么？**

画布节点继续对齐 coze 能力（更多节点类型与交互）；复杂检索链路的可观测性加强；热点配置缓存与限流策略细化；长任务与事件通知继续异步化；完善指标看板和告警。注意区分“已实现”和“规划中”，面试时不要夸大。

### 13.8 面试时打开哪些文件

| 想讲的内容 | 打开 |
| --- | --- |
| 应用装配、中间件顺序 | `backend/web/app.py` |
| 登录、刷新、撤销 | `backend/internal/application/auth_service.py`、`backend/internal/infrastructure/security/tokens.py` |
| 鉴权与 RBAC | `backend/web/deps/auth.py`、`backend/web/admin/router.py` |
| 应用与画布写入 | `backend/web/admin/routers/apps_admin.py`、`backend/internal/application/apps/application_service.py` |
| 画布模型与转换 | `backend/internal/domain/canvas/node_meta.py`、`backend/internal/domain/canvas/convert.py` |
| 图运行时与检查点 | `backend/internal/domain/graph/runtime.py`、`backend/internal/domain/graph/checkpoint.py` |
| 对话与工作流运行 | `backend/internal/application/apps/chat_service.py`、`backend/web/deps/graph.py` |
| RAG 链路 | `backend/internal/application/retrieval_service.py`、`backend/internal/domain/retrieval/` |
| 工具治理 | `backend/internal/domain/agent/tool_gateway.py`、`backend/internal/domain/agent/tool_executor.py`、`backend/internal/infrastructure/security/ssrf_guard.py` |
| 多租户作用域解析与租户管理 | `backend/web/deps/tenant.py`、`backend/internal/application/tenant_service.py`、`backend/migrations/versions/0004_multi_tenant.py` |
| 事务与仓储 | `backend/internal/infrastructure/model/uow.py`、`backend/internal/infrastructure/repository/` |
| 迁移与就绪检查 | `backend/migrations/env.py`、`backend/web/health.py` |
| 前端无感刷新 | `frontend/admin/src/api/client.ts`、`frontend/admin/src/auth/AuthContext.tsx` |
| 生产反代与限流 | `frontend/admin/nginx/default.conf`、`frontend/user/nginx/default.conf` |
| 生产编排与容器安全 | `ops/docker-compose.yml`、`backend/Dockerfile` |

### 13.9 面试演示建议

1. 提前启动好数据库、Redis、后端、Celery worker 和管理端，避免现场等依赖安装。
2. 演示路径：登录 → 首次改密 → 创建应用 → 画布拖入 LLM / HTTP / 知识检索节点 → 调试运行看 SSE → 发布版本 → 市场开通给租户 → 查看运行历史与审计日志。
3. 准备一个 viewer 账号，演示写接口返回 403。
4. 打开 `/docs` 展示 OpenAPI，再打开日志展示 `request_id`。
5. 如果允许看代码，按 13.8 的顺序讲 2–3 个点即可，不要试图讲完所有文件。

---

