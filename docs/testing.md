> 返回 [项目手册](../README.md)

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

