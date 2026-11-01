> 返回 [项目手册](../README.md)

## 5. 目录结构与代码分层

### 5.1 目录树

```text
boxia-agent/
├── backend/                     # 后端（Python）
│   ├── web/                     # HTTP 层：路由、请求/响应模型、异常处理
│   │   ├── app.py               # 应用工厂：按站点装配共享基础设施与路由
│   │   ├── app_admin.py         # 管理端入口：仅装配 admin 路由
│   │   ├── app_user.py          # 用户端入口：仅装配 user 路由
│   │   ├── api_v1.py            # admin / user 两套独立的 /api/v1 路由聚合
│   │   ├── admin/               # 管理端站点
│   │   │   ├── router.py        # 受保护路由聚合（统一前缀与管理员鉴权）
│   │   │   ├── routers/         # 接口（按资源拆分：agents / tenants / users ...）
│   │   │   └── schemas/         # 请求/响应模型（按职责拆分：auth / tenant / resource ...）
│   │   ├── user/                # 用户端站点（router.py 聚合 + routers/ 业务接口）
│   │   └── deps/                # 数据库、服务、鉴权、租户作用域依赖
│   ├── internal/                # 业务实现
│   │   ├── domain/              # 实体（含租户/请求上下文）、分页对象、仓储协议
│   │   ├── application/         # 用例服务、统一业务异常
│   │   └── infrastructure/      # 配置、ORM、仓储、安全、日志、中间件、链路追踪
│   ├── docker/                  # 本地 PostgreSQL 编排（项目名固定为 postgresql）
│   ├── migrations/              # Alembic 迁移（0001 基线、0002 认证加固、0003 搜索索引、0004 多租户、0005 技能包文件）
│   ├── scripts/                 # create_admin / seed_demo / skill_package / wait_for_db
│   ├── tests/                   # 后端接口测试
│   └── Dockerfile
├── frontend/
│   ├── admin/                   # 管理端（端口 5173）
│   │   ├── src/                 # api / auth / tenant / components / layouts / pages / router
│   │   ├── e2e/                 # Playwright 端到端用例（含多租户场景）
│   │   ├── nginx/               # 生产 Nginx 配置（SPA、反代、限流、安全头）
│   │   └── Dockerfile           # Node 构建 + nginx-unprivileged 运行
│   ├── user/                    # 用户端门户（端口 5174，含 nginx / Dockerfile）
│   └── scripts/                 # 前端启停脚本（支持 admin / user / all）
├── ops/                         # 跨端运维入口
│   ├── docker-compose.yml       # 多环境编排：db / migrate / backend-admin / backend-user / 两端 frontend
│   ├── .env.prod          # 部署配置，自行创建且不入 Git（变量清单见 14.3）
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
2. **业务规则在 `internal/application`**：用例服务负责编排。
3. **数据库操作在 `internal/infrastructure/repository`**：仓储只负责读写。
4. **事务统一提交**：仓储内部只 `flush()`，应用服务在用例结束时统一 `commit()`；审计日志和业务数据在同一个事务里。
5. **新增管理端接口默认受保护**：`web/admin/router.py` 统一挂载了管理员鉴权。

### 5.4 想改某个功能，应该动哪里

| 需求               | 通常要改的文件                                                                                                                                                                          |
|--------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 新增一个管理端接口 | `backend/web/admin/routers/xxx.py`（路由）+ `backend/web/admin/schemas/xxx.py`（请求响应模型）→ `backend/internal/application/xxx_service.py`（业务）→ `backend/internal/infrastructure/repository/postgres_xxx_repository.py`（SQL） |
| 新增一张表         | `backend/internal/infrastructure/model/xxx.py`（ORM 模型）→ `backend/internal/domain/entity/xxx.py`（领域实体）→ 生成 Alembic 迁移                                                      |
| 新增一个管理端页面 | `frontend/admin/src/pages/`（页面）→ `frontend/admin/src/router.tsx`（路由）→ `frontend/admin/src/api/`（接口封装）                                                                     |
| 调整权限           | `backend/web/deps/auth.py`、`backend/web/admin/router.py`、前端 `RequireRole`                                                                                                           |
| 调整租户识别与隔离 | `backend/web/deps/tenant.py`、仓储的 `_visible` / `_owned`、`backend/tests/test_tenants.py`                                                                                             |
| 调整登录/令牌逻辑  | `backend/internal/application/auth_service.py`、`backend/internal/infrastructure/security/tokens.py`、前端 `src/api/client.ts`、`src/auth/AuthContext.tsx`                              |
| 调整数据库结构     | 修改 ORM 模型 → `uv run alembic revision --autogenerate -m "说明"` → 检查生成的迁移 → `uv run alembic upgrade head`                                                                     |

---

## 6. 配置说明

### 6.1 配置文件从哪来

- 本地开发：复制 `backend/.env.example` 为 `backend/.env` 后修改。
- 部署：`ops/` 下没有模板文件，直接新建 `.env.prod`（开发/测试环境分别新建 `.env.dev`、`.env.test`），按 14.3 的清单填写。

真实配置文件都已被 `.gitignore` 忽略，不会进入 Git。第一次使用先确认必填项，其余变量都有默认值，可以等需要时再调整：

| 配置文件 | 必填项 |
|----------|--------|
| `backend/.env`（本地） | `DATABASE_URL`、`JWT_SECRET`；`ROOT_DOMAIN` 设为 `localhost` 或留空（自动回退） |
| `ops/.env.*`（部署） | `POSTGRES_PASSWORD`、`DATABASE_URL`（账号密码库名与 `POSTGRES_*` 一致）、`JWT_SECRET`、`ROOT_DOMAIN` |

### 6.2 变量一览

| 变量                          | 默认值              | 必填     | 说明                                                                                                                                                  |
|-------------------------------|---------------------|----------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| `APP_ENV`                     | `local`             | 否       | `local`（本机调试）/ `dev` / `test` / `prod`                                                                                            |
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
| `JWT_AUDIENCE`                | `boxia-admin`       | 否       | 令牌受众，会写入并校验 `aud`                                                                                                                          |
| `ACCESS_TOKEN_MINUTES`        | `30`                | 否       | 访问令牌有效期                                                                                                                                        |
| `REFRESH_TOKEN_DAYS`          | `14`                | 否       | 刷新令牌有效期                                                                                                                                        |
| `BCRYPT_ROUNDS`               | `12`                | 否       | 密码哈希成本因子                                                                                                                                      |
| `LOGIN_MAX_ATTEMPTS`          | `5`                 | 否       | 连续失败几次后锁定                                                                                                                                    |
| `LOGIN_LOCK_MINUTES`          | `15`                | 否       | 锁定时长（分钟）                                                                                                                                      |
| `PASSWORD_MIN_LENGTH`         | `12`                | 否       | 密码最小长度（字符数，8-64；代码默认 12，`.env.example` 本地为 10）；改动后后端校验与前端表单同时生效                                                  |
| `PASSWORD_MAX_BYTES`          | `72`                | 否       | 密码最大字节数（UTF-8，32-72）；bcrypt 只处理前 72 字节                                                                                               |
| `PASSWORD_MIN_CATEGORIES`     | `3`                 | 否       | 至少包含的字符类别数（1-4：大写字母、小写字母、数字、符号）                                                                                           |
| `SKILL_PACKAGE_MAX_FILES`     | `200`               | 否       | 单个技能包最大文件数（1-2000）                                                                                                                        |
| `SKILL_PACKAGE_MAX_FILE_BYTES`| `1048576`           | 否       | 单个技能文件最大字节数（1 KiB-16 MiB）                                                                                                                |
| `SKILL_PACKAGE_MAX_TOTAL_BYTES`| `8388608`          | 否       | 单个技能包总大小上限（1 KiB-64 MiB）                                                                                                                  |
| `ROOT_DOMAIN`                 | 空                  | 部署必填 | 每个环境独立的租户根域名，如 `dev.example.com` / `test.example.com` / `example.com`；`local` 设为 `localhost`（或留空自动回退）即可免 DNS 验证 `*.localhost`，其余环境未配置会拒绝启动，见 6.4 |
| `PLATFORM_ADMIN_SUBDOMAIN`    | `adminsystem`       | 否       | 产品级平台子域名前缀，最终为 `adminsystem.<ROOT_DOMAIN>`                                                                                              |
| `PLATFORM_NAME`               | `AI智能体运营管理平台` | 否       | 管理端展示的平台名称                                                                                                                                  |
| `DEFAULT_TENANT_CODE`         | 空                  | 否       | 访问根域名时默认进入的租户；留空则拒绝根域名访问                                                                                                      |
| `ALLOW_TENANT_HEADER`         | `false`             | 否       | 是否允许 `X-Tenant-Code` 请求头识别租户；**仅 `local` 有效**，开发/测试/生产开启会拒绝启动                                                            |
| `CORS_ORIGINS`                | 空                  | 否       | 逗号分隔的允许来源；生产禁止 `*`                                                                                                                      |
| `DOCS_ENABLED`                | 生产关闭            | 否       | 是否暴露 Swagger 文档                                                                                                                                 |
| `LEGACY_API_ENABLED`          | `true`              | 否       | 是否保留 `/api` 兼容别名                                                                                                                              |
| `USER_JWT_AUDIENCE`           | `boxia-user`        | 否       | 最终用户令牌受众；与管理端 `JWT_AUDIENCE` 隔离，防止两端令牌互相冒用                                                                                  |
| `LOG_LEVEL`                   | `INFO`              | 否       | 日志级别                                                                                                                                              |
| `LOG_JSON`                    | 生产默认 `true`     | 否       | 是否输出 JSON 日志                                                                                                                                    |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 空                  | 否       | 链路数据上报地址，不配则不上报                                                                                                                        |
| `OTEL_SERVICE_NAME`           | `boxia-agent`       | 否       | 链路服务名                                                                                                                                            |
| `OTEL_TRACES_SAMPLER_RATIO`   | `1.0`               | 否       | 链路采样率                                                                                                                                            |
| `WEB_CONCURRENCY`             | `2`（镜像）         | 否       | 后端 worker 数                                                                                                                                        |
| `EMBEDDING_API_KEY`           | 无                  | RAG 必填 | Embedding / Rerank 服务 API Key（SiliconFlow 等 OpenAI 兼容服务）                                                                                     |
| `EMBEDDING_BASE_URL`          | `https://api.siliconflow.cn/v1` | 否 | Embedding / Rerank 服务端点                                                                                                                           |
| `EMBEDDING_MODEL`            | `BAAI/bge-large-zh-v1.5` | 否   | 向量模型（1024 维，最大输入 512 tokens）                                                                                                              |
| `EMBEDDING_TIMEOUT_SECONDS`   | `30`                | 否       | Embedding / Rerank HTTP 超时                                                                                                                          |
| `LLM_API_KEY`                 | 无                  | RAG 必填 | LLM 服务 API Key（用于 query 改写）                                                                                                                   |
| `LLM_BASE_URL`                | `https://api.siliconflow.cn/v1` | 否 | LLM 端点                                                                                                                                              |
| `LLM_MODEL_ID`                | 无                  | RAG 必填 | LLM 模型 ID                                                                                                                                           |
| `LLM_TIMEOUT_SECONDS`         | `60`                | 否       | LLM HTTP 超时                                                                                                                                         |
| `RAG_CHUNK_SIZE`              | `500`               | 否       | 文档分块字符数（受 bge 512 tokens 输入限制，勿超 600）                                                                                                  |
| `RAG_CHUNK_OVERLAP`           | `80`                | 否       | 分块重叠字符数                                                                                                                                        |
| `RAG_TOP_K`                    | `5`                 | 否       | 最终返回给 prompt 的 chunk 数                                                                                                                         |
| `RAG_SIMILARITY_THRESHOLD`    | `0.55`              | 否       | 向量余弦阈值（rerank 关闭时使用）                                                                                                                      |
| `RAG_RERANK_ENABLED`           | `true`              | 否       | 是否启用 Cross-Encoder 精排；关闭时退化为向量余弦过滤                                                                                                  |
| `RAG_RERANK_MODEL`            | `BAAI/bge-reranker-v2-m3` | 否 | Rerank 模型                                                                                                                                           |
| `RAG_RERANK_TOP_N`            | `5`                 | 否       | Rerank 返回的候选数                                                                                                                                    |
| `RAG_RECALL_MULTIPLIER`       | `10`                | 否       | 向量召回倍数（粗排候选 = top_k × multiplier）                                                                                                         |
| `RAG_QUERY_REWRITE_ENABLED`   | `true`              | 否       | 是否启用 LLM query 改写（指代消解 + 多 query 变体）                                                                                                  |
| `RAG_QUERY_REWRITE_VARIANTS`  | `3`                 | 否       | 每次改写生成的同义变体数（1-5）                                                                                                                       |
| `CELERY_BROKER_URL`           | `redis://127.0.0.1:6379/1` | 否   | Celery broker（Redis DB 1，与短期记忆 DB 0 隔离）                                                                                                     |
| `CELERY_RESULT_BACKEND`       | `redis://127.0.0.1:6379/2` | 否   | Celery 结果后端（Redis DB 2）                                                                                                                         |
| `ADMIN_AUTO_INIT`             | `false`            | 否       | 部署时是否自动初始化首个平台管理员账号（仅 admin 站点启动时生效）；需与 `ADMIN_INITIAL_PASSWORD` 同时配置才会执行                                          |
| `ADMIN_INITIAL_USERNAME`     | `admin`            | 否       | 自动初始化的平台管理员用户名                                                                                                                          |
| `ADMIN_INITIAL_DISPLAY_NAME`  | `系统管理员`        | 否       | 自动初始化的平台管理员显示名                                                                                                                          |
| `ADMIN_INITIAL_PASSWORD`      | 空                | 否       | 自动初始化的平台管理员密码；为空时跳过初始化；需符合密码策略                                                                                              |
| `ADMIN_INITIAL_ROLE`          | `superadmin`       | 否       | 自动初始化的平台角色编码（必须是已存在的平台角色）                                                                                                      |
| `ADMIN_INITIAL_MUST_CHANGE_PASSWORD` | `true`      | 否       | 首次登录是否强制改密（自动化环境可设为 `false`）                                                                                                       |

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

后端启动前会按 `APP_ENV` 检查多租户配置，不合格直接拒绝启动，避免带病运行或静默回退到产品级平台：

- 所有环境：`PLATFORM_ADMIN_SUBDOMAIN` 必须是一级域名标签（字母、数字、连字符）。
- `dev` / `test` / `prod`：
  - 必须配置 `ROOT_DOMAIN`，且不能是 `localhost`、`*.localhost` 或 IP 地址；
  - 禁止开启 `ALLOW_TENANT_HEADER`，部署环境只认二级域名。
- `prod` 额外要求：
  - `JWT_SECRET` 至少 32 字符，且不能使用示例占位值；
  - `CORS_ORIGINS` 不允许 `*`。

这些检查是为了避免“复制示例配置直接上线”或漏配域名时把请求放进最高权限的产品级平台。

### 6.4 多租户域名与使用方式

**作用域判定**

| 访问地址                  | 作用域      | 能力                                                    |
|---------------------------|-------------|---------------------------------------------------------|
| `adminsystem.example.com` | 产品级平台  | 跨租户管理、创建/停用租户、维护产品级智能体与资源       |
| `acme.example.com`        | 租户 `acme` | 维护本租户账号与资源；可使用产品级资源，但不能修改      |
| `example.com`             | 根域名      | 配置了 `DEFAULT_TENANT_CODE` 则进入该租户，否则返回 404 |

**域名是作用域的唯一事实来源。** 部署环境必须配置 `ROOT_DOMAIN`，只能通过二级域名（`adminsystem.<根域名>` 或 `<租户编码>.<根域名>`）访问；部署环境中的 `localhost`、回环地址、未知域名与多级子域名一律返回 404，**不再静默回退到产品级平台**。`X-Tenant-Code` 请求头与 `?tenant=` 参数只在 `local` 环境、且 `ALLOW_TENANT_HEADER=true` 时生效，并且只在回环/本机主机上生效；访问 `acme.localhost` 时即使带了其他租户的请求头，也以域名为准。

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
| 开发环境部署 | `dev` | 必填，如 `dev.example.com`  | `adminsystem.dev.example.com`  | `acme.dev.example.com`  | 仅二级域名                                    |
| 测试环境部署 | `test`        | 必填，如 `test.example.com` | `adminsystem.test.example.com` | `acme.test.example.com` | 仅二级域名                                    |
| 线上环境     | `prod`  | 必填，如 `example.com`      | `adminsystem.example.com`      | `acme.example.com`      | 仅二级域名                                    |

部署环境只认域名：前端在服务端报告 `tenant_switch_mode=none` 时会清掉本地残留的租户覆盖值；`?tenant=` 参数会被直接忽略并移出地址栏，不会误清登录态。开发/测试环境如确需临时联调请求头切换，仍需把 `APP_ENV` 改为 `local`，不要在生产打开该能力。

`/public/context` 与 `/admin/context` 会返回 `app_env`、`tenant_resolution`（`host` / `header` / `default`）、`tenant_switch_mode`（`none` / `header` / `host`）与 `platform_admin_host`，登录页和管理端侧边栏会展示环境与解析来源，便于排查“为什么进了错误租户”。

**部署配置（以生产为例）**

1. DNS：将 `*.example.com`（含 `adminsystem.example.com`）解析到入口；开发/测试环境分别解析 `*.dev.example.com`、`*.test.example.com`。
2. Nginx：仓库自带的 `frontend/admin/nginx/default.conf` 与 `frontend/user/nginx/default.conf` 均使用 `server_name _;` 并透传 `Host $host`，泛域名无需逐个配置。若外层还有代理/网关，必须保留原始 Host 头。
3. 环境变量：按 14.3 创建 `ops/.env.prod`，设置 `ROOT_DOMAIN=example.com`，按需调整 `PLATFORM_ADMIN_SUBDOMAIN`、`PLATFORM_NAME`、`DEFAULT_TENANT_CODE`；开发/测试环境对应使用 `.env.dev` / `.env.test`。
4. 若前后端分离部署，`CORS_ORIGINS` 需要列出实际使用的平台与租户域名。

**数据隔离规则**

- 资源与账号都带 `tenant_id`：`NULL` 表示产品级，非空表示租户私有。
- 产品级智能体必须显式授权给租户后才可见；产品级资源按自身授权或所属智能体授权放行；租户资源只对本租户可见。
- 授权可按角色收窄：`role_id` 为空表示整个租户，非空仅指定角色可见。
- 登录、刷新与访问令牌都绑定作用域，跨作用域使用直接返回 401。
- 同一作用域内资源名称唯一，不同租户之间允许同名；租户不能与产品级资源重名（产品级资源可能被授权给该租户，需保持名称唯一以避免混淆）。
- 用户名同样按作用域唯一：不同作用域可以有同名账号，它们属于不同的人。

**创建并使用租户**

1. 用产品级账号登录 `adminsystem.example.com`，进入「租户管理」新建租户。
2. 租户编码即子域名前缀（如 `acme` → `acme.example.com`），创建后不可修改。
3. 新建时填写的租户管理员账号首次登录会强制改密；该账号只能登录本租户子域名。
4. 停用租户后，该子域名下的登录与已登录会话都会立即被拒绝。

**本地开发**

`backend/.env` 使用 `APP_ENV=local`（`.env.example` 默认值）时有两种本地调试方式：

1. **请求头模式**：`ROOT_DOMAIN` 可留空（回退 `localhost`），保持 `ALLOW_TENANT_HEADER=true`。访问 `http://localhost:5173` 默认进入产品级平台；产品级登录页提供作用域下拉框，也可用 `?tenant=acme`（产品级用 `?tenant=platform`）或接口请求头 `X-Tenant-Code: acme` 切换。进入租户级后下拉框隐藏，只展示当前租户名称。
2. **真实子域名模式**：直接访问 `http://adminsystem.localhost:5173` 或 `http://<租户编码>.localhost:5173`。Vite 会透传原始 `Host`，后端按域名解析；此时 `X-Tenant-Code` 不生效，切换租户由前端跳转到对应子域名。

若关闭 `ALLOW_TENANT_HEADER`，请求头与 `?tenant=` 都会失效，只能使用子域名方式访问。

---

## 7. 登录、权限与安全

### 7.1 两种令牌，通俗理解

登录成功后服务器返回两个令牌：

- **Access Token（访问令牌）**：短期的“临时通行证”，默认 30 分钟。前端只放在内存里，刷新页面后会用 Refresh Token 重新换取，不需要重新登录。
- **Refresh Token（刷新令牌）**：长期的“续期凭证”，默认 14 天。数据库只保存它的哈希值，不保存明文。

安全机制：

- 刷新令牌**用过一次就作废**，同时发一个新的（单次轮换）。
- 如果旧的刷新令牌被再次使用，系统会认为可能被盗用，撤销整条会话链，要求重新登录。
- 登出、改密、禁用或删除管理员时，该账号已有令牌立即失效。
- 令牌绑定作用域：Access Token 里的 `tid` 必须与账号归属、当前子域名一致，拿产品级令牌访问租户子域名会被拒绝（反之亦然）。
- 前端多标签页之间会同步登录和登出状态。

### 7.2 登录保护

- 不存在的用户名也会执行一次密码校验，防止攻击者通过响应速度判断用户名是否存在。
- 连续 5 次密码错误锁定 15 分钟，返回 `429` 和 `Retry-After`。
- 登录成功后失败次数清零。
- Nginx 在生产环境对登录接口限流（`10 次/分钟`），普通接口 `30 次/秒`。

### 7.3 权限（RBAC）

权限分两层：

- **功能权限**：角色与全局权限资源目录（`permission_resources`）通过 `role_permissions` 建立多对多关系，决定能否看到菜单/页面/按钮，以及能否对资源做增删改查。
- **数据权限**：`resource_grants` 决定角色能看到哪些资源实例（智能体、技能、工具、组件、提示词），属于实例级授权。

权限资源随迁移预置、只读维护，分类为 `system` / `menu` / `page` / `button` / `agent` / `skill` / `tool` / `component` / `prompt`。管理端只提供查询接口，不提供新增或修改。

约束与规则：

- 每次请求都以数据库中的实时角色、权限与账号状态为准（`AdminPrincipal.permissions` 每次重建），不信任令牌里的旧角色信息。
- `system:console:access` 控制管理端登录；`system:data:all` 跳过数据授权过滤，但仍受租户隔离约束。
- 超级管理员角色拥有所属作用域全部权限，功能权限与数据授权均不可单独调整。
- 平台角色不能授予租户专属菜单与按钮（`menu:grants`、`menu:users`、`menu:departments`、`menu:employments`、`page:users`、`page:departments`、`page:employments`、`button:user:*`、`button:department:*`、`button:employment:*`）；租户角色不能授予平台级租户管理权限（`menu:tenants` 等）。
- 授权只允许授予调用者已拥有的权限，复制角色同样校验；写入时对角色行加锁，避免并发授权互相覆盖。
- 前端隐藏菜单和按钮只是体验优化，所有接口都以服务端权限校验为准，不满足返回 403。

**租户角色与资源可见性**：

- 租户管理员与普通用户都通过 `user_roles` 绑定租户角色（`users.role_id` 保留主角色），角色拥有的功能权限决定能否进入管理端及可执行的操作。
- 产品级智能体必须存在授权记录（`resource_grants`），租户才能看到；`role_id = NULL` 表示授予整个租户，否则仅授予指定角色。
- 租户自有智能体默认对本租户全部角色可见；配置了角色授权后按授权收紧。
- 技能、工具、组件、提示词同样支持角色授权；未单独配置授权时随所属智能体放行。
- 未授权对象在详情与写操作中统一返回 404，避免泄露资源是否存在。
- 管理端「授权管理」按资源类型集中维护授权；平台视角按租户逐个配置，租户视角只能维护本租户角色。
- 前端隐藏菜单和按钮只是体验优化，所有可见性与写权限都以服务端校验为准。

### 7.4 审计日志

以下操作会写入 `audit_logs`：

| 类别                 | action                                                                                           |
|----------------------|--------------------------------------------------------------------------------------------------|
| 认证                 | `auth.login`、`auth.login_failed`、`auth.refresh_replay`、`auth.logout`、`auth.password_changed` |
| 管理员               | `admin_user.created`、`admin_user.updated`、`admin_user.password_reset`                          |
| 租户（仅产品级平台） | `tenant.created`、`tenant.updated`                                                               |
| 角色与用户           | `role.created`、`role.updated`、`role.deleted`、`user.created`、`user.updated`、`user.deleted`、`user.password_reset` |
| 授权与资源           | `grant.updated`、`resource.cloned`                                                               |
| 用户端认证           | `user_auth.login`、`user_auth.login_failed`、`user_auth.refresh_replay`、`user_auth.logout`      |

每条记录包含操作者、动作、资源、`request_id`、IP、User-Agent、作用域（`tenant_id`）和详情，便于追溯。登录失败、登出、改密也会写入归属的作用域：租户账号的审计只在租户内可见，产品级账号可以查看全部。

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
- [ ] 无对应 `button:*` 权限的角色调用写接口返回 403，管理端隐藏操作按钮
- [ ] `/admin/users`、`/admin/admin-users`、`/admin/audit-logs` 仅授予对应 `page:*` 权限的角色可访问
- [ ] 角色授权不能授予调用者自身不具备的权限（越权授权返回 403）
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
  - 用户端站点（`web.app_user:app`）：`/api/v1/user/**`，最终用户使用账号密码登录获得 JWT，且必须通过租户子域名访问
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
| GET  | `/admin/context`       | 当前登录账号的作用域、租户与域名配置        |

匿名接口（登录页使用）：

| 方法 | 路径              | 说明                                                    |
|------|-------------------|---------------------------------------------------------|
| GET  | `/public/context` | 按当前域名返回产品级/租户级模式与平台名称               |
| GET  | `/public/tenants` | 仅 `local` 环境返回可选租户列表；开发/测试/线上返回 403 |

`/public/context` 与 `/admin/context` 的关键字段：

| 字段                                                       | 说明                                                                      |
|------------------------------------------------------------|---------------------------------------------------------------------------|
| `scope`                                                    | `platform`（产品级）或 `tenant`（租户级）                                 |
| `tenant`                                                   | 当前租户信息；产品级为 `null`                                             |
| `app_env`                                                  | `local` / `dev` / `test` / `prod`                           |
| `tenant_resolution`                                        | 作用域来源：`host`（域名）/ `header`（本地请求头）/ `default`（本地兜底） |
| `tenant_switch_mode`                                       | 前端切换方式：`none`（仅域名）/ `header`（请求头）/ `host`（子域名跳转）  |
| `platform_admin_host`                                      | 产品级平台完整主机名，如 `adminsystem.dev.example.com`                    |
| `root_domain`、`platform_admin_subdomain`、`platform_name` | 当前环境的根域名、平台子域名与展示名称                                    |
| `password_policy`                                          | 密码策略 `{min_length, max_bytes, min_categories}`，前端表单按此动态校验 |

`/admin/context` 额外返回当前账号的权限信息（匿名接口不含）：

| 字段          | 说明                                                                 |
|---------------|----------------------------------------------------------------------|
| `role_code`   | 当前账号绑定角色的编码，如 `superadmin`、`admin` 或自定义编码         |
| `role_name`   | 角色名称                                                             |
| `permissions` | 角色拥有的功能权限编码集合（如 `menu:roles`、`button:agent:create`），前端据此控制菜单、路由与按钮 |
| `menus`       | 由 `menu:*` 权限推导出的可见菜单键；平台账号不会包含租户专属菜单     |

### 8.3 资源接口

`{resource}` 可以是 `agents`、`skills`、`tools`、`components`、`prompts`：

| 方法   | 路径                            | 说明                                                                                     |
|--------|---------------------------------|------------------------------------------------------------------------------------------|
| GET    | `/admin/{resource}`             | 分页查询，参数 `page`、`page_size`（≤100）、`keyword`、`is_enabled`、`agent_id`          |
| POST   | `/admin/{resource}`             | 创建，返回 201（无 `button:{resource}:create` 返回 403）；技能/工具/组件/提示词可传 `agent_id` 绑定归属智能体 |
| GET    | `/admin/{resource}/{id}`        | 详情；未授权统一返回 404                                                                 |
| PUT    | `/admin/{resource}/{id}`        | 全量更新（无 `button:{resource}:update` 返回 403）                                       |
| DELETE | `/admin/{resource}/{id}`        | 删除，返回 204（无 `button:{resource}:delete` 返回 403），同事务清理授权记录              |
| POST   | `/admin/{resource}/{id}/clone`  | 克隆到目标智能体，入参 `{agent_id, name?}`，返回 201 与独立副本                          |

智能体额外提供 user 端可见范围维护（仅租户智能体，平台智能体调用返回 400）：

| 方法 | 路径                                  | 说明                                                                                  |
|------|---------------------------------------|---------------------------------------------------------------------------------------|
| GET  | `/admin/agents/{id}/visibility`        | 查询可见范围：`mode`（`all`/`custom`）、`departments:[{department_id, include_subtree}]`、`user_ids` |
| PUT  | `/admin/agents/{id}/visibility`        | 全量替换可见范围；`all` 模式忽略部门/人员列表，`custom` 模式按部门（含子树）或指定人员收敛 |

分页响应格式：

```json
{ "items": [], "total": 0, "page": 1, "page_size": 20 }
```

资源与智能体的响应都带 `tenant_id`（`null` 表示产品级）和 `is_platform`：租户内看到的平台级资源 `is_platform=true`，前端据此切换只读状态；租户自有资源 `tenant_id` 为当前租户。技能/工具/组件/提示词额外返回 `agent_id`，表示数据归属的智能体。

智能体的特殊字段：

- 创建/更新时可以传 `config`（对象）、`tool_ids`、`skill_ids`；后端会去重并校验关联是否存在。
- `tool_ids` / `skill_ids` 仅为兼容旧数据保留，标注 deprecated；新数据以资源的 `agent_id` 归属为准，列表与详情会合并两种来源。
- 列表只返回摘要（不含 `config` 和关联 ID），详情返回完整配置。
- `config` 中缺失的子项由后端补默认值。
- 响应带 `visibility_mode`（`all`/`custom`，默认 `all`）；仅作用于租户智能体的 user 端可见过滤，管理端列表不受影响。

可见性规则（服务端唯一事实来源）：

| 场景                       | 可见条件                                                                 |
|----------------------------|--------------------------------------------------------------------------|
| 平台级智能体 @ 租户        | 存在授权记录，且 `role_id` 为 `NULL` 或命中当前账号角色                    |
| 租户自有智能体 @ 租户       | 同租户；未配置授权时全角色可见，配置后按授权收紧                           |
| 平台级资源 @ 租户          | 直接授权命中，或（无直接授权且所属智能体可见）                             |
| 租户自有资源 @ 租户        | 随所属智能体规则                                                         |
| 用户端（管理端账号）       | 在租户规则上追加 `is_enabled=true`，角色集合仅本人角色                     |
| 用户端（user 端普通用户）   | 在租户规则上叠加智能体实例级可见范围：`all` 直接放行；`custom` 需命中以下任一 —— 当前用户 `id` 出现在 `agent_visibility_users`、当前任职部门 id 直接命中 `agent_visibility_departments`、或当前任职部门 path 前缀命中 `include_subtree=true` 的规则 |

### 8.3.1 技能包文件接口

管理端入口：**智能体详情 → 技能与资源 → 技能 → 列表行「技能包」**。抽屉内可查看/编辑文件、导入和导出 zip。

技能在存储上是一个虚拟目录：每个技能由若干文本文件组成，`SKILL.md` 为入口文件，其余文件（如 `references/**`、脚本说明等）按相对路径存放。文件内容只存在 `skill_files` 表，`skills.content` 是 `SKILL.md` 的镜像，供列表与搜索使用。

平台级与租户级技能不做物理目录区分，归属完全由 `skills.tenant_id` 决定：

- `tenant_id = NULL`：平台级技能，仅产品级平台可维护；租户需有直接授权，或技能所属智能体对租户可见时才能看到。
- `tenant_id = 当前租户`：租户级技能，仅本租户可见可维护。
- 租户若需修改平台级技能，必须调用克隆接口生成独立副本，不建立跨租户引用。
- 后续若迁移到对象存储，key 约定为 `skills/platform/{skill_id}/{path}` 与 `skills/tenants/{tenant_id}/{skill_id}/{path}`，与应用层路径规则一致。

| 方法   | 路径                                  | 说明                                                       |
|--------|---------------------------------------|------------------------------------------------------------|
| GET    | `/admin/skills/{id}/files`            | 文件清单（不含正文），支持 `prefix` 前缀过滤                |
| GET    | `/admin/skills/{id}/files/content`    | 读取单文件，参数 `path`                                     |
| PUT    | `/admin/skills/{id}/files`            | 新增或覆盖文件；写 `SKILL.md` 同步入口内容                  |
| DELETE | `/admin/skills/{id}/files`            | 删除文件，参数 `path`；删除 `SKILL.md` 清空入口内容         |
| POST   | `/admin/skills/{id}/import`           | 上传 `application/zip` 全量替换；自动去掉压缩包公共根目录    |
| GET    | `/admin/skills/{id}/export`           | 导出确定性 zip（固定时间戳，便于比对）                      |
| POST   | `/admin/skills/{id}/clone`            | 克隆到目标智能体，入参 `{agent_id, name?}`，返回 201 与独立副本 |

写入约束：

- 路径必须是相对路径，统一 `/` 分隔；拒绝 `..`、绝对路径、反斜杠、控制字符与 `: * ? " < > |` 等不可移植字符。
- 仅接受 UTF-8 文本，拒绝含 NUL 的二进制内容。
- 配额默认 200 个文件、单文件 1 MiB、整包 8 MiB，对应 `SKILL_PACKAGE_MAX_FILES` / `SKILL_PACKAGE_MAX_FILE_BYTES` / `SKILL_PACKAGE_MAX_TOTAL_BYTES`。
- `PUT` 支持 `expected_hash`：与当前文件 SHA-256 不一致返回 409，避免多人同时编辑互相覆盖。
- 全量替换（导入/目录导入）在单个事务内完成，失败不会留下半包数据。
- 删除技能时 `skill_files` 随外键级联删除。

### 8.3.2 RAG 知识库文档接口

管理端入口：**智能体详情 → 配置 → 知识库**。文档原文内联传入，ingest 由 Celery worker 异步执行。

| 方法   | 路径                          | 说明                                                                                                  |
|--------|-------------------------------|-------------------------------------------------------------------------------------------------------|
| GET    | `/admin/documents`            | 分页列表，参数 `keyword`、`agent_id`、`ingest_status`（`document:read`）                              |
| POST   | `/admin/documents`            | 创建文档元数据，状态置为 `pending`（`document:create`）                                               |
| GET    | `/admin/documents/{id}`        | 文档详情（含 `ingest_status` / `chunk_count` / `ingest_error`）                                       |
| DELETE | `/admin/documents/{id}`       | 删除文档及其全部分块（`document:delete`）                                                              |
| POST   | `/admin/documents/{id}/ingest`| 触发异步 ingest：状态置为 `queued`，投递到 Celery 队列 `rag`，立即返回（`document:update`）；`queued/processing` 中重复触发返回 409 |
| GET    | `/admin/documents/{id}/ingest` | 查询 ingest 状态（前端轮询用）                                                                         |

ingest 状态机：`pending → queued → processing → ready`（成功）或 `failed`（错误，`ingest_error` 字段记录原因，可重新触发）。

检索链路（在用户端对话时由 `AgentRunService` 自动调用，无需前端单独发起；Workflow LLM 节点开启 `retrieval.enabled` 时走同一份 `apply_rag_to_prompt()`）：

```text
   用户 query + 最近历史
            │
            ▼
   ┌────────────────────────┐
   │ ① LLM query 改写        │
   │   - standalone 指代消解 │
   │   - 生成 N 个同义变体   │
   └────────────┬───────────┘
                ▼ 多个 query 变体并行
   ┌────────────────────────┐
   │ ② Embedding (bge-large-zh) │
   │   每个变体向量化          │
   └────────────┬───────────┘
                ▼
   ┌────────────────────────┐
   │ ③ pgvector 余弦召回     │
   │   top_k × recall_mult   │
   └────────────┬───────────┘
                ▼
   ┌────────────────────────┐
   │ ④ 按 (doc_id, chunk_idx) │
   │   去重合并               │
   └────────────┬───────────┘
                ▼
   ┌────────────────────────┐
   │ ⑤ Cross-Encoder 精排    │
   │   bge-reranker-v2-m3    │
   └────────────┬───────────┘
                ▼
   ┌────────────────────────┐
   │ ⑥ rerank 阈值 0.1 过滤  │
   │   取 top_k             │
   └────────────┬───────────┘
                ▼
   ┌────────────────────────┐
   │ ⑦ 拼装注入 system_prompt │
   │   "[资料 N | 章节路径]\n│
   │    {chunk 内容}]"         │
   └────────────────────────┘
```

降级策略：rerank 失败自动退化为向量余弦过滤；query 改写失败退化为原始 query；embedding 临时故障由 Celery retry 兜底。

### 8.3.3 工作流与工具治理接口

**工作流 CRUD**（admin 端，权限 `workflow:read/create/update/delete`）：

| 方法   | 路径                                  | 说明                                                                 |
|--------|---------------------------------------|----------------------------------------------------------------------|
| GET    | `/admin/workflows`                    | 分页列表，参数 `keyword`、`is_enabled`                                |
| POST   | `/admin/workflows`                    | 创建，body 为 `{name, description, graph, is_enabled}`；graph 是 JSONB 整图 |
| GET    | `/admin/workflows/{id}`               | 详情（含完整 graph）                                                  |
| PUT    | `/admin/workflows/{id}`               | 更新（整图覆盖）                                                      |
| DELETE | `/admin/workflows/{id}`               | 删除                                                                 |
| POST   | `/admin/workflows/{id}/validate`      | 拓扑校验：环检测、start/end 唯一性、模板语法；不落库                   |
| POST   | `/admin/workflows/{id}/clone-from-template/{template_id}` | 从模板市场一键复制为新工作流 |

graph 结构示例：

```jsonc
{
  "variables": [{"key": "query", "type": "string", "required": true}],
  "nodes": [
    {"id": "start_1", "type": "start",  "position": {"x":0,"y":0},
     "data": {"output_schema": {"query": "string"}}},
    {"id": "llm_1",    "type": "llm",    "position": {"x":300,"y":0},
     "data": {"model_id": "default",
              "system_prompt_tpl": "你是助手",
              "user_prompt_tpl": "{{query}}",
              "temperature": 0.7,
              "retrieval": {"enabled": true, "document_ids": ["<uuid>"]}}},
    {"id": "end_1",    "type": "end",    "position": {"x":600,"y":0},
     "data": {"output_tpl": {"answer": "{{llm_1.output}}"}}}
  ],
  "edges": [
    {"source": "start_1", "target": "llm_1"},
    {"source": "llm_1",  "target": "end_1"}
  ]
}
```

**工具治理辅助接口**（admin 端，权限 `tool:read` / `tool:create`）：

| 方法   | 路径                            | 说明                                                                 |
|--------|---------------------------------|----------------------------------------------------------------------|
| POST   | `/admin/tools/pull-mcp-tools`    | 输入 `{server_url}`，SSRF 校验后调 MCP `list_tools`，返回工具候选列表（不落库） |
| POST   | `/admin/tools/import-mcp-tools`  | 批量入库：body 为 `{server_url, tools:[{name, description, tool_name_remote, input_schema}]}`，每个工具创建一条 `type=mcp` 的 Tool 实体 |
| POST   | `/admin/tools/parse-curl`        | 输入 `{curl_command}`，用 shlex 解析为 `{method, url, headers, body, notes}`，前端回填 HTTP 工具表单 |
| POST   | `/admin/tools/{id}/test-invoke`  | 在 admin 端试调工具，返回 `{success, duration_ms, output, error}`；不落库 |

所有出站 URL 强制经过 `ssrf_guard.validate_outbound_url()`：拒绝 loopback / 云元数据（169.254.169.254）/ 链路本地 / 组播 / 保留地址；允许 RFC1918 私网（租户内网 MCP 合法）。

### 8.4 管理员、用户与审计

管理员账号接口（平台作用域操作 `admin_users`，租户作用域操作拥有管理端入口权限的 `users`；需 `page:admin-users` 及对应按钮权限）：

| 方法   | 路径                               | 说明                                                   |
|--------|------------------------------------|--------------------------------------------------------|
| GET    | `/admin/admin-users`               | 管理员列表（关键字搜索、分页）                         |
| POST   | `/admin/admin-users`               | 创建管理员，返回 201                                   |
| PATCH  | `/admin/admin-users/{id}`          | 修改角色 / 显示名 / 启用状态                           |
| POST   | `/admin/admin-users/{id}/password` | 重置密码，返回 204                                     |
| DELETE | `/admin/admin-users/{id}`          | 删除管理员账号，返回 204                               |
| GET    | `/admin/audit-logs`                | 审计查询（按时间、用户、动作筛选）                     |

租户管理（需 `page:tenants` 及 `button:tenant:*`，仅产品级平台角色可授予）：

| 方法  | 路径                  | 说明                                 |
|-------|-----------------------|--------------------------------------|
| GET   | `/admin/tenants`      | 租户分页列表，支持 `keyword`         |
| POST  | `/admin/tenants`      | 创建租户并初始化租户管理员，返回 201 |
| GET   | `/admin/tenants/{id}` | 租户详情                             |
| PATCH | `/admin/tenants/{id}` | 修改租户名称或启用状态               |

管理员账号没有跨租户查询入口：产品级平台只能维护 `admin_users`，租户管理员则通过本租户的用户管理页维护。创建租户时同步创建租户超管用户，不再写入 `admin_users`。

- 审计查询同样按作用域过滤：租户只返回本租户记录，平台返回全部记录。

### 8.4.1 角色、用户与授权

角色接口（平台管理平台角色，租户管理本租户角色；两者数据隔离）。平台默认只能看到平台角色，传 `tenant_id` 查询租户角色返回 403；租户无法看到平台角色：

| 方法   | 路径                  | 说明                                                       |
|--------|-----------------------|------------------------------------------------------------|
| GET    | `/admin/roles`        | 角色列表，参数 `include_inactive`（`page:roles`）           |
| POST   | `/admin/roles`        | 创建角色，返回 201（`button:role:create`）；新角色默认无功能权限，产品级入口创建的角色为系统角色 |
| POST   | `/admin/roles/{id}/copy` | 复制角色、功能权限与数据授权，入参 `{code,name,description?}`，返回 201（`button:role:copy`）；副本为自定义角色，`superadmin` 不支持复制 |
| GET    | `/admin/roles/{id}`   | 角色详情（`page:roles`）                                    |
| PATCH  | `/admin/roles/{id}`   | 修改名称/描述/启停（`button:role:update`）；系统角色不可停用 |
| DELETE | `/admin/roles/{id}`   | 删除角色（`button:role:delete`）；系统角色、被账号或授权引用时拒绝 |

角色功能权限接口（权限目录只读，授权需 `button:role:grant`；`superadmin` 角色不可单独调整）：

| 方法   | 路径                                    | 说明                                                     |
|--------|-----------------------------------------|----------------------------------------------------------|
| GET    | `/admin/permissions`                    | 当前作用域可授权的功能权限目录（`page:roles`）           |
| GET    | `/admin/roles/{id}/permissions`         | 角色已授予的功能权限，返回 `items` 与 `codes`（`page:roles`） |
| PUT    | `/admin/roles/{id}/permissions`         | 整体替换，入参 `{codes}`                                 |
| POST   | `/admin/roles/{id}/permissions`         | 追加授权，入参 `{codes}`                                 |
| DELETE | `/admin/roles/{id}/permissions/{code}`  | 移除单个功能权限                                         |

角色数据授权接口（需 `button:role:grant`；`superadmin` 角色默认拥有全部资源，只读）：

| 方法   | 路径                                         | 说明                                     |
|--------|----------------------------------------------|------------------------------------------|
| GET    | `/admin/roles/{id}/grants`                   | 授权候选/已授权资源，参数 `resource_type`、`granted_only` |
| GET    | `/admin/roles/{id}/grants/summary`           | 各资源类型的有效授权数量                 |
| POST   | `/admin/roles/{id}/grants/{resource_type}`   | 追加授权，入参 `{resource_ids}`          |
| PUT    | `/admin/roles/{id}/grants/{resource_type}`   | 整体替换授权，空数组表示清空             |
| DELETE | `/admin/roles/{id}/grants/{resource_type}/{resource_id}` | 移除单个资源授权               |

平台角色的授权对象只能是平台级资源（`tenant_id IS NULL`）；平台账号绑定 `admin` / `viewer` / 自定义平台角色后，只能看到授权给该角色的平台资源。

用户接口（租户作用域）：

| 方法   | 路径                         | 说明                                     |
|--------|------------------------------|------------------------------------------|
| GET    | `/admin/users`               | 分页查询，参数 `keyword`                 |
| POST   | `/admin/users`               | 创建用户并绑定 `role_ids`（至少一个）    |
| PATCH  | `/admin/users/{id}`          | 修改显示名、`role_ids`、启用状态         |
| POST   | `/admin/users/{id}/password` | 重置密码，返回 204                       |
| DELETE | `/admin/users/{id}`          | 删除用户，返回 204                       |

授权接口：

| 方法 | 路径                                        | 说明                                                                              |
|------|---------------------------------------------|-----------------------------------------------------------------------------------|
| GET  | `/admin/grants/overview?resource_type=`     | 分页查询可授权资源及授权汇总，参数 `page`、`page_size`、`keyword`、`grant_state`   |
| GET  | `/admin/grants?resource_type=&resource_id=` | 查询资源授权，可选 `tenant_id`；租户视角只返回本租户记录                           |
| PUT  | `/admin/grants/batch`                       | 批量授权，入参 `{resource_type, resource_ids, mode, tenant_id?, role_ids}`        |
| PUT  | `/admin/grants?resource_type=&resource_id=` | 整体替换单资源授权，入参 `{grants:[{tenant_id, role_id?}]}`；幂等                   |

- `resource_type` 取值：`agent`、`skill`、`tool`、`component`、`prompt`。
- `role_id` 为空表示授予整个租户（该租户所有角色可见）。
- 产品级 superadmin 可操作任意租户；租户 superadmin 仅限本租户角色。

`overview` 只返回当前作用域**可管理**的资源：平台视角为平台级资源，租户视角为本租户自有资源；并返回 `grant_count`、`tenant_count`、`role_count` 与 `is_default_visible`（租户自有资源且无授权时为 `true`）。`grant_state` 取 `granted` 或 `ungranted`，按目标作用域的直接授权记录过滤。列表不返回授权明细，抽屉再按租户按需加载，避免迁移回填产生的大量授权记录进入列表响应。

`batch` 的 `mode` 取值为 `merge`（追加角色）、`replace`（覆盖该租户授权）、`clear`（清空该租户授权）；所有模式都只作用于 `tenant_id` 指定的租户，不会影响其他租户。平台可选「整个租户」或「指定角色」，租户视角在 `merge` / `replace` 时必须指定本租户角色；`clear` 后租户自有资源恢复为全部角色可见，平台资源则该租户不可见。

- 单次最多 100 个资源，资源 id 自动去重；任一资源不存在或无权管理时整批返回 404 且不写入。
- 平台调用 `batch` 必须指定存在的租户；角色必须属于目标租户，否则返回 422。
- 批量写入先按资源排序获取 advisory lock，再读取旧授权并逐资源写入；同一事务内完成并逐资源记录 `grant.updated` 审计（before/after 仅包含目标租户）。
- 单资源 `PUT /admin/grants` 保留用于兼容与脚本调用，语义为整体替换该资源的全部授权。

### 8.5 运维端点

| 方法 | 路径            | 说明                                         |
|------|-----------------|----------------------------------------------|
| GET  | `/health/live`  | 进程是否存活                                 |
| GET  | `/health/ready` | 数据库连通且迁移版本与代码一致；失败返回 503 |
| GET  | `/metrics`      | Prometheus 指标；生产由 Nginx 拒绝外部访问   |

业务指标清单（带 `tenant` / `tool` / `model` 标签，`tenant` 用短码 `platform` 或前 8 位 UUID，避免标签爆炸）：

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `boxia_http_request_duration_seconds` | Histogram | 每个 HTTP 接口耗时 |
| `boxia_llm_request_duration_seconds` | Histogram | LLM `/chat/completions` 耗时（按 model / status 分桶） |
| `boxia_llm_tokens_total` | Counter | LLM token 用量（prompt / completion 分类） |
| `boxia_tool_invoke_duration_seconds` | Histogram | 工具调用耗时（按 tenant / tool / status 分桶） |
| `boxia_tool_invoke_total` | Counter | 工具调用次数（含 success / error / circuit_open / rate_limited） |
| `boxia_agent_run_iterations` | Histogram | 单次 agent 运行的 function calling 迭代数 |

### 8.6 用户端接口

用户端站点（`web.app_user:app`）只有 `/api/v1/user/**`，与管理端完全隔离。最终用户由租户管理员在管理端“用户管理”中创建并绑定角色：

| 方法 | 路径                            | 说明                                                                 |
|------|---------------------------------|----------------------------------------------------------------------|
| POST | `/user/auth/login`              | 账号密码登录，返回 access/refresh、有效期与用户角色信息              |
| POST | `/user/auth/refresh`            | 轮换刷新令牌；检测到重放会撤销整个会话族                             |
| POST | `/user/auth/logout`             | 撤销当前会话族，返回 204                                             |
| GET  | `/user/me`                      | 当前用户、所属租户、角色与功能权限编码                               |
| GET  | `/user/agents`                   | 分页查询当前角色可见且已启用的智能体，支持 `keyword`                 |
| GET  | `/user/agents/{id}`              | 智能体详情及已过滤的技能/工具/组件/提示词；不可见统一返回 404        |
| POST | `/user/agents/{id}/run`          | 同步运行智能体，返回完整 final 文本 + 工具调用轨迹 + usage            |
| POST | `/user/agents/{id}/run/stream`   | SSE 流式运行：边跑边推 `run_start / llm_start / llm_delta / tool_start / tool_end / final` 事件，前端 ChatPage 逐字渲染 |
| GET  | `/user/workflows`                | 分页查询当前角色可见且已启用的工作流（我的 + 平台模板）              |
| POST | `/user/workflows/{id}/run`        | 同步运行一次工作流，body 为 `{"inputs":{"query":"..."},"conversation_id":"..."}`；返回 `outputs`、每节点状态/耗时/错误、usage、finish_reason |
| POST | `/user/workflows/{id}/run/stream` | SSE 流式运行工作流：边跑边推 `node_start / node_end / result` 事件，画布可实时高亮节点状态 |

- 鉴权：Access Token + Refresh Token，与管理员令牌使用不同 `aud`（`USER_JWT_AUDIENCE`），两端令牌不能互相冒用。
- 租户作用域：必须通过租户子域名访问（`<租户编码>.<ROOT_DOMAIN>`）；平台域名或未知域名返回 404/403。登录与刷新令牌都校验租户一致性。
- 可见性：在租户规则上追加 `is_enabled=true`，角色集合仅本人 `role_id`；未显式授权的智能体不可见。
- 实例级可见范围：管理端可为租户智能体配置 `visibility_mode=custom` 与可见部门（含子树）/指定人员列表；user 端查询在租户授权之上叠加该过滤，未命中返回 404。无当前任职的用户仅命中 `all` 模式与直接指定的 `user_id` 规则。
- 用户端站点不挂载 `/admin/**` 与 `/public/**`；用户登录、刷新重放与登出写入审计日志。

**SSE 事件帧格式**（`/run/stream` 接口）：

```text
event: run_start
data: {"run_id":"...","agent_id":"..."}

event: llm_start
data: {"model":"deepseek-chat"}

event: llm_delta
data: {"text":"你"}

event: llm_delta
data: {"text":"好"}

event: tool_start
data: {"tool_name":"query_erp","arguments":{"q":"北京天气"}}

event: tool_end
data: {"tool_name":"query_erp","output":"晴天 25℃","duration_ms":234}

event: final
data: {"content":"今天北京晴天 25℃","usage":{"prompt_tokens":123,"completion_tokens":45}}
```

工作流流式接口用相同的帧格式，但事件名为 `node_start` / `node_end`（携带 `node_id` / `node_type` / `status`），最终事件为 `result`（携带完整 outputs）。响应头带 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`（Nginx 不缓冲）。

### 8.7 调用示例（Git Bash）

```bash
# 登录
LOGIN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/admin/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"你的密码"}')
TOKEN=$(echo "$LOGIN" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 查询智能体列表
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/admin/agents?page=1&page_size=10"

# 创建一条技能
curl -X POST http://127.0.0.1:8000/api/v1/admin/skills \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"剧本生成","description":"示例","content":"生成剧本","config":{}}'

# 本地开发：按租户作用域登录（产品级用 platform；部署环境忽略该请求头）
# 需要 APP_ENV=local 且 ALLOW_TENANT_HEADER=true
# acme-admin 是创建租户时填写的管理员用户名，实际使用时替换成你的账号
TENANT_LOGIN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/admin/auth/login \
  -H 'X-Tenant-Code: acme' -H 'Content-Type: application/json' \
  -d '{"username":"acme-admin","password":"你的密码"}')
```

> 域名优先：访问 `<code>.localhost` 或部署环境子域名时，`X-Tenant-Code` 会被忽略。只有本地回环主机（`localhost` / `127.0.0.1` 等）才允许用请求头切换作用域。

> PowerShell 中 `curl` 是别名，请改用 `curl.exe`。

### 8.8 错误响应

```json
{ "detail": "错误说明", "code": "ERROR_CODE", "request_id": "..." }
```

| 状态码 | code                              | 含义                                   |
|--------|-----------------------------------|----------------------------------------|
| 400    | `BAD_REQUEST`                     | 请求不合法                             |
| 401    | `UNAUTHORIZED`                    | 未登录，或令牌无效/过期/已撤销         |
| 403    | `FORBIDDEN`                       | 角色不足或账号被禁用                   |
| 404    | `NOT_FOUND`                       | 资源不存在                             |
| 409    | `CONFLICT`                        | 名称重复或唯一约束冲突                 |
| 422    | `VALIDATION_ERROR`                | 参数或业务校验失败（含 `errors` 明细） |
| 429    | `ACCOUNT_LOCKED` / `RATE_LIMITED` | 登录锁定或触发限流，含 `Retry-After`   |
| 500    | `INTERNAL_ERROR`                  | 服务异常，只返回通用文案，堆栈只进日志 |
| 503    | `SERVICE_UNAVAILABLE`             | 依赖不可用（如就绪检查失败）           |

---

## 9. 数据库与迁移

### 9.1 表结构

| 表                                            | 说明                                                                                     |
|-----------------------------------------------|------------------------------------------------------------------------------------------|
| `tenants`                                     | 租户编码（即子域名前缀）、名称、启用状态                                                 |
| `admin_users`                                 | 产品级平台账号、绑定平台角色 `role_id`、锁定状态、`token_version`、首登改密标记；不保存租户维度 |
| `admin_refresh_tokens`                        | 产品级平台 Refresh Token 哈希、会话链、轮换/撤销状态、IP/UA                              |
| `roles`                                       | 平台或租户角色：`tenant_id`（`NULL` 为平台角色）、`code`、`name`、`description`、`is_system`（系统角色不可删/不可停用）、启用状态 |
| `permission_resources`                        | 全局功能权限目录（只读）：`code` 唯一、`category`、`action`、`sort_order`、启用状态         |
| `role_permissions`                            | 角色与权限资源的多对多关系；`(role_id, permission_id)` 唯一，记录授予人                        |
| `users`                                       | 租户管理员与普通用户统一账号、密码哈希、主角色 `role_id`、锁定状态、`token_version`；`(tenant_id, username)` 唯一；带 `UNIQUE(tenant_id,id)` 供复合外键引用 |
| `departments`                                 | 租户部门树：`parent_id` 自引用（根为 NULL）、物化路径 `path=/<root>/.../<self>/`、`level`（1..10）、`code`（租户内唯一）、`sort_order`、`is_active`；`UNIQUE(tenant_id,id)`、`UNIQUE(tenant_id,path)`，子树查询用 `text_pattern_ops` 索引 |
| `user_employments`                            | 用户任职记录：`user_id` 复合 FK `(tenant_id,user_id)`、`department_id` 复合 FK `(tenant_id,department_id)`、`position`、`is_current`、`started_at`、`ended_at`（历史必填）；部分唯一索引 `(tenant_id,user_id) WHERE is_current` 保证单一主任职 |
| `user_roles`                                  | 用户与租户角色的多对多关系；租户管理员通过角色的 `system:console:access` 获得管理端权限     |
| `user_refresh_tokens`                         | 租户用户 Refresh Token 哈希、会话族、轮换/撤销状态、IP/UA                                |
| `resource_grants`                             | 多态授权：`resource_type`（agent/skill/tool/component/prompt）+ `resource_id` + 可空 `tenant_id` + 可空 `role_id`；`tenant_id` 非空且 `role_id=NULL` 表示整个租户，`tenant_id=NULL` 表示平台角色授权 |
| `audit_logs`                                  | 审计日志（操作者、动作、资源、`request_id`、详情 JSONB）；`tenant_id` 决定哪些作用域可见 |
| `agents`                                      | 智能体，`config` 为 JSONB 完整配置；`department_id` 可空（租户智能体挂接部门，复合 FK `(tenant_id,department_id)`，平台智能体必须为 NULL）；`visibility_mode`（`all`/`custom`）控制 user 端实例级可见范围，默认 `all` |
| `skills` / `tools` / `components` / `prompts` | 四类资源表；`agent_id` 为数据归属的智能体（可空，历史数据通过迁移回填）                   |
| `skill_files`                                 | 技能包内文本文件；`(skill_id, path)` 唯一，随技能级联删除，归属由所属技能决定              |
| `agent_tools` / `agent_skills`                | 旧版智能体关联表，仅兼容保留（deprecated）；新代码以资源 `agent_id` 为准                   |
| `agent_visibility_departments`                | 智能体可见部门关联：`(agent_id, department_id)` 复合主键，`include_subtree` 表示是否按部门物化路径前缀命中子树 |
| `agent_visibility_users`                      | 智能体可见人员关联：`(agent_id, user_id)` 复合主键；被指定用户即使无当前任职也直接命中     |
| `documents`                                    | RAG 知识库文档：`title`、`source_type`（markdown/text/pdf...）、`raw_content`（原文）、`agent_id`（绑定智能体，可空）、`ingest_status`（`pending/queued/processing/ready/failed`）、`ingest_error`、`chunk_count` |
| `document_chunks`                             | 文档分块：`document_id` FK、`chunk_index`、`content`、`embedding`（pgvector 1024 维）、`metadata` JSONB（含 `heading_path` 标题路径）；向量列建 HNSW cosine 索引 |
| `workflows`                                    | 工作流：`name`、`description`、`graph` JSONB（`{variables, nodes, edges}` 整图）、`is_enabled`、`visibility_mode`、`created_by`；`tenant_id` NOT NULL，产品级为全零 UUID |
| `workflow_templates`                          | 工作流模板市场：产品管理员发布的样板工作流，结构同 `workflows`；租户通过 `clone-from-template` 一键复制为自己的工作流 |
| `alembic_version`                             | 当前迁移版本                                                                             |

约定：

- 资源与审计记录都带 `tenant_id`：**迁移 `0024_platform_tenant_migration` 后所有表该字段一律 NOT NULL**；产品级资源统一使用全零 UUID `00000000-0000-0000-0000-000000000000`（常量 `PLATFORM_TENANT_ID`），不再使用 `NULL` 表示产品级。UoW 过滤统一为 `tenant_id IN (当前租户, PLATFORM_TENANT_ID)`。平台账号表 `admin_users` 不保存租户维度，通过 `role_id` 绑定平台角色。
- 资源名称与用户名按作用域唯一：唯一索引为 `(COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'), lower(name))` 与 `(COALESCE(tenant_id, ...), username)`，不同租户可以同名；应用层额外禁止租户与产品级资源重名。
- 所有表都有 `created_at` / `updated_at`，`updated_at` 由触发器维护。
- 列表默认按 `updated_at DESC, id DESC` 排序。
- 资源名称和描述使用 `pg_trgm` 索引，支持模糊搜索。
- RAG 向量列依赖 `pgvector` 扩展：迁移 `0022_rag_documents` 会自动 `CREATE EXTENSION IF NOT EXISTS vector`，但 PostgreSQL 镜像必须预装该扩展（推荐 `pgvector/pgvector:pg17`）；自建外部库时需 DBA 先装好 `vector` 包。
- 迁移 `0006_roles_and_resource_access` 新增角色、最终用户、授权表与资源 `agent_id`，并为存量数据回填系统角色、归属与租户授权；DDL 支持 downgrade，但数据回填不可逆，升级前必须备份并在预发库演练。
- 迁移 `0025_workflows` 建 `workflows` / `workflow_templates` 两表（直接 NOT NULL）；`0026_workflow_permissions` 预置 `workflow:read/create/update/delete` 权限并回填内置角色；`0027_tool_menu_permissions` 预置 `menu:tools` / `page:tools` 菜单权限。
- 迁移 `0010_platform_roles` 引入平台角色与平台角色授权：`roles.tenant_id`、`resource_grants.tenant_id` 允许为空，回填 `admin_users.role_id`，并把存量平台资源授权给平台 `admin` / `viewer` 角色（`superadmin` 默认全量可见）。降级会丢失平台角色绑定与授权，需先备份。
- 迁移 `0011_rbac_permission_resources` 新增 `permission_resources` 与 `role_permissions`，移除 `roles.system_role` 与 `admin_users.role`，并按原 `system_role` 回填内置角色的功能权限（空角色平台账号回退到平台只读角色）。降级会重建 `roles.system_role` 与 `admin_users.role` 字段，但角色功能权限关系不可恢复，回滚前必须备份 `role_permissions`。
- 迁移 `0015_organization` 新增 `departments` / `user_employments` 表、给 `users` 加 `UNIQUE(tenant_id,id)`、给 `agents` 加 `department_id` 列与复合外键，并回填租户侧系统角色的组织架构权限（`menu:departments`、`menu:employments`、`page:departments`、`page:employments`、`button:department:*`、`button:employment:*`）。DDL 支持 downgrade。
- 迁移 `0020_agent_visibility` 给 `agents` 加 `visibility_mode`（默认 `all`）与 CheckConstraint，新建 `agent_visibility_departments` / `agent_visibility_users` 两张关联表；仅作用于租户智能体的 user 端可见过滤，管理端列表不受影响。DDL 支持 downgrade。

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

### 9.3 初始化与演示数据

```bash
# 创建或重置管理员（默认首次登录强制改密）
uv run python -m scripts.create_admin

# 为指定租户创建管理员（租户需已存在；不传 TENANT_CODE 则创建产品级账号）
TENANT_CODE=acme uv run python -m scripts.create_admin

# 自动化环境可跳过首登改密（仅测试/演示）
ADMIN_MUST_CHANGE_PASSWORD=false uv run python -m scripts.create_admin

# 写入本地演示资源（幂等，可重复执行；写入产品级资源，需授权后租户才可见）
uv run python -m scripts.seed_demo

# 技能包运维：目录导入 / 导出 / 克隆到租户 / 列文件
uv run python -m scripts.skill_package import --dir ../skills/foo --name "技能名"
uv run python -m scripts.skill_package import --dir ./foo --name "技能名" --tenant acme --replace
uv run python -m scripts.skill_package export --id 3 --output ./exported
uv run python -m scripts.skill_package clone --id 3 --tenant acme --name "技能副本"
uv run python -m scripts.skill_package list --id 3
```

---

