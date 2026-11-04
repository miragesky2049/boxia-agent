# boxia-agent 项目手册

[![License: AGPL-3.0 + Commercial](https://img.shields.io/badge/license-AGPL--3.0%20%2B%20Commercial-blue.svg)](./OPEN-SOURCE-POLICY.md)

> 面向企业内部的 **AI 应用编排与运营平台**。管理员在管理端用可视化画布组合模型、提示词、工具与知识库，把编排好的应用发布到市场，按租户与角色授权给最终用户使用。
>
> 内置 RAG 检索增强（pgvector + bge embedding + cross-encoder rerank）、统一工具治理网关（熔断 / 限流 / 重试 / 连接池 / SSRF 防护）、HTTP 与 MCP 双工具协议、多租户行级数据隔离、RBAC 权限、审计日志与 OpenTelemetry 可观测性。技术栈为 FastAPI + React 19 + PostgreSQL 17 + Redis + Celery，Docker Compose 一键拉起。

---

## 📜 开源协议

**个人学习、研究、非商业使用免费；企业闭源商用、对外提供 SaaS 须购买商业授权。**
本项目采用 **AGPL-3.0 + 商业授权** 双授权，两者互斥、二选一：

| 你的场景 | 适用授权 | 是否付费 |
| --- | --- | --- |
| 个人学习 / 研究 / 毕设 / 技术验证 | AGPL-3.0 | **免费** |
| 个人开源项目，代码本来就公开 | AGPL-3.0 | **免费** |
| 企业内部使用，愿意公开修改后的源码 | AGPL-3.0 | **免费** |
| 企业内部使用，不愿公开源码 | 商业授权 | **付费** |
| 闭源集成 / SaaS 托管 / 白标转售 | 商业授权 | **付费** |

- 协议全文：[LICENSE](./LICENSE)（AGPL-3.0）
- 授权选择指南：[OPEN-SOURCE-POLICY.md](./OPEN-SOURCE-POLICY.md)
- 商业授权条款与价格：[COMMERCIAL-TERMS.md](./COMMERCIAL-TERMS.md)
- 商业授权联系：**zhm2049@163.com**

### 归属声明（Attribution）

本项目的工作流画布与节点 DSL 设计参考了 [coze-studio](https://github.com/coze-dev/coze-studio)（Apache License 2.0）。依据 Apache 2.0 第 4(b) 条，本项目在分发时保留了原作者版权声明与协议文本：

- Apache 2.0 协议全文：[third_party/coze-studio/APACHE-2.0.txt](./third_party/coze-studio/APACHE-2.0.txt)
- 归属与衍生说明：[NOTICE](./NOTICE)
- 原项目：https://github.com/coze-dev/coze-studio

---

## 🚀 30 秒速通

### 一句话这是什么

一个"**不写代码就能搭企业 AI 应用**"的平台：管理员在画布上编排应用 → 发布到市场 → 授权给租户 → 租户员工在用户端直接对话，或由租户管理员在管理端自助试运行与查看运行记录。

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
   │ (平台/租户管理员)     │              │ (普通员工)           │
   └──────────┬──────────┘              └──────────┬──────────┘
              │ /api/v1/admin/**                     │ /api/v1/user/**
              ▼                                      ▼
   ┌──────────────────────────────────────────────────────────────┐
   │              FastAPI (Python 3.12, Uvicorn)                   │
   │  ┌────────────────┐                              ┌───────────┐ │
   │  │ admin 站点 8000 │                              │ user 8001 │ │
   │  └──────┬─────────┘                              └─────┬─────┘ │
   │         └──────────────┬─────────────────────────────────┘     │
   │                        ▼                                        │
   │  ┌────────────────────────────────────────────────────────┐    │
   │  │ GraphRuntime（LangGraph DAG：调试 / 试运行 / 断点续跑） │    │
   │  │ ChatService（ReAct 对话循环 + SSE）                     │    │
   │  │ ToolGateway（SSRF / 熔断 / 限流 / 重试 / 连接池）       │    │
   │  │ RetrievalService（RAG 召回 + 精排 + prompt 注入）       │    │
   │  └──┬──────────────┬──────────────┬───────────────┬────────┘    │
   └─────┼──────────────┼──────────────┼───────────────┼─────────────┘
         ▼              ▼              ▼               ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐    ┌──────────────┐
   │ Postgres │  │  Redis   │  │  Celery  │    │  大模型服务   │
   │  17+pgv  │  │ 记忆/队列 │  │(RAG/权益)│    │ OpenAI兼容    │
   │  :5432   │  │  :6379   │  │          │    │              │
   └──────────┘  └──────────┘  └──────────┘    └──────────────┘
                         │
                         ▼
                  ┌──────────────┐
                  │ 外部租户工具  │  ◄── SSRF 防护 + 治理网关
                  │ HTTP / MCP   │
                  └──────────────┘
```

- **后端**：Python + FastAPI，两个独立站点（admin / user），共享同一套业务与引擎层
- **管理端前端**：React 19 + Ant Design 5 + ReactFlow 画布
- **用户端前端**：React 19
- **数据库**：PostgreSQL 17（Docker 启动，不用自己装）+ Redis + Celery

### 5 分钟把项目跑起来

> 前提：已装 **Git、Docker Desktop、Python 3.12、uv、Node.js 20+/22+、pnpm 11**。详见 [准备软件](docs/getting-started.md#2-准备软件)。

```bash
# 1. 拉代码
git clone https://github.com/miragesky2049/boxia-agent.git
cd boxia-agent

# 2. 启动数据库与 Redis（Docker 一键起）
docker compose -f backend/docker/postgresql/docker-compose.yml up -d
docker compose -f backend/docker/redis/docker-compose.yml up -d

# 3. 初始化后端配置 + 依赖 + 数据库表
cd backend
cp .env.example .env
uv sync --python 3.12.10
uv run alembic upgrade head

# 4. 创建第一个管理员（按提示输入自己的强密码，勿用文档或他人示例中的密码）
uv run python -m scripts.create_admin

# 5. 启动后端（四个终端，或用一键脚本）
uv run uvicorn web.app_admin:app --reload                       # 终端 A：管理端 :8000
uv run uvicorn web.app_user:app --reload --port 8001            # 终端 B：用户端 :8001
uv run celery -A internal.infrastructure.celery_app worker --loglevel=info -Q rag  # 终端 C：异步任务 worker（RAG ingest + 权益周期任务）
uv run celery -A internal.infrastructure.celery_app beat --loglevel=info           # 终端 D：定时任务调度器

# 6. 启动前端（新终端，回到仓库根目录）
cd frontend/admin && pnpm install && pnpm run dev              # 管理端 http://localhost:5173
cd ../user && pnpm install && pnpm run dev                      # 用户端 http://localhost:5174（可选）
```

浏览器打开 <http://localhost:5173>，用 `admin` + 第 4 步设置的密码登录，**首次登录强制改密**。

> 💡 **懒人一键启动**（需要 Git Bash）：仓库根目录执行 `./ops/dev.sh`，会自动完成 2~5 步，并额外拉起 Redis、Celery worker（RAG + 权益周期任务）与 beat 定时调度器（权益生效/到期流转、宽限期回收、对账），以及清理上次残留的 Vite / Uvicorn 端口占用（但仍需先创建管理员）。

### 端口速查

| 服务            | 本地地址                              | 谁在用               |
|-----------------|---------------------------------------|----------------------|
| 管理端前端      | http://localhost:5173                 | 平台/租户管理员      |
| 用户端前端      | http://localhost:5174                 | 普通员工             |
| 管理端后端 API  | http://127.0.0.1:8000                 | 管理端前端调用       |
| 用户端后端 API  | http://127.0.0.1:8001                 | 用户端前端调用       |
| 后端接口文档    | http://127.0.0.1:8000/docs            | Swagger（开发环境）  |
| PostgreSQL      | 127.0.0.1:5432                        | 后端                 |
| Redis           | 127.0.0.1:6379                        | 记忆 / Celery        |

### 接下来去哪？

- 跑起来想搭第一个应用 → [画布编排 5 分钟上手](docs/features.md#画布编排-5-分钟上手)
- 想给应用接外部接口（HTTP/MCP）→ [工具接入 5 分钟上手](docs/features.md#工具接入-5-分钟上手)
- 卡住了 → [新手常见问题](docs/getting-started.md#4-新手常见问题)
- 想改代码 → [目录结构与代码分层](docs/development.md#5-目录结构与代码分层)
- 想部署上线 → [生产环境落地部署](docs/deployment.md#14-生产环境落地部署)
- 想面试讲清楚 → [面试讲解指南](docs/interview.md#13-面试讲解指南)

---

> 建议在 **Git Bash**（Windows）、macOS 或 Linux 终端中执行本文命令。仓库中的 `ops/*.sh` 脚本需要 Bash；Windows 安装 [Git for Windows](https://git-scm.com/download/win) 即可获得 Git Bash。
>
> ⚠️ PowerShell 里的 `bash` 指向 WSL（`C:\Windows\System32\bash.exe`），而 Docker Desktop 自带的默认发行版 `docker-desktop` 没有 `/bin/bash`，直接执行会报 `execvpe(/bin/bash) failed: No such file or directory`。请改用 Git Bash，或显式指定 Git Bash 路径：`& "C:\Program Files\Git\bin\bash.exe" ops/dev.sh`。

---

## 🧭 应用模型速览（必读）

平台统一为 **应用（Application）** 模型，老 agent/workflow/skill/component/prompt 链路已物理下线。理解以下 4 个概念即可上手：

| 概念 | 归属 | 说明 |
| --- | --- | --- |
| **应用 Application** | 平台（产品级） | 一个可视化画布 = 一张 DAG / agent_loop 图，存 `application` + `application_graph`；发布后生成不可变图版本。租户不直接建应用，而是开通实例 |
| **资源 Resource** | 平台或租户 | 工具、提示词、技能、知识四类统一存 `resource` 表；通过 `resource_grant` 开放给租户 |
| **租户实例 TenantApplicationInstance** | 租户 | 租户从市场自助开通产品级应用后生成的运行实例（含授权方式、配额、有效期、钉住的图版本），存 `tenant_application_instance` |
| **角色授权 RoleGrant** | 角色 | 角色可被授权资源（工具 / 提示词 / 技能 / 知识）；应用通过市场实例与可见范围控制 |

**两类管理端入口**：

- **产品级平台**（`adminsystem.<root>`）：维护全部租户、产品级应用、资源、模型供应商与模型目录、审计日志
- **租户级管理端**（`<tenant>.<root>`）：维护本租户用户、角色、授权、组织架构、已开通应用

**用户端**（`<tenant>.<root>` 的 `/`）：普通员工登录后看到"我的应用"卡片，直接对话或运行。

**关键菜单**：应用管理（`/apps`）、应用市场（`/marketplace`）、资源管理（`/resources`）、工具（`/tools`）、授权（`/grants`）、角色（`/roles`）、用户（`/users`）、组织架构（`/departments`、`/employments`、`/mgmt-units`）、租户（`/tenants`）、审计（`/audit`）。

---

## 📚 文档导航

| 分册 | 内容 | 适合谁 |
| --- | --- | --- |
| [docs/getting-started.md](docs/getting-started.md) | 1-4 章：项目定位、准备软件、第一次启动、新手常见问题 | 第一次跑起来 |
| [docs/development.md](docs/development.md) | 5-9 章：目录结构、断点调试、配置、权限安全、接口手册、数据库迁移 | 改代码、查配置 |
| [docs/features.md](docs/features.md) | 10 章：管理端功能（画布编排 / 工具接入 5 分钟上手） | 搭第一个应用 |
| [docs/testing.md](docs/testing.md) | 11 章：测试与质量门禁 | CI / 提交前 |
| [docs/architecture.md](docs/architecture.md) | 12 章：系统运行流程（启动、多租户、登录、应用运行、令牌轮换、迁移） | 讲架构 |
| [docs/interview.md](docs/interview.md) | 13 章：面试讲解指南 | 面试 / 对外介绍 |
| [docs/deployment.md](docs/deployment.md) | 14 章：生产部署（HTTPS、备份、监控、回滚、RAG 依赖） | 上线运维 |

---

## 15. 许可证

主协议为 [AGPL-3.0](./LICENSE)，商业使用另见 [OPEN-SOURCE-POLICY.md](./OPEN-SOURCE-POLICY.md) 与 [COMMERCIAL-TERMS.md](./COMMERCIAL-TERMS.md)。
第三方组件（coze-studio，Apache-2.0）的版权与协议声明见 [NOTICE](./NOTICE)。
