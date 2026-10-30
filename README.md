# boxia-agent 项目手册

> 面向企业内部的 AI 智能体开发与运营平台。管理员在网页上零代码组合模型、提示词、技能、工具与知识库，通过可视化画布编排多步工作流，按租户与角色授权发布给最终用户使用。
>
> 内置 RAG 检索增强（pgvector + bge embedding + cross-encoder rerank）、统一工具治理网关（熔断 / 限流 / 重试 / 连接池 / SSRF 防护）、HTTP 与 MCP 双工具协议、多租户行级数据隔离、RBAC 权限、审计日志与 OpenTelemetry 可观测性。技术栈为 FastAPI + React 19 + PostgreSQL 17 + Redis + Celery，Docker Compose 一键拉起。

---

## 📜 开源协议（双授权）

本项目采用 **AGPL-3.0 + 商业授权** 双授权模式：

- **个人学习 / 开源研究**：可免费使用，受 AGPL-3.0 约束（衍生代码需同协议开源）。
- **商用（闭源集成 / SaaS 托管 / 私有化部署）**：需购买商业授权，档位、权利、限制与联系渠道详见 [COMMERCIAL-LICENSE.md](./COMMERCIAL-LICENSE.md)。

### 归属声明（Attribution）

本项目的工作流画布与节点 DSL 设计参考了 [coze-studio](https://github.com/coze-dev/coze-studio)（Apache License 2.0）。依据 Apache 2.0 第 4(b) 条，本项目在分发时保留了原作者版权声明与协议文本：

- Apache 2.0 协议全文：[LICENSE-APACHE](./LICENSE-APACHE)
- 归属与衍生说明：[NOTICE](./NOTICE)
- 原项目：https://github.com/coze-dev/coze-studio

---

## 🚀 小白速通（30 秒看完）

### 一句话这是什么

一个"**不写代码就能搭 AI 助手**"的企业内部平台：管理员在网页上配置智能体 → 发布给某个租户 → 租户员工登录用户端直接使用。

### 一张图看懂架构

```text
                        ┌─────────────────────┐
   你的浏览器 ──────────►│  Nginx (生产反代)   │
                        └────┬───────┬───────┘
                             │       │
              ┌──────────────┘       └──────────────┐
              ▼                                     ▼
   ┌─────────────────────┐              ┌─────────────────────┐
   │ 管理端  React 5173   │              │ 用户端  React 5174   │
   │ (运营/管理员)         │              │ (普通员工)           │
   └──────────┬──────────┘              └──────────┬──────────┘
              │ /api/v1/admin/**                     │ /api/v1/user/**
              ▼                                      ▼
   ┌──────────────────────────────────────────────────────────────┐
   │              FastAPI (Python 3.12, Uvicorn)                   │
   │  ┌────────────────┐                              ┌───────────┐ │
   │  │ admin 站点 8000 │                              │ user 8001 │ │
   │  └──────┬─────────┘                              └─────┬─────┘ │
   │         │                                                 │     │
   │         └──────────────┬──────────────────────────────────┘     │
   │                        ▼                                        │
   │  ┌────────────────────────────────────────────────────────┐    │
   │  │ 引擎层：FunctionCallAgentRunner / WorkflowExecutor     │    │
   │  │        ToolGateway (熔断/限流/重试/连接池)             │    │
   │  │        RetrievalService (RAG)                         │    │
   │  └──┬──────────────┬──────────────┬───────────────┬────────┘    │
   └─────┼──────────────┼──────────────┼───────────────┼─────────────┘
         ▼              ▼              ▼               ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐    ┌──────────────┐
   │ Postgres │  │  Redis   │  │  Celery  │    │  大模型网关   │
   │  17+pgv  │  │  (broker)│  │ (RAG切分)│    │ OpenAI兼容    │
   │  :5432   │  │  :6379   │  │          │    │              │
   └──────────┘  └──────────┘  └──────────┘    └──────────────┘
                         │
                         ▼
                  ┌──────────────┐
                  │ 外部租户工具  │  ◄── SSRF 防护 + 治理网关
                  │ HTTP / MCP   │
                  └──────────────┘
```

- **后端**：Python + FastAPI，两个独立站点（admin / user）
- **管理端前端**：React 19 + Ant Design 5
- **用户端前端**：React 19
- **数据库**：PostgreSQL 17（Docker 启动，不用自己装）

### 5 分钟把项目跑起来

> 前提：已装 **Git、Docker Desktop、Python 3.12、uv、Node.js 20+/22+、pnpm 11**。详见 [docs/getting-started.md](docs/getting-started.md#2-准备软件)。

```bash
# 1. 拉代码
git clone https://github.com/miragesky2049/boxia-agent.git
cd boxia-agent

# 2. 启动数据库（Docker 一键起 PostgreSQL）
docker compose -f backend/docker/postgresql/docker-compose.yml up -d

# 3. 初始化后端配置 + 依赖 + 数据库表
cd backend
cp .env.example .env
uv sync --python 3.12.10
uv run alembic upgrade head

# 4. 创建第一个管理员（按提示输入密码，建议示例：Boxia-2026-Root!）
uv run python -m scripts.create_admin

# 5. 启动后端（两个终端，或用一键脚本）
uv run uvicorn web.app_admin:app --reload                       # 终端 A：管理端 :8000
uv run uvicorn web.app_user:app --reload --port 8001            # 终端 B：用户端 :8001

# 6. 启动前端（新终端，回到仓库根目录）
cd frontend/admin && pnpm install && pnpm run dev              # 管理端 http://localhost:5173
# 可选：用户端
cd ../user && pnpm install && pnpm run dev                      # 用户端 http://localhost:5174
```

浏览器打开 <http://localhost:5173>，用 `admin` + 第 4 步设置的密码登录，**首次登录强制改密**。

> 💡 **懒人一键启动**（需要 Git Bash）：仓库根目录执行 `./ops/dev.sh`，会自动完成 2~5 步，并额外拉起 Redis、Celery RAG worker，以及清理上次残留的 Vite / Uvicorn 端口占用（但仍需先创建管理员）。

### 端口速查

| 服务            | 本地地址                              | 谁在用               |
|-----------------|---------------------------------------|----------------------|
| 管理端前端      | http://localhost:5173                 | 运营/管理员          |
| 用户端前端      | http://localhost:5174                 | 普通员工             |
| 管理端后端 API  | http://127.0.0.1:8000                 | 管理端前端调用       |
| 用户端后端 API  | http://127.0.0.1:8001                 | 用户端前端调用       |
| 后端接口文档    | http://127.0.0.1:8000/docs            | Swagger（开发环境）  |
| 数据库          | 127.0.0.1:5432                        | 后端用              |

### 接下来去哪？

- 跑起来想搭第一个 AI 助手 → [docs/features.md](docs/features.md#101-工作流-5-分钟上手小白实战)
- 想给智能体接外部接口（HTTP/MCP）→ [docs/features.md](docs/features.md#102-工具接入-5-分钟上手小白实战)
- 卡住了 → [docs/getting-started.md](docs/getting-started.md#4-新手常见问题)
- 想改代码 → [docs/development.md](docs/development.md#5-目录结构与代码分层)
- 想部署上线 → [docs/deployment.md](docs/deployment.md#14-生产环境落地部署)
- 想面试讲清楚 → [docs/interview.md](docs/interview.md#13-面试讲解指南)

---

> 建议在 **Git Bash**（Windows）、macOS 或 Linux 终端中执行本文命令。仓库中的 `ops/*.sh` 脚本需要 Bash；Windows 安装 [Git for Windows](https://git-scm.com/download/win) 即可获得 Git Bash。
>
> ⚠️ PowerShell 里的 `bash` 指向 WSL（`C:\Windows\System32\bash.exe`），而 Docker Desktop 自带的默认发行版 `docker-desktop` 没有 `/bin/bash`，直接执行会报 `execvpe(/bin/bash) failed: No such file or directory`。请改用 Git Bash，或显式指定 Git Bash 路径：`& "C:\Program Files\Git\bin\bash.exe" ops/dev.sh`。详见 [docs/getting-started.md](docs/getting-started.md#413-windows-powershell-下运行-opssh-报-binbash-no-such-file-or-directory)。

---

## 🧭 应用模型速览（必读）

平台已下线老 agent/workflow/skill/component/prompt 链路，统一为 **应用（Application）** 模型。理解这 4 个概念即可上手：

| 概念 | 归属 | 说明 |
| --- | --- | --- |
| **应用 Application** | 平台（platform）或 租户（tenant） | 一个可视化画布 = 一个 DAG/agent_loop 图，存 `application` + `application_graph` 两张表 |
| **资源 Resource** | 平台或租户 | 统一为 `tool / prompt / skill / knowledge` 四种类型，存 `resource` 表；通过 `resource_grant` 开放给租户 |
| **租户实例 TenantApplicationInstance** | 租户 | 租户从市场自助开通产品级应用后生成的运行实例，存 `tenant_application_instance` |
| **角色授权 RoleGrant** | 角色 | 角色可被授权资源（tool）+ 应用（app），决定租户内哪些角色能用哪些应用 |

**两类管理端入口**：

- **产品级平台**（`adminsystem.<root>`）：维护全部租户、产品级应用、资源、模型、审计日志
- **租户级管理端**（`<tenant>.<root>`）：维护本租户用户、角色、已开通应用、本租户资源

**用户端**（`<tenant>.<root>` 的 `/`）：普通员工登录后看到"我的应用"卡片，直接对话/运行。

**关键菜单**：应用管理（`/apps`）、应用市场（`/marketplace`）、资源管理（`/resources`）、角色管理（`/roles`）、审计日志（`/audit`）。

---

## 📚 文档导航

| 分册 | 内容 | 适合谁 |
| --- | --- | --- |
| [docs/getting-started.md](docs/getting-started.md) | 1-4 章：项目定位、准备软件、第一次启动、新手常见问题 | 第一次跑起来 |
| [docs/development.md](docs/development.md) | 5-9 章：目录结构、配置、权限安全、接口手册、数据库迁移 | 改代码、查配置 |
| [docs/features.md](docs/features.md) | 10 章：管理端功能（工作流/工具接入 5 分钟上手） | 搭第一个 AI 助手 |
| [docs/testing.md](docs/testing.md) | 11 章：测试与质量门禁 | CI / 提交前 |
| [docs/architecture.md](docs/architecture.md) | 12 章：系统运行流程（启动、多租户、登录、令牌轮换） | 讲架构 |
| [docs/interview.md](docs/interview.md) | 13 章：面试讲解指南 | 面试 / 对外介绍 |
| [docs/deployment.md](docs/deployment.md) | 14 章：生产环境落地部署（HTTPS、备份、监控、回滚） | 上线运维 |

---

## 15. 日常运维

### 15.1 健康检查

```bash
curl -s http://127.0.0.1:8080/healthz       # 管理端前端 Nginx 存活（端口为 HTTP_PORT）
curl -s http://127.0.0.1:8081/healthz       # 用户端前端 Nginx 存活（端口为 USER_HTTP_PORT）

docker compose -f ops/docker-compose.yml exec backend-admin \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"

docker compose -f ops/docker-compose.yml exec backend-user \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"

docker compose -f ops/docker-compose.yml exec backend-admin \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode())"
```

`/health/ready` 返回 503 时，查看响应里的 `components.database`：

- `database_unavailable`：数据库连不上
- `migration_outdated`：代码比数据库新，需要执行迁移

### 15.2 日志

- 生产默认 JSON 日志，包含时间、级别、`request_id`、`trace_id`、方法、路径、状态码、耗时、客户端 IP。
- 每个响应都带 `X-Request-ID`，可以用它把 Nginx、后端和审计记录串起来。
- 日志不会记录密码、令牌、Cookie 和请求体。

### 15.3 发布与回滚

见 [docs/deployment.md](docs/deployment.md#149-升级与回滚)。

---

## 16. 更多问题

**Q1：接口返回 401**

确认请求带的是 Access Token 且未过期。令牌过期时前端会自动刷新并重试；登出、改密、禁用后旧令牌立即失效，需要重新登录。

**Q2：接口返回 409**

名称重复（忽略大小写唯一），换一个名称或编辑已有记录。

**Q3：生产页面刷新后 404**

生产环境依赖 Nginx 的 SPA 回退（`try_files $uri $uri/ /index.html`），仓库中的 `frontend/admin/nginx/default.conf` 与 `frontend/user/nginx/default.conf` 均已配置好。

**Q4：`alembic check` 报模型与迁移不一致**

新增或修改了 ORM 模型，但没有生成迁移文件。执行：

```bash
cd backend
uv run alembic revision --autogenerate -m "描述本次变更"
uv run alembic upgrade head
uv run alembic check
```

**Q5：运行 pytest 提示无法创建测试库**

`boxia_agent_test` 由测试自动创建，数据库账号需要有建库权限。本地默认的 `postgres` 账号即可；如果是自定义账号，请授权 `CREATEDB`。

**Q6：历史数据库如何接入 Alembic**

先确认表结构与 `0001_baseline` 一致，执行 `uv run alembic stamp 0001_baseline`，再 `upgrade head`。

**Q7：如何创建或修改用户端登录账号**

用户端不再使用静态令牌。由租户管理员在管理端「用户管理」创建账号并绑定租户角色，最终用户在用户端登录页输入账号密码获取 JWT；重置密码也在同一页面完成。用户端要求请求来自租户子域名，平台域名或未知域名会返回 404/403。

**Q8：怎样确认自己没有把密码提交到 Git**

提交前先看暂存区：

```bash
git diff --cached --stat
git diff --cached | grep -iE "password|secret|token"
```

仓库已经配置了 `.gitignore` 和 pre-commit 的私钥检测；真实配置只放在 `backend/.env` 和 `ops/.env.*` 中，这些文件不会进入 Git。

**Q9：不同租户可以有同名资源或同名账号吗**

可以。资源名和用户名的唯一索引都带作用域：`(COALESCE(tenant_id,0), lower(name))`、`(COALESCE(tenant_id,0), username)`。同一作用域内仍然唯一；租户不能与产品级资源重名，避免产品级资源授权给该租户后出现同名歧义。

**Q10：怎么新增租户，编码能改吗**

用产品级账号登录平台，在「租户管理」新建；`code` 就是子域名前缀（如 `acme` → `acme.example.com`），创建后不可修改。也可以先在命令行建账号：

```bash
cd backend
TENANT_CODE=acme uv run python -m scripts.create_admin
```

停用租户会立即生效：该子域名下的登录和已登录会话都会被拒绝。

**Q11：本地没有配 DNS，怎么验证多租户**

`APP_ENV=local` 且 `ROOT_DOMAIN` 留空（自动回退 `localhost`）时，可以直接用 RFC 6761 规定的 `*.localhost` 验证真实子域名，无需配置 DNS：

- `http://adminsystem.localhost:5173` → 产品级平台；
- `http://acme.localhost:5173` → 租户 `acme`（需先创建该租户）；
- `http://localhost:5173` → 回环主机，设置 `ALLOW_TENANT_HEADER=true` 后可继续用登录页下拉框、`?tenant=acme` 或 `X-Tenant-Code: acme`（产品级用 `platform`）切换。

`X-Tenant-Code` 只在回环/本机主机上生效，访问子域名时以域名为准。部署到开发/测试/线上环境时 `ALLOW_TENANT_HEADER` 必须关闭（开启会导致启动失败），只按二级域名解析租户；`?tenant=` 链接不会切换作用域，前端会移除该参数并保持当前登录态。

---

## 17. 许可证

本项目采用 **AGPL-3.0 + 商业授权** 双授权模式，两种授权互斥，须二选一：

- **选项 A：AGPL-3.0** —— 遵守 AGPL-3.0 全部条款（衍生代码同协议开源、网络对外提供服务也须公开源码）即可免费使用。协议全文见 [LICENSE-AGPL](./LICENSE-AGPL)，双授权说明见 [LICENSE](./LICENSE)。
- **选项 B：商业授权** —— 不想开源衍生代码、需闭源集成 / SaaS 托管 / 私有化部署 / 商业支持时，需向作者购买商业授权。档位、权利、限制与购买方式见 [COMMERCIAL-LICENSE.md](./COMMERCIAL-LICENSE.md)。
