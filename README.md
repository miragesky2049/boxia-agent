# boxia-agent 项目手册

基于大语言模型的**智能体开发与运营平台**：管理员在后台创建智能体、配置模型与提示词、挂载技能和工具；后端提供登录鉴权、资源管理、租户与角色授权和审计能力；最终用户在用户端登录后，只看到被授权且已启用的智能体。

---

## 🚀 小白速通（30 秒看完）

### 一句话这是什么

一个"**不写代码就能搭 AI 助手**"的企业内部平台：管理员在网页上配置智能体 → 发布给某个租户 → 租户员工登录用户端直接使用。

### 一张图看懂架构

```text
你的浏览器
   │
   ├── 管理端 (运营/管理员)  http://localhost:5173
   └── 用户端 (普通员工)    http://localhost:5174
            │
            │  /api/v1/admin/**  、 /api/v1/user/**
            ▼
   ┌──────────────────────────────┐
   │ 后端 FastAPI (Python 3.12)  │
   │  - 管理端后端 :8000         │
   │  - 用户端后端 :8001         │
   └──────────────┬───────────────┘
                  ▼
          PostgreSQL 17 (:5432)
```

- **后端**：Python + FastAPI，两个独立站点（admin / user）
- **管理端前端**：React 19 + Ant Design 5
- **用户端前端**：React 19
- **数据库**：PostgreSQL 17（Docker 启动，不用自己装）

### 5 分钟把项目跑起来

> 前提：已装 **Git、Docker Desktop、Python 3.12、uv、Node.js 20+/22+、pnpm 11**。详见 [第 2 章](#2-准备软件)。

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

- 卡住了 → [第 4 章 新手常见问题](#4-新手常见问题)
- 想改代码 → [第 5 章 目录结构与代码分层](#5-目录结构与代码分层)
- 想部署上线 → [第 14 章 生产环境落地部署](#14-生产环境落地部署)
- 想面试讲清楚 → [第 13 章 面试讲解指南](#13-面试讲解指南)

---

> 建议在 **Git Bash**（Windows）、macOS 或 Linux 终端中执行本文命令。仓库中的 `ops/*.sh` 脚本需要 Bash；Windows 安装 [Git for Windows](https://git-scm.com/download/win) 即可获得 Git Bash。
>
> ⚠️ PowerShell 里的 `bash` 指向 WSL（`C:\Windows\System32\bash.exe`），而 Docker Desktop 自带的默认发行版 `docker-desktop` 没有 `/bin/bash`，直接执行会报 `execvpe(/bin/bash) failed: No such file or directory`。请改用 Git Bash，或显式指定 Git Bash 路径：`& "C:\Program Files\Git\bin\bash.exe" ops/dev.sh`。详见 [4.13](#413-windows-powershell-下运行-opssh-报-binbash-no-such-file-or-directory)。

---

## 目录

### 📖 入门必读（第一次跑起来）

- [1. 项目是什么](#1-项目是什么)
- [2. 准备软件](#2-准备软件)
- [3. 第一次启动](#3-第一次启动)
- [4. 新手常见问题](#4-新手常见问题)

### 🛠️ 开发参考（改代码、查配置）

- [5. 目录结构与代码分层](#5-目录结构与代码分层)
- [6. 配置说明](#6-配置说明)
- [7. 登录、权限与安全](#7-登录权限与安全)
- [8. 接口手册](#8-接口手册)
- [9. 数据库与迁移](#9-数据库与迁移)
- [10. 管理端功能](#10-管理端功能)
- [11. 测试与质量门禁](#11-测试与质量门禁)
- [12. 系统运行流程](#12-系统运行流程)

### 🎯 场景化使用

- [13. 面试讲解指南](#13-面试讲解指南)
- [14. 生产环境落地部署](#14-生产环境落地部署)
- [15. 日常运维](#15-日常运维)
- [16. 更多问题](#16-更多问题)
- [17. 许可证](#17-许可证)

---

## 1. 项目是什么

### 1.1 一句话定位

**一个面向企业内部的 AI 智能体配置与运营平台。** 管理员不用写代码，就能在后台组合模型、提示词、技能、工具和知识库，快速发布一个可用的 AI 助手。

### 1.2 系统组成

项目由三块组成，彼此独立开发、通过 HTTP 接口通信：

```text
你的浏览器
│
├── 管理端  http://localhost:5173    ← 运营/管理员使用（React）
│           http://*.localhost:5173  ← 本地验证平台/租户子域名
├── 用户端  http://localhost:5174    ← 最终用户使用（登录后浏览已授权智能体）
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
- **管理端**：React 19 + TypeScript + Ant Design，负责智能体、资源、租户、管理员和审计管理。
- **用户端**：React + TypeScript，最终用户登录后浏览可见智能体及其技能、工具、组件与提示词。
- **数据库**：PostgreSQL 17。开发时用 Docker 启动，不需要单独安装。

### 1.3 核心能力

| 模块         | 能力                                                                                           |
|--------------|------------------------------------------------------------------------------------------------|
| 智能体管理   | 新建、编辑、启用/停用、删除；配置模型、提示词、记忆、欢迎语、FAQ、发布渠道、工具、技能、知识库 |
| RAG 知识库   | 文档按 Markdown 标题层级切分（保留 heading_path）→ embedding（bge-large-zh）写入 pgvector；检索链路：LLM query 改写（指代消解 + 多 query 变体）→ 并行向量召回 → Cross-Encoder rerank 精排（bge-reranker-v2-m3）→ 阈值过滤注入 prompt；ingest 走 Celery 异步任务，状态机 `pending → queued → processing → ready/failed` |
| 资源管理     | 技能、工具、组件、提示词归属智能体，在智能体详情内增删改查、搜索、分页、启用/停用；跨智能体复用通过克隆副本 |
| 租户授权     | 产品级智能体必须显式授权给租户后才可见；通过独立「授权管理」菜单按租户/角色集中配置                 |
| 多租户       | 按二级域名区分产品级平台与租户；租户数据行级隔离，产品级智能体授权后租户只读使用               |
| 角色管理     | 平台与租户各自维护角色体系；角色通过权限资源目录授权功能权限，新建角色默认无权限；产品级入口创建的角色为系统角色；平台角色可授权平台级资源 |
| 用户管理     | 租户管理员与普通用户统一为 `users` 账号体系，通过角色赋权；用户端仅能看到被授权且已启用的智能体 |
| 组织架构     | 部门树（物化路径、最多 10 级）、用户任职记录（单一主任职 + 调岗归档 + 历史可查）、智能体归属部门；为后续部门数据权限预留接入点 |
| 认证与会话   | 短期 Access Token + 可撤销 Refresh Token，单次轮换、重放检测、跨标签页同步                     |
| 权限控制     | 功能权限按权限资源编码校验菜单、页面、按钮与资源读写；列表、详情、写操作均由服务端按数据授权过滤 |
| 安全防护     | 登录锁定、防用户名枚举、密码策略、统一错误模型、安全响应头、接口限流                           |
| 审计与可观测 | 审计日志、请求 ID、结构化日志、OpenTelemetry 链路追踪、Prometheus 指标                         |
| 工程化交付   | Alembic 迁移、Docker Compose、Nginx 反代、GitHub Actions、备份恢复脚本                         |

### 1.4 名词解释

第一次看可能不懂的词，先看这张表：

| 名词              | 用大白话解释                                                                         |
|-------------------|--------------------------------------------------------------------------------------|
| 智能体（Agent）   | 一个配置好的 AI 助手。比如“陪练剧本生成助手”，它有自己的人设、模型、欢迎语和可用能力 |
| 技能（Skill）     | 智能体会的一项本领，比如“根据业务信息生成剧本”                                       |
| 工具（Tool）      | 智能体可以调用的外部接口，比如“查询天气”“创建工单”                                   |
| 组件（Component） | 对话页面上的展示模块，比如欢迎语卡片、常见问题列表                                   |
| 提示词（Prompt）  | 写给 AI 模型的指令模板，决定它怎么理解和回答                                         |
| 迁移（Migration） | 数据库结构的升级脚本。代码更新后执行迁移，表结构才会同步                             |
| Token             | 登录成功后服务器发的“通行证”。之后每次请求都带上它，服务器才知道你是谁               |
| RBAC              | 基于角色的权限控制。不同角色能做的事不一样                                           |
| 产品级平台        | 通过 `adminsystem.<根域名>` 访问，跨租户运营，维护产品级智能体与资源并按租户/角色授权 |
| 租户级平台        | 通过 `<租户编码>.<根域名>` 访问，只能维护本租户自己的智能体与资源                    |
| 部门（Department）| 租户内的组织单元，支持树形层级（最多 10 级），用物化路径 `path=/<root>/.../<self>/` 存储以高效查询子树 |
| 任职（Employment）| 用户在某个部门的任职记录；同一用户同一时刻仅一条 `is_current=TRUE`（部分唯一索引约束），调岗自动归档旧记录并写入新记录，保留完整历史 |

### 1.5 角色与权限

系统预置全局只读的权限资源目录，覆盖管理端菜单（`menu:*`）、页面（`page:*`）、按钮（`button:*`）以及智能体/技能/工具/组件/提示词的增删改查（如 `agent:read`、`agent:update`）。角色通过 `role_permissions` 绑定权限编码，账号绑定角色后实时生效。

| 权限类别 | 作用                         | 示例                                                         |
|----------|------------------------------|--------------------------------------------------------------|
| `system` | 管理端入口与全量数据范围     | `system:console:access`、`system:data:all`                   |
| `menu`   | 左侧菜单可见性               | `menu:roles`                                                 |
| `page`   | 页面与对应接口访问           | `page:roles`                                                 |
| `button` | 页面操作按钮                 | `button:role:grant`                                          |
| 资源     | 资源读写                     | `agent:create` / `agent:read` / `agent:update` / `agent:delete` |

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
| RAG      | bge-large-zh-v1.5（embedding）、bge-reranker-v2-m3（cross-encoder 精排）、OpenAI 兼容 LLM（query 改写） |
| 管理端   | React 19、TypeScript 6、Vite 8、Ant Design 5                                 |
| 用户端   | React 19、TypeScript、Vite                                                   |
| 可观测性 | 结构化日志、请求追踪（OpenTelemetry）、Prometheus 指标                       |
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
- [ ] 登录后能看到“智能体列表”页面
- [ ] 能进入任一资源页面（如“技能”），成功新建一条记录
- [ ] `http://adminsystem.localhost:5173` 能打开产品级登录页
- [ ] 创建租户后，`http://<租户编码>.localhost:5173` 能打开对应租户的登录页

全部通过，说明本地环境已经可用。

### 3.5 第五步（可选）：启动用户端

再开一个终端，回到仓库根目录后执行：

```bash
cd frontend/user
pnpm install
pnpm run dev     # http://localhost:5174
```

也可以从 `frontend/` 根目录执行 `pnpm run dev user`（或 `pnpm run dev` 同时启动两端）。

用户端接口走独立后端 `127.0.0.1:8001`，使用最终用户账号密码登录。账号需由租户管理员在管理端“用户管理”中创建并绑定角色。用户端必须通过租户子域名访问（如 `http://<租户编码>.localhost:5174`），根域名 `localhost:5174` 会被拒绝；本地回环主机调试时可在登录页填写租户编码或使用 `?tenant=<租户编码>`。

### 3.6 懒人版一键启动

先回到仓库根目录。如果数据库已经在运行，并且能使用 Git Bash，可以用一条命令启动指定站点（含对应后端与自动迁移），不带参数时启动两个站点：

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

它会：

1. 通过 docker compose 拉起 PostgreSQL（`backend/docker/postgresql/`）和 Redis（`backend/docker/redis/`），已在运行则跳过
2. 清理上次残留的 Vite（5173/5174）和 Uvicorn（8000/8001）端口占用，避免 "Port already in use"
3. 如果 `backend/.env` 不存在，自动从 `.env.example` 复制
4. 执行 `uv sync` 和 `alembic upgrade head`
5. 按参数后台启动对应后端：管理端 `127.0.0.1:8000`、用户端 `127.0.0.1:8001`
6. 后台启动 Celery RAG worker（队列 `rag`），供文档异步 ingest 与向量写入
7. 按参数前台启动对应 Vite：管理端 `localhost:5173`、用户端 `localhost:5174`
8. `Ctrl + C` 时一并停止本次启动的后端、Celery worker 与 Vite

注意：

- 它**不会自动创建管理员**，仍然需要先完成 3.2 第 4 步。
- RAG / Agent 运行依赖 `LLM_API_KEY`、`EMBEDDING_API_KEY`，首次启动前请在 `backend/.env` 中填入；缺失时对话与知识库接口会报错，但不影响登录与基础管理。

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

然后重新执行 3.1 的命令。生产镜像的加速方式见 [14.7](#147-docker-hub-访问受限时)。

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

---

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

检索链路（在用户端对话时由 `AgentRunService` 自动调用，无需前端单独发起）：

```
用户 query + 最近历史
  → LLM query 改写（standalone 指代消解 + N 个同义变体）
  → 对每个变体并行 embedding → pgvector cosine 召回 top_k × recall_multiplier
  → 按 (document_id, chunk_index) 去重合并
  → Cross-Encoder rerank 精排（bge-reranker-v2-m3）
  → 按 rerank 阈值 0.1 过滤 → 取 top_k
  → 拼装 "[资料 N | 章节路径]\n{chunk 内容}" 注入 system_prompt
```

降级策略：rerank 失败自动退化为向量余弦过滤；query 改写失败退化为原始 query；embedding 临时故障由 Celery retry 兜底。

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

### 8.6 用户端接口

用户端站点（`web.app_user:app`）只有 `/api/v1/user/**`，与管理端完全隔离。最终用户由租户管理员在管理端“用户管理”中创建并绑定角色：

| 方法 | 路径                   | 说明                                                                 |
|------|------------------------|----------------------------------------------------------------------|
| POST | `/user/auth/login`     | 账号密码登录，返回 access/refresh、有效期与用户角色信息              |
| POST | `/user/auth/refresh`   | 轮换刷新令牌；检测到重放会撤销整个会话族                             |
| POST | `/user/auth/logout`    | 撤销当前会话族，返回 204                                             |
| GET  | `/user/me`             | 当前用户、所属租户、角色与功能权限编码                               |
| GET  | `/user/agents`         | 分页查询当前角色可见且已启用的智能体，支持 `keyword`                 |
| GET  | `/user/agents/{id}`    | 智能体详情及已过滤的技能/工具/组件/提示词；不可见统一返回 404        |

- 鉴权：Access Token + Refresh Token，与管理员令牌使用不同 `aud`（`USER_JWT_AUDIENCE`），两端令牌不能互相冒用。
- 租户作用域：必须通过租户子域名访问（`<租户编码>.<ROOT_DOMAIN>`）；平台域名或未知域名返回 404/403。登录与刷新令牌都校验租户一致性。
- 可见性：在租户规则上追加 `is_enabled=true`，角色集合仅本人 `role_id`；未显式授权的智能体不可见。
- 实例级可见范围：管理端可为租户智能体配置 `visibility_mode=custom` 与可见部门（含子树）/指定人员列表；user 端查询在租户授权之上叠加该过滤，未命中返回 404。无当前任职的用户仅命中 `all` 模式与直接指定的 `user_id` 规则。
- 用户端站点不挂载 `/admin/**` 与 `/public/**`；用户登录、刷新重放与登出写入审计日志。

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
| `alembic_version`                             | 当前迁移版本                                                                             |

约定：

- 资源与审计记录都带 `tenant_id`：`NULL` 表示产品级，非空表示租户私有；平台账号表 `admin_users` 不保存租户维度，通过 `role_id` 绑定平台角色。
- 资源名称与用户名按作用域唯一：唯一索引为 `(COALESCE(tenant_id, 0), lower(name))` 与 `(COALESCE(tenant_id, 0), username)`，不同租户可以同名；应用层额外禁止租户与产品级资源重名。
- 所有表都有 `created_at` / `updated_at`，`updated_at` 由触发器维护。
- 列表默认按 `updated_at DESC, id DESC` 排序。
- 资源名称和描述使用 `pg_trgm` 索引，支持模糊搜索。
- RAG 向量列依赖 `pgvector` 扩展：迁移 `0022_rag_documents` 会自动 `CREATE EXTENSION IF NOT EXISTS vector`，但 PostgreSQL 镜像必须预装该扩展（推荐 `pgvector/pgvector:pg17`）；自建外部库时需 DBA 先装好 `vector` 包。
- 迁移 `0006_roles_and_resource_access` 新增角色、最终用户、授权表与资源 `agent_id`，并为存量数据回填系统角色、归属与租户授权；DDL 支持 downgrade，但数据回填不可逆，升级前必须备份并在预发库演练。
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

## 10. 管理端功能

| 模块                        | 能力                                                                                                                                                            |
|-----------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 登录                        | 账号密码登录、本地作用域切换（回环主机用下拉框/`?tenant=`，子域名主机跳转对应域名；部署环境仅域名）、环境与解析来源标识、锁定提示、登录后回跳、首次登录强制改密 |
| 会话                        | Access Token 只存内存、自动刷新、跨标签页同步、退出时通知后端撤销                                                                                               |
| 智能体管理                  | 搜索、状态筛选（平台视角含“仅已授权”）、分页、新建、配置、启用/停用、删除                                                                                        |
| 智能体配置                  | Tabs：配置（基础信息、模型、角色与提示词、记忆、对话体验、发布渠道、知识库等）、技能与资源、可见范围（仅租户智能体；全员可见 / 自定义部门含子树 + 指定人员）           |
| 技能与资源                  | 在智能体详情内管理所属技能/工具/组件/提示词；增删改查、搜索、分页、克隆到其他智能体；按 `button:{resource}:*` 权限控制操作入口                                  |
| 技能包                      | 抽屉内管理多文件：查看/编辑、新建、删除、zip 导入导出；平台级技能可克隆到本租户                                                                                 |
| 授权管理                    | 独立菜单按资源类型集中授权；资源列表与详情页不再提供授权入口；支持授权状态筛选、多选批量追加/覆盖/移除；平台视角按租户逐个配置，租户视角仅本租户角色               |
| 角色管理                    | 平台/租户各自维护角色增删改与复制；详情页按权限目录维护功能权限；系统角色不可删除、不可停用；平台角色可授权平台级资源（`button:role:*`）                       |
| 用户管理                    | 租户管理员与普通用户统一账号：增删改、多角色绑定、重置密码、启停（`button:user:*`）；列表展示「当前部门」（来自当前任职），支持按部门（含下级）筛选  |
| 部门管理                    | 租户内部门树增删改查、层级（最多 10 级）、编码、排序、启停切换；删除时若存在子部门/任职记录/归属智能体则禁止（409 引导停用）；停用部门不可再挂接任职或智能体 |
| 任职管理                    | 用户任职记录增删改查、按用户/部门/状态筛选；同一用户同时仅一条当前任职；调岗自动归档旧记录并写入新记录；支持结束任职、查看完整历史                            |
| 智能体配置-基础信息         | 租户智能体可选「所属部门」（TreeSelect），平台智能体该字段隐藏且强制为 NULL；同租户与启用校验                                                                    |
| 管理员账号                  | 平台维护产品级账号，租户维护拥有管理角色的用户；列表、创建、角色/状态调整、重置密码、删除（`button:admin-user:*`）                                               |
| 租户管理                    | 租户列表、新建、编辑名称与启用状态（`button:tenant:*`，仅产品级平台角色可授予）                                                                                  |
| 菜单与路由                  | 菜单由 `/admin/context` 的 `menus`（`menu:*`）驱动，路由由 `page:*` 权限守卫；无权限路由返回 404                                                                |
| 多租户标识                  | 产品级资源显示「平台级」，租户内部只读；租户自有资源显示「本租户」                                                                                              |
| 健壮性                      | 路由懒加载、错误边界、404 页面、请求超时与重试                                                                                                                  |

页面路由：

```text
/login
/change-password
/agents                  智能体列表
/agents/new              新建智能体
/agents/:id/edit         智能体配置 + 技能与资源
/grants                  授权管理（menu:grants）
/roles                   角色管理（menu:roles；平台显示平台角色，租户显示本租户角色）
/users                   用户管理（menu:users，租户）
/departments             部门管理（menu:departments，租户；组织架构分组）
/employments             任职管理（menu:employments，租户；组织架构分组）
/admin-users             管理员账号（menu:admin-users）
/tenants                 租户管理（menu:tenants，产品级）
*                        404
```

菜单由 `/admin/context` 返回的 `menus` 驱动，来源是角色拥有的 `menu:*` 权限：平台 superadmin 为 `agents, grants, roles, admin-users, tenants, audit`；租户 superadmin 为 `agents, grants, roles, users, departments, employments, admin-users, audit`。`departments` 与 `employments` 在前端合并为「组织架构」SubMenu，自定义角色按实际授权显示，无权限路由返回 404。

授权管理页同样按视角收敛：平台只列平台级资源，租户只列本租户自有资源；列表展示授权汇总与授权状态，翻页保留勾选（单次最多 100 个），可批量追加/覆盖/移除。行内「配置授权」抽屉按租户配置访问范围（平台为「该租户不可见 / 整个租户 / 指定角色」，租户为「全部角色可见（默认）/ 指定角色」），保存只写入当前租户并刷新汇总。

---

## 11. 测试与质量门禁

### 11.1 后端

```bash
cd backend

uv run ruff check .                 # 代码规范
uv run ruff format --check .        # 格式检查
uv run mypy internal web            # 类型检查
uv run pytest --cov=internal --cov=web --cov-report=term-missing --cov-fail-under=80
uv run alembic check                # 迁移漂移检查
```

> 运行测试前，先确认本地 PostgreSQL 已经启动（即 3.1 的 Docker 容器处于运行状态）。

测试会自动创建独立数据库 `boxia_agent_test`，每次会话重建并执行全部迁移，每个用例前清理数据，互不影响。测试默认连接 `postgres:postgres@127.0.0.1:5432`，且账号需要有建库权限；如果你的本地配置不同，需要修改 `backend/tests/conftest.py` 顶部的连接配置。

覆盖范围包括：登录/刷新/撤销/锁定、RBAC、审计、四类资源 CRUD、智能体配置、多租户作用域隔离（子域名识别、跨作用域令牌拒绝、租户账号与审计隔离）、角色与用户管理、管理员账号、授权汇总/批量授权/租户作用域与可见性矩阵、资源克隆、用户门户（`tests/test_roles.py`、`test_users.py`、`test_admin_users.py`、`test_grants.py`、`test_resource_clone.py`、`test_user_portal.py`）、admin/user 站点路由隔离（`tests/test_site_isolation.py`）、错误模型、健康检查等。

### 11.2 管理端

```bash
cd frontend/admin

pnpm run typecheck
pnpm run lint
pnpm run format:check
pnpm run test:coverage
pnpm run build
```

用户端（`frontend/user`）：

```bash
cd frontend/user

pnpm run typecheck
pnpm run lint
pnpm test
pnpm run build
```

### 11.3 端到端（Playwright）

E2E 需要一个**不需要改密**的管理员，并通过环境变量 `E2E_PASSWORD` 提供密码。仓库里没有默认密码，缺少该变量时测试会直接报错。

准备测试管理员：

```bash
export E2E_PASSWORD='Boxia-2026-E2e!'
cd backend
ADMIN_USERNAME=admin ADMIN_PASSWORD="$E2E_PASSWORD" \
  ADMIN_MUST_CHANGE_PASSWORD=false ADMIN_ROLE=superadmin \
  uv run python -m scripts.create_admin
```

运行：

```bash
cd ../frontend/admin
pnpm exec playwright install chromium
E2E_PASSWORD="$E2E_PASSWORD" pnpm run e2e
```

如果你是在新的终端里操作，请从仓库根目录执行 `cd frontend/admin`。

> PowerShell 不支持 `变量=值 命令` 这种写法。请先执行 `$env:E2E_PASSWORD="Boxia-2026-E2e!"`，再直接运行 `pnpm run e2e`。

前置条件：

1. 后端已启动在 `127.0.0.1:8000`，数据库已迁移。
2. Vite 会由测试自动启动（默认 `http://localhost:5173`）。
3. 前端目录是 `frontend/admin`，后端目录是 `backend`，两个目录同级。

本地跑 E2E 时，后端需以本地调试配置启动（`DATABASE_URL`、`JWT_SECRET` 仍从 `backend/.env` 读取）：

```bash
cd backend
APP_ENV=local ROOT_DOMAIN=localhost ALLOW_TENANT_HEADER=true \
  uv run uvicorn web.app_admin:app --host 127.0.0.1 --port 8000
```

覆盖场景：登录失败、会话恢复、登出跳转、智能体内技能 CRUD、智能体保存回显、404、首登改密、viewer 只读（无写入口、越权页面 404）。

多租户用例（`e2e/tenant.spec.ts`）会通过平台 API 创建测试租户并切换作用域：本地 `localhost` 上使用登录页下拉框或 `?tenant=`（请求头模式），同时覆盖直接访问 `http://<租户编码>.localhost:5173` 的真实子域名解析。因此 `E2E_USERNAME` 必须是**产品级 superadmin**（默认 `admin`），后端需以 `APP_ENV=local`、`ROOT_DOMAIN=localhost`、`ALLOW_TENANT_HEADER=true` 启动（CI 已配置）。用例覆盖：平台租户管理（含编辑租户名称）、作用域切换限制、租户子域名访问、租户管理员作用域限制、平台智能体授权后才在租户可见、租户管理员管理角色与用户。

### 11.4 CI 与提交前检查

- `.github/workflows/ci.yml`：后端 lint / 类型 / 测试 / 迁移漂移；前端类型 / Lint / 格式 / 单测 / 构建；Playwright E2E；Docker 构建 + Trivy 漏洞扫描。
- `.github/workflows/docker-publish.yml`：main 分支或 tag 推送时发布镜像到 GHCR。
- E2E 测试密码在 CI 运行时随机生成并脱敏输出，不依赖仓库中的固定值。
- 本地一键检查（与 CI 基本一致）：

```bash
bash ops/check.sh
```

- 安装提交前钩子（ruff、prettier、oxlint、空白/YAML/TOML/私钥检查）：

```bash
cd backend
uv run pre-commit install   # 钩子安装在仓库根目录
```

---

## 12. 系统运行流程

这一章把各个模块串起来，面试讲解时可以按这里的顺序展开。

### 12.1 启动流程

1. `docker compose` 启动 PostgreSQL。
2. 后端启动时读取环境变量，校验配置；生产环境还会校验密钥强度。
3. 后端装配中间件：请求 ID → 访问日志 → 审计 → 安全响应头 → CORS。
4. 按站点装配路由：`/health/*`、`/metrics`，以及本站点的 `/api/v1/*`（可选 `/api/*` 兼容别名）；管理端挂 admin/public，用户端只挂 user。
5. 两个站点各自启动 Uvicorn：管理端 8000、用户端 8001，多个 worker 同时监听。
6. 两个前端分别由 Nginx 提供静态文件，并把 `/api/` 反向代理到本站点后端。

### 12.2 多租户作用域解析

```text
请求进入
  ▼
web/deps/tenant.py 读取 Host（去端口、转小写、去尾点）
  ├─ local + 回环/本机主机（localhost、127.0.0.1、任意 IP、testserver）
  │    ├─ ALLOW_TENANT_HEADER=true 且带 X-Tenant-Code → 按请求头（platform 表示产品级）
  │    └─ 未指定 → DEFAULT_TENANT_CODE 或产品级平台（resolution=default）
  ├─ adminsystem.<ROOT_DOMAIN> → 产品级平台（resolution=host）
  ├─ <code>.<ROOT_DOMAIN>      → 按 code 查询租户（域名优先于请求头，resolution=host）
  │    ├─ 不存在 → 404；已停用 → 403
  │    └─ 存在 → 租户作用域（tenant_id = 该租户）
  ├─ 根域名 → DEFAULT_TENANT_CODE 对应租户；未配置则 404
  └─ 其他 Host → 404（绝不静默回退产品级平台）
  ▼
RequestContext（scope、tenant、resolution）
  ├─ /public/context：返回 app_env、tenant_resolution、tenant_switch_mode、platform_admin_host
  ├─ 登录/刷新：账号只在当前作用域查找，JWT 携带 tid
  └─ 鉴权：令牌 tid、账号归属、当前作用域三者任一不一致 → 401
```

仓储层还会再按作用域过滤一次：平台只读写产品级数据（`tenant_id IS NULL`）；租户能“看到本租户 + 产品级”，但只能写本租户。即使上层校验有遗漏，SQL 层也不会跨租户读写。

### 12.3 一次登录请求的完整旅程

```text
浏览器
  │ POST /api/v1/admin/auth/login
  ▼
Nginx（生产，限流 10r/m）
  ▼
FastAPI 中间件（request_id、访问日志、审计、安全头）
  ▼
web/admin/routers/auth.py（参数校验）
  ▼
application/auth_service.py
  ├─ 按当前作用域查询管理员（repository）
  ├─ 账号不存在：执行一次固定 bcrypt 校验（防用户名枚举）
  ├─ 校验锁定状态 / 密码
  ├─ 成功：清零失败次数
  ├─ 生成 Access Token（JWT，30 分钟）
  ├─ 生成 Refresh Token（随机串，数据库只存 SHA-256 哈希）
  └─ 写审计日志（与业务同事务）
  ▼
返回 access_token / refresh_token / 用户信息
  ▼
前端：access 放内存，refresh 放 localStorage
```

### 12.4 一次资源查询/写入的旅程

```text
GET/POST /api/v1/admin/agents
  ▼
web/admin/router.py（统一管理员鉴权）
  ▼
web/deps/auth.py
  ├─ 解析 Bearer Token
  ├─ 校验签名、过期时间、token_version
  ├─ 校验令牌作用域与当前域名一致（跨作用域 401）
  ├─ 查询数据库中的账号、角色与功能权限编码
  ├─ 构建 AdminPrincipal + AccessScope（tenant_id、role_id、是否平台）
  └─ 接口再按 page:*/button:*/资源读写权限校验（不满足返回 403）
  ▼
web/admin/routers/agents.py（请求/响应模型）
  ▼
Scoped UnitOfWork：在同一 Session 上重建仓储并应用作用域
  ▼
application/agent_service.py（业务规则、默认值、归属校验、克隆与授权）
  ▼
infrastructure/repository/postgres_agent_repository.py
  ├─ tenant_id 过滤（平台只看产品级，租户看本租户 + 被授权产品级）
  ├─ resource_grants EXISTS 子查询按角色收窄，不产生行膨胀
  └─ 未授权详情统一返回 404
  ▼
UnitOfWork.commit()
  ├─ 业务数据（资源、授权、审计同一事务）
  └─ 审计日志
```

### 12.5 刷新令牌的轮换流程

```text
前端发现 Access Token 过期（401）
  ▼
调用 /admin/auth/refresh（沿用登录时的作用域头/子域名）
  ▼
后端校验 Refresh Token 哈希、会话状态与作用域
  ├─ 正常：旧令牌标记已轮换 → 签发新 refresh → 签发新 access
  ├─ 已轮换的旧令牌再次出现：判定为重放 → 撤销整族会话
  └─ 已撤销 / 过期 / 归属作用域不一致：返回 401，要求重新登录
  ▼
前端更新内存中的 access 和 localStorage 中的 refresh
  ▼
重放刚才失败的请求（仅一次）
```

多个标签页同时刷新时，前端使用 Web Locks 保证只有一个标签页真正发起刷新，其他标签页等待结果。

### 12.6 数据库迁移流程

```text
修改 ORM 模型
  ▼
alembic revision --autogenerate
  ▼
人工检查生成的迁移脚本（自动生成不一定完全正确）
  ▼
alembic upgrade head
  ▼
/health/ready 校验 alembic_version 与代码 head 一致
  ▼
应用发布
```

生产 Compose 中由一次性 `migrate` 服务执行迁移，`backend-admin` / `backend-user` 等它成功后才启动，避免“代码已经更新、表结构还没更新”的窗口。

---

## 13. 面试讲解指南

这一章不是功能文档，而是帮你把项目讲清楚。建议先自己运行一遍，再按下面的顺序准备。

### 13.1 30 秒介绍模板

> 这是一个 AI 智能体配置与运营平台。管理端用 React 做后台，可以创建智能体、配置模型和提示词、挂载技能与工具；后端用 FastAPI 提供登录鉴权和资源管理；数据存在 PostgreSQL。项目重点不在“调模型”，而在工程化：完整的认证会话、RBAC、审计、数据库迁移、可观测性、容器化部署和 CI 质量门禁。

### 13.2 2 分钟介绍模板

1. **背景和目标**：企业内部需要快速配置和发布 AI 助手，但配置项多、权限复杂，需要一个统一平台。
2. **系统组成**：管理端、用户端、后端 API、PostgreSQL，前后端分离，Nginx 反向代理。
3. **核心流程**：管理员登录 → 创建智能体 → 配置模型/提示词/技能/工具 → 启用发布。
4. **工程重点**：短 Access Token + 可撤销 Refresh Token、RBAC、审计日志、统一错误模型、迁移与就绪检查、结构化日志与指标、容器安全加固。
5. **个人贡献/亮点**：选 1–2 个你最熟的点展开，比如“刷新令牌的轮换与重放检测”或“审计与业务同事务”。

### 13.3 架构怎么讲

```text
┌──────────────────────────────┐
│  管理端（React + Nginx）      │
│  登录 / 智能体 / 资源 / 用户  │
└───────────────┬──────────────┘
                │ HTTPS + /api
┌───────────────▼──────────────┐
│  后端（FastAPI）              │
│  web → application → domain   │
│  infrastructure（ORM/仓储）   │
└───────────────┬──────────────┘
                │ SQL
┌───────────────▼──────────────┐
│  PostgreSQL（JSONB + 索引）   │
└──────────────────────────────┘
```

讲解时强调三点：

1. **前后端完全分离**：开发时 Vite 代理 `/api`，生产时 Nginx 反代，前端不直接连数据库。
2. **后端分层**：Web 层做协议转换，Application 层做业务编排，Domain 层放实体和仓储协议，Infrastructure 层实现数据库与安全。
3. **事务边界**：仓储只 `flush`，应用服务统一 `commit`，审计与业务同事务。

### 13.4 技术选型与理由

| 选择                                  | 理由                                                                       | 代价/替代方案                                                        |
|---------------------------------------|----------------------------------------------------------------------------|----------------------------------------------------------------------|
| FastAPI                               | 类型提示 + Pydantic 自动校验、自动生成 OpenAPI、开发效率高                 | 同步 ORM 需要线程池；纯高并发 IO 场景可换 async 或 Go                |
| PostgreSQL                            | JSONB 适合存智能体这类结构多变的配置；事务、索引、`pg_trgm` 模糊搜索都成熟 | 比 MySQL 运维门槛略高                                                |
| SQLAlchemy 2.0                        | 成熟、类型友好、迁移生态完善                                               | 同步模型在极高并发下需要调连接池                                     |
| DDD 分层                              | 业务规则与 HTTP/ORM 解耦，便于测试和演进                                   | 文件数量增加，小项目可能显得重                                       |
| 短 Access + 可撤销 Refresh            | 兼顾性能和可撤销性；Access 不落 localStorage，降低 XSS 风险                | Refresh 仍存 localStorage，需要 CSP、轮换和重放检测兜底              |
| Nginx 做前端与反代                    | 静态资源、SPA 回退、限流、安全头一次解决                                   | 多一层需要维护                                                       |
| 多租户：共享库 + `tenant_id` 行级隔离 | 一套代码、一套数据库，迁移和升级只做一次，运维成本低                       | 查询必须始终带作用域条件；强合规或超大租户可演进为独立 Schema/独立库 |
| Docker Compose                        | 小团队部署成本低，服务边界清晰                                             | 大规模编排可迁移到 Kubernetes                                        |

### 13.5 五个可讲的亮点

1. **会话安全**
   - Access Token 只存内存，Refresh Token 数据库只存 SHA-256 哈希。
   - 单次轮换 + 重放检测：旧 refresh 再次使用会撤销整族会话。
   - `token_version` 让登出、改密、禁用、删除立即失效。
   - 多标签页用 Web Locks 单飞刷新，避免并发刷新导致令牌互相失效。

2. **防爆力破解与用户名枚举**
   - 未知用户名也执行固定 bcrypt 校验，响应时间接近。
   - 连续失败锁定，Nginx 再叠加限流。
   - 统一错误模型，不泄露内部细节。

3. **事务与审计一致性**
   - 仓储不提交事务，应用服务统一提交。
   - 审计日志与业务写入同事务，避免“业务成功但审计丢失”。
   - 认证失败使用独立短事务记录，避免影响主流程。

4. **数据库工程化**
   - Alembic 版本化迁移，CI 中执行 `alembic check` 防止模型和迁移漂移。
   - 迁移前加 advisory lock，避免多个实例并发迁移。
   - 就绪检查同时验证数据库连通性和迁移版本，部署时能快速发现“代码新、库旧”。

5. **可观测性与交付**
   - 每个请求有 `request_id`，并支持 W3C `traceparent` 传播。
   - 结构化日志、OpenTelemetry 链路、Prometheus 指标。
   - 容器非 root、只读根文件系统、`cap_drop: ALL`，CI 中用 Trivy 扫描镜像漏洞。

6. **多租户作用域隔离**
   - 同一套代码按二级域名区分产品级与租户级，不需要为每个租户部署一套服务。
   - 作用域在请求入口解析一次，贯穿认证、RBAC、仓储三层校验，令牌跨作用域直接拒绝。
   - 产品级智能体必须授权给租户、资源可再按角色收窄；租户之间的数据、账号、审计完全隔离，同名资源按作用域唯一。
   - 仅本地回环主机保留请求头切换作为调试逃生口；开发/测试/线上只认域名，配置错误启动即失败。

### 13.6 难点与取舍

| 难点                     | 做法                                    | 取舍                                       |
|--------------------------|-----------------------------------------|--------------------------------------------|
| 令牌既要安全又要无感刷新 | 短 Access + 轮换 Refresh + 请求排队重放 | 实现复杂，前端需要处理并发刷新             |
| 事务边界清晰             | UnitOfWork + 仓储只 flush               | 代码层级增多                               |
| 迁移安全                 | advisory lock + 就绪检查 + CI 漂移检查  | 上线流程要求先迁移后启动                   |
| 权限实时生效             | 每次请求查数据库校验角色/状态           | 每个请求多一次查询，用索引和连接池控制成本 |
| 前后端分离部署           | Nginx 同源反代 `/api`                   | 需要维护 Nginx 配置和 SPA 回退             |

### 13.7 高频面试问答

**Q1：为什么用 FastAPI，不用 Django/Spring？**

FastAPI 类型提示友好、Pydantic 校验和 OpenAPI 文档开箱即用，适合以 API 为主的项目；团队是 Python 技术栈。Django 更适合全家桶式业务，Spring 更重但生态成熟。选型主要看团队和交付速度。

**Q2：为什么做 DDD 分层，会不会过度设计？**

这个项目除了 CRUD，还有登录会话、RBAC、审计、资源关联等规则，放一起会很快失控。分层让业务规则可测试、可替换；代价是文件多。如果只是纯 CRUD 小工具，确实可以更简单。

**Q3：Access Token 和 Refresh Token 怎么设计？**

Access 用 JWT（HS256），默认 30 分钟，前端只存内存；Refresh 是随机串，数据库只存 SHA-256 哈希，默认 14 天。刷新时轮换，旧令牌立即失效；检测到旧令牌重放就撤销整条会话链。

**Q4：为什么 Refresh Token 存数据库？**

为了可撤销。JWT 本身无状态，签发后无法主动失效；把 refresh 存库并维护会话状态，才能在登出、改密、禁用时立即让会话失效。

**Q5：怎么防止 Refresh Token 被盗用？**

轮换 + 重放检测 + 短有效期 + 前端 CSP + 登录/改密时撤销全部会话。检测到已轮换令牌再次出现时，认为可能被盗，撤销整族并要求重新登录。

**Q6：怎么防暴力破解和用户名枚举？**

未知用户名也做一次固定 bcrypt 校验，避免响应时间差；连续失败锁定 15 分钟；Nginx 对登录接口限流；错误文案统一，不区分“用户不存在”和“密码错误”。

**Q7：RBAC 怎么实现？**

角色存数据库，每次请求解析令牌后查实时账号和角色；路由层统一挂管理员鉴权，写接口再校验 `admin`/`superadmin`，管理员账号、租户、角色、授权和审计只允许 `superadmin`。不信任令牌里的角色快照，避免改角色后旧令牌继续生效。

**Q8：审计日志怎么保证不丢？**

业务审计和业务写入在同一个数据库事务里提交；登录失败这类没有业务事务的场景，用独立短事务写入，避免影响主流程。

**Q9：数据库迁移怎么保证安全？**

用 Alembic 版本化；迁移脚本进入代码评审；CI 跑 `alembic check` 检查模型漂移；迁移时加 advisory lock 防止并发；就绪检查校验迁移版本；生产由一次性 `migrate` 服务先执行，后端等成功后再启动。

**Q10：可观测性怎么做的？**

请求 ID 贯穿 Nginx、后端和审计；结构化日志带 `trace_id`/`span_id`；OpenTelemetry 上报链路；Prometheus 暴露 HTTP 和业务指标；健康和就绪检查用于容器编排。

**Q11：前端无感刷新怎么实现？**

Access 过期返回 401 时，前端用 Web Locks 保证同一时刻只有一个刷新请求，其他请求排队；刷新成功后重放一次原请求；刷新失败清理会话并跳转登录。

**Q12：生产环境做了哪些安全加固？**

配置启动校验、无默认账号、CORS 白名单、登录限流、安全响应头、Swagger 生产关闭；容器非 root、只读根文件系统、`cap_drop: ALL`、数据库不对外发布；CI 做镜像漏洞扫描；备份和恢复有脚本和演练流程。

**Q13：性能瓶颈可能在哪，怎么扩展？**

后端是无状态的，可以水平扩 worker 或实例；瓶颈通常在 PostgreSQL。可以通过连接池、索引（`pg_trgm`、唯一索引）、分页和避免 N+1 查询优化；再往上可以加只读副本、缓存热点配置，或把长任务拆到消息队列。

**Q14：为什么测试用真实 PostgreSQL，不用 mock？**

迁移、JSONB、唯一索引、触发器这些行为 mock 不出来；用真实数据库能验证迁移和 SQL 是否正确。代价是测试环境依赖数据库，CI 用 service 容器解决。

**Q15：如果继续演进，你会做什么？**

用户端接入真实用户体系和多租户隔离；RBAC 细化到资源级；热点配置加缓存；长任务异步化；完善指标看板和告警；按需引入消息队列做事件通知。注意区分“已实现”和“规划中”，面试时不要夸大。

### 13.8 面试时打开哪些文件

| 想讲的内容                 | 打开                                                                                                                               |
|----------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| 应用装配、中间件顺序       | `backend/web/app.py`                                                                                                               |
| 登录、刷新、撤销           | `backend/internal/application/auth_service.py`、`backend/internal/infrastructure/security/tokens.py`                               |
| 鉴权与 RBAC                | `backend/web/deps/auth.py`、`backend/web/admin/router.py`                                                                          |
| 多租户作用域解析与租户管理 | `backend/web/deps/tenant.py`、`backend/internal/application/tenant_service.py`、`backend/migrations/versions/0004_multi_tenant.py` |
| 事务与仓储                 | `backend/internal/infrastructure/model/uow.py`、`backend/internal/infrastructure/repository/`                                      |
| 迁移与就绪检查             | `backend/migrations/env.py`、`backend/web/health.py`                                                                               |
| 前端无感刷新               | `frontend/admin/src/api/client.ts`、`frontend/admin/src/auth/AuthContext.tsx`                                                      |
| 生产反代与限流             | `frontend/admin/nginx/default.conf`、`frontend/user/nginx/default.conf`                                                            |
| 生产编排与容器安全         | `ops/docker-compose.yml`、`backend/Dockerfile`                                                                                     |

### 13.9 面试演示建议

1. 提前启动好数据库、后端和管理端，避免现场等依赖安装。
2. 演示路径：登录 → 首次改密 → 创建技能 → 创建智能体并关联技能 → 查看审计日志（superadmin）。
3. 准备一个 viewer 账号，演示写接口返回 403。
4. 打开 `/docs` 展示 OpenAPI，再打开日志展示 `request_id`。
5. 如果允许看代码，按 13.8 的顺序讲 2–3 个点即可，不要试图讲完所有文件。

---

## 14. 生产环境落地部署

> 本节命令用于 **Linux 生产服务器**。本地开发不需要看这一节。执行前请先在服务器安装 Docker Engine 与 Docker Compose v2，并克隆代码。

### 14.1 推荐部署架构

```text
用户浏览器
   │ HTTPS 443
   ▼
TLS 终止层（云负载均衡 / 宿主机 Nginx / Caddy）
   │ HTTP 127.0.0.1:8080（HTTP_PORT）
   │ HTTP 127.0.0.1:8081（USER_HTTP_PORT）
   ▼
frontend-admin / frontend-user 容器（Nginx，静态文件 + /api 反代）
   │ 内部网络
   ▼
backend-admin / backend-user 容器（FastAPI）
   │              │
   │              ├──► db 容器（PostgreSQL 17 + pgvector，不对外）
   │              │
   │              └──► Redis（DB 0 短期记忆 / DB 1 Celery broker / DB 2 Celery result）
   ▲                          ▲
   └──────── celery-worker 容器（消费 RAG ingest 队列，独立进程）
```

- 只暴露 443（以及 80 用于跳转 HTTPS）。
- 入口使用泛域名 `*.example.com`：`adminsystem.example.com` 为产品级平台，其余子域为租户。
- `backend-admin`、`backend-user`、`db`、`redis`、`celery-worker` 不发布端口，只走 Compose 内部网络。
- 两个站点镜像与容器独立：`backend-admin` 只挂 admin 路由，`backend-user` 只挂 user 路由。
- `celery-worker` 与 backend 镜像同包，仅启动命令不同；不使用知识库时可以不启动。
- `/metrics` 由前端 Nginx 直接拒绝外部访问；如需采集，从内部网络访问。

### 14.2 服务器准备

| 项目       | 建议                                                |
|------------|-----------------------------------------------------|
| 操作系统   | Ubuntu 22.04 / 24.04 LTS 或同类 Linux               |
| CPU / 内存 | 最低 2 核 4 GB；建议 4 核 8 GB                      |
| 磁盘       | 40 GB 以上，数据库单独规划增长                      |
| 软件       | Docker Engine 24+、Docker Compose v2、Git           |
| 网络       | 安全组/防火墙只开放 22、80、443；22 建议限制来源 IP |
| 域名       | 准备一个域名并解析到服务器公网 IP                   |
| 时间同步   | 开启 NTP，避免令牌和日志时间异常                    |

### 14.3 准备环境变量与密钥

`ops/` 下没有模板文件，直接新建生产配置：

```bash
cat > ops/.env.prod <<'EOF'
# ===== 必填 =====
# 数据库：POSTGRES_* 用于初始化容器，DATABASE_URL 中的账号密码库名必须与之一致
POSTGRES_DB=boxia
POSTGRES_USER=boxia
POSTGRES_PASSWORD=CHANGE_ME_STRONG_DB_PASSWORD
DATABASE_URL=postgresql+psycopg://boxia:CHANGE_ME_STRONG_DB_PASSWORD@db:5432/boxia

# JWT 签名密钥：执行 openssl rand -hex 32 生成，至少 32 字符
JWT_SECRET=CHANGE_ME_64_HEX_CHARACTERS

# 租户根域名：未配置或不是完整域名会拒绝启动
ROOT_DOMAIN=example.com

# ===== 按部署形态确认 =====
APP_ENV=prod
# 产品级平台子域名前缀，最终为 adminsystem.example.com
PLATFORM_ADMIN_SUBDOMAIN=adminsystem
PLATFORM_NAME=AI智能体运营管理平台
# 部署环境只按域名识别租户；生产开启该项会拒绝启动
ALLOW_TENANT_HEADER=false
DOCS_ENABLED=false
CORS_ORIGINS=
# 可选：访问根域名时默认进入的租户编码，留空则根域名返回 404
# DEFAULT_TENANT_CODE=acme

# ===== Compose 插值 =====
# 对外端口（前面有 TLS 终止层时可改为 127.0.0.1:8080 / :8081）
HTTP_PORT=80
USER_HTTP_PORT=8081
WEB_CONCURRENCY=2

# ===== Redis（短期记忆 + Celery broker/result）=====
# 三个 DB 互相隔离：DB 0 短期记忆、DB 1 Celery broker、DB 2 Celery result
# 生产建议用独立 Redis 实例或云托管 Redis，不要与 db 容器同机
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
MEMORY_MAX_TURNS=20
MEMORY_TTL_SECONDS=1800

# ===== LLM / Embedding（RAG 知识库使用，不使用知识库可留空）=====
# LLM：用于对话生成 + query 改写（OpenAI 兼容协议）
LLM_API_KEY=CHANGE_ME_LLM_API_KEY
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL_ID=deepseek-v4-flash
LLM_TIMEOUT_SECONDS=60
# Embedding / Rerank：SiliconFlow 托管 bge 模型（OpenAI 兼容 /v1/embeddings 与 /v1/rerank）
EMBEDDING_API_KEY=CHANGE_ME_SILICONFLOW_API_KEY
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DIMENSIONS=1024
EMBEDDING_TIMEOUT_SECONDS=30
# RAG 行为开关（一般保持默认；无 rerank 客户端时自动降级为向量余弦过滤）
RAG_RERANK_ENABLED=true
RAG_QUERY_REWRITE_ENABLED=true

# ===== 可选 =====
LOG_LEVEL=INFO
LOG_JSON=true
EOF
chmod 600 ops/.env.prod
```

生成随机值：

```bash
openssl rand -hex 32
```

开发/测试环境同样在 `ops/` 下新建 `.env.dev`、`.env.test`，把 `APP_ENV` 改为 `dev` / `test`，根域名换成独立泛域名（如 `dev.example.com` / `test.example.com`），`HTTP_PORT` / `USER_HTTP_PORT` 建议 `8081` / `8082`。每个环境使用独立的泛域名与泛域名证书，例如开发 `*.dev.example.com`、测试 `*.test.example.com`、线上 `*.example.com`。

启动时通过 `ENV_FILE` 指定容器读取的文件（默认 `.env.prod`），并把同一份文件交给 `--env-file` 供 Compose 插值：

```bash
cd ops
ENV_FILE=.env.dev docker compose --env-file .env.dev up -d
```

注意事项：

- `POSTGRES_PASSWORD` 和 `DATABASE_URL` 里的密码必须一致。
- `CORS_ORIGINS` 同源部署留空；前后端分离时填管理端域名，禁止 `*`。
- `ops/.env.*` 含密钥，权限设为 600，不要提交 Git，也不要贴到聊天工具。

### 14.4 构建并启动

```bash
# 在仓库根目录执行；--env-file 让 HTTP_PORT、WEB_CONCURRENCY 等插值变量生效
docker compose -f ops/docker-compose.yml --env-file ops/.env.prod up -d --build
docker compose -f ops/docker-compose.yml --env-file ops/.env.prod ps
```

也可以只启动一个站点。Compose 会按 `depends_on` 自动带上 `db` 和 `migrate`，但不会启动另一个站点：

```bash
# 只启动管理端（backend-admin + frontend-admin）
docker compose -f ops/docker-compose.yml --env-file ops/.env.prod up -d --build \
  backend-admin frontend-admin

# 只启动用户端（backend-user + frontend-user）
docker compose -f ops/docker-compose.yml --env-file ops/.env.prod up -d --build \
  backend-user frontend-user

# 只停止管理端 / 用户端（保留容器，下次 up -d 可快速恢复）
docker compose -f ops/docker-compose.yml stop backend-admin frontend-admin
docker compose -f ops/docker-compose.yml stop backend-user frontend-user
```

> 两个站点共享同一个 `db`；单独启动任一站点时都会先等一次性迁移服务成功（Alembic 幂等，已是最新版本时不会产生变更）。

开发/测试环境复用同一份 compose 文件，通过 `ENV_FILE` 指定对应的配置文件（相对 `ops/` 目录，默认 `.env.prod`）：

```bash
cd ops
ENV_FILE=.env.dev docker compose --env-file .env.dev up -d --build
ENV_FILE=.env.test docker compose --env-file .env.test up -d --build
```

> `ENV_FILE` 只决定 `db` / `migrate` / `backend-admin` / `backend-user` 容器读取哪个 env_file。`HTTP_PORT`、`USER_HTTP_PORT`（端口映射）、`WEB_CONCURRENCY`（compose 的 `environment`）和镜像变量属于 Compose 自身的插值，只写进 env_file 不会生效，必须像上面这样用 `--env-file` 提供；也可以把这些变量导出到当前 shell。

服务说明：

| 服务            | 作用                                          | 对外                            |
|-----------------|-----------------------------------------------|---------------------------------|
| `db`            | PostgreSQL 17（含 pgvector HNSW 索引），数据存 volume | 否                              |
| `migrate`       | 一次性执行 `alembic upgrade head`，成功后退出 | 否                              |
| `redis`         | Redis 7，DB 0 短期记忆 / DB 1 Celery broker / DB 2 Celery result | 否                              |
| `backend-admin` | 管理端 FastAPI，仅 admin 路由                 | 否                              |
| `backend-user`  | 用户端 FastAPI，仅 user 路由                  | 否                              |
| `celery-worker` | RAG ingest 异步 worker，消费队列 `rag`（与 backend 同镜像，仅启动命令不同） | 否                              |
| `frontend-admin` | 管理端 Nginx 静态站点 + `/api` 反代           | 是（`HTTP_PORT:8080`）          |
| `frontend-user` | 用户端 Nginx 静态站点 + `/api` 反代           | 是（`USER_HTTP_PORT:8080`）     |

除一次性执行的 `migrate` 外，其他服务都配置了健康检查；所有服务都有日志轮转和内存上限。

> **不使用知识库时**：可以不启动 `celery-worker`，并把 `RAG_RERANK_ENABLED` / `RAG_QUERY_REWRITE_ENABLED` 置为 `false`。`redis` 服务仍需保留（短期记忆依赖它）。
> **celery-worker 启动命令**：与 backend 同镜像，启动命令为 `celery -A internal.infrastructure.celery_app worker --loglevel=info -Q rag`；如需在 compose 外单独跑，宿主机先 `pip install celery[redis]` 后用同一份 `.env.prod` 启动即可。

> CI 会把镜像发布到 GHCR（`ghcr.io/<owner>/<repo>-backend-admin`、`-backend-user`、`-frontend-admin`、`-frontend-user`，支持 main 分支、`v*` tag 和 `sha-*`）。服务器资源紧张时，可以改用 CI 构建好的镜像：把对应服务的 `build` 配置替换为 `image: ghcr.io/...`。仓库默认仍采用本地构建，便于直接改代码上线。

### 14.4.1 RAG 部署依赖

知识库功能依赖三类外部资源，按启用情况准备：

| 依赖 | 用途 | 不启用时 |
|------|------|----------|
| **PostgreSQL pgvector 扩展** | `document_chunks.embedding` 1024 维向量列 + HNSW cosine 索引 | 不装扩展则迁移 `0022_rag_documents` 失败；自建库时先 `CREATE EXTENSION IF NOT EXISTS vector;` |
| **Redis** | 短期记忆（DB 0）+ Celery broker（DB 1）+ result backend（DB 2） | 短期记忆不可用；celery-worker 起不来则 ingest 任务堆积在 `queued` |
| **OpenAI 兼容 LLM / Embedding / Rerank API** | 对话生成、query 改写、bge embedding、bge-reranker 精排 | 任一字段留空时对应功能自动降级；三个都没配则 RAG 不可用 |

生产建议：

- PostgreSQL 用 `pgvector/pgvector:pg17` 镜像（已内置扩展）；自建外部库时 DBA 需预装 `vector` 扩展。
- Redis 用 `redis:7-alpine`，3 个 DB 通过逻辑隔离即可，无需起 3 个实例；AOF 开启，maxmemory 设 256mb + `allkeys-lru`。
- LLM / Embedding / Rerank 推荐走云托管（SiliconFlow / DeepSeek / 内部 LLM 代理）；API Key 写入 `ops/.env.prod`，权限 600，不进 Git。
- Celery worker 内存上限建议 512m（embedding 单次批处理 ≤ 20 条时够用）；如批量文档 ingest 频繁，可单独 scale 多个 worker。

**复用已有 PostgreSQL / Redis**

如果生产环境已经有现成的 PostgreSQL（含 pgvector）或 Redis（如云托管 RDS / ElastiCache / 公司内部实例），不需要起 compose 自带的 `db` / `redis` 容器：

1. 在 `ops/.env.prod` 中把 `DATABASE_URL` / `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` 指向外部地址（参考本地开发 3.1 节的连接串写法）。
2. 在 `ops/docker-compose.yml` 中**注释掉 `db` 和 `redis` 两个服务**，并把 `backend-admin` / `backend-user` / `migrate` / `celery-worker` 的 `depends_on` 中对应行删掉（否则 compose 会等一个不会启动的容器健康）。
3. 外部 PostgreSQL 必须先 `CREATE EXTENSION IF NOT EXISTS vector;`；外部 Redis 需要开放 DB 0/1/2 三个逻辑库（或找运维开多 DB）。
4. `migrate` 一次性任务仍由 compose 触发，它会直接连外部库执行 Alembic 升级，不需要改代码。

### 14.5 创建首个管理员

交互方式（推荐）：

```bash
docker compose -f ops/docker-compose.yml run --rm -it \
  backend-admin python -m scripts.create_admin
```

> Windows Git Bash 如果提示 `the input device is not a TTY`，改用下面的非交互方式。

非交互方式：

```bash
docker compose -f ops/docker-compose.yml run --rm \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD='<符合密码策略的强密码>' \
  backend-admin python -m scripts.create_admin
```

首次登录会强制改密。默认创建的是产品级平台账号，租户管理员请登录平台后在「租户管理」中创建。自动化/演示环境可额外传 `-e ADMIN_MUST_CHANGE_PASSWORD=false`。

> 非交互方式会把密码留在 shell 历史和进程列表中，生产环境优先用交互方式；如果必须非交互，执行后清理历史记录。

### 14.6 配置 HTTPS

推荐用云负载均衡或宿主机 Nginx/Caddy 终止 TLS，再按域名转发：`adminsystem.<根域名>` 到 `frontend-admin`，根域名与租户子域名到 `frontend-user`。

多租户使用泛域名，证书必须同时覆盖根域和所有子域（如 `example.com` + `*.example.com`）。Let's Encrypt 的泛域名证书只能通过 DNS-01 验证申请。

宿主机 Nginx 示例：

```nginx
# HTTP → HTTPS
server {
    listen 80;
    server_name example.com *.example.com;
    return 301 https://$host$request_uri;
}

# 管理端：仅平台子域名
server {
    listen 443 ssl http2;
    server_name adminsystem.example.com;

    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;  # HTTP_PORT
        # 必须透传原始域名：后端据此判断产品级 / 租户作用域
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}

# 用户端：根域名与租户子域名
server {
    listen 443 ssl http2;
    server_name example.com *.example.com;

    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8081;  # USER_HTTP_PORT
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

`adminsystem.example.com` 是精确匹配，优先级高于 `*.example.com`，顺序不影响结果。

对应地把 `.env.prod` 的 `HTTP_PORT` / `USER_HTTP_PORT` 分别改为 `127.0.0.1:8080` / `127.0.0.1:8081`，让两个前端容器端口只绑定本机。

如果外层还有云负载均衡或网关，同样要求它**保留原始 Host 头**；把域名改写成固定后端地址会导致所有请求落到平台作用域。

### 14.7 Docker Hub 访问受限时

镜像拉取失败时，可以通过构建参数替换基础镜像（示例为 daocloud，按实际可用源调整）：

```bash
PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim \
NODE_IMAGE=docker.m.daocloud.io/library/node:24-alpine \
NGINX_IMAGE=docker.m.daocloud.io/nginxinc/nginx-unprivileged:1.27-alpine \
docker compose -f ops/docker-compose.yml build
```

也可以给 Docker 配置 `registry-mirrors` 后重新拉取。

### 14.8 上线验证

按顺序检查：

```bash
# 1. 容器状态：都应 healthy 或正常退出（migrate 为 exited 0）
docker compose -f ops/docker-compose.yml ps

# 2. 前端 Nginx 存活：管理端 HTTP_PORT（示例 8080）、用户端 USER_HTTP_PORT（示例 8081）
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8081/healthz

# 3. 两个后端都就绪（数据库连通 + 迁移版本一致）
docker compose -f ops/docker-compose.yml exec backend-admin \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
docker compose -f ops/docker-compose.yml exec backend-user \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"

# 4. 查看迁移服务日志
docker compose -f ops/docker-compose.yml logs migrate
```

然后在浏览器中：

- [ ] 通过 HTTPS 打开 `https://adminsystem.<根域名>`，使用首个管理员登录并完成改密
- [ ] 在「租户管理」创建一个租户，确认租户子域名可正常打开
- [ ] 用该租户管理员登录租户子域名，确认看不到「租户管理」入口
- [ ] 在平台侧创建一个产品级智能体，确认未授权时租户列表不可见；授权给租户角色后可见但只读
- [ ] 在租户内创建一条技能并归属本租户智能体，确认另一个租户看不到
- [ ] 在租户内创建自定义角色与最终用户，绑定角色后用用户端登录，确认只看到已授权且启用的智能体
- [ ] 用 viewer 账号验证写接口返回 403
- [ ] 用 superadmin 查看审计日志，确认租户审计只在租户内可见，授权变更留有 `grant.updated` 记录
- [ ] 确认 `/docs` 在生产不可访问（`DOCS_ENABLED=false`）
- [ ] 确认 `/metrics` 从外部不可访问
- [ ] 打开用户端站点（`USER_HTTP_PORT`，示例 8081），用最终用户账号登录，确认智能体列表与详情可用；未登录调用 `/api/v1/user/me` 返回 401
- [ ] 路由隔离：管理端站点访问 `/api/v1/user/me` 返回 404；用户端站点访问 `/api/v1/admin/*`、`/api/v1/public/*` 返回 404

### 14.9 升级与回滚

**升级流程：**

1. 先备份数据库（见 14.10）。
2. 拉取新代码。
3. 重新构建并启动：`docker compose -f ops/docker-compose.yml --env-file ops/.env.prod up -d --build`。
4. `migrate` 服务自动执行迁移，`backend-admin` / `backend-user` 等它成功后才启动。
5. 按 14.8 验证。

**回滚流程：**

1. 镜像按 tag 发布时，切回上一个 tag 重新 `up -d`。
2. 如果新版本包含数据库迁移，回滚前确认迁移是否可逆；可逆时使用 `alembic downgrade <revision>`，不可逆时用备份恢复。
3. 恢复后重新检查 `/health/ready` 和业务日志。

> 建议数据库变更遵循“先加字段、再写数据、最后删旧字段”的渐进式策略，降低回滚难度。

### 14.10 备份、恢复与演练

```bash
# 备份（custom 格式，默认保留 14 天）
bash ops/backup.sh

# 恢复（需要输入 RESTORE 二次确认，会覆盖现有数据）
bash ops/restore.sh ops/backups/boxia-YYYYMMDD-HHMMSS.dump
```

建议：

1. 把备份加入 cron，例如每天凌晨 3 点：
   ```cron
   0 3 * * * cd /opt/boxia-agent && bash ops/backup.sh >> /var/log/boxia-backup.log 2>&1
   ```
2. 备份目录同步到独立存储（对象存储或另一台机器），避免和数据库同盘。
3. **定期做恢复演练**：在测试环境用最新备份恢复一次，确认能启动并通过 `/health/ready`。没有演练过的备份不算可靠备份。

### 14.11 监控与日志

- **健康检查**：Compose 已配置容器健康检查；外部监控建议分别探测管理端域名与用户端域名下的 `/healthz`、`/health/ready`。
- **日志**：生产默认 JSON 日志，包含 `request_id`、`trace_id`、路径、状态码、耗时。查看实时日志：
  ```bash
  docker compose -f ops/docker-compose.yml logs -f backend-admin backend-user
  ```
- **指标**：`/metrics` 为 Prometheus 格式，默认只允许内部访问。需要采集时，在内部网络部署 Prometheus 或通过 sidecar 抓取。
- **告警建议**：容器重启次数、`/health/ready` 失败、5xx 比例、登录 429 数量、数据库连接数、磁盘使用率、备份失败。

### 14.12 安全加固清单

- [ ] 防火墙只开放 22、80、443；数据库和后端端口不对外
- [ ] SSH 只允许密钥登录，禁用 root 远程登录
- [ ] `ops/.env.*` 权限 600，密钥随机且未出现在 Git 历史中
- [ ] `APP_ENV=prod`、`DOCS_ENABLED=false`
- [ ] HTTPS 使用 TLS 1.2/1.3，证书自动续期
- [ ] 容器非 root、只读根文件系统、`cap_drop: ALL`、`no-new-privileges`
- [ ] `/metrics` 和 `/health/*` 不对外暴露
- [ ] 定期轮换 JWT 密钥和数据库密码（轮换前评估会话失效影响）
- [ ] 依赖和镜像定期扫描（CI 已有 Trivy，生产镜像也建议定期扫描）
- [ ] 备份加密并异地保存，恢复演练通过

### 14.13 生产常见问题

| 现象                                                  | 排查方向                                                                                                                                     |
|-------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| 访问域名 502                                          | 对应 `frontend-admin` / `frontend-user` 容器是否健康；对应 `backend-admin` / `backend-user` 是否启动；Nginx 日志                              |
| `/health/ready` 返回 503 `migration_outdated`         | 查看 `migrate` 服务日志，确认迁移是否成功                                                                                                    |
| 登录返回 429                                          | 触发登录限流或账号锁定；查看 `Retry-After`                                                                                                   |
| 容器启动后立即退出                                    | `docker compose logs <服务名>`，常见原因是环境变量缺失或数据库连不上                                                                         |
| 只读文件系统报错                                      | 应用需要写入临时目录时，确认 Compose 已挂载 `tmpfs`                                                                                          |
| 磁盘占满                                              | 检查数据库 volume、备份目录和容器日志轮转                                                                                                    |
| 时间不对导致令牌异常                                  | 检查服务器 NTP 时间同步                                                                                                                      |
| 租户子域名返回 404 / 403                              | 404 多为 `ROOT_DOMAIN` 配置不符、租户不存在，或根域名未配 `DEFAULT_TENANT_CODE`；403 多为租户已停用                                          |
| 未知域名也返回 404                                    | 这是预期行为：部署环境只认 `adminsystem.<ROOT_DOMAIN>` 与 `<租户编码>.<ROOT_DOMAIN>`，不会回退产品级平台；检查 DNS、`ROOT_DOMAIN` 与租户编码 |
| 启动失败：`必须配置 ROOT_DOMAIN`                      | 除 `local` 外，`dev` / `test` / `prod` 都必须配置完整域名                                                                      |
| 启动失败：`仅 local 环境允许开启 ALLOW_TENANT_HEADER` | 部署环境删除该配置或设为 `false`；请求头切换只用于本地回环主机                                                                               |
| 所有子域名都进入平台作用域                            | 反向代理或网关没有透传原始 `Host` 头；或 `ROOT_DOMAIN` 配成了不包含该子域的根域名                                                            |
| 本地 `acme.localhost` 打不开                          | 确认后端以 `APP_ENV=local` 启动；Vite 需允许 `*.localhost` 并透传原始 `Host`（仓库配置已处理）                                               |
| 登录提示账号不属于该租户                              | 账号只能登录其所属作用域：产品级账号走 `adminsystem`，租户账号走本租户子域名                                                                 |

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

见 [14.9](#149-升级与回滚)。

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

本项目采用 [Apache License 2.0](LICENSE)。
