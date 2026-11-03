> 返回 [项目手册](../README.md)

## 1. 项目是什么

### 1.1 一句话定位

**一个面向企业内部的 AI 应用编排与运营平台。** 管理员不用写代码，就能在可视化画布上组合模型、提示词、工具与知识库，编排成应用后发布到市场，按租户与角色授权给最终用户使用。

### 1.2 系统组成

项目由三块组成，彼此独立开发、通过 HTTP 接口通信：

```text
你的浏览器
│
├── 管理端  http://localhost:5173    ← 平台/租户管理员使用（React）
│           http://*.localhost:5173  ← 本地验证平台/租户子域名
├── 用户端  http://localhost:5174    ← 最终用户使用（登录后浏览已授权应用）
│
├──────────────┬────────────────────
▼              ▼
管理端 API      用户端 API
127.0.0.1:8000  127.0.0.1:8001     ← 两个站点独立打包、独立路由
/admin/**       /user/**
/public/**
│              │
└──────┬───────┘
       ▼
  PostgreSQL 数据库               ← 所有数据保存在这里
```

- **后端**：Python 3.12 + FastAPI，两个独立站点入口（`web.app_admin:app` / `web.app_user:app`），负责登录鉴权、数据读写、业务规则。
- **管理端**：React 19 + TypeScript + Ant Design + ReactFlow，负责应用画布、市场、资源、工具、授权、租户与审计管理。
- **用户端**：React + TypeScript，最终用户登录后浏览可见应用并直接对话。
- **数据库**：PostgreSQL 17（开发时用 Docker 启动）+ Redis（记忆 / Celery）+ Celery（知识库异步 ingest）。

### 1.3 核心能力

| 模块         | 能力                                                                                           |
|--------------|------------------------------------------------------------------------------------------------|
| 应用编排     | 可视化画布（ReactFlow，节点 / 连线 / 小地图 / 缩放）；节点覆盖 Start、End、LLM、HTTP、API 插件、Code、Dataset 检索、IF、Loop、Sub-workflow、Set Variable、Variable Merge、Text、JSON、Batch、Conversation、Agent Loop、Human Approval 等（节点类型与 coze 数字编码对齐，未实现类型在转换阶段显式报错） |
| 图执行引擎   | LangGraph 运行时：DAG 编译、拓扑校验（环检测 / 多 Start / 变量类型）、节点级状态机、checkpoint 断点续跑、调试运行（整图 / 单节点 / 流式 SSE）、运行记录与节点耗时用量 |
| 应用发布     | 草稿图与不可变发布版本分离；发布生成 graph version，可回滚；租户可钉住发布版本；上架市场、上下架、启用/停用 |
| 应用市场     | 平台应用上架后，租户可浏览、申请/订阅、试用；租户开通生成 `tenant_application_instance`（授权方式、配额、有效期、钉住版本） |
| RAG 知识库   | 文档按 Markdown 标题层级切分（保留 heading_path）→ embedding（bge-large-zh）写入向量库；检索链路：LLM query 改写（指代消解 + 多 query 变体）→ 并行向量召回 → Cross-Encoder rerank 精排（bge-reranker-v2-m3）→ 阈值过滤注入 prompt；ingest 走 Celery 异步任务，状态机 `pending → queued → processing → ready/failed`；向量库抽象支持 pgvector / Milvus |
| 工具治理网关 | 所有跨网 HTTP 工具调用统一经过 `tool_gateway`：超时三档、可重试错误指数退避、按 (租户, 工具) 熔断、按租户限流、按 base_url 共享 httpx 连接池（HTTP/2 + keep-alive）、响应超 8KB 自动裁剪；熔断/限流/连接失败时返回中文降级文本回灌 LLM，不中断主循环 |
| 工具接入向导 | admin 工具页 4 Tab（基础信息/服务连接/高级治理/试运行）；粘贴 curl 自动解析 method/url/headers/body；输入 MCP server URL 自动 `list_tools` 拉取工具列表勾选批量入库；高级配置滑块调超时/重试/熔断/限流 |
| SSRF 防护    | 所有出站 URL 强制校验：拒绝 loopback（127.0.0.0/8）、链路本地（169.254.0.0/16，含云元数据 169.254.169.254）、组播、保留、未指定地址；允许 RFC1918 私网（10.x / 172.16-31.x / 192.168.x）——租户内网 MCP 是合法部署形态 |
| 资源管理     | 工具、提示词、技能、知识四类资源统一存 `resource` 表，按平台 / 租户归属；资源可通过 `resource_grant` 开放给租户，租户内再按角色收窄 |
| 模型管理     | 平台维护模型供应商（`model_provider`：base_url / api_key）与模型目录（`model_catalog`：模型 ID、显示名、能力标签）；租户可在平台允许范围内选择模型 |
| 租户授权     | 平台应用必须显式开通/授权给租户后才可见；租户可在开通实例上按角色放行；资源授权与角色功能权限分开管理 |
| 多租户       | 按二级域名区分产品级平台与租户；租户数据行级隔离，平台资源授权后租户只读使用               |
| 角色管理     | 平台与租户各自维护角色体系；角色通过权限资源目录授权功能权限，新建角色默认无权限；产品级入口创建的角色为系统角色；平台角色可授权平台级资源 |
| 用户管理     | 租户管理员与普通用户统一为 `users` 账号体系，通过角色赋权；用户端仅能看到被授权且已启用的应用 |
| 用户端会话   | 登录后浏览应用列表 → 进入对话；多轮对话保存到 `conversation` / `message`，回复内联展示工具调用轨迹（工具名、入参、返回、是否出错）并支持折叠，Markdown + GFM 渲染，可查看历史会话 |
| 组织架构     | 部门树（物化路径、最多 10 级）、用户任职记录（单一主任职 + 调岗归档 + 历史可查）、管理单元（跨部门/人员的数据范围）、人力资源字典 |
| 认证与会话   | 短期 Access Token + 可撤销 Refresh Token，单次轮换、重放检测、跨标签页同步                     |
| 权限控制     | 功能权限按权限资源编码校验菜单、页面、按钮与资源读写；列表、详情、写操作均由服务端按数据授权过滤 |
| 安全防护     | 登录锁定、防用户名枚举、密码策略、统一错误模型、安全响应头、接口限流                           |
| 审计与可观测 | 审计日志、请求 ID、结构化日志、OpenTelemetry 链路追踪、Prometheus 指标、租户 token 用量账本     |
| 工程化交付   | Alembic 迁移、Docker Compose、Nginx 反代、GitHub Actions、备份恢复脚本                         |

### 1.4 名词解释

第一次看可能不懂的词，先看这张表：

| 名词              | 用大白话解释                                                                         |
|-------------------|--------------------------------------------------------------------------------------|
| 应用（Application）| 一个配置好的 AI 应用，本质是一张画布（DAG 或 Agent Loop），有自己的模型、提示词、工具与知识库 |
| 画布（Canvas）    | 可视化编排界面。拖节点、连线，就得到一条可执行流程 |
| 节点（Node）      | 画布里的一个步骤。Start 收输入、LLM 调模型、HTTP/API 调接口、Dataset 查知识库、IF 做分支、End 输出结果 |
| 图版本（Graph Version） | 发布时冻结的图快照。改草稿不影响线上运行，可回滚，租户可钉住某个版本 |
| 运行（Run）       | 一次执行记录，保存输入、输出、节点级耗时与用量，可用于排障与回放 |
| 工具（Tool）      | 应用可以调用的外部接口，比如"查询天气""创建工单"。支持 HTTP 直连和 MCP 协议两种 |
| MCP               | Model Context Protocol，一种标准的工具协议。租户跑一个 MCP Server，平台连上去自动发现它提供哪些工具，不用手写 JSON Schema |
| 资源（Resource）  | 工具、提示词、技能、知识四类可复用能力的统一抽象，平台维护后可授权给租户 |
| 提示词（Prompt）  | 写给 AI 模型的指令模板，决定它怎么理解和回答；支持 `{{变量}}` / `{{节点名.字段}}` 模板插值 |
| 熔断（Circuit Breaker） | 保险丝。某个工具连续失败达到阈值后自动"跳闸"，一段时间内不调它，直接返回"稍后重试"，避免压垮对方 |
| 限流（Rate Limit） | 每个租户每秒最多调固定次数工具，超出直接返回"请稍后再试"，防止一个租户刷爆平台 |
| SSRF              | 服务端请求伪造。防止 AI 被 prompt 注入后让平台去访问云元数据（169.254.169.254）、本机（127.0.0.1）等危险地址 |
| 应用市场          | 平台管理员上架应用，租户浏览、订阅/试用后在自己租户内使用 |
| 迁移（Migration） | 数据库结构的升级脚本。代码更新后执行迁移，表结构才会同步                             |
| Token             | 登录成功后服务器发的"通行证"。之后每次请求都带上它，服务器才知道你是谁               |
| RBAC              | 基于角色的权限控制。不同角色能做的事不一样                                           |
| 产品级平台        | 通过 `adminsystem.<根域名>` 访问，跨租户运营，维护产品级应用、资源、模型与租户授权；产品级资源统一用全零 UUID（`00000000-0000-0000-0000-000000000000`）标识 |
| 租户级平台        | 通过 `<租户编码>.<根域名>` 访问，从市场开通应用，维护本租户自己的资源、角色与用户    |
| 部门（Department）| 租户内的组织单元，支持树形层级（最多 10 级），用物化路径 `path=/<root>/.../<self>/` 存储以高效查询子树 |
| 任职（Employment）| 用户在某个部门的任职记录；同一用户同一时刻仅一条 `is_current=TRUE`（部分唯一索引约束），调岗自动归档旧记录并写入新记录，保留完整历史 |
| 管理单元（Mgmt Unit）| 跨部门 / 跨人员的业务管理范围，可把若干部门与人员组合成一个数据范围，用于授权与统计 |

### 1.5 角色与权限

系统预置全局只读的权限资源目录，覆盖管理端菜单（`menu:*`）、页面（`page:*`）与按钮（`button:*`）。角色通过 `role_permissions` 绑定权限编码，账号绑定角色后实时生效。

| 权限类别 | 作用                         | 示例                                                         |
|----------|------------------------------|--------------------------------------------------------------|
| `system` | 管理端入口与全量数据范围     | `system:console:access`、`system:data:all`                   |
| `menu`   | 左侧菜单可见性               | `menu:roles`、`menu:apps`、`menu:marketplace`                |
| `page`   | 页面与对应接口访问           | `page:roles`、`page:apps`、`page:resources`                  |
| `button` | 页面操作按钮                 | `button:role:grant`、`button:app:create`、`button:admin-user:create` |

- 产品级平台与每个租户各自拥有 `superadmin` / `admin` / `viewer` 三个内置系统角色，不可删除、不可停用；平台与租户角色数据完全隔离。
- `superadmin` 默认拥有所属作用域全部权限（含 `system:data:all`），其功能权限与数据授权在角色详情中只读。
- 通过产品级入口「角色管理」新建的角色自动标记为系统角色；复制出的角色为可删除的自定义角色，并继承源角色的功能权限与数据授权。
- 新建角色默认没有任何功能权限，需要在其详情页勾选，或复制现有角色继承。
- `system:console:access` 是登录管理端的必要条件，未授予该权限的角色不能绑定管理端账号。
- 授权遵循最小权限：只能授予自己已拥有的功能权限，也不能复制包含自身不具备权限的角色。
- 产品级平台账号单独存于 `admin_users` 并绑定平台角色；租户管理员与普通用户统一存于 `users`，通过 `user_roles` 绑定租户角色。
- 角色只在所属作用域内生效：产品级账号只能登录 `adminsystem.<根域名>`，租户账号只能登录本租户子域名；不同作用域可以使用相同用户名。

> 项目**不预置任何默认账号和默认密码**。第一个管理员必须由你手动创建，见 3.2。

### 1.6 技术栈速览

| 部分     | 主要技术                                                                     |
|----------|------------------------------------------------------------------------------|
| 后端     | Python 3.12、FastAPI、SQLAlchemy 2.0、PostgreSQL 17（pgvector HNSW）、Alembic、PyJWT + bcrypt |
| 异步任务 | Celery 5 + Redis（broker DB=1 / result backend DB=2），用于文档 ingest      |
| RAG      | bge-large-zh-v1.5（embedding）、bge-reranker-v2-m3（cross-encoder 精排）、OpenAI 兼容 LLM（query 改写）；向量库支持 pgvector / Milvus |
| 管理端   | React 19、TypeScript 6、Vite 8、Ant Design 5、@xyflow/react（画布）、zustand（画布状态） |
| 用户端   | React 19、TypeScript、Vite                                                   |
| 图执行引擎 | LangGraph 运行时（checkpoint 断点续跑）、节点编译与拓扑校验、SSE 流式调试 |
| 工具协议 | MCP（Model Context Protocol）Streamable HTTP/SSE；HTTP 工具走统一治理网关 |
| 可观测性 | 结构化日志、请求追踪（OpenTelemetry）、Prometheus 指标、租户用量账本         |
| 测试     | pytest + httpx、Vitest + Testing Library、Playwright                         |
| 代码质量 | ruff、mypy、oxlint、Prettier、pre-commit                                     |
| 部署     | Docker Compose、Nginx、GitHub Actions                                        |

---

## 2. 准备软件

### 2.1 安装清单

| 软件           | 版本要求                  | 用途                       | 检查命令                                       |
|----------------|---------------------------|----------------------------|------------------------------------------------|
| Git            | 最新版                    | 下载代码                   | `git --version`                                |
| Python         | 3.12 或更高               | 运行后端                   | `python --version`                             |
| uv             | 最新版                    | 管理 Python 依赖和虚拟环境 | `uv --version`                                 |
| Node.js        | `^20.19.0` 或 `>=22.12.0` | 运行前端                   | `node --version`                               |
| pnpm           | 11 或更高                 | 安装前端依赖               | `pnpm --version`                               |
| Docker Desktop | 最新版                    | 启动本地 PostgreSQL 数据库 | `docker --version` 和 `docker compose version` |

安装参考：

```bash
# Git：Windows 下载 Git for Windows，安装后自带 Git Bash
# uv：Windows 可用 winget，也可以 pip install uv
winget install astral-sh.uv
# 或者
pip install uv

# pnpm：Node 自带的 corepack 可直接启用
corepack enable pnpm
# 或者
npm install -g pnpm@11
```

- **Python 可以不用手动装**：`uv sync` 发现系统没有 Python 3.12 时会自动下载一个。
- Node.js 建议安装 LTS 版本（22 或 24）。
- 前端依赖用 pnpm 管理；`frontend/admin/.npmrc`、`frontend/user/.npmrc` 已配置国内镜像源。
- **Windows 安装 Docker Desktop 需要开启 WSL 2**，按安装向导提示操作即可。
- Docker Desktop 安装后需要先启动，任务栏出现 Docker 图标、`docker ps` 不报错才算就绪。
- 安装完后**重新打开终端**，再执行检查命令。

### 2.2 获取代码

```bash
# 方式一：HTTPS（没有配置 SSH 密钥时用这个）
git clone https://github.com/miragesky2049/boxia-agent.git

# 方式二：SSH（已经配置好 GitHub SSH 密钥时用这个）
# git clone git@github.com:miragesky2049/boxia-agent.git

cd boxia-agent
```

> 克隆私有仓库时，HTTPS 方式会要求输入 GitHub 用户名和 Token（不是登录密码）；SSH 方式要求本机已生成并上传 SSH 公钥。

后面的命令默认都在**仓库根目录**执行；需要切换目录时文中会注明 `cd`。如果不确定自己在哪，执行 `pwd` 查看当前目录。

> 不用 Docker 也可以：本地安装 PostgreSQL 17，然后把 `backend/.env` 里的 `DATABASE_URL` 改成你自己的连接串即可。其他步骤不变。

---

## 3. 第一次启动

整个过程分三步：启动数据库 → 启动后端 → 启动管理端。

### 3.1 第一步：启动数据库

在仓库根目录执行：

```bash
docker compose -f backend/docker/postgresql/docker-compose.yml up -d
```

这条命令会在后台启动一个 PostgreSQL 容器（默认账号 `postgres`，密码 `postgres`，数据库 `boxia_agent`），端口只绑定本机 `127.0.0.1:5432`。编排文件把 Compose 项目名固定为 `postgresql`，因此 `docker compose ls` 中显示的名称不受执行目录影响。

确认它真的起来了：

```bash
docker ps
```

看到 `postgres` 且状态是 `Up ... (healthy)` 就表示成功了。

> 如果镜像拉取失败，看 [4.2](#42-docker-拉取镜像失败)；如果提示 Docker daemon 连不上，看 [4.10](#410-docker-报-cannot-connect-to-the-docker-daemon)。

**可选：把数据库数据目录放到宿主机**

默认使用 Docker 命名卷 `pgdata` 存数据，它位于 Docker 虚拟机内部（Windows 下在 Docker Desktop 的 WSL 发行版里），资源管理器看不到。如果希望数据直接落在宿主机某个目录，启动前设置 `PG_DATA_DIR`：

```powershell
# Windows PowerShell（当前会话有效）
$env:PG_DATA_DIR = "D:/Docker/postgresql"
docker compose -f backend/docker/postgresql/docker-compose.yml up -d
```

```bash
# Linux / macOS
export PG_DATA_DIR=$PWD/.pgdata
docker compose -f backend/docker/postgresql/docker-compose.yml up -d
```

也可以把 `PG_DATA_DIR=...` 写进 `backend/docker/.env`，之后每次 `docker compose -f backend/docker/postgresql/docker-compose.yml` 都会自动读取，不用重复设置。

确认实际挂载位置：

```bash
docker inspect postgres --format '{{range .Mounts}}{{.Type}}  {{.Source}}  ->  {{.Destination}}{{"\n"}}{{end}}'
```

`Type` 为 `volume` 表示用的是命名卷，为 `bind` 表示已经指向宿主机目录。

> 切换挂载方式**不会迁移已有数据**，直接切换会得到一个空库。已有数据时先 `docker compose -f backend/docker/postgresql/docker-compose.yml down`，把旧数据 `pg_dump` 出来，用新目录启动后再恢复。

**另起一个终端启动 Redis**（短期记忆 + Celery broker/result 依赖）：

```bash
docker compose -f backend/docker/redis/docker-compose.yml up -d
```

Redis 默认绑 `127.0.0.1:6379`，开 AOF + 256mb `allkeys-lru`；DB 0 短期记忆、DB 1 Celery broker、DB 2 Celery result 三个逻辑库共用同一实例。

**已有 PostgreSQL / Redis 时，跳过上面的 `docker compose up`**

如果你本地或公司内网已经有 PostgreSQL、Redis（比如直装的 PG、公司云托管 Redis、其他项目共用的实例），不需要再起一套 Docker 容器，只要改 `backend/.env` 里的四个连接串即可：

| 场景 | 改哪个变量 |
|------|------------|
| 已有 PostgreSQL | `DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:<port>/<db>` |
| 已有 Redis（短期记忆） | `REDIS_URL=redis://:<password>@<host>:<port>/0` |
| 已有 Redis（Celery broker） | `CELERY_BROKER_URL=redis://:<password>@<host>:<port>/1` |
| 已有 Redis（Celery result） | `CELERY_RESULT_BACKEND=redis://:<password>@<host>:<port>/2` |

前置条件：

- **自建 PostgreSQL 必须预装 pgvector 扩展**。RAG 知识库的 `document_chunks.embedding` 向量列依赖它，迁移 `0022_rag_documents` 时会自动 `CREATE EXTENSION`，但如果数据库账号没有建扩展权限会失败。用管理员账号先在目标库执行一次：
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```
  本地直装 PG / 公司内网 PG / 云托管 PG（如阿里云 RDS、AWS RDS）都需要这一步；只有仓库自带的 `pgvector/pgvector:pg17` 镜像已内置扩展。
- **三个 Redis 逻辑库必须互相隔离**：短期记忆用 DB 0、Celery broker 用 DB 1、Celery result 用 DB 2。如果外部 Redis 是云托管的只有单 DB，需要找运维开多个 DB 或换实例。
- **后端代码零改动**：连接串全部走 `backend/internal/infrastructure/config/settings.py` 的 pydantic-settings，没有任何硬编码主机名。

跳过 Docker 启动后，直接进 3.2 节初始化后端即可。

### 3.2 第二步：初始化并启动后端

**1）进入后端目录，准备配置文件**

```bash
cd backend
cp .env.example .env
```

Windows PowerShell 用户把 `cp` 换成：

```powershell
Copy-Item .env.example .env
```

`.env` 是本地配置文件，**不要提交到 Git**（`.gitignore` 已经忽略它）。示例配置里的数据库连接正好对应上一步启动的 PostgreSQL，所以本地开发不用改。

**2）安装后端依赖**

```bash
# 推荐指定python版本3.12.10
uv sync --python 3.12.10
# 不指定python
# uv sync
```

第一次执行会下载依赖（必要时自动下载 Python），可能需要几分钟。成功后 `backend/.venv/` 目录会出现。

**3）创建数据库表**

```bash
uv run alembic upgrade head
```

这条命令把数据库结构升级到最新版本。输出分两种情况：

- **有迁移需要执行**：打印若干 `Running upgrade 0001_baseline -> 0002_auth_hardening` 这样的日志，最后一条指向最新版本。
- **数据库已经是最新版本**：只打印 `Context impl PostgresqlImpl.` 和 `Will assume transactional DDL.` 两行连接信息，然后直接退出。这同样表示成功，不是报错。

无论哪种情况，都可以用下面的命令确认当前库版本。输出末尾带 `(head)` 就表示已是最新：

```bash
uv run alembic current
```

> 迁移日志输出到 **stderr** 而不是 stdout。如果重定向到文件（如 `uv run alembic upgrade head > log.txt`），需要写成 `... > log.txt 2>&1` 才能收集到这些日志。

**4）创建第一个管理员**

有两种方式，任选其一：

**方式 A：启动时自动初始化（推荐用于部署环境）**

在 `ops/.env.*` 或 `backend/.env` 中开启：

```bash
ADMIN_AUTO_INIT=true
ADMIN_INITIAL_PASSWORD='Boxia-2026-Root!'
ADMIN_INITIAL_USERNAME=admin
ADMIN_INITIAL_DISPLAY_NAME=系统管理员
ADMIN_INITIAL_ROLE=superadmin
ADMIN_INITIAL_MUST_CHANGE_PASSWORD=true
```

启动 admin 站点时，**同时满足以下两个条件**才会执行自动初始化：

1. `ADMIN_AUTO_INIT=true`
2. `ADMIN_INITIAL_PASSWORD` 非空

执行时若 `admin_users` 表为空（首次部署），会自动创建首个平台管理员账号；表中已有账号则跳过。密码不符合策略、角色不存在时跳过并输出告警日志。

**方式 B：手动脚本（适合本地调试或自动化流水线）**

```bash
uv run python -m scripts.create_admin
```

终端会提示：

```text
管理员密码:
```

输入密码时**屏幕不会显示字符**，这是正常的。输入完按回车。默认会创建：

- 用户名：`admin`
- 绑定平台 `superadmin` 角色（默认拥有所属作用域全部功能权限与数据范围，可用 `ADMIN_ROLE` 指定其他平台角色编码）
- 首次登录必须改密

默认创建的是**产品级平台账号**，只能登录平台子域名（生产为 `adminsystem.<根域名>`；本地为 `localhost:5173` 或 `adminsystem.localhost:5173`）。租户管理员由平台在「租户管理」中创建，或用下文的 `TENANT_CODE` 方式创建。

**密码规则**（统一读取 `backend/.env` 的 `PASSWORD_*` 配置，后端校验与前端表单同时生效，不符合会直接报错）：

- 长度不少于 `PASSWORD_MIN_LENGTH`（默认 12 位）
- 大写字母、小写字母、数字、符号，至少包含其中 `PASSWORD_MIN_CATEGORIES` 类（默认 3 类）
- UTF-8 编码不超过 `PASSWORD_MAX_BYTES` 字节（默认 72，即 bcrypt 的处理上限）
- 不能包含用户名（默认用户名是 `admin`，所以密码里不能出现 `admin`）
- 不能是常见弱口令，例如 `password1234`

可以用这个示例：`Boxia-2026-Root!`

推荐用交互方式输入密码，这样密码不会留在命令历史里。如果你确实需要非交互方式（比如自动化脚本）：

```bash
ADMIN_USERNAME=admin ADMIN_PASSWORD='Boxia-2026-Root!' uv run python -m scripts.create_admin
```

PowerShell 写法：

```powershell
$env:ADMIN_USERNAME="admin"; $env:ADMIN_PASSWORD="Boxia-2026-Root!"; uv run python -m scripts.create_admin
```

> 同一命令可以重复执行。用户名已存在时会重置该账号的密码，不会创建重复账号；重置后同样会要求下次登录改密。

**5）启动后端**

```bash
# 管理端后端（端口 8000）
uv run uvicorn web.app_admin:app --reload

# 用户端后端（端口 8001，另开一个终端执行）
uv run uvicorn web.app_user:app --reload --port 8001

# RAG 文档 ingest 异步 worker（另开终端，仅使用知识库时需要）
uv run celery -A internal.infrastructure.celery_app worker --loglevel=info -Q rag
```

终端会被占用，属于正常现象；关闭终端或按 `Ctrl + C` 就会停止后端。管理端后端地址是 `http://127.0.0.1:8000`，用户端后端是 `http://127.0.0.1:8001`。Celery worker 依赖 Redis（默认 `redis://127.0.0.1:6379/1`），未启动 worker 时文档 ingest 会一直停在 `queued` 状态。

**6）验证后端**

保持后端终端运行，用浏览器依次打开：

| 地址                                 | 应该看到                                           |
|--------------------------------------|----------------------------------------------------|
| <http://127.0.0.1:8000/health/live>  | `{"status":"ok"}`                                  |
| <http://127.0.0.1:8000/health/ready> | `status` 为 `ok`，表示数据库已连通且表结构是最新的 |
| <http://127.0.0.1:8000/docs>         | Swagger 接口文档（开发环境自动开启）               |
| <http://127.0.0.1:8001/health/live>  | 用户端后端存活；用户端文档在 `8001/docs`           |

如果 `/health/ready` 返回 503，看 [4.6](#46-healthready-返回-503-migration_outdated)。

### 3.3 第三步：启动管理端

**另开一个终端**（后端终端不要关）。先回到仓库根目录（如果当前还在 `backend`，执行 `cd ..`），然后执行：

```bash
cd frontend/admin
pnpm install
pnpm run dev
```

- `pnpm install` 会严格按照 `pnpm-lock.yaml` 安装依赖；首次较慢，之后复用全局 store，安装基本是秒级。
- `pnpm run dev` 启动开发服务器，成功后终端会显示访问地址。

也可以在 `frontend/` 根目录按站点启停（先确保对应子目录已 `pnpm install`）：

```bash
cd frontend
pnpm run dev admin     # 只启动管理端（5173）
pnpm run dev user      # 只启动用户端（5174）
pnpm run dev           # 两个前端一起启动
pnpm run stop admin    # 只停止管理端
pnpm run stop          # 停止两个前端
```

打开 <http://localhost:5173>：

1. 账号填 `admin`，密码填你在 3.2 第 4 步设置的密码。
2. **首次登录会强制跳转到改密页面**，按提示设置新密码。
3. 改密后会自动回到登录页，用新密码重新登录，即可进入管理后台。

### 3.4 第四步：确认一切正常

逐项打勾：

- [ ] `http://127.0.0.1:8000/health/ready` 返回 `ok`
- [ ] `http://127.0.0.1:8000/docs` 能打开
- [ ] `http://localhost:5173` 能用 `admin` 登录
- [ ] 登录后能看到「应用管理」页面
- [ ] 能进入「资源管理」页面，成功新建一条记录
- [ ] `http://adminsystem.localhost:5173` 能打开产品级登录页
- [ ] 创建租户后，`http://<租户编码>.localhost:5173` 能打开对应租户的登录页

启动用户端后再补打勾：

- [ ] `http://127.0.0.1:8001/health/live` 能返回
- [ ] `http://<租户编码>.localhost:5174`（或 `http://localhost:5174?tenant=<租户编码>`）能用普通用户账号登录
- [ ] 登录后看到应用卡片列表，能进入对话页
- [ ] 进入对话页能发送一条消息并收到回复；若应用挂了工具，回复下方能看到可折叠的工具调用轨迹

全部通过，说明本地环境已经可用。

### 3.5 第五步（可选）：启动用户端

再开一个终端，回到仓库根目录后执行：

```bash
cd frontend/user
pnpm install
pnpm run dev     # http://localhost:5174
```

也可以从 `frontend/` 根目录执行 `pnpm run dev user`（或 `pnpm run dev` 同时启动两端）。

用户端接口走独立后端 `127.0.0.1:8001`，使用最终用户账号密码登录。账号需由租户管理员在管理端"用户管理"中创建并绑定角色。用户端必须通过租户子域名访问（如 `http://<租户编码>.localhost:5174`），根域名 `localhost:5174` 会被拒绝；本地回环主机调试时可在登录页填写租户编码或使用 `?tenant=<租户编码>`，登录页会自动把租户编码写入 `localStorage`（键 `boxia.user-tenant-code`）并作为 `X-Tenant-Code` 请求头透传。

登录后路由与页面能力：

> 前端页面路径暂沿用 `/agents/:appId`（历史路径），语义上就是「应用」。

| 路径                          | 页面           | 能力                                                                                                          |
|-------------------------------|----------------|---------------------------------------------------------------------------------------------------------------|
| `/login`                      | 登录页         | 用户名/密码 + 租户编码（仅本地回环展示）；`next` 参数仅限站内相对路径，防开放重定向                             |
| `/`                           | 应用列表       | 卡片展示当前租户下可见且已启用的应用（头像、名称、简介、入口按钮）                                              |
| `/agents/:appId`              | 应用详情       | 展示应用元信息与可用工具/提示词（资源 Tab 按数量自动隐藏空 Tab），可直接进入对话                                |
| `/agents/:appId/chat`         | 对话页         | 多轮对话（携带 `conversation_id`）、建议提示词、Markdown + GFM 渲染、清空会话、工具调用轨迹折叠（名称/入参/返回/是否出错） |

用户端接口（前缀 `/api/v1/user`）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/user/agents` | 分页返回当前用户可见应用卡片 |
| GET | `/user/agents/{appId}` | 应用详情（模型、提示词、工具等运行前元信息） |
| POST | `/user/agents/{appId}/run/stream` | SSE 流式对话，推送 `run_start / llm_start / llm_end / tool_start / tool_end / result / error / final` |
| POST | `/user/agents/{appId}/run` | 非流式对话（同步返回 `content`、`tool_traces[]`、`iterations`、`usage`、`finish_reason`） |
| POST | `/user/agents/{appId}/workflow/run` | 按 DAG 模式非流式运行 |
| GET | `/user/agents/{appId}/conversations` | 会话列表 |
| GET | `/user/agents/{appId}/conversations/{conversationId}/messages` | 会话消息历史 |

> 对话页按「渐进式披露」原则默认折叠工具调用细节，只在用户主动展开时展示入参与返回。

### 3.6 懒人版一键启动

先回到仓库根目录。如果能使用 Git Bash，一条命令就能拉起全部服务（含数据库、后端、Celery、前端），不带参数时启动两个站点：

```bash
./ops/dev.sh          # 统一启动：管理端 + 用户端
./ops/dev.sh admin    # 只启动管理端：后端 8000 + Vite 5173
./ops/dev.sh user     # 只启动用户端：后端 8001 + Vite 5174
```

PowerShell 需要显式指定 Git Bash 路径（不要直接写 `bash ops/dev.sh`，那会调用 WSL 的 bash）：

```powershell
& "C:\Program Files\Git\bin\bash.exe" ops/dev.sh
& "C:\Program Files\Git\bin\bash.exe" ops/dev.sh admin
& "C:\Program Files\Git\bin\bash.exe" ops/dev.sh user
```

> 仓库中的 `.sh` 脚本在 Windows 上通常没有可执行权限，所以也可以统一用 `bash 脚本名` 运行（仅在 Git Bash 终端内有效）。
>
> 仓库根目录的 `.gitattributes` 已声明 `*.sh text eol=lf`，正常情况下脚本不会被 checkout 成 CRLF；若从旧版本更新后仍报 `$'\r': command not found`，执行 `sed -i 's/\r$//' ops/*.sh` 转换一次即可。

它会按顺序执行：

1. 通过 docker compose 拉起 PostgreSQL（`backend/docker/postgresql/`）和 Redis（`backend/docker/redis/`），已在运行则跳过
2. 清理上次残留的 Vite（5173/5174）和 Uvicorn（8000/8001）端口占用，避免 "Port already in use"
3. 如果 `backend/.env` 不存在，自动从 `.env.example` 复制
4. 执行 `uv sync` 和 `alembic upgrade head`
5. 按参数后台启动对应后端：管理端 `127.0.0.1:8000`、用户端 `127.0.0.1:8001`（热重载模式）
6. 后台启动 Celery RAG worker（队列 `rag`），Windows 下自动切 `--pool=solo`，详见 [4.14](#414-windows-下-celery-worker-报-permissionerror13-拒绝访问)
7. 按参数前台启动对应 Vite：管理端 `localhost:5173`、用户端 `localhost:5174`
8. `Ctrl + C` 时一并停止本次启动的后端、Celery worker 与 Vite

注意：

- 它**不会自动创建管理员**，仍然需要先完成 3.2 第 4 步。
- RAG / Agent 运行依赖 `LLM_API_KEY`、`EMBEDDING_API_KEY`，首次启动前请在 `backend/.env` 中填入；缺失时对话与知识库接口会报错，但不影响登录与基础管理。
- 如果 Vite 控制台报 `ECONNREFUSED 127.0.0.1:8001`，说明对应用户端后端没起，见 [4.15](#415-vite-控制台报-http-proxy-error-api-econnrefused-1270018001)。

### 3.7 如何停止服务

| 服务            | 停止方式                                                                                              |
|-----------------|-------------------------------------------------------------------------------------------------------|
| 后端            | 在启动它的终端按 `Ctrl + C`；用 `ops/dev.sh` 启动时按一次会同时停止对应的所有后端                     |
| 管理端 / 用户端 | 在对应终端按 `Ctrl + C`；或执行 `cd frontend && pnpm run stop`（两个前端）/ `pnpm run stop admin`（单个） |
| 数据库          | 执行 `docker compose -f backend/docker/postgresql/docker-compose.yml down`              |

> `down` 只停止并删除容器，**不会删除数据**。只有加 `-v` 才会连数据一起删除，见 [4.9](#49-想彻底重置本地数据库)。

### 3.8 端口速查

| 服务                 | 地址                                                 | 说明                                       |
|----------------------|------------------------------------------------------|--------------------------------------------|
| 管理端               | <http://localhost:5173>                              | 管理后台（本地回环，可用请求头切换作用域） |
| 管理端（平台子域名） | <http://adminsystem.localhost:5173>                  | 本地验证产品级平台域名解析                 |
| 管理端（租户子域名） | `http://<租户编码>.localhost:5173`                   | 本地验证租户域名解析，需先创建租户         |
| 用户端               | <http://localhost:5174>                              | 最终用户门户，需租户子域名访问             |
| 用户端（租户子域名） | `http://<租户编码>.localhost:5174`                   | 本地验证用户端域名解析与最终用户登录       |
| 管理端后端           | <http://127.0.0.1:8000/>                             | 仅 admin / public 路由                     |
| 用户端后端           | <http://127.0.0.1:8001/>                             | 仅 user 路由                               |
| 健康检查             | `http://127.0.0.1:8000/health/live`、`/health/ready` | 管理端后端存活 / 就绪                      |
| 接口文档             | <http://127.0.0.1:8000/docs>                         | 管理端在线调试（用户端为 8001/docs）       |
| 数据库               | `127.0.0.1:5432`                                     | 仅本机可访问                               |

### 3.9 常用命令速查

```bash
# 以下命令都在仓库根目录执行

# 启动数据库
docker compose -f backend/docker/postgresql/docker-compose.yml up -d

# 启动后端（控制台 1）
cd backend && uv run uvicorn web.app_admin:app --reload                # 管理端 8000
cd backend && uv run uvicorn web.app_user:app --reload --port 8001     # 用户端 8001
cd backend && uv run celery -A internal.infrastructure.celery_app worker --loglevel=info -Q rag  # RAG ingest worker

# 启动前端（控制台 2）
cd frontend && pnpm run dev admin   # 只启动管理端 5173
cd frontend && pnpm run dev user    # 只启动用户端 5174
cd frontend && pnpm run dev         # 两个前端一起启动

# 执行数据库迁移
cd backend && uv run alembic upgrade head

# 创建/重置管理员
cd backend && uv run python -m scripts.create_admin

# 运行后端测试
cd backend && uv run pytest

# 运行前端单元测试
cd frontend/admin && pnpm test
```

---

## 4. 新手常见问题

### 4.1 提示 `uv: command not found`

先安装 uv 并重新打开终端：

```bash
winget install astral-sh.uv
# 或
pip install uv
```

### 4.2 Docker 拉取镜像失败

如果拉取 `postgres:17-alpine` 超时，可以使用国内镜像源（以 daocloud 为例）：

```bash
docker pull docker.m.daocloud.io/library/postgres:17-alpine
docker tag docker.m.daocloud.io/library/postgres:17-alpine postgres:17-alpine
```

然后重新执行 3.1 的命令。生产镜像的加速方式见 [14.7](deployment.md#147-docker-hub-访问受限时)。

### 4.3 创建管理员提示“密码不符合策略”

按 3.2 的密码规则重新输入。最常见的原因：

- 长度不足 `PASSWORD_MIN_LENGTH`（代码默认 12 位；`backend/.env.example` 本地模板为 10 位）
- 只有字母或只有数字，字符类别不足 `PASSWORD_MIN_CATEGORIES`（默认 3 类）
- 密码里包含用户名 `admin`
- 使用了常见弱口令

### 4.4 登录提示“用户名或密码错误”

- 本项目**没有默认密码**，必须先执行过 `uv run python -m scripts.create_admin`。
- 忘记了密码：重新执行同一条命令即可重置（用户名已存在时会更新密码）。
- 首次登录后修改过密码，请使用**新密码**登录。
- 连续输错 5 次会锁定 15 分钟，等待后再试，或让超级管理员重置。

### 4.5 端口被占用（8000 / 8001 / 5173 / 5174）

前端可以按站点停止开发服务器：

```bash
cd frontend
pnpm run stop         # 停止两个
pnpm run stop admin   # 只停止管理端
pnpm run stop user    # 只停止用户端
```

后端 8000（管理端）或 8001（用户端）端口在 Windows 下可以这样排查：

```powershell
netstat -ano | findstr :8000
taskkill /PID <上一步查到的PID> /F
```

macOS / Linux：

```bash
lsof -i :8000
kill <PID>
```

### 4.6 `/health/ready` 返回 503 `migration_outdated`

代码版本比数据库新，执行：

```bash
cd backend
uv run alembic upgrade head
```

如果用的是生产 Compose，检查一次性 `migrate` 服务的日志。

### 4.7 Windows 下环境变量设置不生效

`ADMIN_USERNAME=admin ...` 这种写法只在 Bash 中有效。PowerShell 请先进入 `backend` 目录，再使用：

```powershell
cd backend
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="你的密码"
uv run python -m scripts.create_admin
```

或者干脆不加环境变量，直接在 `backend` 目录运行 `uv run python -m scripts.create_admin`，按提示输入。

### 4.8 启动前端提示 Node 版本过低

升级 Node.js 到 `20.19+` 或 `22.12+`。安装新版本后重新打开终端，用 `node --version` 确认。

### 4.9 想彻底重置本地数据库

如果数据库被改乱、迁移对不上，可以删掉本地数据重新开始：

> 警告：下面的命令会**删除本地数据库中的所有数据**，只适合本地开发环境，千万不要在生产服务器执行。

```bash
# 回到仓库根目录
docker compose -f backend/docker/postgresql/docker-compose.yml down -v
docker compose -f backend/docker/postgresql/docker-compose.yml up -d

cd backend
uv run alembic upgrade head
uv run python -m scripts.create_admin
```

### 4.10 Docker 报 `Cannot connect to the Docker daemon`

说明 Docker Desktop 没有启动，或者 WSL 2 没有配置好：

1. 打开 Docker Desktop，等待左下角显示引擎已运行。
2. Windows 上如果提示 WSL 2 相关错误，按 Docker Desktop 的提示安装/升级 WSL 2，然后重启电脑。
3. 重新执行 `docker ps`，能正常输出空列表（或已有容器）就说明好了。

### 4.11 启动数据库时报 5432 端口被占用

通常是本机已经装了 PostgreSQL，或者另一个 PostgreSQL 容器占用了端口。

先确认占用者：

```bash
docker ps --filter "publish=5432"
```

- 如果是别的容器，先停止它。
- 如果本机安装了 PostgreSQL 服务，可以停止该服务（Windows 在“服务”中停止 `postgresql-x64-*`），或者修改 `backend/docker/postgresql/docker-compose.yml` 的端口映射，同时修改 `backend/.env` 里的 `DATABASE_URL` 端口。

---

### 4.12 执行 `alembic upgrade head` 没看到 `Running upgrade` 日志

这通常说明**数据库已经是最新版本**，没有迁移需要执行。`upgrade head` 是幂等的：数据库版本等于代码 head 时会直接跳过，只打印两行连接信息就退出，退出码为 0，属于成功。

确认办法：

```bash
cd backend
uv run alembic current     # 输出形如 0003_search_trgm (head)
uv run alembic heads       # 与 current 一致即表示已是最新
```

另外，alembic 的日志输出到 **stderr**。如果只用 `> log.txt` 重定向 stdout，日志会被漏掉，需要写成 `2>&1`。

想在本地看清 `Running upgrade` 的完整输出，可以先降一级再升回来（会真实回滚数据库，只在本地开发库执行）：

```bash
uv run alembic downgrade -1
uv run alembic upgrade head
```

### 4.13 Windows PowerShell 下运行 `ops/*.sh` 报 `/bin/bash: No such file or directory`

完整报错类似：

```text
WSL (109097 - Relay) ERROR: CreateProcessCommon:818: execvpe(/bin/bash) failed: No such file or directory
```

原因：PowerShell 的 `bash` 解析到 `C:\Windows\System32\bash.exe`（WSL），而本机默认 WSL 发行版是 Docker Desktop 的 `docker-desktop`，其中没有 `/bin/bash`。可用 `wsl -l -v` 确认：

```text
  NAME              STATE           VERSION
* docker-desktop    Running         2
```

解决办法（任选其一）：

1. **用 Git Bash 运行**（推荐）：开始菜单打开 Git Bash，进入仓库根目录后执行 `./ops/dev.sh`。
2. **在 PowerShell 中显式指定 Git Bash**：
   ```powershell
   & "C:\Program Files\Git\bin\bash.exe" ops/dev.sh
   ```
3. 如果确实希望 PowerShell 里的 `bash` 可用，安装一个带 Bash 的 WSL 发行版并设为默认：
   ```powershell
   wsl --install -d Ubuntu
   wsl --set-default Ubuntu
   ```
   但 `ops/dev.sh` 只调用 Windows 侧的 `uv` / `pnpm`，用 Git Bash 更直接。

### 4.14 Windows 下 Celery worker 报 `PermissionError(13, '拒绝访问。')`

完整报错类似：

```text
[ERROR/SpawnPoolWorker-1] Pool process ... error: PermissionError(13, '拒绝访问。', None, 5, None)
...
PermissionError: [WinError 5] 拒绝访问。
```

原因：Celery 默认的 prefork 池依赖 Unix fork 语义，在 Windows 上 billiard 子进程在获取信号量时会被系统拒绝。这是 Windows 平台的已知限制，不是代码问题。

解决办法：使用 `--pool=solo`（单进程，调试友好）或 `--pool=threads`。`ops/dev.sh` 已经自动检测 Git Bash / MSYS 环境并切到 `--pool=solo`，无需手动处理。如果单独启动 worker，请加参数：

```bash
uv run celery -A internal.infrastructure.celery_app worker --loglevel=info -Q rag --pool=solo
```

### 4.15 Vite 控制台报 `http proxy error: /api/... ECONNREFUSED 127.0.0.1:8001`

完整报错类似：

```text
23:06:36 [vite] http proxy error: /api/v1/user/auth/login
Error: connect ECONNREFUSED 127.0.0.1:8001
    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1705:16)
```

原因：**user 端 FastAPI 后端没有启动**，不是 `vite.config.ts` 配置问题。

前端代理规则（`frontend/user/vite.config.ts`）：

```ts
proxy: {
  '/api': {
    target: env.VITE_PROXY_TARGET || 'http://127.0.0.1:8001',
    changeOrigin: false,
  },
}
```

- `frontend/user` 下所有 `/api/*` 请求都会被转发到 `127.0.0.1:8001`（user 端后端）。
- `frontend/admin` 下的 `/api/*` 转发到 `127.0.0.1:8000`（admin 端后端）。
- 若报错是 `8000 ECONNREFUSED`，对应就是 admin 端后端没起，排查思路一致。

先确认端口是否真的在监听：

```bash
# Windows (Git Bash / PowerShell)
netstat -ano | findstr :8001

# macOS / Linux
lsof -i :8001
```

没有输出即说明后端进程没在跑。解决方法任选其一：

1. **推荐：一键脚本拉起全部服务**（数据库 + 双后端 + Celery + Vite）：
   ```bash
   ./ops/dev.sh all
   ```
2. **单独启动 user 端后端**（另开一个终端，保持运行）：
   ```bash
   cd backend
   uv run uvicorn web.app_user:app --reload --host 127.0.0.1 --port 8001
   ```
3. **单独启动 admin 端后端**（如果报错的是 8000）：
   ```bash
   cd backend
   uv run uvicorn web.app_admin:app --reload --host 127.0.0.1 --port 8000
   ```

启动后看到 `Application startup complete.` 即可回到前端页面重试登录，Vite 控制台不再报 ECONNREFUSED。

> 想让前端代理指向其它后端地址（如远程联调环境），可在 `frontend/user/.env.local` 中设置 `VITE_PROXY_TARGET=http://<host>:<port>`，无需改 `vite.config.ts`。

---

