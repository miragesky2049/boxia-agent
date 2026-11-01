> 返回 [项目手册](../README.md)

## 5. 目录结构与代码分层

### 5.1 目录树

```text
boxia-agent/
├── backend/                     # 后端（Python 3.12）
│   ├── web/                     # HTTP 层：路由、请求/响应模型、异常处理
│   │   ├── app.py               # 应用工厂：按站点装配共享基础设施与路由
│   │   ├── app_admin.py         # 管理端入口：仅装配 admin 路由
│   │   ├── app_user.py          # 用户端入口：仅装配 user 路由
│   │   ├── api_v1.py            # admin / user 两套独立的 /api/v1 路由聚合
│   │   ├── admin/
│   │   │   ├── router.py        # 受保护路由聚合（统一前缀与管理员鉴权）
│   │   │   ├── routers/         # 接口：apps_admin / marketplace / resources / tools /
│   │   │   │                    #       documents / models / roles / users / tenants /
│   │   │   │                    #       departments / employments / mgmt_units / applies ...
│   │   │   └── schemas/         # 请求/响应模型
│   │   ├── user/                # 用户端站点：agents（应用）/ chat / auth / profile
│   │   └── deps/                # 数据库、服务、鉴权、租户作用域、SSE 依赖
│   ├── internal/
│   │   ├── domain/              # 领域层（纯业务，不依赖框架）
│   │   │   ├── entity/          # 实体：application / resource / role / user / tenant / department ...
│   │   │   ├── repository/      # 仓储协议
│   │   │   ├── agent/           # Agent Loop：plan/execute/reflect、工具执行、MCP client、tool_gateway
│   │   │   ├── canvas/          # 画布 DSL：node_type / node_meta / 转换 / 校验 / 表达式
│   │   │   ├── graph/           # 图运行时：compiler / runtime / checkpoint / state / nodes/*
│   │   │   ├── llm/             # LLM 适配层：client / adapter / messages
│   │   │   ├── retrieval/       # RAG：embedding / vector_store / rerank / query_rewrite / text_split
│   │   │   └── storage/         # 对象存储抽象
│   │   ├── application/         # 用例服务（编排）
│   │   │   ├── apps/            # application_service / chat_service / resource_service /
│   │   │   │                    # model_service / tenant_settings_service / prompt_optimize_service
│   │   │   └── ...              # auth / role / tenant / user / department / employment / grant ...
│   │   └── infrastructure/      # 配置、ORM、仓储实现、安全、日志、中间件、链路追踪、Celery
│   ├── docker/                  # 本地 PostgreSQL / Redis 编排
│   ├── migrations/              # Alembic 迁移（当前 head：0048_document_permissions）
│   ├── scripts/                 # create_admin / seed_demo / wait_for_db
│   ├── tests/                   # 后端接口与运行时测试
│   └── Dockerfile
├── frontend/
│   ├── admin/                   # 管理端（端口 5173）
│   │   ├── src/                 # api / auth / tenant / components / layouts / pages / router
│   │   │   └── pages/apps/      # 应用列表、画布、节点配置、运行历史、资源、市场
│   │   ├── e2e/                 # Playwright 端到端用例
│   │   ├── nginx/               # 生产 Nginx 配置（SPA、反代、限流、安全头）
│   │   └── Dockerfile
│   ├── user/                    # 用户端门户（端口 5174，含 nginx / Dockerfile）
│   └── scripts/                 # 前端启停脚本（admin / user / all）
├── ops/                         # 跨端运维入口
│   ├── docker-compose.yml       # 多环境编排：db / migrate / backend-admin / backend-user / frontend
│   ├── dev.sh                   # 本地启动（admin / user / all）
│   ├── check.sh                 # 本地质量门禁（与 CI 基本一致）
│   ├── backup.sh                # 数据库备份
│   └── restore.sh               # 数据库恢复（二次确认）
├── .github/workflows/           # CI 与镜像发布
├── .pre-commit-config.yaml      # 提交前自动检查
└── README.md
```

### 5.2 根目录文件为什么这样放

| 路径                      | 用途                             | 为什么在根目录                    |
|---------------------------|----------------------------------|-----------------------------------|
| `backend/`、`frontend/`   | 两个可独立构建的应用             | 按端拆分，互不依赖                |
| `ops/`                    | 跨端的开发、检查、部署、备份脚本 | 不属于任何一个端                  |
| `.github/workflows/`      | CI 与镜像发布                    | GitHub 固定读取这个路径           |
| `.pre-commit-config.yaml` | 提交前质量钩子                   | pre-commit 默认只从仓库根目录读取 |

### 5.3 代码分层约定

1. **Web 层只做“翻译”**：参数校验、协议转换，不写业务规则。
2. **业务规则在 `internal/application`**：用例服务负责编排；应用相关的用例集中在 `internal/application/apps/`。
3. **领域能力在 `internal/domain`**：画布解析、图运行时、Agent Loop、LLM 适配、RAG 检索都在领域层，可脱离 FastAPI 单测。
4. **数据库操作在 `internal/infrastructure/repository`**：仓储只负责读写。
5. **事务统一提交**：仓储内部只 `flush()`，应用服务在用例结束时统一 `commit()`；审计日志和业务数据在同一个事务里。
6. **新增管理端接口默认受保护**：`web/admin/router.py` 统一挂载管理员鉴权，再按 `page:*` / `button:*` / `tool:*` / `document:*` 收窄。

### 5.4 想改某个功能，应该动哪里

| 需求                 | 通常要改的文件                                                                                                                                                                 |
|----------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 新增一个管理端接口   | `backend/web/admin/routers/xxx.py`（路由）+ `backend/web/admin/schemas/xxx.py`（模型）→ `backend/internal/application/xxx_service.py`（业务）→ 仓储实现 |
| 调整画布节点类型     | `backend/internal/domain/canvas/node_type.py`（编码）+ `node_meta.py`（元数据）+ `internal/domain/graph/nodes/*`（运行实现）                                                     |
| 调整图执行           | `backend/internal/domain/graph/compiler.py`、`runtime.py`、`state.py`、`checkpoint.py`                                                                                          |
| 调整 Agent Loop      | `backend/internal/domain/agent/loop.py`、`tools.py`、`tool_executor.py`、`tool_gateway.py`                                                                                      |
| 调整 RAG             | `backend/internal/domain/retrieval/*` + `backend/internal/application/ingestion_service.py`                                                                                     |
| 新增一张表           | `backend/internal/infrastructure/model/xxx.py`（ORM）→ `backend/internal/domain/entity/xxx.py`（实体）→ 生成 Alembic 迁移                                                        |
| 新增一个管理端页面   | `frontend/admin/src/pages/`（页面）→ `frontend/admin/src/router.tsx`（路由）→ `frontend/admin/src/api/`（接口封装）                                                              |
| 调整权限             | `backend/internal/domain/entity/permission.py`（权限目录）、`backend/web/deps/auth.py`、前端 `RequirePermission`                                                               |
| 调整租户识别与隔离   | `backend/web/deps/tenant.py`、仓储的租户过滤、`backend/tests/test_tenants.py`                                                                                                   |
| 调整登录/令牌逻辑    | `backend/internal/application/auth_service.py`、`backend/internal/infrastructure/security/tokens.py`、前端 `src/api/client.ts`                                                  |
| 调整数据库结构       | 修改 ORM 模型 → `uv run alembic revision --autogenerate -m "说明"` → 检查生成的迁移 → `uv run alembic upgrade head`                                                              |

---

## 6. 配置说明

### 6.1 配置文件从哪来

- 本地开发：复制 `backend/.env.example` 为 `backend/.env` 后修改。
- 部署：在 `ops/` 下新建 `.env.prod`（开发/测试环境分别新建 `.env.dev`、`.env.test`），按 14.3 的清单填写。

真实配置文件都已被 `.gitignore` 忽略，不会进入 Git。第一次使用先确认必填项，其余变量都有默认值，可以等需要时再调整：

| 配置文件 | 必填项 |
|----------|--------|
| `backend/.env`（本地） | `DATABASE_URL`、`JWT_SECRET`；`ROOT_DOMAIN` 设为 `localhost` 或留空（自动回退）；跑对话需 `LLM_API_KEY`，跑知识库需 `EMBEDDING_API_KEY` |
| `ops/.env.*`（部署） | `POSTGRES_PASSWORD`、`DATABASE_URL`（账号密码库名与 `POSTGRES_*` 一致）、`JWT_SECRET`、`ROOT_DOMAIN` |

### 6.2 变量一览

| 变量                          | 默认值              | 必填     | 说明                                                                                                                                                  |
|-------------------------------|---------------------|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| `APP_ENV`                     | `local`             | 否       | `local`（本机调试）/ `dev` / `test` / `prod`                                                                                                          |
| `APP_NAME`                    | `boxia-agent`       | 否       | 服务名，出现在根路径响应和日志中                                                                                                                      |
| `APP_VERSION`                 | `1.0.0`             | 否       | 服务版本，出现在根路径响应中                                                                                                                          |
| `DATABASE_URL`                | 无                  | 是       | 形如 `postgresql+psycopg://user:pass@host:5432/db`                                                                                                    |
| `DATABASE_POOL_SIZE`          | `10`                | 否       | 连接池大小                                                                                                                                            |
| `DATABASE_MAX_OVERFLOW`       | `10`                | 否       | 池溢出连接数                                                                                                                                          |
| `DATABASE_POOL_TIMEOUT`       | `10`                | 否       | 获取连接超时（秒）                                                                                                                                    |
| `DATABASE_POOL_RECYCLE`       | `1800`              | 否       | 连接回收周期（秒）                                                                                                                                    |
| `STATEMENT_TIMEOUT_MS`        | `5000`              | 否       | 单条 SQL 超时                                                                                                                                         |
| `LOCK_TIMEOUT_MS`             | `3000`              | 否       | 锁等待超时                                                                                                                                            |
| `JWT_SECRET`                  | 无                  | 是       | 签名密钥；生产需至少 32 字符且不能是示例值（`openssl rand -hex 32`）                                                                                  |
| `JWT_ALGORITHM`               | `HS256`             | 否       | 签名算法，除迁移场景外不建议修改                                                                                                                      |
| `JWT_ISSUER`                  | `boxia-agent`       | 否       | 令牌签发方，会写入并校验 `iss`                                                                                                                        |
| `JWT_AUDIENCE`                | `boxia-admin`       | 否       | 管理端令牌受众，会写入并校验 `aud`                                                                                                                    |
| `USER_JWT_AUDIENCE`           | `boxia-user`        | 否       | 用户端令牌受众；与管理端隔离，两端令牌不能互相冒用                                                                                                    |
| `ACCESS_TOKEN_MINUTES`        | `30`                | 否       | 访问令牌有效期                                                                                                                                        |
| `REFRESH_TOKEN_DAYS`          | `14`                | 否       | 刷新令牌有效期                                                                                                                                        |
| `BCRYPT_ROUNDS`               | `12`                | 否       | 密码哈希成本因子                                                                                                                                      |
| `LOGIN_MAX_ATTEMPTS`          | `5`                 | 否       | 连续失败几次后锁定                                                                                                                                    |
| `LOGIN_LOCK_MINUTES`          | `15`                | 否       | 锁定时长（分钟）                                                                                                                                      |
| `PASSWORD_MIN_LENGTH`         | `12`                | 否       | 密码最小长度（字符数，8-64；代码默认 12，`.env.example` 本地为 10）                                                                                    |
| `PASSWORD_MAX_BYTES`          | `72`                | 否       | 密码最大字节数（UTF-8，32-72）；bcrypt 只处理前 72 字节                                                                                               |
| `PASSWORD_MIN_CATEGORIES`     | `3`                 | 否       | 至少包含的字符类别数（1-4）                                                                                                                           |
| `ROOT_DOMAIN`                 | 空                  | 部署必填 | 每个环境独立的租户根域名，如 `dev.example.com` / `example.com`；`local` 设为 `localhost`（或留空自动回退）                                              |
| `PLATFORM_ADMIN_SUBDOMAIN`    | `adminsystem`       | 否       | 产品级平台子域名前缀，最终为 `adminsystem.<ROOT_DOMAIN>`                                                                                              |
| `PLATFORM_NAME`               | `AI智能体运营管理平台` | 否    | 管理端展示的平台名称                                                                                                                                  |
| `DEFAULT_TENANT_CODE`         | 空                  | 否       | 访问根域名时默认进入的租户；留空则拒绝根域名访问                                                                                                      |
| `ALLOW_TENANT_HEADER`         | `false`             | 否       | 是否允许 `X-Tenant-Code` 请求头识别租户；**仅 `local` 有效**                                                                                          |
| `CORS_ORIGINS`                | 空                  | 否       | 逗号分隔的允许来源；生产禁止 `*`                                                                                                                      |
| `DOCS_ENABLED`                | 生产关闭            | 否       | 是否暴露 Swagger 文档                                                                                                                                 |
| `LEGACY_API_ENABLED`          | `true`              | 否       | 是否保留 `/api` 兼容别名                                                                                                                              |
| `LOG_LEVEL`                   | `INFO`              | 否       | 日志级别                                                                                                                                              |
| `LOG_JSON`                    | 生产默认 `true`     | 否       | 是否输出 JSON 日志                                                                                                                                    |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 空                  | 否       | 链路数据上报地址，不配则不上报                                                                                                                        |
| `OTEL_SERVICE_NAME`           | `boxia-agent`       | 否       | 链路服务名                                                                                                                                            |
| `OTEL_TRACES_SAMPLER_RATIO`   | `1.0`               | 否       | 链路采样率                                                                                                                                            |
| `WEB_CONCURRENCY`             | `2`（镜像）         | 否       | 后端 worker 数                                                                                                                                        |
| `LLM_API_KEY`                 | 无                  | 对话必填 | LLM 服务 API Key（OpenAI 兼容协议）                                                                                                                   |
| `LLM_BASE_URL`                | `https://api.deepseek.com` | 否 | LLM 端点                                                                                                                                              |
| `LLM_MODEL_ID`                | `deepseek-v4-flash` | 对话必填 | 默认 LLM 模型 ID（未配置租户默认模型时使用）                                                                                                           |
| `LLM_TEMPERATURE`             | `0.7`               | 否       | 默认采样温度                                                                                                                                          |
| `LLM_MAX_TOKENS`              | `1024`              | 否       | 单次补全最大 token                                                                                                                                    |
| `LLM_MAX_ITERATIONS`          | `6`                 | 否       | 单次运行最大工具调用轮次，防止失控循环                                                                                                                |
| `LLM_TIMEOUT_SECONDS`         | `60`                | 否       | LLM HTTP 超时                                                                                                                                         |
| `REDIS_URL`                   | `redis://127.0.0.1:6379/0` | 否 | 短期记忆（多轮对话历史）Redis DB 0                                                                                                                    |
| `MEMORY_MAX_TURNS`            | `20`                | 否       | 单会话最多保留的 user+assistant 轮数，超出从头部裁剪                                                                                                  |
| `MEMORY_TTL_SECONDS`          | `1800`              | 否       | 会话空闲过期时间（秒）                                                                                                                                |
| `EMBEDDING_API_KEY`           | 无                  | RAG 必填 | Embedding / Rerank 服务 API Key                                                                                                                       |
| `EMBEDDING_BASE_URL`          | `https://api.siliconflow.cn/v1` | 否 | Embedding / Rerank 服务端点                                                                                                                           |
| `EMBEDDING_MODEL`             | `BAAI/bge-large-zh-v1.5` | 否  | 向量模型（1024 维，最大输入 512 tokens）                                                                                                              |
| `EMBEDDING_DIMENSIONS`        | `1024`              | 否       | 向量维度，必须与数据库列维度一致                                                                                                                      |
| `EMBEDDING_TIMEOUT_SECONDS`   | `30`                | 否       | Embedding / Rerank HTTP 超时                                                                                                                          |
| `VECTOR_STORE_PROVIDER`       | `pgvector`          | 否       | 向量库实现：`pgvector` / `milvus`                                                                                                                     |
| `MILVUS_URI` / `MILVUS_TOKEN` | 空                  | 否       | 使用 Milvus 时的连接地址与令牌                                                                                                                        |
| `RAG_CHUNK_SIZE`              | `500`               | 否       | 文档分块字符数（受 bge 512 tokens 输入限制，勿超 600）                                                                                                  |
| `RAG_CHUNK_OVERLAP`           | `80`                | 否       | 分块重叠字符数                                                                                                                                        |
| `RAG_TOP_K`                   | `5`                 | 否       | 最终返回给 prompt 的 chunk 数                                                                                                                         |
| `RAG_SIMILARITY_THRESHOLD`    | `0.55`              | 否       | 向量余弦阈值（rerank 关闭时使用）                                                                                                                      |
| `RAG_RERANK_ENABLED`          | `true`              | 否       | 是否启用 Cross-Encoder 精排                                                                                                                           |
| `RAG_RERANK_MODEL`            | `BAAI/bge-reranker-v2-m3` | 否 | Rerank 模型                                                                                                                                           |
| `RAG_RERANK_TOP_N`            | `5`                 | 否       | Rerank 返回的候选数                                                                                                                                    |
| `RAG_RECALL_MULTIPLIER`       | `10`                | 否       | 向量召回倍数（粗排候选 = top_k × multiplier）                                                                                                         |
| `RAG_QUERY_REWRITE_ENABLED`   | `true`              | 否       | 是否启用 LLM query 改写                                                                                                                               |
| `RAG_QUERY_REWRITE_VARIANTS`  | `3`                 | 否       | 每次改写生成的同义变体数（1-5）                                                                                                                       |
| `CELERY_BROKER_URL`           | `redis://127.0.0.1:6379/1` | 否 | Celery broker（Redis DB 1）                                                                                                                           |
| `CELERY_RESULT_BACKEND`       | `redis://127.0.0.1:6379/2` | 否 | Celery 结果后端（Redis DB 2）                                                                                                                         |
| `OBJECT_STORAGE_ENDPOINT`     | 空                  | 否       | S3 兼容对象存储地址；不配则使用本地存储                                                                                                               |
| `OBJECT_STORAGE_ACCESS_KEY` / `OBJECT_STORAGE_SECRET_KEY` | 空 | 否 | 对象存储凭据                                                                                                                                          |
| `OBJECT_STORAGE_BUCKET`       | 空                  | 否       | 对象存储桶名                                                                                                                                          |
| `OBJECT_STORAGE_SECURE`       | `true`              | 否       | 是否使用 HTTPS 访问对象存储                                                                                                                           |
| `ADMIN_AUTO_INIT`             | `false`             | 否       | 部署时是否自动初始化首个平台管理员（仅 admin 站点启动时生效）                                                                                          |
| `ADMIN_INITIAL_USERNAME`      | `admin`             | 否       | 自动初始化的平台管理员用户名                                                                                                                          |
| `ADMIN_INITIAL_DISPLAY_NAME`  | `系统管理员`        | 否       | 自动初始化的平台管理员显示名                                                                                                                          |
| `ADMIN_INITIAL_PASSWORD`      | 空                  | 否       | 自动初始化的平台管理员密码；为空时跳过初始化                                                                                                          |
| `ADMIN_INITIAL_ROLE`          | `superadmin`        | 否       | 自动初始化的平台角色编码                                                                                                                              |
| `ADMIN_INITIAL_MUST_CHANGE_PASSWORD` | `true`      | 否       | 首次登录是否强制改密                                                                                                                                  |

> 本地开发直接使用 `.env.example` 即可；`JWT_SECRET` 此时只是开发占位值，**生产必须换成随机值**。

以下变量只在部署配置（`ops/.env.*`，需自行创建）中使用，本地 `backend/.env` 不需要：

| 变量                                                       | 默认值               | 说明                                                         |
|------------------------------------------------------------|----------------------|--------------------------------------------------------------|
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD`      | 示例 `boxia` / `boxia` | 初始化数据库容器；密码必须与 `DATABASE_URL` 中的完全一致     |
| `HTTP_PORT`                                                | `80`                 | 管理端前端容器映射到宿主机的端口                             |
| `USER_HTTP_PORT`                                           | `8081`               | 用户端前端容器映射到宿主机的端口                             |
| `PYTHON_IMAGE` / `NODE_IMAGE` / `NGINX_IMAGE`              | 官方镜像             | 构建阶段的基础镜像，国内网络受限时可替换，见 14.7            |

> `ENV_FILE`、`HTTP_PORT`、`USER_HTTP_PORT`、`WEB_CONCURRENCY` 和上述镜像变量由 Compose 在启动时插值读取，**不会**从 `env_file` 注入容器，因此启动时需用 `--env-file` 或导出到当前 shell，见 14.4。

### 6.3 环境启动校验

后端启动前会按 `APP_ENV` 检查多租户配置，不合格直接拒绝启动：

- 所有环境：`PLATFORM_ADMIN_SUBDOMAIN` 必须是一级域名标签（字母、数字、连字符）。
- `dev` / `test` / `prod`：必须配置 `ROOT_DOMAIN`，且不能是 `localhost`、`*.localhost` 或 IP 地址；禁止开启 `ALLOW_TENANT_HEADER`。
- `prod` 额外要求：`JWT_SECRET` 至少 32 字符且不能是示例占位值；`CORS_ORIGINS` 不允许 `*`。

这些检查是为了避免“复制示例配置直接上线”或漏配域名时把请求放进最高权限的产品级平台。

### 6.4 多租户域名与使用方式

**作用域判定**

| 访问地址                  | 作用域      | 能力                                                                 |
|---------------------------|-------------|----------------------------------------------------------------------|
| `adminsystem.example.com` | 产品级平台  | 跨租户管理、创建/停用租户、维护产品级应用、资源、模型与授权           |
| `acme.example.com`        | 租户 `acme` | 维护本租户账号、角色、组织架构；浏览市场并开通应用；只读使用平台资源  |
| `example.com`             | 根域名      | 配置了 `DEFAULT_TENANT_CODE` 则进入该租户，否则返回 404              |

**域名是作用域的唯一事实来源。** 部署环境必须配置 `ROOT_DOMAIN`，只能通过二级域名访问；部署环境中的 `localhost`、回环地址、未知域名与多级子域名一律返回 404。`X-Tenant-Code` 请求头与 `?tenant=` 参数只在 `local` 环境、且 `ALLOW_TENANT_HEADER=true` 时生效，并且只在回环/本机主机上生效。

本地不配置 `ROOT_DOMAIN` 时自动回退 `localhost`，因此可以直接验证真实子域名：

| 本地访问地址                              | 作用域                   | 解析方式                       |
|-------------------------------------------|--------------------------|--------------------------------|
| `http://localhost:5173`                   | 产品级平台（无请求头时） | 默认兜底 `resolution=default`  |
| `http://localhost:5173/login?tenant=acme` | 租户 `acme`              | 请求头模式 `resolution=header` |
| `http://adminsystem.localhost:5173`       | 产品级平台               | 域名 `resolution=host`         |
| `http://acme.localhost:5173`              | 租户 `acme`              | 域名 `resolution=host`         |

**多环境策略**

| 环境         | `APP_ENV`     | 根域名                      | 平台地址                       | 租户地址                | 租户切换方式                                  |
|--------------|---------------|-----------------------------|--------------------------------|-------------------------|-----------------------------------------------|
| 本地调试     | `local`       | 可留空（回退 `localhost`）  | `adminsystem.localhost:5173`   | `acme.localhost:5173`   | 回环主机走请求头/`?tenant=`；子域名按域名跳转 |
| 开发环境部署 | `dev`         | 必填，如 `dev.example.com`  | `adminsystem.dev.example.com`  | `acme.dev.example.com`  | 仅二级域名                                    |
| 测试环境部署 | `test`        | 必填，如 `test.example.com` | `adminsystem.test.example.com` | `acme.test.example.com` | 仅二级域名                                    |
| 线上环境     | `prod`        | 必填，如 `example.com`      | `adminsystem.example.com`      | `acme.example.com`      | 仅二级域名                                    |

`/public/context` 与 `/admin/context` 会返回 `app_env`、`tenant_resolution`、`tenant_switch_mode` 与 `platform_admin_host`，登录页和管理端侧边栏会展示环境与解析来源，便于排查“为什么进了错误租户”。

**数据隔离规则**

- 业务表统一带 `tenant_id`：产品级统一使用全零 UUID（`PLATFORM_TENANT_ID`），租户使用真实租户 ID；仓储过滤为 `tenant_id IN (当前租户, PLATFORM_TENANT_ID)`。
- 应用通过 `tenant_application_instance` 开通：未开通的租户看不到该应用；开通时可钉住图版本、配置配额与有效期。
- 工具资源通过 `resource_grant` 授权给租户；应用与工具授权都只在授权作用域内生效。
- 用户的数据范围由角色 + 管理单元（`user_mgmt_unit_grants`）决定；应用还支持按部门（含子树）/指定人员配置实例级可见范围。
- 登录、刷新与访问令牌都绑定作用域，跨作用域使用直接返回 401。
- 同一作用域内资源名称唯一，不同租户之间允许同名。

**创建并使用租户**

1. 用产品级账号登录 `adminsystem.example.com`，进入「租户管理」新建租户。
2. 租户编码即子域名前缀（如 `acme` → `acme.example.com`），创建后不可修改。
3. 新建时填写的租户管理员账号首次登录会强制改密；该账号只能登录本租户子域名。
4. 停用租户后，该子域名下的登录与已登录会话都会立即被拒绝。
5. 租户管理员到「应用市场」浏览并开通产品级应用，开通后在「我的应用」中使用。

---

## 7. 登录、权限与安全

### 7.1 两种令牌，通俗理解

登录成功后服务器返回两个令牌：

- **Access Token（访问令牌）**：短期的“临时通行证”，默认 30 分钟。前端只放在内存里，刷新页面后会用 Refresh Token 重新换取，不需要重新登录。
- **Refresh Token（刷新令牌）**：长期的“续期凭证”，默认 14 天。数据库只保存它的哈希值，不保存明文。

安全机制：

- 刷新令牌**用过一次就作废**，同时发一个新的（单次轮换）。
- 如果旧的刷新令牌被再次使用，系统会认为可能被盗用，撤销整条会话链，要求重新登录。
- 登出、改密、禁用或删除账号时，该账号已有令牌立即失效。
- 令牌绑定作用域：Access Token 里的 `tid` 必须与账号归属、当前子域名一致，跨作用域访问会被拒绝。
- 管理端与用户端令牌使用不同 `aud`，不能互相冒用。
- 前端多标签页之间会同步登录和登出状态。

### 7.2 登录保护

- 不存在的用户名也会执行一次密码校验，防止攻击者通过响应速度判断用户名是否存在。
- 连续 5 次密码错误锁定 15 分钟，返回 `429` 和 `Retry-After`。
- 登录成功后失败次数清零。
- Nginx 在生产环境对登录接口限流（`10 次/分钟`），普通接口 `30 次/秒`。

### 7.3 权限（RBAC）

权限分两层：

- **功能权限**：角色与全局权限目录（`permission_resources`）通过 `role_permissions` 建立多对多关系，决定能否看到菜单/页面/按钮，以及能否对工具与文档做增删改查。
- **数据权限**：`tenant_application_instance`（应用开通实例）+ `resource_grant`（工具等资源授权）+ 管理单元（`user_mgmt_unit_grants`）共同决定能看到哪些应用、工具与数据范围。

权限目录随迁移预置、只读维护，分类为：

| 类别 | 作用 | 示例 |
| --- | --- | --- |
| `system` | 管理端入口与全量数据范围 | `system:console:access`、`system:data:all` |
| `menu` | 左侧菜单可见性 | `menu:apps`、`menu:marketplace`、`menu:resources` |
| `page` | 页面与对应接口访问 | `page:apps`、`page:tools`、`page:resources` |
| `button` | 页面操作按钮 | `button:app:create`、`button:tool:create`、`button:role:grant` |
| `tool` | 工具与知识库文档读写（`document:*` 归入该类别） | `tool:create` / `tool:read` / `tool:update` / `tool:delete`；`document:create` / `document:read` / `document:update` / `document:delete` |

约束与规则：

- 每次请求都以数据库中的实时角色、权限与账号状态为准（`AdminPrincipal.permissions` 每次重建），不信任令牌里的旧角色信息。
- `system:console:access` 控制管理端登录；`system:data:all` 跳过数据授权过滤，但仍受租户隔离约束。
- 超级管理员角色拥有所属作用域全部权限，功能权限与数据授权均不可单独调整。
- 平台角色不能授予租户专属菜单与按钮（`menu:grants`、`menu:users`、`menu:departments`、`menu:employments`、`menu:mgmt-units` 等）；租户角色不能授予平台级租户管理权限（`menu:tenants` 等）。
- 授权只允许授予调用者已拥有的权限，复制角色同样校验；写入时对角色行加锁，避免并发授权互相覆盖。
- 前端隐藏菜单和按钮只是体验优化，所有接口都以服务端权限校验为准，不满足返回 403。

**应用与资源的可见性**：

- 应用必须存在 `tenant_application_instance` 开通记录，租户内用户才能看到；应用还支持 `application_visibility_departments` / `application_visibility_users` 做部门（含子树）与指定人员收窄。
- 工具等资源通过 `resource_grant` 授权到租户；未授权的租户不可见。
- 用户可见的应用范围 = 开通实例 ∩ 角色/管理单元数据范围 ∩ 应用实例可见范围 ∩ `is_enabled=true`。
- 未授权对象在详情与写操作中统一返回 404，避免泄露资源是否存在。
- 用户授权页按用户维护角色与管理单元，可批量操作（单次最多 200 个用户）。

### 7.4 审计日志

以下操作会写入 `audit_logs`（动作编码以代码实际写入为准）：

| 类别                 | action 示例                                                                                          |
|----------------------|------------------------------------------------------------------------------------------------------|
| 认证                 | `auth.login`、`auth.login_failed`、`auth.refresh_replay`、`auth.logout`、`auth.password_changed`     |
| 管理员               | `admin_user.created`、`admin_user.updated`、`admin_user.deleted`、`admin_user.password_reset`        |
| 租户（仅产品级平台） | `tenant.created`、`tenant.updated`                                                                   |
| 角色与用户           | `role.created`、`role.updated`、`role.copied`、`role.deleted`、`user.created`、`user.updated`、`user.roles_granted`、`user.deleted`、`user.password_reset` |
| 组织架构             | `department.created/updated/deleted/activated/disabled`、`employment.created/updated/transferred/archived/deleted`、`mgmt_unit.created/updated/deleted/departments_replaced/users_replaced` |
| 授权与资源           | `grant.updated`                                                                                      |
| 用户端认证           | `user_auth.login`、`user_auth.login_failed`、`user_auth.refresh_replay`、`user_auth.logout`          |

每条记录包含操作者、动作、资源、`request_id`、IP、User-Agent、作用域（`tenant_id`）和详情。租户账号的审计只在租户内可见，平台账号可以查看全部。

### 7.5 密码与密钥安全约定

- 仓库**不包含任何默认账号或默认密码**，第一个管理员必须手动创建。
- `backend/.env`、`ops/.env.*` 不进入 Git；仓库只保留 `backend/.env.example` 模板。
- 生产环境的示例 `JWT_SECRET` 会被校验拒绝，必须换成随机值（`openssl rand -hex 32`）。
- CI 中的 E2E 测试密码在运行时随机生成，不写死在仓库里。
- `backend/tests/`、`frontend/admin/e2e/` 里的固定口令只用于一次性测试数据库，不是真实凭据。

### 7.6 上线安全验收清单

- [ ] 弱口令被拒绝（长度、字符类别、常见口令、包含用户名）
- [ ] 连续 5 次登录失败触发 15 分钟锁定，返回 429 与 `Retry-After`
- [ ] Refresh Token 重放会撤销整条会话链
- [ ] 登出后 Access / Refresh Token 均立即失效
- [ ] 改密后所有旧会话失效
- [ ] 无对应 `button:*` / `tool:*` / `document:*` 权限的角色调用写接口返回 403
- [ ] `/admin/roles`、`/admin/users`、`/admin/admin-users`、`/admin/audit-logs` 仅授予对应 `page:*` 权限的角色可访问
- [ ] 角色授权不能授予调用者自身不具备的权限（越权授权返回 403）
- [ ] 未开通应用的租户访问详情与运行接口返回 404
- [ ] 错误响应不含堆栈，500 只返回通用文案
- [ ] 日志与审计不含密码、令牌等敏感信息
- [ ] 生产环境无默认账号，`JWT_SECRET` 不是示例值
- [ ] 响应包含安全头（nosniff、DENY、Referrer-Policy、CSP）
- [ ] 登录相关响应带 `Cache-Control: no-store`
- [ ] 后端、数据库端口未对外暴露，`/metrics` 外部不可访问
- [ ] 容器以非 root 运行、根文件系统只读、`cap_drop: ALL`

---

## 8. 接口手册

### 8.1 基本约定

- 统一前缀：`/api/v1`
- 兼容别名：`LEGACY_API_ENABLED=true` 时同时注册 `/api`（不进入文档）
- 两个站点独立部署、独立路由：
  - 管理端站点（`web.app_admin:app`）：`/api/v1/admin/**`、`/api/v1/public/**`
  - 用户端站点（`web.app_user:app`）：`/api/v1/user/**`，必须通过租户子域名访问
- 除登录、刷新、`/public/*` 外，管理端接口都需要请求头：

```http
Authorization: Bearer <access_token>
```

### 8.2 认证接口

| 方法 | 路径                   | 说明                                        |
|------|------------------------|---------------------------------------------|
| POST | `/admin/auth/login`    | 登录，返回 access/refresh、有效期和用户信息 |
| POST | `/admin/auth/refresh`  | 用 refresh 换新令牌                         |
| POST | `/admin/auth/logout`   | 登出并撤销当前会话，返回 204                |
| POST | `/admin/auth/password` | 修改密码并撤销全部会话，返回 204            |
| GET  | `/admin/auth/me`       | 当前管理员信息（含角色）                    |
| GET  | `/admin/context`       | 当前登录账号的作用域、租户、权限与菜单      |

匿名接口（登录页使用）：

| 方法 | 路径              | 说明                                                    |
|------|-------------------|---------------------------------------------------------|
| GET  | `/public/context` | 按当前域名返回产品级/租户级模式与平台名称               |
| GET  | `/public/tenants` | 仅 `local` 环境返回可选租户列表；其他环境返回 403       |

`/public/context` 与 `/admin/context` 的关键字段：

| 字段                                                       | 说明                                                                      |
|------------------------------------------------------------|---------------------------------------------------------------------------|
| `scope`                                                    | `platform`（产品级）或 `tenant`（租户级）                                 |
| `tenant`                                                   | 当前租户信息；产品级为 `null`                                             |
| `app_env`                                                  | `local` / `dev` / `test` / `prod`                                         |
| `tenant_resolution`                                        | `host` / `header` / `default`                                             |
| `tenant_switch_mode`                                       | `none` / `header` / `host`                                                |
| `platform_admin_host`                                      | 产品级平台完整主机名                                                      |
| `root_domain`、`platform_admin_subdomain`、`platform_name` | 当前环境的根域名、平台子域名与展示名称                                    |
| `password_policy`                                          | 密码策略 `{min_length, max_bytes, min_categories}`                        |

`/admin/context` 额外返回 `role_code`、`role_name`、`permissions`（功能权限编码集合）与 `menus`（由 `menu:*` 推导的可见菜单键）。

### 8.3 应用管理接口（产品级平台）

`/admin/apps` 整组路由要求平台管理员（`require_platform_admin`），租户子域名调用返回 403。

| 方法   | 路径                                     | 说明                                                       |
|--------|------------------------------------------|------------------------------------------------------------|
| GET    | `/admin/apps`                            | 应用列表（平台视角）                                       |
| POST   | `/admin/apps`                            | 新建应用，返回 201                                         |
| GET    | `/admin/apps/{id}`                       | 应用详情                                                   |
| PATCH  | `/admin/apps/{id}`                       | 更新基础信息 / 启用状态 / 上下架                           |
| GET    | `/admin/apps/{id}/graph`                 | 读取草稿图 `{schema_json, graph_schema_version, runtime_mode}` |
| PUT    | `/admin/apps/{id}/graph`                 | 保存草稿图（整图覆盖）                                     |
| POST   | `/admin/apps/validate-graph`             | 校验图：环检测、Start/End 唯一性、变量类型，不落库          |
| GET    | `/admin/apps/{id}/graph-versions`        | 发布版本列表                                               |
| POST   | `/admin/apps/{id}/graph-rollback`        | 回滚到指定版本                                             |
| POST   | `/admin/apps/{id}/publish`               | 发布：严格校验通过后生成不可变图版本                       |
| POST   | `/admin/apps/{id}/graph-pin`             | 钉住字段/图版本                                            |
| POST   | `/admin/apps/{id}/listing`               | 上架 / 下架市场                                            |
| POST   | `/admin/apps/{id}/enabled`               | 启用 / 停用                                                |
| GET/PUT| `/admin/apps/{id}/visibility`            | 读取/替换实例级可见范围（部门含子树 / 指定人员）           |
| POST   | `/admin/apps/{id}/tenant-config`         | 写入租户级应用覆盖配置                                     |
| DELETE | `/admin/apps/{id}/tenant-config`         | 删除租户级覆盖配置                                         |
| POST   | `/admin/apps/debug/run/stream`           | SSE 整图调试运行（节点实时状态 + 日志）                    |
| POST   | `/admin/apps/debug/run/node`             | 单节点调试运行                                             |
| POST   | `/admin/apps/debug/run/stream/resume`    | 人工审批后续跑                                             |
| GET    | `/admin/apps/{id}/conversations`         | 调试会话列表                                               |
| GET    | `/admin/apps/conversations/{id}/messages`| 调试会话消息                                               |
| DELETE | `/admin/apps/conversations/{id}`         | 删除调试会话                                               |
| DELETE | `/admin/apps/conversations/{id}/messages/{message_id}` | 删除单条消息                                 |

`/admin/node-meta` 返回画布节点目录（类型编码、`type_key`、标题、颜色、分类、配置 Schema），前端据此渲染节点库与配置表单。

### 8.4 应用市场与运行接口（租户）

| 方法 | 路径                                                    | 说明                                                     |
|------|---------------------------------------------------------|----------------------------------------------------------|
| GET  | `/admin/marketplace/applications`                       | 浏览已上架应用（cursor 分页）                            |
| GET  | `/admin/marketplace/applications/{id}`                  | 市场应用详情 + 当前租户授权/申请状态                     |
| POST | `/admin/marketplace/subscribe`                          | 租户自助开通应用                                         |
| GET  | `/admin/marketplace/my-apps`                            | 当前租户已开通应用                                       |
| POST | `/admin/marketplace/applications/{id}/run`              | 运行应用，body 为 `{inputs}`                             |
| POST | `/admin/marketplace/applications/{id}/runs/{thread_id}/resume` | 人工审批恢复运行                                  |
| GET  | `/admin/marketplace/applications/{id}/runs`             | 运行历史                                                 |
| GET  | `/admin/marketplace/applications/{id}/inputs`           | 应用启动参数 Schema                                      |
| GET  | `/admin/marketplace/runs/{run_id}`                      | 运行详情（节点级状态/耗时/用量）                         |
| GET  | `/admin/marketplace/runs/{run_id}/checkpoints`          | checkpoint 列表（时间旅行）                              |
| POST | `/admin/marketplace/runs/{run_id}/fork`                 | 从 checkpoint fork 新运行                                |
| GET/POST | `/admin/marketplace/webhooks`                       | Webhook 列表 / 创建                                      |
| DELETE | `/admin/marketplace/webhooks/{id}`                    | 删除 Webhook                                             |

应用申请（销售/审批流）：

| 方法 | 路径                                  | 说明                     |
|------|---------------------------------------|--------------------------|
| POST | `/admin/applies`                      | 提交开通申请             |
| GET  | `/admin/applies/mine`                 | 我的申请                 |
| GET  | `/admin/applies/pass-pending`         | 待通过申请               |
| GET  | `/admin/applies/sales-mine`           | 我负责的销售申请         |
| POST | `/admin/applies/{id}/claim`           | 认领申请                 |
| POST | `/admin/applies/{id}/pass`            | 通过申请                 |
| POST | `/admin/applies/{id}/reject`          | 驳回申请                 |
| GET  | `/admin/applies/ops/pending`          | 运营待处理               |
| GET  | `/admin/applies/ops/dashboard`        | 运营看板                 |

### 8.5 资源管理接口

`resource` 统一承载 `tool` / `prompt` / `skill` / `knowledge` 四类资源。平台管理员维护并授权给租户：

| 方法   | 路径                                    | 说明                                             |
|--------|-----------------------------------------|--------------------------------------------------|
| GET    | `/admin/resources`                      | 资源列表，参数 `type`、`owner_type`               |
| POST   | `/admin/resources`                      | 创建资源，body 为 `{type, name, config, owner_type, owner_id?}` |
| GET    | `/admin/resources/{id}`                 | 资源详情                                         |
| PATCH  | `/admin/resources/{id}`                 | 更新名称 / 配置 / 启停 / 废弃标记                |
| DELETE | `/admin/resources/{id}`                 | 删除资源并同事务清理授权                         |
| POST   | `/admin/resources/{id}/grants`          | 授权给租户，body 为 `{tenant_id}`                |
| GET    | `/admin/resources/{id}/grants`          | 资源已授权租户列表                               |
| DELETE | `/admin/resources/{id}/grants/{tenant_id}` | 撤销租户授权                                  |
| GET    | `/admin/my-resources`                   | 租户浏览已授权给自己的资源                       |

### 8.6 工具与知识库接口

**工具管理**（权限 `tool:read` / `tool:create` / `tool:update` / `tool:delete`）：

| 方法   | 路径                              | 说明                                                                    |
|--------|-----------------------------------|-------------------------------------------------------------------------|
| GET    | `/admin/tools`                    | 工具列表                                                                |
| POST   | `/admin/tools`                    | 创建工具                                                                |
| POST   | `/admin/tools/pull-mcp-tools`     | 输入 `{server_url}`，SSRF 校验后调 MCP `list_tools`，返回候选（不落库）|
| POST   | `/admin/tools/import-mcp-tools`   | 批量入库 MCP 工具                                                       |
| POST   | `/admin/tools/parse-curl`         | 解析 curl 为 `{method, url, headers, body, notes}`                      |
| GET    | `/admin/tools/{id}`               | 工具详情                                                                |
| PUT    | `/admin/tools/{id}`               | 更新工具                                                                |
| DELETE | `/admin/tools/{id}`               | 删除工具                                                                |
| POST   | `/admin/tools/{id}/test-invoke`   | 试调用，返回 `{success, duration_ms, output, error}`（不落库）          |

所有出站 URL 强制经过 `ssrf_guard.validate_outbound_url()`：拒绝 loopback / 云元数据（169.254.169.254）/ 链路本地 / 组播 / 保留地址；允许 RFC1918 私网（租户内网 MCP 合法）。

**知识库文档**（权限 `document:*`；文档与租户绑定，可被 Dataset 节点引用）：

| 方法   | 路径                            | 说明                                                                 |
|--------|---------------------------------|----------------------------------------------------------------------|
| GET    | `/admin/documents`              | 分页列表，参数 `keyword`、`ingest_status`                            |
| POST   | `/admin/documents`              | 创建文档元数据，状态置为 `pending`                                   |
| GET    | `/admin/documents/{id}`         | 文档详情（含 `ingest_status` / `chunk_count` / `ingest_error`）      |
| DELETE | `/admin/documents/{id}`         | 删除文档及其全部分块                                                 |
| POST   | `/admin/documents/{id}/ingest`  | 触发异步 ingest，投递 Celery 队列 `rag`，立即返回                    |
| GET    | `/admin/documents/{id}/ingest`  | 查询 ingest 状态（前端轮询）                                         |

ingest 状态机：`pending → queued → processing → ready` 或 `failed`（可重新触发）。

**模型目录**（产品级平台）：

| 方法   | 路径                            | 说明                     |
|--------|---------------------------------|--------------------------|
| GET/POST | `/admin/models/providers`     | 模型供应商列表 / 新建    |
| PATCH/DELETE | `/admin/models/providers/{id}` | 更新 / 删除供应商  |
| GET    | `/admin/models/catalog`         | 模型目录                 |
| GET    | `/admin/models/catalog/available` | 当前可用模型           |
| POST   | `/admin/models/catalog`         | 新建模型                 |
| PATCH/DELETE | `/admin/models/catalog/{id}` | 更新 / 删除模型      |
| POST   | `/admin/prompt-optimize`        | 用 LLM 优化提示词        |

检索链路（用户端对话与 Dataset 节点共用，`apply_rag_to_prompt()`）：

```text
   用户 query + 最近历史
            │
            ▼
   ① LLM query 改写（指代消解 + N 个同义变体）
            │
            ▼
   ② Embedding（bge-large-zh）
            │
            ▼
   ③ 向量召回（pgvector / Milvus，top_k × recall_multiplier）
            │
            ▼
   ④ 按 (doc_id, chunk_idx) 去重合并
            │
            ▼
   ⑤ Cross-Encoder 精排（bge-reranker-v2-m3）
            │
            ▼
   ⑥ 阈值过滤后取 top_k
            │
            ▼
   ⑦ 按「[资料 N | 章节路径]」拼装注入 prompt
```

降级策略：rerank 失败退化为向量余弦过滤；query 改写失败退化为原始 query；embedding 临时故障由 Celery retry 兜底。

### 8.7 角色、用户、授权与租户接口

角色接口（平台管理平台角色，租户管理本租户角色；数据隔离）：

| 方法   | 路径                                | 说明                                                       |
|--------|-------------------------------------|------------------------------------------------------------|
| GET    | `/admin/roles`                      | 角色列表，参数 `include_inactive`（`page:roles`）           |
| POST   | `/admin/roles`                      | 创建角色（`button:role:create`）；新角色默认无功能权限      |
| GET    | `/admin/roles/{id}`                 | 角色详情                                                   |
| PATCH  | `/admin/roles/{id}`                 | 修改名称/描述/启停（`button:role:update`）                  |
| DELETE | `/admin/roles/{id}`                 | 删除角色（`button:role:delete`）；系统角色/被引用时拒绝      |
| POST   | `/admin/roles/{id}/copy`            | 复制角色与权限（`button:role:copy`）                        |
| GET    | `/admin/permissions`                | 当前作用域可授权的功能权限目录                              |
| GET/PUT/POST/DELETE | `/admin/roles/{id}/permissions[/{code}]` | 读取 / 替换 / 追加 / 移除功能权限（`button:role:grant`） |
| GET    | `/admin/roles/{id}/grants`          | 角色数据授权候选/已授权，参数 `resource_type`、`granted_only` |
| GET    | `/admin/roles/{id}/grants/summary`  | 各资源类型有效授权数量                                      |
| POST/PUT/DELETE | `/admin/roles/{id}/grants/{resource_type}[/{resource_id}]` | 追加 / 替换 / 移除数据授权 |

用户接口（租户作用域）：

| 方法   | 路径                         | 说明                                     |
|--------|------------------------------|------------------------------------------|
| GET    | `/admin/users`               | 分页查询，参数 `keyword`                 |
| POST   | `/admin/users`               | 创建用户并绑定 `role_ids`                |
| PATCH  | `/admin/users/{id}`          | 修改显示名、`role_ids`、启停             |
| POST   | `/admin/users/{id}/password` | 重置密码，返回 204                       |
| DELETE | `/admin/users/{id}`          | 删除用户，返回 204                       |

用户授权（角色 + 管理单元）：

| 方法 | 路径                          | 说明                                                   |
|------|-------------------------------|--------------------------------------------------------|
| GET  | `/admin/grants/overview`      | 分页查询可授权对象及授权汇总（`page:grants`）          |
| PUT  | `/admin/grants/batch`         | 批量授权，`mode` 取 `merge` / `replace` / `clear`      |
| POST | `/admin/grants/users`         | 按用户授权角色/管理单元（`button:grant:manage`）       |
| GET  | `/admin/grants`               | 查询授权记录                                           |
| PUT  | `/admin/grants`               | 整体替换单对象授权（幂等）                             |

管理员账号（`page:admin-users` + `button:admin-user:*`）：

| 方法   | 路径                               | 说明                     |
|--------|------------------------------------|--------------------------|
| GET    | `/admin/admin-users`               | 管理员列表               |
| POST   | `/admin/admin-users`               | 创建管理员               |
| PATCH  | `/admin/admin-users/{id}`          | 修改角色 / 显示名 / 启停 |
| DELETE | `/admin/admin-users/{id}`          | 删除管理员               |
| POST   | `/admin/admin-users/{id}/password` | 重置密码                 |

租户管理（`page:tenants` + `button:tenant:*`，仅产品级平台）：

| 方法  | 路径                          | 说明                                 |
|-------|-------------------------------|--------------------------------------|
| GET   | `/admin/tenants`              | 租户分页列表，支持 `keyword`         |
| POST  | `/admin/tenants`              | 创建租户并初始化租户管理员           |
| GET   | `/admin/tenants/{id}`         | 租户详情                             |
| PATCH | `/admin/tenants/{id}`         | 修改租户名称或启用状态               |
| GET   | `/admin/tenants/{id}/settings`| 读取租户运行时配置（默认模型/白名单）|
| PUT   | `/admin/tenants/{id}/settings`| 覆盖式写入租户运行时配置             |

组织架构：

| 方法   | 路径                                    | 说明                                   |
|--------|-----------------------------------------|----------------------------------------|
| GET/POST/PATCH/DELETE | `/admin/departments[/{id}]` | 部门树增删改查（`page:departments`）   |
| GET/POST/PATCH/DELETE | `/admin/employments[/{id}]` | 任职记录增删改查（`page:employments`） |
| GET     | `/admin/hr-dictionaries`               | 人力资源字典                           |
| GET/POST/PATCH/DELETE | `/admin/mgmt-units[/{id}]` | 管理单元增删改查（`page:mgmt-units`）  |
| GET/PUT | `/admin/mgmt-units/{id}/departments`   | 管理单元部门范围                       |
| GET/PUT | `/admin/mgmt-units/{id}/users`         | 管理单元人员范围                       |

审计：

| 方法   | 路径                 | 说明                                                   |
|--------|----------------------|--------------------------------------------------------|
| GET    | `/admin/audit-logs`  | 审计查询（按时间、用户、动作筛选，`page:audit`）        |
| DELETE | `/admin/audit-logs`  | 清空审计日志（`button:audit:clear`）                    |

### 8.8 运维端点

| 方法 | 路径            | 说明                                         |
|------|-----------------|----------------------------------------------|
| GET  | `/health/live`  | 进程是否存活                                 |
| GET  | `/health/ready` | 数据库连通且迁移版本与代码一致；失败返回 503 |
| GET  | `/metrics`      | Prometheus 指标；生产由 Nginx 拒绝外部访问   |

业务指标（带 `tenant` / `tool` / `model` 标签，`tenant` 用短码 `platform` 或前 8 位 UUID）：

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `boxia_http_request_duration_seconds` | Histogram | 每个 HTTP 接口耗时 |
| `boxia_llm_request_duration_seconds` | Histogram | LLM `/chat/completions` 耗时 |
| `boxia_llm_tokens_total` | Counter | LLM token 用量（prompt / completion） |
| `boxia_tool_invoke_duration_seconds` | Histogram | 工具调用耗时 |
| `boxia_tool_invoke_total` | Counter | 工具调用次数（含 success / error / circuit_open / rate_limited） |
| `boxia_agent_run_iterations` | Histogram | 单次 agent 运行的 function calling 迭代数 |

### 8.9 用户端接口

用户端站点只有 `/api/v1/user/**`，与管理端完全隔离。最终用户由租户管理员在管理端「用户管理」中创建并绑定角色：

| 方法 | 路径                                                      | 说明                                                         |
|------|-----------------------------------------------------------|--------------------------------------------------------------|
| POST | `/user/auth/login`                                        | 账号密码登录，返回 access/refresh、有效期与用户角色信息       |
| POST | `/user/auth/refresh`                                      | 轮换刷新令牌；检测到重放会撤销整个会话族                     |
| POST | `/user/auth/logout`                                       | 撤销当前会话族，返回 204                                     |
| GET  | `/user/me`                                                | 当前用户、所属租户、角色与功能权限编码                       |
| GET  | `/user/agents`                                            | 分页查询当前角色可见且已启用的应用，支持 `keyword`           |
| GET  | `/user/agents/{appId}`                                    | 应用详情与可用的工具/提示词元信息；不可见统一返回 404        |
| POST | `/user/agents/{appId}/run`                                | 同步运行应用，返回最终文本 + 工具调用轨迹 + usage            |
| POST | `/user/agents/{appId}/run/stream`                         | SSE 流式运行（事件见下）                                     |
| POST | `/user/agents/{appId}/workflow/run`                       | 按 DAG 模式非流式运行                                        |
| GET  | `/user/agents/{appId}/conversations`                      | 会话列表                                                     |
| GET  | `/user/agents/{appId}/conversations/{conversationId}/messages` | 会话消息历史                                          |

> 用户端前端路由暂沿用 `/agents/:appId`，语义为应用。

- 鉴权：Access Token + Refresh Token，与管理员令牌使用不同 `aud`（`USER_JWT_AUDIENCE`）。
- 租户作用域：必须通过租户子域名访问（`<租户编码>.<ROOT_DOMAIN>`）；平台域名或未知域名返回 404/403。
- 可见性：开通实例 ∩ 角色/管理单元数据范围 ∩ 实例级可见范围 ∩ `is_enabled=true`。

**SSE 事件帧格式**（`/run/stream`）：

```text
event: run_start
data: {"run_id":"...","agent_id":"..."}

event: llm_start
data: {"model":"deepseek-chat"}

event: llm_delta
data: {"text":"你"}

event: tool_start
data: {"tool_name":"query_erp","arguments":{"q":"北京天气"}}

event: tool_end
data: {"tool_name":"query_erp","output":"晴天 25℃","duration_ms":234}

event: final
data: {"content":"今天北京晴天 25℃","usage":{"prompt_tokens":123,"completion_tokens":45}}
```

响应头带 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`（Nginx 不缓冲）。

### 8.10 调用示例（Git Bash）

```bash
# 登录
LOGIN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/admin/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"你的密码"}')
TOKEN=$(echo "$LOGIN" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 查询应用列表（产品级）
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/admin/apps"

# 读取画布节点目录
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/admin/node-meta"

# 创建一条工具资源
curl -X POST http://127.0.0.1:8000/api/v1/admin/resources \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"tool","name":"天气查询","config":{},"owner_type":"platform"}'

# 浏览应用市场（租户作用域，需通过租户子域名访问）
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/admin/marketplace/applications"

# 本地开发：按租户作用域登录（需要 APP_ENV=local 且 ALLOW_TENANT_HEADER=true）
TENANT_LOGIN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/admin/auth/login \
  -H 'X-Tenant-Code: acme' -H 'Content-Type: application/json' \
  -d '{"username":"acme-admin","password":"你的密码"}')
```

> 域名优先：访问 `<code>.localhost` 或部署环境子域名时，`X-Tenant-Code` 会被忽略。只有本地回环主机才允许用请求头切换作用域。

> PowerShell 中 `curl` 是别名，请改用 `curl.exe`。

### 8.11 错误响应

```json
{ "detail": "错误说明", "code": "ERROR_CODE", "request_id": "..." }
```

| 状态码 | code                              | 含义                                   |
|--------|-----------------------------------|----------------------------------------|
| 400    | `BAD_REQUEST`                     | 请求不合法                             |
| 401    | `UNAUTHORIZED`                    | 未登录，或令牌无效/过期/已撤销         |
| 403    | `FORBIDDEN`                       | 角色不足或账号被禁用                   |
| 404    | `NOT_FOUND`                       | 资源不存在或未开通/未授权              |
| 409    | `CONFLICT`                        | 名称重复或唯一约束冲突                 |
| 422    | `VALIDATION_ERROR`                | 参数或业务校验失败（含 `errors` 明细） |
| 429    | `ACCOUNT_LOCKED` / `RATE_LIMITED` | 登录锁定或触发限流，含 `Retry-After`   |
| 500    | `INTERNAL_ERROR`                  | 服务异常，只返回通用文案，堆栈只进日志 |
| 503    | `SERVICE_UNAVAILABLE`             | 依赖不可用（如就绪检查失败）           |

---

## 9. 数据库与迁移

### 9.1 表结构

| 表 | 说明 |
|----|------|
| `tenants` | 租户编码（子域名前缀）、名称、启用状态 |
| `admin_users` | 产品级平台账号、平台角色 `role_id`、锁定状态、`token_version`、首登改密标记 |
| `admin_refresh_tokens` | 产品级平台 Refresh Token 哈希、会话链、轮换/撤销状态、IP/UA |
| `users` | 租户管理员与普通用户统一账号；`(tenant_id, username)` 唯一；带 `UNIQUE(tenant_id,id)` 供复合外键 |
| `user_roles` | 用户与租户角色多对多 |
| `user_refresh_tokens` | 租户用户 Refresh Token 哈希、会话族、轮换/撤销状态 |
| `roles` | 平台/租户角色：`tenant_id`、`code`、`name`、`is_system`、启用状态 |
| `permission_resources` | 全局功能权限目录（只读）：`code`、`category`、`action`、`sort_order` |
| `role_permissions` | 角色与权限资源多对多 |
| `resource_grants` | 数据授权：`resource_type`、`resource_id`、`tenant_id`、可空 `role_id` |
| `departments` | 租户部门树：物化路径 `path`、`level`（≤10）、`code`、`sort_order`、`is_active` |
| `user_employments` | 用户任职记录；部分唯一索引保证单一主任职；调岗保留历史 |
| `mgmt_units` | 管理单元（跨部门/人员的数据范围），同样使用物化路径与层级 |
| `mgmt_unit_departments` | 管理单元关联部门（`include_subtree`） |
| `mgmt_unit_users` | 管理单元关联人员 |
| `user_mgmt_unit_grants` | 用户被授权的管理单元 |
| `hr_dictionaries` | 人力资源字典（类别、编码、名称、排序、启停） |
| `audit_logs` | 审计日志（操作者、动作、资源、`request_id`、详情 JSONB） |
| `application` | 应用主表：`owner_type`/`owner_id`、名称、头像、简介、启停、`is_listed_in_market`、`visibility_mode`、`sale_mode`、`published_graph_version` |
| `application_graph` | 草稿图：`schema_json`（节点/连线/变量）、`graph_schema_version`、`runtime_mode` |
| `application_graph_version` | 发布快照：版本号、`schema_json`、`runtime_mode`、变更说明 |
| `tenant_application_instance` | 租户开通实例：状态、来源、覆盖配置、`pinned_graph_version`、授权方式、配额、起止时间 |
| `tenant_application_config` | 租户级应用配置覆盖（`config_key` / `config_value`） |
| `application_apply` | 应用开通申请（申请类型、状态、联系人、合同号、审批信息） |
| `application_visibility_departments` | 应用实例可见部门（`include_subtree`） |
| `application_visibility_users` | 应用实例可见人员 |
| `resource` | 统一资源目录：`type`（tool/prompt/skill/knowledge）、`owner_type`/`owner_id`、`config`、版本、启停/废弃 |
| `resource_grant` | 统一资源授权：`resource_id` + `tenant_id`，供资源页与市场使用 |
| `resource_grants` | 旧 RBAC 授权表：`resource_type` + `resource_id` + `tenant_id` + 可空 `role_id`，角色授权与授权汇总接口仍在用（兼容期） |
| `tools` | 可执行工具定义：`type`（http/mcp）、`config`（URL/headers/schema/治理参数）、启停 |
| `documents` | 知识库文档：标题、来源、原文、`content_hash`、`ingest_status`、`ingest_error`、`chunk_count` |
| `document_chunks` | 文档分块：`chunk_index`、`content`、`embedding`（pgvector 1024 维）、`metadata`（含 `heading_path`） |
| `model_provider` | 模型供应商：名称、`base_url`、`api_key`、归属 |
| `model_catalog` | 模型目录：`provider_id`、`model_id`、显示名、能力标签 |
| `run` | 应用运行记录：租户、应用、图快照、输入/输出、状态、`thread_id`、起止时间 |
| `run_node_execution` | 节点级执行记录：节点 ID/类型、输入/输出、错误、耗时、`usage` |
| `conversation` | 会话：租户、用户、应用、标题 |
| `message` | 消息：角色、内容、工具调用、`run_id`、元数据 |
| `tenant_settings` | 租户运行时配置：默认模型、允许模型白名单、工具白名单 |
| `tenant_usage_ledger` | 租户 token 用量账本：应用、运行、节点、模型、prompt/completion/total tokens |
| `event_webhook` | 事件 Webhook：租户、应用、事件类型、URL、启停 |
| `checkpoints` / `checkpoint_blobs` / `checkpoint_writes` / `checkpoint_migrations` | LangGraph 断点续跑与时间旅行所需的状态快照 |
| `alembic_version` | 当前迁移版本 |

约定：

- 业务表统一带 `tenant_id`，产品级使用全零 UUID（`PLATFORM_TENANT_ID`）；仓储过滤为 `tenant_id IN (当前租户, PLATFORM_TENANT_ID)`。
- 资源名称与用户名按作用域唯一，不同租户可以同名。
- 所有表都有 `created_at` / `updated_at`，`updated_at` 由触发器维护。
- 列表默认按 `updated_at DESC, id DESC` 排序。
- 资源名称和描述使用 `pg_trgm` 索引，支持模糊搜索。
- RAG 向量列依赖 `pgvector` 扩展；使用 Milvus 时由 `VECTOR_STORE_PROVIDER` 切换实现。
- `run.workflow_id` 为历史列名，语义上是应用 ID。
- 迁移 `0037_drop_legacy` 起，旧版 agent/workflow/skill/component/prompt 相关表已物理下线；`0043_drop_legacy_field_version` 又下线了字段级版本表，当前只保留应用模型所需的表。

### 9.2 迁移命令

```bash
cd backend

uv run alembic upgrade head        # 升级到最新
uv run alembic check               # 检查模型和迁移是否一致
uv run alembic downgrade -1        # 回滚一个版本
uv run alembic history             # 查看迁移历史
uv run alembic current             # 查看数据库当前版本（带 (head) 即最新）
```

- **全新数据库**：直接 `alembic upgrade head`。
- **早期手工初始化过的数据库**（表结构已与基线一致）：先 `uv run alembic stamp 0001_baseline`，再 `upgrade head`。
- **生产环境**：由 Compose 中的一次性 `migrate` 服务自动执行，`backend-admin` / `backend-user` 等它成功后才启动。
- 升级前请备份数据库；涉及数据回填的迁移即使 DDL 可降级，数据也未必可逆。

### 9.3 初始化与演示数据

```bash
# 创建或重置管理员（默认首次登录强制改密）
uv run python -m scripts.create_admin

# 为指定租户创建管理员（租户需已存在；不传 TENANT_CODE 则创建产品级账号）
TENANT_CODE=acme uv run python -m scripts.create_admin

# 自动化环境可跳过首登改密（仅测试/演示）
ADMIN_MUST_CHANGE_PASSWORD=false uv run python -m scripts.create_admin

# 写入本地演示数据（幂等，可重复执行）
uv run python -m scripts.seed_demo
```
