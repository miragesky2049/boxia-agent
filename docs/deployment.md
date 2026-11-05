> 返回 [项目手册](../README.md)

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
   ├─── celery-worker 容器（消费 RAG ingest 与权益周期任务队列，独立进程）
   └─── celery-beat 容器（定时投递权益周期任务，必须单副本）
```

- 只暴露 443（以及 80 用于跳转 HTTPS）。
- 入口使用泛域名 `*.example.com`：`platform.example.com` 为产品级平台，其余子域为租户。
- `backend-admin`、`backend-user`、`db`、`redis`、`celery-worker`、`celery-beat` 不发布端口，只走 Compose 内部网络。
- 两个站点镜像与容器独立：`backend-admin` 只挂 admin 路由，`backend-user` 只挂 user 路由。
- `celery-worker` 与 backend 镜像同包，仅启动命令不同；它同时消费知识库 ingest 与权益周期任务（生效 / 到期流转、宽限期回收、对账），生产环境应保持运行。
- `celery-beat` 同样与 backend 镜像同包，只按周期投递任务、不执行任务；**必须保持单副本**，多实例会导致定时任务重复投递。
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
# 产品级平台子域名前缀，最终为 platform.example.com
PLATFORM_ADMIN_SUBDOMAIN=platform
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
# 向量库：memory 仅用于开发（重启丢数据）；生产必须用 pgvector 或 milvus
VECTOR_STORE_PROVIDER=pgvector
# 可选：Milvus（VECTOR_STORE_PROVIDER=milvus 时填写）
# MILVUS_URI=http://milvus:19530
# MILVUS_TOKEN=

# ===== 可选：大图对象存储（MinIO / S3 兼容）=====
# 单个 graph JSON 超过阈值时写入对象存储，留空则内联写库
# OBJECT_STORAGE_ENDPOINT=minio:9000
# OBJECT_STORAGE_ACCESS_KEY=
# OBJECT_STORAGE_SECRET_KEY=
# OBJECT_STORAGE_BUCKET=boxia-graphs
# OBJECT_STORAGE_SECURE=false

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

> `ENV_FILE` 决定 `db` / `migrate` / `backend-admin` / `backend-user` / `celery-worker` / `celery-beat` 容器读取哪个 env_file。`HTTP_PORT`、`USER_HTTP_PORT`（端口映射）、`WEB_CONCURRENCY`（compose 的 `environment`）和镜像变量属于 Compose 自身的插值，只写进 env_file 不会生效，必须像上面这样用 `--env-file` 提供；也可以把这些变量导出到当前 shell。

服务说明：

| 服务            | 作用                                          | 对外                            |
|-----------------|-----------------------------------------------|---------------------------------|
| `db`            | PostgreSQL 17（含 pgvector HNSW 索引），数据存 volume | 否                              |
| `migrate`       | 一次性执行 `alembic upgrade head`，成功后退出 | 否                              |
| `redis`         | Redis 7，DB 0 短期记忆 / DB 1 Celery broker / DB 2 Celery result | 否                              |
| `backend-admin` | 管理端 FastAPI，仅 admin 路由                 | 否                              |
| `backend-user`  | 用户端 FastAPI，仅 user 路由                  | 否                              |
| `celery-worker` | RAG ingest 与权益周期任务 worker，消费队列 `rag`（与 backend 同镜像，仅启动命令不同） | 否                              |
| `celery-beat` | 定时任务调度器，按周期投递权益生效 / 到期流转、到期提醒、宽限期回收、每日对账（与 backend 同镜像，仅启动命令不同；**强制单副本**） | 否                              |
| `frontend-admin` | 管理端 Nginx 静态站点 + `/api` 反代           | 是（`HTTP_PORT:8080`）          |
| `frontend-user` | 用户端 Nginx 静态站点 + `/api` 反代           | 是（`USER_HTTP_PORT:8080`）     |

`db`、`redis`、`backend-admin`、`backend-user` 与两个前端服务配置了健康检查；`migrate` 为一次性任务，`celery-worker` / `celery-beat` 为后台进程，不提供 HTTP 探活，依靠 `restart: unless-stopped` 兜底；所有服务都有日志轮转和内存上限。

> **不使用知识库时**：可把 `RAG_RERANK_ENABLED` / `RAG_QUERY_REWRITE_ENABLED` 置为 `false`，但 `celery-worker` 与 `celery-beat` 仍建议保持运行——权益的未来生效、到期流转、宽限期回收与每日对账都由 beat 投递、worker 执行；停掉后这些状态只能等下次进程恢复时补扫。`redis` 服务始终需要保留（短期记忆依赖它）。
> **celery-worker 启动命令**：与 backend 同镜像，启动命令为 `celery -A internal.infrastructure.celery_app worker --loglevel=info -Q rag`；如需在 compose 外单独跑，宿主机先 `pip install celery[redis]` 后用同一份 `.env.prod` 启动即可。
> **celery-beat 启动命令**：与 backend 同镜像，启动命令为 `celery -A internal.infrastructure.celery_app beat --loglevel=info --schedule=/tmp/celerybeat-schedule`（compose 服务已内置该命令）。beat 只负责投递、不执行任务，必须与 worker 同时存在；全局只能运行一个实例，切勿 `docker compose up --scale celery-beat=2`，否则定时任务会被重复投递。

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
- 生产把 `VECTOR_STORE_PROVIDER` 设为 `pgvector`（复用业务库）或 `milvus`；`memory` 只用于开发，重启后向量数据会丢失。
- Redis 用 `redis:7-alpine`，3 个 DB 通过逻辑隔离即可，无需起 3 个实例；AOF 开启，maxmemory 设 256mb + `allkeys-lru`。
- LLM / Embedding / Rerank 推荐走云托管（SiliconFlow / DeepSeek / 内部 LLM 代理）；API Key 写入 `ops/.env.prod`，权限 600，不进 Git。
- Celery worker 内存上限建议 512m（embedding 单次批处理 ≤ 20 条时够用）；如批量文档 ingest 频繁，可单独 scale 多个 worker。

**复用已有 PostgreSQL / Redis**

如果生产环境已经有现成的 PostgreSQL（含 pgvector）或 Redis（如云托管 RDS / ElastiCache / 公司内部实例），不需要起 compose 自带的 `db` / `redis` 容器：

1. 在 `ops/.env.prod` 中把 `DATABASE_URL` / `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` 指向外部地址（参考本地开发 3.1 节的连接串写法）。
2. 在 `ops/docker-compose.yml` 中**注释掉 `db` 和 `redis` 两个服务**，并把 `backend-admin` / `backend-user` / `migrate` / `celery-worker` / `celery-beat` 的 `depends_on` 中对应行删掉（否则 compose 会等一个不会启动的容器健康）。
3. 外部 PostgreSQL 必须先 `CREATE EXTENSION IF NOT EXISTS vector;`；外部 Redis 需要开放 DB 0/1/2 三个逻辑库（或找运维开多 DB）。
4. `migrate` 一次性任务仍由 compose 触发，它会直接连外部库执行 Alembic 升级，不需要改代码。

### 14.5 创建首个管理员

**方式 A：随容器启动自动初始化（推荐生产使用）**

在 `ops/.env.prod` 中追加以下配置，`backend-admin` 容器启动时若 `admin_users` 表为空会自动创建首个平台账号：

```bash
ADMIN_AUTO_INIT=true
ADMIN_INITIAL_PASSWORD='<符合密码策略的强密码>'
ADMIN_INITIAL_USERNAME=admin
ADMIN_INITIAL_DISPLAY_NAME=系统管理员
ADMIN_INITIAL_ROLE=superadmin
ADMIN_INITIAL_MUST_CHANGE_PASSWORD=true
```

**必须同时配置 `ADMIN_AUTO_INIT=true` 和 `ADMIN_INITIAL_PASSWORD` 才会执行**；只开开关不配密码会被跳过并输出日志。首次登录会强制改密。表中已有账号时自动跳过，不影响存量账号；密码不符合策略或角色不存在时跳过并输出告警日志。多副本同时首启时依赖 `username` 唯一索引 + `ON CONFLICT DO NOTHING` 兜底，仅一个实例实际写入，不会产生重复账号。

> **首次登录并改密成功后**，请从 `ops/.env.prod` 移除 `ADMIN_INITIAL_PASSWORD`（或直接关闭 `ADMIN_AUTO_INIT`）并重新部署。该配置只在 `admin_users` 表为空时生效一次，移除不影响已创建的账号；保留它会让初始密码长期残留在 env 文件、容器环境（`docker inspect` 可见）和部署记录中。

**方式 B：手动脚本**

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

默认创建的是产品级平台账号，租户管理员请登录平台后在「租户管理」中创建。自动化/演示环境可额外传 `-e ADMIN_MUST_CHANGE_PASSWORD=false`。

> 非交互方式会把密码留在 shell 历史和进程列表中，生产环境优先用交互方式；如果必须非交互，执行后清理历史记录。

### 14.6 配置 HTTPS

推荐用云负载均衡或宿主机 Nginx/Caddy 终止 TLS，再按域名转发：`platform.<根域名>` 到 `frontend-admin`，根域名与租户子域名到 `frontend-user`。

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
    server_name platform.example.com;

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

`platform.example.com` 是精确匹配，优先级高于 `*.example.com`，顺序不影响结果。

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

- [ ] 通过 HTTPS 打开 `https://platform.<根域名>`，使用首个管理员登录并完成改密
- [ ] 在「租户管理」创建一个租户，确认租户子域名可正常打开
- [ ] 用该租户管理员登录租户子域名，确认看不到「租户管理」入口
- [ ] 在平台侧创建一个产品级应用并发布版本，确认未开通时租户市场不可见；在「应用市场」开通给租户后，租户可看到实例但只能用自己的配置
- [ ] 在平台侧创建一个资源（工具 / 提示词 / 技能 / 知识），确认未授权给租户时租户不可见；授权后租户可见，且另一个租户看不到
- [ ] 在租户内创建自定义角色与最终用户，绑定角色后用用户端登录，确认只看到已开通且启用的应用
- [ ] 在租户内打开应用对话，确认 SSE 增量输出、工具调用轨迹和运行历史可用
- [ ] 用 viewer 账号验证写接口返回 403
- [ ] 用 superadmin 查看审计日志，确认租户审计只在租户内可见，授权变更留有 `grant.updated` 记录
- [ ] 确认 `/docs` 在生产不可访问（`DOCS_ENABLED=false`）
- [ ] 确认 `/metrics` 从外部不可访问
- [ ] 打开用户端站点（`USER_HTTP_PORT`，示例 8081），用最终用户账号登录，确认应用列表与详情可用；未登录调用 `/api/v1/user/me` 返回 401
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
| 未知域名也返回 404                                    | 这是预期行为：部署环境只认 `platform.<ROOT_DOMAIN>` 与 `<租户编码>.<ROOT_DOMAIN>`，不会回退产品级平台；检查 DNS、`ROOT_DOMAIN` 与租户编码 |
| 启动失败：`必须配置 ROOT_DOMAIN`                      | 除 `local` 外，`dev` / `test` / `prod` 都必须配置完整域名                                                                      |
| 启动失败：`仅 local 环境允许开启 ALLOW_TENANT_HEADER` | 部署环境删除该配置或设为 `false`；请求头切换只用于本地回环主机                                                                               |
| 所有子域名都进入平台作用域                            | 反向代理或网关没有透传原始 `Host` 头；或 `ROOT_DOMAIN` 配成了不包含该子域的根域名                                                            |
| 本地 `acme.localhost` 打不开                          | 确认后端以 `APP_ENV=local` 启动；Vite 需允许 `*.localhost` 并透传原始 `Host`（仓库配置已处理）                                               |
| 登录提示账号不属于该租户                              | 账号只能登录其所属作用域：产品级账号走 `platform`，租户账号走本租户子域名                                                                 |

---

