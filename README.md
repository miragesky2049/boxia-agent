# boxia-agent

基于大语言模型的智能体开发与运营平台，采用前后端分离架构：

- **后端**：Python 3.12 + FastAPI + PostgreSQL，DDD 分层，提供管理端（admin）与用户端（user）接口
- **管理端前端**：React 19 + TypeScript + Ant Design 5，覆盖登录、智能体、技能、工具、组件、提示词与管理员管理
- **用户端前端**：React + TypeScript，面向最终用户（当前为骨架）
- **交付形态**：Docker Compose + Nginx 一键部署，Alembic 版本化迁移，GitHub Actions 质量门禁

管理端已按生产标准完成工程化：短时效 Access Token + 可撤销 Refresh Token、RBAC、登录防爆破、审计日志、统一错误模型、请求追踪、结构化日志、Prometheus 指标、健康检查、数据库迁移与备份恢复。

---

## 目录

- [1. 技术栈](#1-技术栈)
- [2. 项目结构](#2-项目结构)
- [3. 本地开发](#3-本地开发)
- [4. 配置说明](#4-配置说明)
- [5. 认证与权限](#5-认证与权限)
- [6. 接口说明](#6-接口说明)
- [7. 数据库与迁移](#7-数据库与迁移)
- [8. 管理端功能](#8-管理端功能)
- [9. 测试与质量门禁](#9-测试与质量门禁)
- [10. 生产部署](#10-生产部署)
- [11. 运维手册](#11-运维手册)
- [12. 安全验收清单](#12-安全验收清单)
- [13. 常见问题](#13-常见问题)

---

## 1. 技术栈

| 层级 | 技术 | 说明 |
| --- | --- | --- |
| 后端语言 | Python 3.12+ | 依赖与虚拟环境由 `uv` 管理 |
| Web 框架 | FastAPI + Uvicorn | 同步 ORM，配合 FastAPI 线程池 |
| 持久化 | PostgreSQL 17 + SQLAlchemy 2.0 + psycopg3 | 智能体配置使用 JSONB |
| 数据库迁移 | Alembic | 基线 + 增量迁移，启动就绪检查校验版本 |
| 认证 | PyJWT（HS256）+ bcrypt | Access Token + 数据库持久化 Refresh Token |
| 可观测性 | 结构化日志、request_id、OpenTelemetry、Prometheus | 访问日志、链路追踪、HTTP/业务指标 |
| 管理端 | React 19 + TypeScript + Vite 8 + Ant Design 5 | `react-router-dom` 7，按路由懒加载 |
| 测试 | pytest + httpx；Vitest + Testing Library；Playwright | 接口、组件、端到端全链路 |

---

## 2. 项目结构

```text
boxia-agent/
├── backend/
│   ├── web/                          # HTTP 层
│   │   ├── app.py                    # 应用工厂：中间件、异常处理、健康检查、指标、路由
│   │   ├── api_v1.py                 # /api/v1 路由聚合（legacy /api 别名）
│   │   ├── errors.py                 # 统一异常处理与错误响应
│   │   ├── health.py                 # /health/live、/health/ready
│   │   ├── admin/                    # 管理端接口与请求/响应模型
│   │   │   ├── auth.py               # 登录、刷新、登出、改密、当前用户
│   │   │   ├── users.py              # 管理员管理（superadmin）
│   │   │   ├── audit_logs.py         # 审计查询（superadmin）
│   │   │   ├── agents.py             # 智能体 CRUD
│   │   │   ├── skills.py             # 技能 CRUD
│   │   │   ├── tools.py              # 工具 CRUD
│   │   │   ├── components.py         # 组件 CRUD
│   │   │   ├── prompts.py            # 提示词 CRUD
│   │   │   ├── schemas.py            # 通用契约
│   │   │   └── agent_schema.py       # 智能体配置契约
│   │   ├── user/                     # 用户端接口（骨架）
│   │   └── deps/                     # 数据库 UoW、服务、鉴权依赖
│   ├── internal/                     # 内部实现（DDD）
│   │   ├── domain/                   # 实体、分页对象、仓储协议
│   │   ├── application/              # 用例服务、统一业务异常
│   │   └── infrastructure/
│   │       ├── config/               # pydantic-settings 配置与生产校验
│   │       ├── model/                # SQLAlchemy 引擎、ORM、UnitOfWork
│   │       ├── repository/           # PostgreSQL 仓储实现
│   │       ├── security/             # JWT、密码哈希与强度校验
│   │       ├── observability/        # 日志、request_id、指标
│   │       └── middleware/           # 访问日志、安全头、审计、请求 ID
│   ├── migrations/                   # Alembic 迁移（0001 基线、0002 认证加固、0003 搜索索引）
│   ├── scripts/                      # create_admin / seed_demo / wait_for_db
│   ├── db/                           # 历史手工 SQL（仅本地演示，非事实来源）
│   ├── tests/                        # pytest 接口测试
│   ├── Dockerfile                    # 非 root、多阶段、健康检查
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── .env.example
├── frontend/
│   ├── admin/                        # 管理端（开发端口 5173）
│   │   ├── src/
│   │   │   ├── api/                  # 请求封装、刷新队列、类型
│   │   │   ├── auth/                 # 登录态、令牌存储、路由守卫
│   │   │   ├── components/           # 错误边界、通用资源列表等
│   │   │   ├── layouts/              # 管理后台布局
│   │   │   ├── pages/                # 登录、改密、用户、资源、智能体配置
│   │   │   └── router.tsx            # 懒加载路由与 404
│   │   ├── e2e/                      # Playwright 端到端用例
│   │   ├── nginx/                    # 生产 Nginx 配置（SPA、反代、限流、安全头）
│   │   └── Dockerfile                # Node 构建 + nginx-unprivileged 运行
│   └── user/                         # 用户端（骨架，端口 5174）
├── ops/                              # 跨端运维入口（本地开发 + 生产部署）
│   ├── docker-compose.yml            # 生产编排：db / migrate / backend / frontend
│   ├── .env.production.example       # 生产环境变量模板
│   ├── dev.sh                        # 本地一键启动（后端热重载 + Vite）
│   ├── check.sh                      # 本地质量门禁（与 CI 一致）
│   ├── backup.sh                     # pg_dump custom 格式备份
│   └── restore.sh                    # 二次确认恢复
├── .github/workflows/                # CI、镜像构建与 GHCR 发布
├── .pre-commit-config.yaml           # Git 钩子（必须在仓库根目录）
└── README.md
```

根目录文件说明：

| 路径 | 用途 | 为什么在根目录 |
| --- | --- | --- |
| `backend/`、`frontend/` | 两个可独立构建的应用 | 业务代码按端拆分 |
| `ops/` | 跨端的开发、检查、部署与备份脚本 | 不属于某一个端 |
| `.github/workflows/` | CI 与镜像发布 | GitHub 固定读取路径 |
| `.pre-commit-config.yaml` | 提交前质量钩子 | pre-commit 默认只从仓库根目录发现配置 |

### 关键约定

1. **前后端完全分离**：开发环境由 Vite 代理 `/api`，生产环境由 Nginx 反向代理。
2. **接口分区**：管理端在 `backend/web/admin/`，用户端在 `backend/web/user/`；`web/admin/router.py` 统一挂载 `require_admin`，新增管理端路由默认受保护。
3. **分层原则**：Web 层只做参数校验与协议转换，业务规则在 `internal/application`，持久化在 `internal/infrastructure/repository`。
4. **事务边界**：仓储只 `flush()` 不提交，应用服务在用例结束前统一 `uow.commit()`；审计与业务同事务。

---

## 3. 本地开发

### 3.0 环境准备

```bash
python --version   # 3.12+
uv --version       # 未安装：winget install astral-sh.uv 或 pip install uv
node --version     # ^20.19.0 或 >=22.12.0
npm --version      # 10+
docker --version   # 用于启动本地 PostgreSQL
```

### 3.1 启动数据库

```bash
# 仓库根目录执行
docker compose -f backend/docker/docker-compose.yml up -d
docker exec postgres pg_isready -U postgres -d boxia_agent
```

### 3.2 初始化后端

```bash
cd backend

cp .env.example .env     # Windows: copy .env.example .env
uv sync
uv run alembic upgrade head

# 创建管理员（默认强制首次登录改密）
ADMIN_USERNAME=admin ADMIN_PASSWORD='请替换为合规强密码' uv run python -m scripts.create_admin

# 可选：写入本地演示资源
uv run python -m scripts.seed_demo

uv run uvicorn web.app:app --reload
```

启动成功后：

- 存活检查 <http://127.0.0.1:8000/health/live>
- 就绪检查 <http://127.0.0.1:8000/health/ready>（数据库连通且迁移版本一致）
- Swagger <http://127.0.0.1:8000/docs>（非生产默认开启）

密码策略：至少 12 位，包含大小写字母、数字、符号中的至少三类，且不能包含用户名。

### 3.3 启动管理端

```bash
cd frontend/admin
npm ci
npm run dev
```

打开 <http://localhost:5173>，使用上一步创建的管理员登录。首次登录会跳转 `/change-password`，修改密码后重新登录。

### 3.4 启动用户端（可选）

```bash
cd frontend/user
npm ci
npm run dev     # http://localhost:5174
```

### 3.5 一键启动

```bash
# 仓库根目录；基于 Git Bash，自动迁移并同时启动前后端
./ops/dev.sh
```

### 3.6 服务地址

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 管理端 | <http://localhost:5173> | 登录后进入管理后台 |
| 用户端 | <http://localhost:5174> | Agent Chat（骨架） |
| 后端 | <http://127.0.0.1:8000/> | 欢迎信息（含 trace_id） |
| 健康检查 | `/health/live`、`/health/ready` | 存活 / 就绪 |
| Swagger | <http://127.0.0.1:8000/docs> | 开发环境在线调试 |

---

## 4. 配置说明

后端通过 `pydantic-settings` 加载 `backend/.env`，进程环境变量优先级更高。生产环境启动时会执行硬校验，配置不合法直接失败。

| 变量 | 默认值 | 必填 | 说明 |
| --- | --- | --- | --- |
| `APP_ENV` | `development` | 否 | `development` / `test` / `production` |
| `DATABASE_URL` | 无 | **是** | `postgresql+psycopg://user:pass@host:5432/db` |
| `DATABASE_POOL_SIZE` | `10` | 否 | 连接池大小 |
| `DATABASE_MAX_OVERFLOW` | `10` | 否 | 池溢出连接数 |
| `DATABASE_POOL_TIMEOUT` | `10` | 否 | 获取连接超时（秒） |
| `DATABASE_POOL_RECYCLE` | `1800` | 否 | 连接回收周期（秒） |
| `STATEMENT_TIMEOUT_MS` | `5000` | 否 | 单条 SQL 超时 |
| `LOCK_TIMEOUT_MS` | `3000` | 否 | 锁等待超时 |
| `JWT_SECRET` | 无 | **是** | 生产至少 32 字符且不得为示例值（`openssl rand -hex 32`） |
| `ACCESS_TOKEN_MINUTES` | `30` | 否 | Access Token 有效期 |
| `REFRESH_TOKEN_DAYS` | `14` | 否 | Refresh Token 有效期 |
| `BCRYPT_ROUNDS` | `12` | 否 | bcrypt 成本因子 |
| `LOGIN_MAX_ATTEMPTS` | `5` | 否 | 连续失败锁定阈值 |
| `LOGIN_LOCK_MINUTES` | `15` | 否 | 锁定时长 |
| `CORS_ORIGINS` | 空 | 否 | 逗号分隔白名单；生产禁止 `*` |
| `DOCS_ENABLED` | 生产关闭 | 否 | 是否暴露 Swagger/OpenAPI |
| `LEGACY_API_ENABLED` | `true` | 否 | 保留 `/api` 兼容别名（下一版本周期移除） |
| `USER_API_TOKEN` | 空 | 否 | 用户端骨架令牌；生产启用时至少 32 字符 |
| `LOG_LEVEL` | `INFO` | 否 | 日志级别 |
| `LOG_JSON` | 生产默认 `true` | 否 | 是否输出 JSON 日志 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 空 | 否 | 配置后上报 OTLP；生产未配置则不导出 |
| `OTEL_SERVICE_NAME` | `boxia-agent` | 否 | 链路服务名 |
| `OTEL_TRACES_SAMPLER_RATIO` | `1.0` | 否 | 采样率 |
| `WEB_CONCURRENCY` | `2`（镜像） | 否 | Uvicorn worker 数 |

> `.env` 与 `ops/.env.production` 均不应提交到 Git。

---

## 5. 认证与权限

### 5.1 令牌模型

- **Access Token**：JWT（HS256，默认 30 分钟），仅存前端内存，不落 localStorage。
- **Refresh Token**：`bxt_` + 随机串，默认 14 天；数据库仅保存 SHA-256 哈希。
- 刷新采用**单次轮换**：旧令牌立即失效并签发同族新令牌；检测到已轮换/已撤销令牌重放时，撤销整族并要求重新登录。
- 登出撤销当前会话族；改密、禁用、删除用户会递增 `token_version` 并撤销全部令牌，Access Token 立即失效。
- 前端刷新使用 Web Locks 单飞 + 请求排队重放，避免多标签页并发刷新；`BroadcastChannel` 同步跨标签页登录/登出。

### 5.2 登录防护

- 未知用户名执行固定 bcrypt 校验，避免用户名枚举与时序差异。
- 连续 5 次密码错误锁定 15 分钟，返回 `429` + `Retry-After` + `ACCOUNT_LOCKED`。
- 登录成功清零失败计数。
- Nginx 对登录接口限制 `10r/m`，普通 API `30r/s`，超限返回 429。

### 5.3 RBAC

| 角色 | 资源读 | 资源写 | 管理员管理 | 审计查询 |
| --- | --- | --- | --- | --- |
| `superadmin` | 是 | 是 | 是 | 是 |
| `admin` | 是 | 是 | 否 | 否 |
| `viewer` | 是 | 否 | 否 | 否 |

每次请求以数据库中的实时角色与状态为准，不信任令牌内的角色快照。

### 5.4 审计

登录成功/失败、登出、改密、资源写操作、管理员管理均写入 `audit_logs`，包含操作者、动作、资源、`request_id`、IP、User-Agent 与详情。业务审计与业务写入同事务；认证失败使用独立短事务。

---

## 6. 接口说明

统一前缀 `/api/v1`。为兼容现有调用，`LEGACY_API_ENABLED=true` 时同时注册 `/api` 别名（不进入 OpenAPI）。除登录、刷新外，管理端接口均需：

```http
Authorization: Bearer <access_token>
```

### 6.1 认证接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/admin/auth/login` | 返回 access/refresh、有效期与用户信息（含 `must_change_password`） |
| POST | `/admin/auth/refresh` | 轮换 refresh，返回新的 access/refresh |
| POST | `/admin/auth/logout` | 撤销当前会话族，204 |
| POST | `/admin/auth/password` | 修改密码并撤销全部会话，204 |
| GET | `/admin/auth/me` | 当前管理员信息（含角色） |

### 6.2 资源接口

`{resource}` 为 `agents` / `skills` / `tools` / `components` / `prompts`：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/{resource}` | 分页查询，参数 `page`、`page_size`（≤100）、`keyword`、`is_enabled` |
| POST | `/admin/{resource}` | 创建，201（viewer 403） |
| GET | `/admin/{resource}/{id}` | 详情 |
| PUT | `/admin/{resource}/{id}` | 全量更新（viewer 403） |
| DELETE | `/admin/{resource}/{id}` | 删除，204（viewer 403） |

分页响应：

```json
{ "items": [], "total": 0, "page": 1, "page_size": 20 }
```

智能体额外字段：

- 创建/更新可传 `config`（对象）、`tool_ids`、`skill_ids`；关联 ID 自动去重并校验存在性。
- 列表返回摘要（不含 `config` / 关联 ID），详情返回全量配置与关联。
- `config` 未提供的子项由后端补默认值。

### 6.3 管理员与审计（superadmin）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/admin/users` | 管理员列表（关键字搜索、分页） |
| POST | `/admin/users` | 创建管理员，201 |
| PATCH | `/admin/users/{id}` | 修改角色/显示名/启用状态 |
| POST | `/admin/users/{id}/password` | 重置密码，204 |
| GET | `/admin/audit-logs` | 审计日志查询（时间/用户/动作筛选） |

### 6.4 运维端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health/live` | 进程存活 |
| GET | `/health/ready` | 数据库连通 + `alembic_version` 与代码 head 一致；失败 503 |
| GET | `/metrics` | Prometheus 文本格式；生产由 Nginx 拒绝外部访问 |

### 6.5 调用示例

```bash
# 登录
LOGIN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/admin/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"你的密码"}')
TOKEN=$(echo "$LOGIN" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 查询智能体
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/admin/agents?page=1&page_size=10"

# 创建技能
curl -X POST http://127.0.0.1:8000/api/v1/admin/skills \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"剧本生成","description":"示例","content":"生成剧本","config":{}}'
```

### 6.6 错误响应

```json
{ "detail": "错误说明", "code": "ERROR_CODE", "request_id": "..." }
```

| 状态码 | code | 含义 |
| --- | --- | --- |
| 400 | `BAD_REQUEST` | 请求不合法 |
| 401 | `UNAUTHORIZED` | 未登录、令牌无效/过期/已撤销 |
| 403 | `FORBIDDEN` | 角色不足或账号被禁用 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFLICT` | 名称重复或唯一约束冲突 |
| 422 | `VALIDATION_ERROR` | 参数或业务校验失败（含 `errors` 明细） |
| 429 | `ACCOUNT_LOCKED` / `RATE_LIMITED` | 登录锁定或触发限流，含 `Retry-After` |
| 500 | `INTERNAL_ERROR` | 服务异常，仅返回通用文案，堆栈只进日志 |
| 503 | `SERVICE_UNAVAILABLE` | 依赖不可用（如就绪检查失败） |

---

## 7. 数据库与迁移

### 7.1 表结构

| 表 | 说明 |
| --- | --- |
| `admin_users` | 管理员账号、角色、锁定状态、`token_version`、首登改密标记 |
| `admin_refresh_tokens` | Refresh Token 哈希、会话族、轮换/撤销状态、IP/UA |
| `audit_logs` | 审计日志（操作者、动作、资源、request_id、详情 JSONB） |
| `agents` | 智能体，`config` 为 JSONB 完整配置 |
| `skills` / `tools` / `components` / `prompts` | 五类资源 |
| `agent_tools` / `agent_skills` | 智能体关联表，级联删除 |
| `alembic_version` | 迁移版本 |

约定：

- 五张资源表名称忽略大小写唯一（`lower(name)` 唯一索引），重名返回 409。
- 所有表含 `created_at` / `updated_at`，`updated_at` 由触发器维护。
- 列表统一按 `updated_at DESC, id DESC` 排序。
- 资源名称/描述启用 `pg_trgm` GIN 索引，支持模糊搜索。

### 7.2 迁移命令

```bash
cd backend

uv run alembic upgrade head        # 应用全部迁移
uv run alembic check               # 检查模型与迁移是否漂移
uv run alembic downgrade -1        # 回滚一个版本
uv run alembic history             # 查看历史
```

- **全新数据库**：直接 `alembic upgrade head`。
- **历史手工初始化库**（曾执行 `db/001_schema.sql`）：先 `uv run alembic stamp 0001_baseline`，再 `upgrade head`。
- 生产 Compose 中由一次性 `migrate` 服务自动执行迁移，`backend` 等待其成功后再启动。

> `backend/db/*.sql` 为早期本地演示脚本，不再是事实来源；不要在生产使用。

### 7.3 初始化与演示数据

```bash
# 生产/测试管理员（默认强制首登改密）
ADMIN_USERNAME=admin ADMIN_PASSWORD='强密码' uv run python -m scripts.create_admin

# 自动化环境可关闭首登改密
ADMIN_MUST_CHANGE_PASSWORD=false ADMIN_PASSWORD='强密码' uv run python -m scripts.create_admin

# 本地演示资源（幂等）
uv run python -m scripts.seed_demo
```

---

## 8. 管理端功能

| 模块 | 能力 |
| --- | --- |
| 登录 | 账号密码登录、锁定提示、`next` 回跳、首次登录强制改密 |
| 会话 | Access Token 内存存储、刷新令牌自动续期、跨标签页同步、退出登录调用后端撤销 |
| 智能体管理 | 列表搜索/状态筛选/分页、新建、配置、启用停用、删除 |
| 智能体配置 | 基础信息、模型、角色与提示词、记忆、对话体验（含 FAQ）、发布渠道、工具与技能、知识库、其他设置、扩展组件 |
| 技能/工具/组件/提示词 | CRUD、搜索、状态筛选、分页；viewer 只读 |
| 管理员管理 | 列表、创建、角色/状态调整、重置密码（仅 superadmin） |
| 健壮性 | 路由懒加载、错误边界、404 页面、请求超时与重试 |

页面路由：

```text
/login
/change-password
/agents                  智能体列表
/agents/new              新建智能体
/agents/:id/edit         智能体配置
/skills  /tools  /components  /prompts
/users                   管理员管理（superadmin）
*                        404
```

---

## 9. 测试与质量门禁

### 9.1 后端

```bash
cd backend

uv run ruff check .
uv run ruff format --check .
uv run mypy internal web
uv run pytest --cov=internal --cov=web --cov-report=term-missing --cov-fail-under=80
uv run alembic check
```

测试使用独立数据库 `boxia_agent_test`，首次运行自动创建并执行迁移；每个用例前清理数据，互不影响。覆盖登录/刷新/撤销/锁定、RBAC、审计、五类资源 CRUD、智能体配置、错误模型、健康检查等。

### 9.2 管理端

```bash
cd frontend/admin

npm run typecheck
npm run lint
npm run format:check
npm run test:coverage     # Vitest + jsdom + Testing Library
npm run build
```

### 9.3 端到端（Playwright）

前置条件：

1. 后端已启动，数据库已迁移。
2. 存在 E2E 管理员（默认账号 `admin`），密码自行设置并通过 `E2E_PASSWORD` 传入；未设置该变量时 e2e 会直接报错。
3. 管理员 `must_change_password=false`，例如：

```bash
export E2E_PASSWORD='<符合密码策略的强密码>'
ADMIN_USERNAME=admin ADMIN_PASSWORD="$E2E_PASSWORD" \
  ADMIN_MUST_CHANGE_PASSWORD=false ADMIN_ROLE=superadmin \
  uv run python -m scripts.create_admin
```

运行：

```bash
cd frontend/admin
npx playwright install chromium
E2E_PASSWORD="$E2E_PASSWORD" npm run e2e
```

套件默认连接 `http://localhost:5173`，会自动启动 Vite；后端需监听 `127.0.0.1:8000`。覆盖：登录失败、会话恢复、登出跳转、技能 CRUD、智能体保存回显、404、首登改密与 viewer 只读。

### 9.4 CI 与本地检查

- `.github/workflows/ci.yml`：后端 lint/类型/测试/迁移漂移；前端类型/Lint/格式/单测/构建；Playwright E2E；Docker 构建 + Trivy 扫描。
- `.github/workflows/docker-publish.yml`：main/tag 推送 GHCR。
- 本地一键检查：`./ops/check.sh`
- 提交前钩子：`pre-commit install`（ruff、prettier、oxlint、空白/YAML/TOML/私钥检查）。

---

## 10. 生产部署

### 10.1 准备环境变量

```bash
cp ops/.env.production.example ops/.env.production
```

至少修改：

- `POSTGRES_PASSWORD` 与 `DATABASE_URL` 中的密码保持一致
- `JWT_SECRET`（`openssl rand -hex 32`）
- `CORS_ORIGINS`（同源部署可留空，禁止 `*`）
- `HTTP_PORT`（默认 80；建议前置 TLS 或改为本机反代端口）

### 10.2 构建与启动

```bash
docker compose -f ops/docker-compose.yml up -d --build
docker compose -f ops/docker-compose.yml ps
```

编排行为：

- `db`：PostgreSQL 17，不发布端口，仅内部网络
- `migrate`：一次性执行 `alembic upgrade head`，成功后才启动后端
- `backend`：非 root、只读根文件系统、`cap_drop: ALL`、不发布端口
- `frontend`：Nginx 静态站点 + `/api` 反代，暴露 `${HTTP_PORT}:8080`
- 所有服务带健康检查、日志轮转与内存限制

### 10.3 创建首个管理员

```bash
docker compose -f ops/docker-compose.yml run --rm \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD='强密码' \
  backend python -m scripts.create_admin
```

首次登录会强制改密。自动化/演示环境可额外传 `-e ADMIN_MUST_CHANGE_PASSWORD=false`。

### 10.4 Docker Hub 访问受限时

镜像源不可直连时，可通过构建参数替换基础镜像（示例为 daocloud 镜像源，按实际可用源调整）：

```bash
PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim \
NODE_IMAGE=docker.m.daocloud.io/library/node:24-alpine \
NGINX_IMAGE=docker.m.daocloud.io/nginxinc/nginx-unprivileged:1.27-alpine \
docker compose -f ops/docker-compose.yml build
```

### 10.5 上线检查

- [ ] `ops/.env.production` 已填写且权限仅运维可读
- [ ] `JWT_SECRET` 为随机值，数据库密码为强密码
- [ ] `APP_ENV=production`、`DOCS_ENABLED=false`（默认）
- [ ] 迁移由 `migrate` 服务执行成功，`/health/ready` 返回 200
- [ ] 已创建管理员并完成首次改密
- [ ] 前置 HTTPS（TLS 1.2/1.3），后端与数据库端口未对外发布
- [ ] `/metrics` 外部不可访问
- [ ] 备份任务已接入计划任务并验证过恢复
- [ ] 已验证 Nginx 登录限流与 429 响应

---

## 11. 运维手册

### 11.1 健康与指标

```bash
curl -s http://127.0.0.1/healthz       # Nginx 自身存活
docker compose -f ops/docker-compose.yml exec backend \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
docker compose -f ops/docker-compose.yml exec backend \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode())"
```

`/health/*` 与 `/metrics` 仅在后端容器内访问，不对外暴露。

`/health/ready` 会校验数据库连通性与迁移版本；返回 `503` 时查看响应中的 `components.database`（`database_unavailable` / `migration_outdated`）。

### 11.2 日志

- 生产默认 JSON 日志，包含 `ts/level/logger/message/request_id/trace_id/span_id/method/path/status/duration_ms/client_ip`。
- 每个响应返回 `X-Request-ID`，可据此串联 Nginx、后端与审计日志。
- 日志不记录密码、令牌、Cookie 与请求体。

### 11.3 备份与恢复

```bash
# 备份（custom 格式，默认保留 14 天）
./ops/backup.sh

# 恢复（输入 RESTORE 二次确认，会覆盖现有数据）
./ops/restore.sh ops/backups/boxia-YYYYMMDD-HHMMSS.dump
```

建议将 `ops/backup.sh` 加入 cron，并把备份目录同步到独立存储。

### 11.4 发布与回滚

1. 发布前执行备份与 `alembic upgrade head`（Compose 自动完成）。
2. 镜像按 tag 发布；回滚时切换到上一个 tag 重新 `up -d`。
3. 如需回滚数据库，使用 `alembic downgrade <revision>`，并确认备份可用。

---

## 12. 安全验收清单

- [ ] 弱口令被拒绝（长度、字符类别、常见口令、包含用户名）
- [ ] 连续 5 次登录失败触发 15 分钟锁定，返回 429 与 `Retry-After`
- [ ] Refresh Token 重放会撤销整族会话
- [ ] 登出后 Access/Refresh Token 均立即失效
- [ ] 改密后所有旧会话失效
- [ ] viewer 写接口返回 403，管理端隐藏写操作入口
- [ ] `/admin/users`、`/admin/audit-logs` 仅 superadmin 可访问
- [ ] 错误响应不含堆栈，500 仅返回通用文案
- [ ] 日志与审计不含密码、令牌等敏感信息
- [ ] 生产环境无默认账号、`JWT_SECRET` 非示例值
- [ ] 响应包含安全头（nosniff、DENY、Referrer-Policy、CSP）
- [ ] 认证响应带 `Cache-Control: no-store`
- [ ] 后端、数据库端口未对外暴露，`/metrics` 外部不可达
- [ ] 容器以非 root 运行、只读根文件系统、`cap_drop: ALL`

---

## 13. 常见问题

**Q1：提示 `uv: command not found`**

执行 `winget install astral-sh.uv` 或 `pip install uv`，安装后重新打开终端。

**Q2：后端启动报配置错误**

`DATABASE_URL`、`JWT_SECRET` 为必填。生产环境还会校验密钥长度、CORS 通配符等，按报错修正 `backend/.env` 或进程环境变量。

**Q3：登录提示「用户名或密码错误」**

本地需先执行 `scripts.create_admin` 创建管理员（历史种子脚本不再预置任何默认账号）。忘记密码可重新执行该脚本重置。

**Q4：登录返回 429 / `ACCOUNT_LOCKED`**

连续密码错误触发锁定，等待 `Retry-After` 指定时间后重试；或由 superadmin 通过管理员管理重置密码/调整状态。

**Q5：`/health/ready` 返回 `migration_outdated`**

代码版本比数据库新，执行 `uv run alembic upgrade head`（Compose 中检查 `migrate` 服务日志）。

**Q6：历史数据库如何接入 Alembic**

先确认结构与 `0001_baseline` 一致，执行 `uv run alembic stamp 0001_baseline`，再 `upgrade head`。不要重复执行 `db/001_schema.sql`。

**Q7：页面刷新后 404**

生产环境依赖 Nginx SPA 回退（`try_files $uri $uri/ /index.html`），仓库内 `frontend/admin/nginx/default.conf` 已配置。

**Q8：接口返回 401**

确认使用 Access Token 且未过期；令牌过期时前端会自动刷新并重放请求。登出/改密/禁用后旧令牌立即失效，需要重新登录。

**Q9：接口返回 409**

名称重复（忽略大小写唯一），请更换名称或编辑已有记录。

**Q10：Docker 镜像拉取失败**

Docker Hub 访问受限时使用 [10.4](#104-docker-hub-访问受限时) 的构建参数替换基础镜像。

**Q11：Playwright 提示管理员密码不合规**

测试管理员密码同样受密码策略约束，且不能包含用户名。通过 `E2E_PASSWORD` 指定合规密码，并用 `ADMIN_MUST_CHANGE_PASSWORD=false` 初始化。

**Q12：运行 pytest 时报无法创建测试库**

`boxia_agent_test` 由测试自动创建，需要 PostgreSQL 账号具备建库权限；使用默认 `postgres` 超级用户即可。

---

## 14. 许可证

本项目采用 [Apache License 2.0](LICENSE)。
