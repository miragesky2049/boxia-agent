> 返回 [项目手册](../README.md)

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

