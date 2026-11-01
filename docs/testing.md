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

覆盖范围按模块分组：

| 领域 | 代表性测试文件 | 覆盖内容 |
| --- | --- | --- |
| 认证与安全 | `test_auth.py`、`test_auth_service.py`、`test_site_isolation.py` | 登录 / 刷新 / 撤销 / 锁定、admin 与 user 站点路由隔离、错误模型 |
| 权限与租户 | `test_roles.py`、`test_role_permissions.py`、`test_platform_roles.py`、`test_tenants.py`、`test_tenant_settings.py` | RBAC 权限目录、平台内置角色、租户作用域、租户配置 |
| 用户与组织 | `test_users.py`、`test_admin_users.py`、`test_departments.py`、`test_employments.py`、`test_employment_hr_fields.py` | 用户、管理员账号、部门 / 任职 / 管理单元 |
| 授权与可见性 | `test_grants.py`（`test_role_grants.py`、`test_user_grant_save.py`）、`test_visibility.py`、`test_marketplace_workbench.py` | 角色授权、资源授权、应用可见范围、市场开通工作台 |
| 资源与工具 | `test_resources.py`、`test_tool_gateway.py`、`test_tool_executor_service.py`、`test_ssrf_guard.py` | 四类资源 CRUD、工具网关（熔断 / 限流 / 重试 / SSRF） |
| 画布与运行时 | `test_canvas_convert.py`、`test_compiler_runtime.py`、`test_node_meta_contract.py`、`test_variable_system.py`、`test_template_refs.py` | 画布 DSL 转换、节点元数据契约、变量系统 |
| 节点实现 | `test_llm_*.py`、`test_http_node.py`、`test_code_node.py`、`test_if_else_node.py`、`test_loop_*.py`、`test_dataset_node.py`、`test_api_plugin_node.py`、`test_subworkflow_node.py`、`test_agent_loop*.py`、`test_comment_node.py` | 各节点类型行为、流式输出、多模态、工具调用、循环与分支 |
| 图生命周期 | `test_publish_graph.py`、`test_single_node_debug.py`、`test_graph_runtime_e2e.py`、`test_graph_object_storage.py`、`test_checkpointer_tenant_isolation.py` | 发布 / 版本、单节点调试、断点续跑、检查点多租户隔离 |
| 会话与多租户运行 | `test_app_conversations.py`、`test_async_message_adapter_tenant_scope.py` | 应用会话历史、异步消息适配器租户隔离 |
| RAG 与模型 | `test_retrieval_services.py`、`test_vector_store_factory.py`、`test_model_service_catalog.py`、`test_llm_node_tools.py` | 召回 / 精排、向量库抽象、模型目录 |
| 运维 | `test_ops.py` | 健康检查、运维接口 |

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

覆盖场景（`e2e/admin.spec.ts`）：登录失败、会话恢复、登出跳转、技能 CRUD、智能体保存回显、404、首登改密、viewer 只读（无写入口、越权页面 404）。

> 注意：E2E 用例目前仍走历史路径 `/agents`（含 `/agents/new`、`/agents/:id/edit`）与历史文案「智能体」，与后端「应用」模型是同一份数据，只是尚未改名。若你改动了这些路由或页面结构，需要同步修改 `e2e/*.spec.ts`。

多租户用例（`e2e/tenant.spec.ts`）会通过平台 API 创建测试租户并切换作用域：本地 `localhost` 上使用登录页下拉框或 `?tenant=`（请求头模式），同时覆盖直接访问 `http://<租户编码>.localhost:5173` 的真实子域名解析。因此 `E2E_USERNAME` 必须是**产品级 superadmin**（默认 `admin`），后端需以 `APP_ENV=local`、`ROOT_DOMAIN=localhost`、`ALLOW_TENANT_HEADER=true` 启动（CI 已配置）。用例覆盖：平台租户管理（含编辑租户名称）、作用域切换限制、租户子域名访问、租户管理员作用域限制、平台应用授权后才在租户可见、租户管理员管理角色与用户。

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

