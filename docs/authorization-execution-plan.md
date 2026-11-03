# 授权体系细化执行计划

> 上游文档：`docs/authorization-roadmap.md`
> 决策确认日期：2026-11-03
> 适用范围：产品级运营管理平台 + 租户级运营管理平台
> 本文档目标：把 roadmap 的 P0–P3 拆成可独立提交、可验收、可回滚的工程任务。

---

## 0. 决策基线

### 0.1 已确认决策

| # | 决策 | 影响 |
| --- | --- | --- |
| D1 | 工具/技能/Prompt/知识**仅产品级直开**，不做市场申请 | 市场只处理 `application`；资源权益 `auth_source` 只需 `OPS`，但字段保留以扩展 |
| D2 | **整租户授权显式化**：保留"全员可见（含未来新增角色）"能力，用 `subject_type` 显式表达 | `resource_grants` 增加 `subject_type`（`tenant`/`role`）；`role_id IS NULL` 回填为 `subject_type='tenant'`，不拆分；服务层按 `subject_type` 分支 |
| D3 | 租户自建资源**需产品级审核**后才能被角色授权 | `resource.review_status`；审核 API；角色授权候选过滤 |
| D4 | 租户自建资源使用**独立按钮权限码** `button:resource:create`（不复用 `button:app:create`） | 权限码种子 8 个；`TENANT_ONLY_CODES` 增加；P1-4 / P1-9 按此实现 |
| D5 | 权益用例落在 `internal/application/apps/entitlement_service.py`，组合根统一在 `web/deps/entitlement_services.py` | 与 apps 上下文同目录；`apps_services.py` 不再新增同名工厂 |
| D6 | 前端申请/开通接口新建 `frontend/admin/src/api/entitlements.ts`，应用申请沿用 `api/apps.ts` | 不新建 `api/roles.ts` / `api/resources.ts` / `api/applies.ts` |

> 注：§7.2 的 `D-1`~`D-6` 是待确认项编号，与本表 `D1`~`D6` 不是同一组编号，避免混淆；§7.2 各项已于 2026-11-03 全部给出结论。

### 0.2 本计划采用的默认假设（如有异议需在 P1 前调整）

| # | 假设 | 理由 |
| --- | --- | --- |
| A1 | 对象类型值统一用 `app`，不用 `application` | 现有前端、`RoleDetailPage`、`RESOURCE_TYPES` 已用 `app`，改造成本最低 |
| A2 | 资源权益复用单数 `resource_grant` 表扩展，不新建表 | 已有 `(resource_id, tenant_id)` 唯一约束，只需补生命周期字段 |
| A3 | 应用权益继续用 `tenant_application_instance` | 已有完整申请/版本/有效期模型，迁移风险大 |
| A4 | `role_id IS NULL` 回填 `subject_type='tenant'`，**不拆分**给具体角色 | 保留"全员可见 + 新增角色自动继承"语义；符合行业显式 subject 建模 |
| A5 | 平台资源默认 `review_status=approved`，存量资源回填 approved | 避免误伤已在使用资源 |
| A6 | 租户自建资源创建即 `pending`，仅 approved 可授权 | 满足 D3 |
| A7 | 产品级入口命名「租户开通」`/entitlements`；租户级「角色授权」`/role-access` | 与"用户授权"区分 |
| A8 | 新迁移从 `0055` 起，依次 0055–0058（P3-3 顺延为 `0059`） | `0054`（`grant_resource_type_unify`）已随 P0-1 交付，原计划编号整体顺延（2026-11-03 P0-7 同步） |

### 0.3 本轮不做

- 资源市场申请（D1）
- 套餐/Plan 模板（P3）
- 应用与资源的物理表合并（P3 评估）
- 资源类型注册表化（P3）
- `subject_type` 扩展到 `user`/`group`（本轮只做 `tenant`/`role`）
- 席位/用量配额的实际扣减（`quota_json` 本轮只存储与展示，不参与判定；执行点见 P3）
- 多租户层级/委派管理（MSP、Microsoft 365 式 delegated admin）：当前为单层租户模型，本轮不引入
- 权益变更的幂等键与对账作业（P3 评估，见 §7.3）

---

## 1. 目标态

### 1.1 两层职责

```text
Entitlement 层（产品级 → 租户）：租户拥有什么
  application → tenant_application_instance
  tool/skill/prompt/knowledge → resource_grant（扩展生命周期）

Permission 层（租户内角色 → 资源）：角色能使用什么
  resource_grants（subject_type='tenant' 全员可见 OR subject_type='role' AND role_id ∈ 当前角色）

约束：Permission ⊆ Entitlement ∩ resource.review_status=approved
```

### 1.2 数据模型总览

| 表 | 变更 | 用途 |
| --- | --- | --- |
| `resource_grant`（单数） | 增加 status/auth_source/auth_type/start_time/expire_time/quota_json/remark/granted_by | 资源权益 |
| `resource` | 增加 review_status/reviewed_by/reviewed_at/review_remark | 租户自建审核 |
| `resource_grants`（复数） | 增加 `subject_type`（`tenant`/`role`）；`role_id` 仅 `role` 档必填；重建作用域约束/索引（resource_type CHECK 统一已随 0054 交付） | 角色授权 + 全员可见 |
| `tenant_application_instance` | 修正 status CHECK | 应用权益 |
| `permission_resources` | 种子新增 8 个权限码 | 菜单/按钮 |

### 1.3 运行时判定链（目标态）

```text
1. 登录 → 角色集合（users.role_id + user_roles）
2. 功能权限：role_permissions 决定菜单/按钮
3. 租户权益：tenant_application_instance(active) ∪ resource_grant(active)
4. 角色资源授权：resource_grants（subject_type='tenant' OR subject_type='role' AND role_id ∈ 当前角色）
5. 资源质量门槛：resource.review_status = 'approved'
6. 最终可见 = 3 ∩ 4 ∩ 5 ∩ resource.is_enabled ∩ application.visibility
```

### 1.4 权限码清单（新增）

| code | 名称 | category | 作用域 |
| --- | --- | --- | --- |
| `menu:entitlements` | 租户开通 | menu | 平台 |
| `page:entitlements` | 租户开通页面 | page | 平台 |
| `button:entitlement:manage` | 租户开通-维护 | button | 平台 |
| `menu:role-access` | 角色授权 | menu | 租户 |
| `page:role-access` | 角色授权页面 | page | 租户 |
| `button:role-access:manage` | 角色授权-维护 | button | 租户 |
| `button:resource:review` | 资源-审核 | button | 平台 |
| `button:resource:create` | 资源-新建（租户自建） | button | 租户 |

作用域归类：
- `PLATFORM_ONLY_CODES` 增加 `menu:entitlements/page:entitlements/button:entitlement:manage/button:resource:review`
- `TENANT_ONLY_CODES` 增加 `menu:role-access/page:role-access/button:role-access:manage/button:resource:create`
- 内置角色种子：平台 superadmin/admin 获得开通与审核；租户 superadmin/admin 获得角色授权与资源新建；viewer 均不授予

---

## 2. 迁移设计

### 2.1 迁移顺序与依赖

```text
0055_resource_grant_lifecycle
      │  resource_grant 加生命周期字段；修正 instance status CHECK
      ▼
0056_resource_review
      │  resource 加审核字段；存量回填 approved
      ▼
0057_grant_subject_type
      │  整租户授权显式化（subject_type）；重建约束/索引（resource_type CHECK 统一已随 0054 提前交付）
      ▼
0058_entitlement_permissions
      │  权限码种子 + 内置角色授权（可独立发）
```

> **编号说明（2026-11-03 P0-7）**：`0054_grant_resource_type_unify` 已随 P0-1 在线交付（可滚动发布、无需停机），故原计划的 0054–0057 整体顺延为 0055–0058，P3-3 顺延为 0059。

> **本次采用停机维护窗口**：0055–0057 与后端代码在同一次停写窗口内完成（停写 → 迁移 → 发代码 → 恢复写），因此 0057 可一次性完成加列、回填、CHECK 与索引重建，无需 expand/contract 拆分。0058 可随后单独发。
> 若未来改为无停机滚动发布，必须按标准 expand → contract 拆成两次迁移（见 §6.1 备注）。

### 2.2 0055：资源权益生命周期

```sql
-- resource_grant（单数）
ALTER TABLE resource_grant
  ADD COLUMN status      VARCHAR(20) NOT NULL DEFAULT 'active',
  ADD COLUMN auth_source VARCHAR(20) NOT NULL DEFAULT 'OPS',
  ADD COLUMN auth_type   VARCHAR(20) NOT NULL DEFAULT 'FORMAL',
  ADD COLUMN start_time  TIMESTAMPTZ NULL,
  ADD COLUMN expire_time TIMESTAMPTZ NULL,
  ADD COLUMN quota_json  JSONB NOT NULL DEFAULT '{}',
  ADD COLUMN remark      TEXT NOT NULL DEFAULT '',
  ADD COLUMN granted_by  UUID NULL;

ALTER TABLE resource_grant
  ADD CONSTRAINT ck_resource_grant_status
    CHECK (status IN ('active','suspended','revoked','wait_effect','expired')),
  ADD CONSTRAINT ck_resource_grant_source
    CHECK (auth_source IN ('OPS','MARKET_APPLY')),
  ADD CONSTRAINT ck_resource_grant_type
    CHECK (auth_type IN ('FORMAL','TRIAL','GIFT'));

CREATE INDEX ix_resource_grant_tenant_status
  ON resource_grant (tenant_id, status);

-- tenant_application_instance：修正状态 CHECK
ALTER TABLE tenant_application_instance
  DROP CONSTRAINT IF EXISTS ck_instance_status;
ALTER TABLE tenant_application_instance
  ADD CONSTRAINT ck_instance_status
    CHECK (status IN ('active','suspended','disabled','revoked','wait_effect','expired'));
```

回滚：删除新增列/约束，恢复 `ck_instance_status` 旧值（需先清理 `wait_effect/expired` 数据）。

### 2.3 0056：资源审核

```sql
ALTER TABLE resource
  ADD COLUMN review_status VARCHAR(20) NOT NULL DEFAULT 'approved',
  ADD COLUMN reviewed_by   UUID NULL,
  ADD COLUMN reviewed_at   TIMESTAMPTZ NULL,
  ADD COLUMN review_remark TEXT NOT NULL DEFAULT '',
  ADD COLUMN created_by    UUID NULL;

ALTER TABLE resource
  ADD CONSTRAINT ck_resource_review_status
    CHECK (review_status IN ('pending','approved','rejected'));

CREATE INDEX ix_resource_review_status
  ON resource (review_status, owner_type);
```

回填：默认值 `approved` 已覆盖存量。平台资源保持 approved；租户自建后续走 pending。

`created_by`：存量平台资源为 `NULL`（历史无记录来源）；新建资源必须写入当前管理员 ID，用于 P1-9 的「审核人不得审核自己创建的资源」（职责分离，行业通用要求）。

### 2.4 0057：整租户授权显式化

> **D-2 已确认（2026-11-03）：路线 1 — 显式 `subject_type`。**
> 保留"全员可见 + 新增角色自动继承"语义，不拆分给具体角色；`role_id IS NULL` 回填为 `subject_type='tenant'`。
> **D-1 孤儿清理与 resource_type CHECK 统一已随 `0054_grant_resource_type_unify` 提前交付（P0-1，可滚动发布，无需停机）**，本迁移不再包含 DELETE 与类型 CHECK 步骤。

> **发布方式（2026-11-03 确认）**：采用停机维护窗口——停写 → 执行 0055–0057 → 发布 P1 后端代码 → 恢复写。因此 0057 可一次性完成加列、回填、CHECK 与索引重建，不存在"旧代码插入 `role_id NULL` 撞新 CHECK"的窗口。
> 若未来改为无停机滚动发布，必须按标准 expand → contract 拆成两次迁移：先加列/回填/建新索引并保留旧索引，代码全量上线后再加 CHECK、删旧索引。

**迁移前盘点（必须先执行，结果留档）：**

```sql
-- 1) 各类资源授权分布
SELECT resource_type, role_id IS NULL AS tenant_wide, count(*)
FROM resource_grants GROUP BY 1,2 ORDER BY 1,2;

-- 2) 历史 agent/component 授权（0054 已清理，执行 0055 前应恒为 0 行，留作核验）
SELECT resource_type, count(*)
FROM resource_grants
WHERE resource_type IN ('agent','component')
GROUP BY 1;

-- 3) 整租户授权涉及租户
SELECT tenant_id, count(*) FROM resource_grants
WHERE role_id IS NULL GROUP BY 1;
```

**迁移步骤：**

```sql
-- 1) 新增 subject_type，默认 role
ALTER TABLE resource_grants
  ADD COLUMN subject_type VARCHAR(10) NOT NULL DEFAULT 'role';

-- 2) 回填：role_id IS NULL → 全员可见；其余保持 role
UPDATE resource_grants SET subject_type = 'tenant' WHERE role_id IS NULL;
UPDATE resource_grants SET subject_type = 'role'  WHERE role_id IS NOT NULL;

-- 3) 重建作用域约束：tenant 档必须无 role_id，role 档必须有 role_id
ALTER TABLE resource_grants DROP CONSTRAINT IF EXISTS ck_resource_grants_scope;
ALTER TABLE resource_grants
  ADD CONSTRAINT ck_resource_grants_subject
    CHECK (
      (subject_type = 'tenant' AND role_id IS NULL)
      OR (subject_type = 'role' AND role_id IS NOT NULL)
    );

-- 4) 索引：tenant 档唯一性用 subject_type 表达；旧索引在新代码上线后删除
CREATE UNIQUE INDEX ux_resource_grants_tenant_subject
  ON resource_grants (resource_type, resource_id, tenant_id)
  WHERE subject_type = 'tenant';

CREATE UNIQUE INDEX ux_resource_grants_role_subject
  ON resource_grants (resource_type, resource_id, tenant_id, role_id)
  WHERE subject_type = 'role';

CREATE UNIQUE INDEX ux_resource_grants_platform_role_subject
  ON resource_grants (resource_type, resource_id, role_id)
  WHERE subject_type = 'role' AND tenant_id = '00000000-0000-0000-0000-000000000000';

DROP INDEX IF EXISTS ux_resource_grants_tenant_wide;
DROP INDEX IF EXISTS ux_resource_grants_role;
DROP INDEX IF EXISTS ux_resource_grants_platform_role;
```

**注意：**
- 本迁移**不删除任何数据**（D-1 孤儿已随 0054 清理），downgrade 可逆：删除新增索引与约束、删除 `subject_type` 列。
- `subject_type='tenant'` 记录在运行时对所有当前及未来角色生效；新增角色天然继承，无需补授权。
- `subject_type='role'` 保持原有按角色授权语义。
- 迁移脚本须在日志中输出回填统计：`tenant` 档与 `role` 档各多少条，便于核对。
- **升级前仍备份 `resource_grants`**（回填与索引重建属高风险 DDL）。

### 2.5 0058：权限码种子

```sql
INSERT INTO permission_resources
  (id, code, name, category, action, description, sort_order, is_active)
VALUES
  (gen_random_uuid(), 'menu:entitlements', '租户开通', 'menu', 'view', '', 15, TRUE),
  (gen_random_uuid(), 'page:entitlements', '租户开通页面', 'page', 'view', '', 115, TRUE),
  (gen_random_uuid(), 'button:entitlement:manage', '租户开通-维护', 'button', 'manage', '', 405, TRUE),
  (gen_random_uuid(), 'menu:role-access', '角色授权', 'menu', 'view', '', 21, TRUE),
  (gen_random_uuid(), 'page:role-access', '角色授权页面', 'page', 'view', '', 121, TRUE),
  (gen_random_uuid(), 'button:role-access:manage', '角色授权-维护', 'button', 'manage', '', 301, TRUE),
  (gen_random_uuid(), 'button:resource:review', '资源-审核', 'button', 'manage', '', 406, TRUE),
  (gen_random_uuid(), 'button:resource:create', '资源-新建', 'button', 'create', '', 302, TRUE)
ON CONFLICT (code) DO NOTHING;
```

内置角色授权：按 `permission.py` 的 `PLATFORM_ADMIN_CODES` / `TENANT_ADMIN_CODES` 同步写入 `role_permissions`。迁移中直接复用角色 code 查询，避免写死 UUID。

---

## 3. 任务 WBS

> 执行者假设：没有本对话上下文。每个任务按「现状 → 改动 → 目标签名/骨架 → 测试 → 验证 → DoD」组织，照做即可。
> 预估单位：人日；每个任务是一个可独立提交的 commit。

### 3.0 执行约定（执行模型必读）

#### 3.0.1 分层与依赖方向

```text
backend/
├── internal/
│   ├── domain/            # 实体 + Protocol 端口，不 import application/infrastructure/web
│   │   ├── entity/
│   │   └── repository/
│   ├── application/       # 用例服务，只依赖 domain 的实体与 Protocol
│   │   ├── apps/          # apps 上下文用例
│   │   └── ...
│   ├── infrastructure/    # 仓储实现、ORM、外部客户端
│   └── ...
├── web/                   # FastAPI 路由 + 依赖装配（组合根）
│   ├── admin/routers/
│   └── deps/
├── migrations/versions/
└── tests/
```

硬性规则：

1. 依赖方向：`web → application → domain`，`infrastructure → domain`。`application` 不得 import `internal.infrastructure.*`。
2. 用例需要新仓储时：先在 `internal/domain/repository/*_protocols.py` 定义 Protocol，再到 `internal/infrastructure/repository/` 实现，最后在 `web/deps/*.py` 组合根注入。
3. router 内不得直接构造仓储或调用 `uow.session.execute`；一律注入用例服务。
4. 资源类型常量只在 `internal/domain/entity/access.py` 定义一份（P0-1 之后），其余文件 import。

#### 3.0.2 两个同名 `GrantService`（最容易搞错）

| | `internal/domain/auth/grant_service.py` | `internal/application/grant_service.py` |
| --- | --- | --- |
| 类名 | `GrantService` | `GrantService` |
| 存储 | `tenant_application_instance`（应用权益，单数语义） | `resource_grants`（RBAC 角色授权，复数） |
| 职责 | 应用开通 / 回收 / 定时生效 | 资源授权 overview/replace/replace_batch/user roles |
| 装配 | `web/deps/apps_services.py::make_apply_service` | `web/deps/services.py::get_grant_service` |
| 本计划涉及 | P0-4、P1-7、P3-1 | P0-3、P1-8、P1-10 |

引用时一律写全模块路径，禁止只写 `GrantService`。

#### 3.0.3 命令与基线

```bash
# 后端单测（基线约 460 个，P0 完成后）
cd backend && python -m pytest -q

# 单文件
cd backend && python -m pytest tests/test_xxx.py -q

# 静态检查
cd backend && ruff check internal web tests
cd backend && mypy internal web

# 迁移（本地库需已启动，测试库见 tests/conftest.py）
cd backend && alembic upgrade head
cd backend && alembic downgrade -1
cd backend && alembic upgrade head

# 前端
cd frontend/admin && pnpm typecheck
cd frontend/admin && pnpm lint
cd frontend/admin && pnpm test
cd frontend/admin && pnpm e2e
```

基线（2026-11-03，P0 完成后实测）：pytest 460 passed；ruff 存量 139（P0 前 146）、mypy 存量 109（P0 前 116），后续任务不得新增。

#### 3.0.4 迁移写法约定

- 文件：`backend/migrations/versions/NNNN_<snake_name>.py`，`revision = "NNNN_<snake_name>"`（与文件名一致的 slug，沿用仓库既有风格），`down_revision = "<上一个 head 的 revision>"`；revision ID 必须 ≤32 字符（`alembic_version.version_num` 为 VARCHAR(32)，超长在写版本号时报 StringDataRightTruncation）；本轮起点 head 为 `0054_grant_resource_type_unify`（P0-1 已交付），P1 自 `0055` 起。
- **revision slug 必须 ≤32 字符**（`alembic_version.version_num` 为 VARCHAR(32)，超长在 upgrade 时报 StringDataRightTruncation）。
- 必须实现 `downgrade()`，且 downgrade 后可再 upgrade。
- 迁移内只允许 `sqlalchemy` / `alembic.op` 与字面常量，不得 import `internal.application` / `internal.domain`。
- 权限种子参考 `backend/migrations/versions/0038_apps_menu_permissions.py` 的 `_PERMISSIONS` + `_code_array()` + `ON CONFLICT DO NOTHING` 写法。
- 数据删除类迁移必须先 `SELECT` 盘点并 `logger.info` 输出数量。

#### 3.0.5 错误映射

| 异常 | HTTP | 使用场景 |
| --- | --- | --- |
| `ValidationError` | 422 | 参数/业务规则不满足（类型非法、未开通、未审核、sale_mode 不符） |
| `NotFoundError` | 404 | 对象不存在或不可见 |
| `ForbiddenError` | 403 | 作用域越权（租户访问平台接口、跨租户操作） |
| 409 语义（当前用 `ValidationError` 承载） | 409 | 重复开通；如需严格 409 需在全局异常处理器补映射 |

来源：`internal/application/errors.py` 与 `web` 全局异常处理器。

#### 3.0.6 现状事实索引（改动前先核对，行号以本次核查为准）

| 事实 | 位置 |
| --- | --- |
| domain 资源类型只有两种 | `internal/domain/entity/access.py:16` |
| ORM 资源类型含 agent/component | `internal/infrastructure/model/access.py:27`、`:188-191` |
| resource_service 四类白名单 | `internal/application/apps/resource_service.py:11` |
| 工具仓储类型硬编码 | `internal/infrastructure/repository/resource_tool_repository.py:26` |
| GrantService 永远查 tools | `internal/application/grant_service.py:371-375` |
| RoleGrantService app 走内联适配器 | `internal/application/role_grant_service.py:50-107`、`:343-347` |
| 可见性 `role_id IS NULL` 判定 | `internal/infrastructure/repository/grant_filters.py:13-22` |
| 整租户仓储方法 | `internal/infrastructure/repository/postgres_resource_grant_repository.py:241-294` |
| 平台角色唯一索引谓词 | 同上 `:447-484`；ORM `internal/infrastructure/model/access.py:221-230` |
| 应用 subscribe 未校验 sale_mode | `internal/application/apps/application_service.py:304-321` |
| get_application 未返回 sale_mode | `internal/infrastructure/repository/apps/application_repository.py:194-204` |
| get_instance 未过滤状态 | `internal/infrastructure/repository/apps/application_repository.py:395-403` |
| 申请单端点鉴权 | `web/admin/routers/applies.py:87-178`（`AdminAuthDep`） |
| claim 未持久化 sales_user_id | `internal/domain/auth/apply_service.py:102-123` |
| 租户资源路由只有 GET | `web/admin/routers/resources.py:26`、`:155-165` |
| uow 仓储装配 | `internal/infrastructure/model/uow.py:82-131` |
| 组合根 apps 服务 | `web/deps/apps_services.py` |
| 平台/租户鉴权依赖 | `web/deps/auth.py:103-122`、`:160-162` |

### 3.1 P0 — 前置修正（1–2 人日）

> **执行状态（2026-11-03）**：P0 全部完成并提交——P0-1 `952e96d`、P0-2 `cf51ab4`、P0-3 `8ab7f2e`、P0-4 `7eeed51`、P0-6 `d2a5da0`；P0-5 并入 P1-1（见其小节）。与计划的两处偏差：① P0-1 额外新建迁移 `0054_grant_resource_type_unify`（孤儿清理 + 类型 CHECK 统一提前交付，P1 迁移整体顺延为 0055–0058）；② P0-3 的 `AppGrantRepository` 按 grant_service 实际消费面补全了 `list_page/get/ids_owned` 等方法（原计划只列 `list_grantable/ids_grantable`）。P0-7 回归基线见 §5.4。

#### P0-1 统一资源类型常量

**现状**
- domain 层 `RESOURCE_TYPES = ("tool", "app")`（`internal/domain/entity/access.py:16`），用于 RBAC 校验。
- ORM 层 `RESOURCE_TYPES = ("agent","skill","tool","component","prompt")`（`internal/infrastructure/model/access.py:27`），CHECK 在 `:188-191`。
- `internal/application/apps/resource_service.py:11` 第三份 `_VALID_TYPES = {"tool","prompt","skill","knowledge"}`。
- `tests/test_role_grants.py:15` 又重复一份 `("tool","app")`。

**改动清单**

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `internal/domain/entity/access.py` | 修改 | 增加 `APP_RESOURCE_TYPE = "app"`、`RESOURCE_TABLE_TYPES = ("tool","skill","prompt","knowledge")`；`RESOURCE_TYPES = (*RESOURCE_TABLE_TYPES, APP_RESOURCE_TYPE)` |
| `internal/infrastructure/model/access.py` | 修改 | 删除本地 `RESOURCE_TYPES`，改为从 domain import；ORM CHECK 文案与迁移同步为 `('app','skill','tool','prompt','knowledge')` |
| `internal/application/apps/resource_service.py` | 修改 | `_VALID_TYPES` 改为 `frozenset(RESOURCE_TABLE_TYPES)` |
| `tests/test_role_grants.py` | 修改 | 删除本地 `_RESOURCE_TYPES`，import domain 常量 |

**目标代码骨架**

```python
# internal/domain/entity/access.py
APP_RESOURCE_TYPE = "app"
RESOURCE_TABLE_TYPES = ("tool", "skill", "prompt", "knowledge")
RESOURCE_TYPES = (*RESOURCE_TABLE_TYPES, APP_RESOURCE_TYPE)
```

```python
# internal/infrastructure/model/access.py
from internal.domain.entity.access import RESOURCE_TYPES
```

**注意**：`role_service.py:184`、`role_grant_service.py:156` 用 `RESOURCE_TYPES` 生成 summary 的 key，扩展后会多出 3 个 key。前端只按 key 取值即可；若前端用 `Object.keys` 顺序渲染，P2 需显式定义展示顺序。

**测试**（新增 `tests/test_resource_types.py`）

```python
from internal.domain.entity.access import APP_RESOURCE_TYPE, RESOURCE_TABLE_TYPES, RESOURCE_TYPES
from internal.infrastructure.model.access import RESOURCE_TYPES as ORM_TYPES

def test_single_source_of_truth():
    assert RESOURCE_TYPES == ORM_TYPES
    assert set(RESOURCE_TYPES) == {"tool", "skill", "prompt", "knowledge", "app"}
    assert APP_RESOURCE_TYPE not in RESOURCE_TABLE_TYPES

def test_no_legacy_types():
    assert "agent" not in RESOURCE_TYPES and "component" not in RESOURCE_TYPES
```

**验证**

```bash
cd backend && python -m pytest tests/test_resource_types.py -q
cd backend && grep -rn '"agent"\|"component"' internal web | grep -v migrations   # 结果应为空
```

**DoD**
- 除迁移历史文件外，全仓不再以 `agent/component` 作为资源类型分支；
- `RESOURCE_TYPES` 只有一处定义；
- 基线 pytest 不减少。

**依赖**：无　**预估**：0.25

---

#### P0-2 参数化资源仓储

**现状**
- `resource_tool_repository.py:26` `_RESOURCE_TYPE = "tool"`，在 `_owned_filter/_visible/_get_owned/_grantable` 等 13 处使用，因此只能服务工具。
- `uow.py:118` 只装配 `self.tools`。

**改动清单**

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `internal/infrastructure/repository/resource_tool_repository.py` | 修改 | 构造增加 `resource_type: str = "tool"`；所有 `_RESOURCE_TYPE` → `self._resource_type`；构造时校验 `resource_type in RESOURCE_TABLE_TYPES` |
| `internal/infrastructure/model/uow.py` | 修改 | 新增 `resource_repo(resource_type)` 工厂；`apply_scope` 同步重建 |
| `internal/domain/repository/protocols.py` | 修改 | `UnitOfWork` 增加 `def resource_repo(self, resource_type: str) -> ResourceRepository[Tool]: ...`（用既有 Protocol 标注，不引用 infra 类） |

**目标签名**

```python
class ResourceToolRepository:
    def __init__(
        self,
        session: Session,
        tenant_id: UUID | None = None,
        role_ids: tuple[UUID, ...] = (),
        apply_role_filter: bool = True,
        resource_type: str = "tool",
    ) -> None: ...
```

```python
# uow.py
def resource_repo(self, resource_type: str) -> ResourceToolRepository:
    """按资源类型返回当前作用域仓储；tools 等价于 resource_repo('tool')。"""
    return ResourceToolRepository(
        self.session,
        self.tenant_id,
        self._scope_role_ids,
        self._scope_apply_role_filter,
        resource_type,
    )
```

**注意**
- `_to_entity` 已取 `row.type`，skill/prompt/knowledge 复用 `Tool` 实体无需改名。
- `create()` 中 `type=_RESOURCE_TYPE` → `self._resource_type`；`update()` 的 `values.get("type")` 分支要校验不能改成非法类型。

**测试**（新增 `tests/test_resource_repository_types.py`）

| 用例 | 断言 |
| --- | --- |
| 平台作用域分别创建 skill/prompt/knowledge | 各自 `list_page` 只返回本类型 |
| 创建 skill 后用 `resource_repo("tool")` 查询 | 查不到 |
| `uow.resource_repo("app")` | 抛 `ValueError` |
| `uow.tools` | 等价于 `resource_repo("tool")` |

**验证**

```bash
cd backend && python -m pytest tests/test_resource_repository_types.py tests/test_resource_types.py tests/test_resources.py -q
```

**DoD**：`uow.resource_repo("skill")` 只返回 skill；既有工具接口行为不变。

**依赖**：P0-1　**预估**：0.5

---

#### P0-3 修复 GrantService 仓储路由

**现状**
- `internal/application/grant_service.py:371-375`：`_resource_repository` 校验类型后**无条件** `return self._uow.tools`，导致 app/skill/prompt/knowledge 的 `overview/list_grants/replace/replace_batch` 全部按 tool 处理。
- `internal/application/role_grant_service.py:50-107` 内联定义了 `_AppGrantRow` / `_AppGrantRepository`（原生 SQL），`:343-347` 仅区分 app 与 tools。

**改动清单**

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| 新增 `internal/infrastructure/repository/apps/app_grant_repository.py` | 新增 | 把 `_AppGrantRow` + `_AppGrantRepository` 迁入并改名为 `AppGrantRepository`，保留 `list_grantable` / `ids_grantable` |
| `internal/application/role_grant_service.py` | 修改 | 删除内联适配器，改为 `self._uow.app_grants` |
| `internal/infrastructure/model/uow.py` | 修改 | 增加 `self.app_grants = AppGrantRepository(self.session)` |
| `internal/domain/repository/apps_protocols.py` | 修改 | 新增 `AppGrantRepositoryProtocol`（`list_grantable` / `ids_grantable`）；`UnitOfWork` 中的 `app_grants` 用该 Protocol 标注，**不要**让 domain import 具体类 |
| `internal/application/grant_service.py` | 修改 | `_resource_repository` 按类型返回 `uow.app_grants` 或 `uow.resource_repo(...)` |

**目标代码**

```python
def _resource_repository(self, resource_type: str) -> Any:
    """按资源类型返回当前作用域的仓储。"""
    if resource_type not in RESOURCE_TYPES:
        raise ValidationError(f"资源类型必须是 {', '.join(RESOURCE_TYPES)} 之一")
    if resource_type == APP_RESOURCE_TYPE:
        return self._uow.app_grants
    return self._uow.resource_repo(resource_type)
```

**测试**（新增 `tests/test_grant_service_types.py`）
- 参数化 `("app","tool","skill","prompt","knowledge")`：`overview` 返回对应类型；`replace` 后 `list_grants` 可读回；`replace_batch` 均生效。
- 反例：对 skill 调用 `overview` 不返回 tool。

**验证**

```bash
cd backend && python -m pytest tests/test_grant_service_types.py tests/test_role_grants.py tests/test_user_grant_save.py -q
```

**DoD**：任意资源类型不再一律查 tool；`role_grant_service` 行为不变。

**依赖**：P0-2　**预估**：0.25

---

#### P0-4 应用实例状态与开通校验

**现状**
- `application_service.py:304-321` `subscribe` 校验 owner_type / is_listed_in_market / is_enabled，**未校验 `sale_mode`**。
- `application_repository.py:194-204` `get_application` 的 SELECT 列表**不含 `sale_mode`**，上游拿不到该字段。
- `application_repository.py:395-403` `get_instance` 无状态过滤；`:383-393` `subscribe` 硬编码 `'active'`、`'marketplace'`。

**改动清单**

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `internal/infrastructure/repository/apps/application_repository.py` | 修改 | ① `get_application` SELECT 增加 `sale_mode`；② 新增 `get_active_instance(tenant_id, application_id)`；③ 可选新增 `list_runtime_blocked_reason` |
| `internal/application/apps/application_service.py` | 修改 | `subscribe` 增加 `if int(app["sale_mode"]) != 2: raise ValidationError("该应用仅支持运营后台开通")`；`get_runtime_graph` / run / resume 改用 `get_active_instance`，非 active 抛 `ForbiddenError("应用授权已失效")` |

**目标签名**

```python
def get_active_instance(self, tenant_id: UUID, application_id: UUID) -> dict | None:
    """仅返回 status='active' 且未过期的实例。"""
    row = self._session.execute(
        text(
            "SELECT * FROM tenant_application_instance "
            "WHERE tenant_id = :tid AND application_id = :aid AND status = 'active' "
            "AND (expire_time IS NULL OR expire_time > now())"
        ),
        {"tid": tenant_id, "aid": application_id},
    ).first()
    return dict(row._mapping) if row else None
```

> `tenant_application_instance.expire_time` 已由 `migrations/versions/0040_application_auth.py:65` 创建，可直接使用（`status` 同理）。

**测试**（新增 `tests/test_application_subscribe.py`）

| 用例 | 期望 |
| --- | --- |
| `sale_mode=1` 调用 `subscribe` | 422 |
| `sale_mode=2` + 下架 / 禁用 | 422 |
| 实例 `revoked` / `expired` 后运行 | 403 |
| `sale_mode=2` 正常开通 | 201，instance active |

**验证**

```bash
cd backend && python -m pytest tests/test_application_subscribe.py tests/test_marketplace_workbench.py -q
```

**DoD**：市场不能绕过 `sale_mode`；失效实例不可运行。

**依赖**：无　**预估**：0.25

---

#### P0-5 修正应用实例状态 CHECK（已并入 P1-1）

**说明**：该改动只能通过迁移完成，故并入 `0055`，随 P1-1 一起交付，不新建迁移文件，避免与 P1-1 抢同一 revision。

**验收**：P1-1 的 `0055` upgrade/downgrade 往返通过，且 `tenant_application_instance` 可写入 `wait_effect`、`expired`。

---

#### P0-6 申请单鉴权与销售归属

**现状**
- `web/admin/routers/applies.py`：
  - `:87-90` `GET /pass-pending` **无任何鉴权依赖**；
  - `:93-99` `GET /sales-mine` 仅 `AdminAuthDep`（租户管理员也可调用）；
  - `:103-116` `claim`、`:129-156` `pass`、`:164-178` `reject` 均为 `AdminAuthDep`，**未限制平台作用域**；
  - `:181-197` 的 `ops/pending`、`ops/dashboard` 已用 `PlatformAdminDep`，可作范例。
- `internal/domain/auth/apply_service.py:102-123` `claim` 只调用 `update_apply_status`，注释声称更新 `sales_user_id`，**实际未写入**。
- `internal/infrastructure/repository/apps/auth_repository.py` 的 `update_apply_status` 不接收 `sales_user_id`。

**改动清单**

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `web/admin/routers/applies.py` | 修改 | `pass-pending`、`sales-mine`、`claim`、`pass`、`reject` 增加 `_principal: PlatformAdminDep`；租户侧 `submit` / `mine` 保持不动 |
| `internal/infrastructure/repository/apps/auth_repository.py` | 修改 | 新增 `claim_apply(apply_id, sales_user_id) -> bool`：`UPDATE application_apply SET status='HANDLING', sales_user_id=:uid, updated_at=now() WHERE id=:id AND status='SUBMITTED'`，返回 `rowcount == 1` |
| `internal/domain/auth/apply_service.py` | 修改 | `claim` 改调 `claim_apply`；失败抛 `ApplyError("申请单状态已变更，请刷新")`；删除误导注释 |
| `internal/domain/repository/apps_protocols.py` | 修改 | 若存在 `AuthRepositoryProtocol`，补 `claim_apply` 声明 |

**目标代码**

```python
def claim(self, apply_id: UUID, sales_user_id: UUID, operator_name: str) -> None:
    row = self._repo.get_apply(apply_id)
    if row is None:
        raise ApplyError("申请单不存在")
    if row["status"] != ApplyStatus.SUBMITTED.value:
        raise ApplyError(f"仅 SUBMITTED 状态可认领，当前状态: {row['status']}")
    if not self._repo.claim_apply(apply_id, sales_user_id):
        raise ApplyError("申请单状态已变更，请刷新后重试")
    self._repo.append_audit_log({...})  # 保持原审计，after 增加 sales_user_id
```

**测试**（新增 `tests/test_applies_auth.py`）

| 用例 | 期望 |
| --- | --- |
| 租户管理员调用 5 个运营端点 | 403 |
| 平台管理员 claim 成功 | 200，`GET /sales-mine` 可查到 |
| 非 SUBMITTED 状态 claim | 422 |
| 并发重复 claim | 第二次 422 |
| 租户访问 `/applies/mine` | 200（保持可用） |

**验证**

```bash
cd backend && python -m pytest tests/test_applies_auth.py -q
```

**DoD**：任意租户管理员不能操作他人申请；`sales_user_id` 落库可追溯。

**依赖**：无　**预估**：0.25

---

#### P0-7 P0 回归

- 跑 `python -m pytest -q` 全量；
- `ruff check internal web tests`、`mypy internal web` 不新增问题；
- 修复 P0 引入的失败用例，不允许用 skip 掩盖。
- **DoD**：基线用例数 ≥ 431 且全绿。

**预估**：0.25

---

### 3.2 P1 — 后端统一 Entitlement（4–6 人日）

> **执行状态（2026-11-03）**：P1-1…P1-11 全部完成。提交依次为 4e9eefe / c9d52c9 / de5079a / c5f7bcc / f79e610 / 704cc66 / 73a87fd / 6d149ce / ebe06ad / 9035df0 / 305a44c；最终回归 pytest 507、ruff 135、mypy 86（均低于基线 460/139/109 的允许水位且持续收敛）。

#### P1-1 迁移 0055：权益生命周期 + 实例状态 CHECK

| 项 | 内容 |
| --- | --- |
| 文件 | `backend/migrations/versions/0055_resource_grant_lifecycle.py` |
| 内容 | 见 §2.2，含 `tenant_application_instance` 的 `ck_instance_status` 重建（原 P0-5） |

**实现要点**
- `revision = "0055_resource_grant_lifecycle"`，`down_revision = "0054_grant_resource_type_unify"`。
- `upgrade()` 顺序：加列 → 加 CHECK → 加索引 → 重建 instance CHECK。
- `downgrade()` 逆序：删索引 → 删 CHECK → 删列 → 恢复 instance 旧 CHECK（旧值先 `grep -n "ck_instance_status" backend/migrations/versions/*.py` 确认）。
- downgrade 前若存在 `wait_effect/expired` 数据会失败，脚本应在 downgrade docstring 明确"需先清理"。

**测试**
- 迁移往返：`alembic upgrade head` → `downgrade -1` → `upgrade head`；
- 插入 `status='wait_effect'`、`'expired'` 各一条成功；`status='bogus'` 失败；
- `resource_grant` 新列默认值正确。

**验证**：`cd backend && alembic upgrade head && alembic downgrade -1 && alembic upgrade head`

**DoD**：两条表具备目标字段与 CHECK；往返迁移通过。
**依赖**：无（P0-5 并入）　**预估**：0.5

---

#### P1-2 迁移 0056：资源审核

| 项 | 内容 |
| --- | --- |
| 文件 | `backend/migrations/versions/0056_resource_review.py`（`revision="0056_resource_review"`，`down_revision="0055_resource_grant_lifecycle"`） |
| 内容 | 见 §2.3 |

**要点**：默认 `approved` 覆盖存量；`reviewed_by/reviewed_at/review_remark` 可空或默认空串；`created_by` 存量置 `NULL`，新建资源必须写入当前管理员 ID（供 P1-9 职责分离校验）。
**测试**：存量行 `review_status='approved'` 且 `created_by IS NULL`；新行可写 `pending`；非法值被拒。
**DoD**：迁移往返通过；`resource` 具备审核字段与 CHECK。
**预估**：0.25

---

#### P1-3 迁移 0057：整租户授权显式化

| 项 | 内容 |
| --- | --- |
| 文件 | `backend/migrations/versions/0057_grant_subject_type.py`（`revision="0057_grant_subject_type"`，`down_revision="0056_resource_review"`） |
| 内容 | 见 §2.4；单次迁移完成加列、回填、subject CHECK、索引重建（停机窗口内执行；`resource_type` CHECK 与孤儿清理已随 0054 交付） |

**配套 ORM 改动**（`internal/infrastructure/model/access.py`）

```python
class ResourceGrantModel(Base):
    ...
    subject_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="role", server_default="role"
    )
```

- `__table_args__`：删除 `ck_resource_grants_scope`，新增 `ck_resource_grants_subject`；三个旧索引不再声明，新增 `ux_resource_grants_tenant_subject`、`ux_resource_grants_role_subject`、`ux_resource_grants_platform_role_subject`（谓词与迁移完全一致）。`ck_resource_grants_type` 五类口径已随 P0-1 更新，无需再改。
- `ResourceGrant` 实体（`internal/domain/entity/access.py:97-108`）增加 `subject_type: str = "role"`，仓储 `_to_entity` 填充。

**测试**（新增 `tests/test_grant_subject_migration.py`）
- 迁移前插入 `role_id IS NULL` / `NOT NULL` 各一条 → 迁移后分别为 `tenant` / `role`，记录数不变；
- 同资源同租户两条 `tenant` → 唯一冲突；
- 同资源同租户同角色两条 `role` → 唯一冲突；
- `subject_type='tenant'` 且 `role_id` 非空 → CHECK 失败；
- downgrade 后列消失。

**验证**：`cd backend && python -m pytest tests/test_grant_subject_migration.py -q`

**特别注意**：`ux_resource_grants_platform_role_subject` 的谓词必须与 `postgres_resource_grant_repository.py:447-484` 的 `on_conflict_do_nothing(index_elements=..., index_where=...)` 完全一致，否则 upsert 报 "no unique or exclusion constraint matching"。

**DoD**：无数据丢失（D-1 孤儿已随 0054 清理）；两档唯一性与 CHECK 生效；downgrade 可逆。
**依赖**：P1-1、P1-2（同发布窗口）　**预估**：0.5

---

#### P1-4 迁移 0058：权限码种子

| 项 | 内容 |
| --- | --- |
| 文件 | `backend/migrations/versions/0058_entitlement_permissions.py`（`revision="0058_entitlement_permissions"`，`down_revision="0057_grant_subject_type"`） |
| 内容 | 见 §2.5 |

**配套代码**（`internal/domain/entity/permission.py`）：同步 `PERMISSION_CATALOG`、`PLATFORM_ONLY_CODES`、`TENANT_ONLY_CODES`、内置角色默认集合。
**内置角色授权写法**：参考 `0038_apps_menu_permissions.py`，按 `roles.code IN (...)` 与 `roles.tenant_id` 区分平台/租户，使用 `INSERT ... SELECT ... WHERE NOT EXISTS` 或 `ON CONFLICT DO NOTHING`。
**测试**：`tests/test_permission_catalog.py` 断言目录与迁移一致；平台 superadmin/admin 有 `menu:entitlements` 与 `button:resource:review`，viewer 没有；租户 superadmin/admin 有 `menu:role-access` 与 `button:resource:create`，viewer 没有。
**DoD**：`/admin/context` 对相应角色返回新菜单；越权 403。
**预估**：0.5

---

#### P1-5 EntitlementService（统一读写模型）

**目标**：屏蔽 `tenant_application_instance` 与 `resource_grant` 两套存储，应用与资源共用一套用例。

**新增/修改文件**

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `internal/domain/entity/entitlement.py` | 新增 | `EntitlementView`、`EntitlementItem`、`BatchPreview`、`BatchResult` 数据类；状态常量 |
| `internal/domain/repository/apps_protocols.py` | 修改 | 新增 `EntitlementRepositoryProtocol` |
| `internal/infrastructure/repository/apps/entitlement_repository.py` | 新增 | 同时读写两套表；只用 SQLAlchemy Core / `text`，不 import application |
| `internal/application/apps/entitlement_service.py` | 新增 | 用例编排 + 审计 |
| `web/deps/entitlement_services.py` | 新增 | `make_entitlement_service(uow) -> EntitlementService`、`make_grant_engine_service(uow) -> GrantService` |

> 服务放在 `application/apps/`（不是 `application/entitlement_service.py`），因为它与 apps 上下文共享 `uow`。组合根统一放 `web/deps/entitlement_services.py`，**不要**再往 `apps_services.py` 里加同名工厂，避免两处装配。

**Protocol 骨架**

```python
class EntitlementRepositoryProtocol(Protocol):
    def list_by_tenant(self, tenant_id: UUID, object_type: str | None,
                       status: str | None, keyword: str | None,
                       page: int, page_size: int) -> tuple[list[EntitlementView], int]: ...
    def list_tenants_by_object(self, object_type: str, object_id: UUID) -> list[dict]: ...
    def get(self, tenant_id: UUID, object_type: str, object_id: UUID) -> EntitlementView | None: ...
    def grant(self, tenant_id: UUID, item: EntitlementItem, granted_by: UUID | None) -> UUID: ...
    def revoke(self, tenant_id: UUID, object_type: str, object_id: UUID) -> bool: ...
    def purge(self, tenant_id: UUID, object_type: str, object_id: UUID) -> int: ...
    def affected_role_grants(self, tenant_id: UUID, object_type: str, object_id: UUID) -> list[dict]: ...
```

**服务骨架**

```python
class EntitlementService:
    def __init__(self, uow: UnitOfWork, repo: EntitlementRepositoryProtocol,
                 context: RequestContext) -> None: ...

    def list_by_tenant(self, tenant_id: UUID, **filters) -> Page[EntitlementView]: ...
    def list_tenants_by_object(self, object_type: str, object_id: UUID) -> list[dict]: ...
    def preview(self, tenant_id: UUID, mode: str, items: list[EntitlementItem]) -> BatchPreview: ...
    def apply_batch(self, tenant_id: UUID, mode: str, items: list[EntitlementItem],
                    *, reason: str, auth_type: str = "FORMAL",
                    start_time: datetime | None = None,
                    expire_time: datetime | None = None,
                    actor_id: UUID, actor_username: str,
                    ip: str | None = None, user_agent: str | None = None) -> BatchResult: ...
```

**关键语义（D-3）**
- `preview(mode="revoke")` 对每个 item 调 `affected_role_grants(...)`，在 `remove` 项上附带 `affected_role_grants` 数量与角色名列表；`grant` 模式不计算。
- `mode="revoke"` 默认软失效：置 `resource_grant.status='revoked'` 或 `tenant_application_instance.status='revoked'`，**不删** `resource_grants`；返回 `affected_role_grants`。
- `settings.entitlement_revoke_strict == True` 时，若 `affected_role_grants > 0` 抛 `ValidationError`（409 语义）。
- `mode="grant"`：已 `active` → `unchanged`；`revoked/expired` → 重新置 `active`（恢复），计入 `updated`。
- 状态映射：实例 `disabled` 视为不可用；`wait_effect` 视为未生效。
- **生效区间语义**：所有时间字段为 UTC；有效期区间按左闭右开 `[start_time, expire_time)` 判定。读侧（`EntitlementView.status`、`grant_filters.entitlement_active_exists`）必须同时按时间计算，不能只信持久化的 `status` 列，避免调度延迟窗口内出现"已过期但仍可用"。
- **状态流转**：`wait_effect → active`、`active → expired` 的持久化由 Celery 任务完成（复用 `infrastructure/tasks/auth_tasks.py`，P3-1）。**但 P1 必须保证读侧不依赖该任务**，否则 P1-7 直开的未来生效权益在 P3 之前永远不会生效。
- **缓存失效**：若未来启用 `domain/auth/cache.py::AuthCache`，写 `tenant_application_instance` 必须调用 `AuthService.invalidate(tenant_id, app_id)`（当前 `web/deps/apps_services.py:90` 为 `cache=None`，仍需在服务中保留失效调用，避免启用缓存后出现权益已回收但仍可用的窗口）。
- **批量事务语义**：`apply_batch` 在单个事务内执行，任一项校验失败整体回滚并返回失败项明细（不做部分成功）；`preview` 不改库。
- **弃用资源**：`resource.is_deprecated=True` 的资源不可新开通、不可新授权；已有权益保留至有效期结束，列表返回 `is_deprecated` 供前端置灰。`purge` 之前不自动清理。
- **租户校验**：所有写操作首先校验 `tenant_id` 存在且租户状态非停用，否则 404/422。
- `purge` 服务层先实现，接口由 P3-6 暴露。

**新增配置**（`internal/infrastructure/config/settings.py`）：`entitlement_revoke_strict: bool = False`、`entitlement_revoke_kill_running: bool = False`。

**测试**（新增 `tests/test_entitlement_service.py`）：五类对象查询；preview 的 add/remove/unchanged；grant→revoke→grant 恢复；软失效不删角色授权；严格模式拒绝。
**DoD**：router 不直接访问两套表；对外只返回 `EntitlementView`。
**依赖**：P1-1、P1-3　**预估**：1.0

---

#### P1-6 产品级 `/admin/entitlements` API

**新增文件**
- `web/admin/routers/entitlements.py`
- `web/admin/schemas/entitlement.py`
- `web/deps/entitlement_services.py`
- `web/admin/router.py` 挂载

**路由骨架**

```python
router = APIRouter(prefix="/entitlements", tags=["entitlements"],
                   dependencies=[Depends(require_platform_admin)])

@router.get("/tenants/{tenant_id}")
def list_tenant_entitlements(
    tenant_id: UUID, ...,
    _p: AdminPrincipal = Depends(require_permission("page:entitlements")),
): ...

@router.get("/objects/{object_type}/{object_id}/tenants")
def list_object_tenants(...): ...

@router.post("/preview")
def preview(...): ...

@router.post("/batch")
def batch(..., _p: AdminPrincipal = Depends(require_permission("button:entitlement:manage"))): ...
```

**payload 模型**

```python
class EntitlementItemIn(BaseModel):
    object_type: Literal["app", "tool", "skill", "prompt", "knowledge"]
    object_id: UUID

class BatchPayload(BaseModel):
    tenant_id: UUID
    mode: Literal["grant", "revoke"]
    items: list[EntitlementItemIn] = Field(min_length=1, max_length=100)
    reason: str = ""
    auth_type: Literal["FORMAL", "TRIAL", "GIFT"] = "FORMAL"
    start_time: datetime | None = None
    expire_time: datetime | None = None
```

**响应**：与 §4.1 一致；`revoke` 返回 `affected_role_grants`。
**审计**：`action="entitlement.batch"`（P1-11）。
**测试**（新增 `tests/test_entitlements_api.py`）：列表/反查/预览/批量/权限（租户 403、缺 button 权限 403、超过 100 项 422）。
**DoD**：平台管理员单页可完成五类开通；取消返回影响面且角色授权保留。
**依赖**：P1-4、P1-5　**预估**：1.0

---

#### P1-7 OPS 直开应用

**现状**：`internal/domain/auth/grant_service.py:40-53` `CreateGrantRequest` 必填 `auth_type / contract_no / quota_json / start_time`，`expire_time` 可空；`:67-146` `create_grant` 已处理 `OPS` 来源、`wait_effect`、审计与缓存失效。领域逻辑无需重写，只需暴露入口。

**改动清单**

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `web/admin/routers/entitlements.py` | 修改 | 新增 `POST /applications/{application_id}/grant` |
| `web/deps/entitlement_services.py` | 修改 | 定义 `make_grant_engine_service(uow) -> GrantService`（`internal.domain.auth`，内部构造 `AuthRepository` + `AuthService` + `GrantService`，与 `make_apply_service` 同构） |
| `internal/domain/auth/grant_service.py` | 不变 | 复用 `create_grant` |

**payload**

```python
class GrantApplicationPayload(BaseModel):
    tenant_id: UUID
    auth_type: Literal["FORMAL", "TRIAL", "GIFT"] = "FORMAL"
    contract_no: str = ""
    quota_json: dict[str, Any] = Field(default_factory=dict)
    start_time: datetime           # 必填
    expire_time: datetime | None = None
    remark: str = ""
```

**关键点**
- `start_time` 必填；否则 `create_grant` 无法判定 `active/wait_effect`。
- 重复开通由 `exists_active_grant` 抛 `GrantError`；接口层转 422（如需 409 在全局异常处理器补映射）。
- `auth_source` 固定 `OPS`；审计由 `create_grant` 内部写入，不重复写。

**测试**（新增 `tests/test_ops_grant_application.py`）：直开 → active + `auth_source=OPS`；重复 → 422；未来 `start_time` → `wait_effect`；租户访问 → 403。
**DoD**：不依赖市场/申请单即可开通。
**依赖**：P1-6　**预估**：0.5

---

#### P1-8 角色授权约束（写侧 + 候选侧）

**现状**
- `role_grant_service.py:349-356` `_validate_ids` 只校验 `ids_grantable`，**不校验租户是否已开通**、**不校验 review_status**。
- `resource_tool_repository.py:267-290` `_grantable` 对平台资源用 `platform_resource_visible(..., (), False)`；`grant_filters.platform_resource_visible` 只查复数表存在性，**不查单数 `resource_grant` 的 status/有效期**。
- `apps/resource_repository.py:188-` `list_available_for_tenant` 只判断存在性，不判断 status。

**改动清单**

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `internal/infrastructure/repository/grant_filters.py` | 修改 | 新增 `entitlement_active_exists(resource_type, resource_id_col, tenant_id)`：`EXISTS (SELECT 1 FROM resource_grant WHERE resource_id=... AND tenant_id=... AND status='active' AND (start_time IS NULL OR start_time <= now()) AND (expire_time IS NULL OR expire_time > now()))`（读写必须同一时间语义）；`platform_resource_visible` 改为 `grant_exists(...) AND entitlement_active_exists(...)` |
| `internal/infrastructure/repository/resource_tool_repository.py` | 修改 | `_grantable` 的平台分支与租户自建分支均叠加 `ResourceModel.review_status == 'approved'` 与 `ResourceModel.is_deprecated.is_(False)`（弃用资源不可新授权） |
| `internal/infrastructure/repository/apps/resource_repository.py` | 修改 | `resolve_for_tenant` / `list_available_for_tenant` 增加 `status='active'` 与有效期条件；返回 `review_status` |
| `internal/application/role_grant_service.py` | 修改 | `replace`/`add` 前校验：app → `get_active_instance`；资源 → 仓储 `ids_grantable` 已含 entitlement 条件；再校验 `review_status='approved'` |
| `internal/infrastructure/repository/apps/app_grant_repository.py` | 修改 | 应用走 `tenant_application_instance`，**不适用** review_status；仅补 `is_tenant_wide` 标记（与 P1-10 联动）。应用的可申请性由 `is_listed_in_market`/`sale_mode` 控制，不在此处重复 |

**错误语义**
- 未开通：`ValidationError("资源未对当前租户开通")` → 422 `RESOURCE_NOT_ENTITLED`
- 未审核：`ValidationError("资源尚未通过审核")` → 422 `RESOURCE_NOT_APPROVED`
- 已弃用：`ValidationError("资源已弃用，不可新授权")` → 422 `RESOURCE_DEPRECATED`

**测试**（新增 `tests/test_role_grant_constraints.py`）：未开通 422；pending 422；approved+entitled 200；entitlement revoked 422；恢复开通后 200；`is_deprecated=True` 422 且已有授权仍可见。
**DoD**：越权授权被拒，提示明确。
**依赖**：P1-2、P1-3、P1-5　**预估**：0.75

---

#### P1-9 资源审核 API + 租户建资源

**现状**
- `web/admin/routers/resources.py`：`admin_router` 全局 `require_platform_admin`；`tenant_router`（`:26`）**只有** `GET /my-resources`（`:155-165`），租户无法创建资源。
- `apps/resource_service.py:22-40` `create_resource` 无审核状态；`AppResourceRepository.create_resource` 不写 `review_status`。

**改动清单**

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `internal/infrastructure/repository/apps/resource_repository.py` | 修改 | `create_resource` 写入 `review_status`（platform→approved、tenant→pending）与 `created_by`；`list_resources` 支持 `review_status` 过滤；新增 `review_resource(resource_id, decision, reviewer_id, remark)`；审核前校验 `created_by != reviewer_id`（职责分离，`created_by IS NULL` 的历史资源放行） |
| `internal/application/apps/resource_service.py` | 修改 | 透传 review 默认值；新增 `review_resource(...)`；`list_resources(review_status=...)` |
| `web/admin/routers/resources.py` | 修改 | ① `POST /admin/resources/{id}/review`，依赖 `require_permission("button:resource:review")`；② `GET /admin/resources?review_status=pending`（平台）；③ `tenant_router` 新增 `POST ""`，依赖 `require_permission("button:resource:create")`，强制 `owner_type='tenant'`、`owner_id=context.tenant_id`；④ `GET /my-resources` 返回 `review_status/review_remark` |

**审核 payload**

```python
class ReviewPayload(BaseModel):
    decision: Literal["approve", "reject"]
    remark: str = ""
```

**审计**：`action="resource.reviewed"`，detail 含 before/after、remark、审核人。
**测试**（新增 `tests/test_resource_review.py`）：平台创建默认 approved；租户创建默认 pending；pending 不可授权；approve 后可授权；reject 保持不可授权；无 `button:resource:review` → 403；租户调用审核 → 403；创建人审核自己的资源 → 403 `SELF_REVIEW_FORBIDDEN`。
**DoD**：审核闭环可用；租户可自助创建并提交审核。
**依赖**：P1-2、P1-4　**预估**：0.75

---

#### P1-10 读侧 subject_type 适配与结构符合性

**现状（读侧仍按 `role_id IS NULL` 判定）**
- `grant_filters.py:13-22` `_role_condition`。
- `postgres_resource_grant_repository.py`：`list_effective_granted_resource_ids`（`:241-255`）、`count_effective_granted`（`:257-269`）、`list_tenant_wide_resource_ids`（`:271-280`）、`has_tenant_wide`（`:282-294`）。
- `add_for_role`（`:341-376`）`index_where=role_id.is_not(None)`；`add_for_platform_role`（`:447-484`）同理。
- `application/grant_service.py:341-355` `_merge_roles` 用 `any(grant.role_id is None ...)`；`:313-339` `_resolve_batch_scope` 用 `None` 表示整租户。
- `role_grant_service.py:322-336` `_demote_tenant_wide` 会拆成其余角色。

**改动清单**

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `grant_filters.py` | 修改 | `_role_condition`：`apply_role_filter=False` → `true()`；否则 `subject_type='tenant' OR (subject_type='role' AND role_id IN role_ids)`；空 `role_ids` 只命中 tenant 档（保持 fail-closed） |
| `postgres_resource_grant_repository.py` | 修改 | 上述 4 个方法改判 `subject_type`；`replace_for_tenant(role_ids=None)` 写 `'tenant'`，否则写 `'role'`；`replace_for_resource` / `replace_for_role` / `add_for_role` / `replace_for_platform_role` / `add_for_platform_role` 显式写 `subject_type`；两处 `on_conflict` 的 `index_where` 改为 `subject_type == "role"` 对应谓词 |
| `application/grant_service.py` | 修改 | `_merge_roles` 改判 `subject_type`；`_grant_views` / `_after_view` 增加 `subject_type` |
| `role_grant_service.py` | 修改 | `_demote_tenant_wide`：删除 tenant 档 + 为其余**启用中**角色写 role 档；无其余角色则直接删除 |
| `internal/domain/repository/protocols.py` | 修改 | 新增 `set_tenant_wide(...)` / `unset_tenant_wide(...)` 声明 |
| `tests/test_apps_protocols_conformance.py` | 修改 | 追加新方法的运行时结构校验 |

**测试**（新增 `tests/test_role_grant_subject.py`）
- tenant 档对任意 `role_ids` 可见（含空角色）；role 档只对指定角色可见；
- `apply_role_filter=False` 时两档均可见；
- `list_tenant_wide_resource_ids` / `has_tenant_wide` 只认 tenant 档；
- 迁移后新建角色自动可见 tenant 档资源；
- `add_for_role` 对已 tenant 档资源返回 0。

**验证**

```bash
cd backend && python -m pytest tests/test_role_grant_subject.py tests/test_apps_protocols_conformance.py tests/test_role_grants.py tests/test_grant_service_types.py -q
cd backend && grep -rn "role_id.is_(None)\|role_id IS NULL" internal web | grep -v migrations   # 目标为空
```

**DoD**：运行时代码不再用 `role_id IS NULL` 表达全员；列表、计数、合并、去重四处一致。
**依赖**：P1-3、P1-8　**预估**：0.5

---

#### P1-11 统一审计

**做法**：在 `EntitlementService.apply_batch` 内调用 `record_audit`（`internal/application/audit.py`）：

```python
record_audit(
    self._uow,
    action="entitlement.batch",
    actor_id=actor_id,
    actor_username=actor_username,
    resource_type="entitlement",
    resource_id=str(tenant_id),
    ip=ip, user_agent=user_agent,
    detail={
        "tenant_id": tenant_id, "mode": mode,
        "items": [item.to_dict() for item in items],
        "add": ..., "remove": ..., "unchanged": ...,
        "reason": reason, "before": before, "after": after,
    },
    tenant_id=tenant_id,
)
```

**测试**（新增 `tests/test_entitlement_audit.py`）：一次 grant + 一次 revoke 后，审计可还原全部字段。
**DoD**：审计可还原一次批量操作。
**依赖**：P1-5　**预估**：0.25

---

### 3.3 P2 — 前端双入口（4–6 人日）

> 前端基线：React 18 + Ant Design 5 + Semi UI，包管理 `pnpm`。以下路径均已核实存在。

#### P2-1 产品级「租户开通」页

| 项 | 内容 |
| --- | --- |
| 新增页面 | `frontend/admin/src/pages/entitlements/TenantEntitlementsPage.tsx`、`EntitlementTable.tsx`、`BatchPreviewModal.tsx` |
| 新增 API | `frontend/admin/src/api/entitlements.ts`（`listTenantEntitlements` / `listObjectTenants` / `previewBatch` / `applyBatch` / `grantApplication`），复用 `api/client.ts` |
| 页面结构 | 顶部租户选择器（搜索 + 最近访问，数据来自 `api/tenant.ts`）；左侧类型导航（全部/app/tool/skill/prompt/knowledge + 计数）；右侧表格（名称/类型/状态/有效期/来源/操作）；多选 + 批量开通/取消；差异预览弹窗；状态/来源筛选 |
| 交互细节 | 取消开通弹窗必须展示 `affected_role_grants` 与角色名，文案："取消后相关角色授权将失效，恢复开通后自动恢复；如需彻底清除请使用下架/清除"；严格模式 409 提示"存在角色授权，请先解除" |
| 测试 | `frontend/admin/src/pages/entitlements/__tests__/`：切换租户、筛选、批量预览、确认、空状态；Playwright 场景见 §5.3 |
| DoD | 运营无需跳转即可完成五类对象开通；取消展示影响面 |
| 依赖 | P1-6　**预估**：1.5 |

#### P2-2 租户级「角色授权」页

| 项 | 内容 |
| --- | --- |
| 新增页面 | `frontend/admin/src/pages/roleAccess/RoleAccessPage.tsx`、`RoleAccessMatrix.tsx` |
| 复用 API | `frontend/admin/src/api/access.ts`（角色与授权接口，已存在；**不存在 `api/roles.ts`**） |
| 页面结构 | 角色选择器；类型导航 + 计数；候选表格仅展示"已开通 + 已审核"；未开通/未审核行置灰并 tooltip 说明；批量授权/取消；"功能权限"与"资源授权"分 Tab |
| tenant 档 | 对 `is_tenant_wide` 资源显示「全员可见」标签；提供"设为全员可见 / 取消全员可见"（P1-10 新增端点）；取消时提示"将降级为按角色授权，仅保留其余角色" |
| 测试 | 置灰提示、批量授权、取消确认、全员可见切换 |
| DoD | 未开通对象不可授权，提示清晰 |
| 依赖 | P1-8、P1-10　**预估**：1.5 |

#### P2-3 菜单 / 路由 / 权限

| 项 | 内容 |
| --- | --- |
| 修改文件 | `frontend/admin/src/layouts/AdminLayout.tsx`（`MENU_META` / `MENU_GROUPS`）、`frontend/admin/src/router.tsx` |
| 具体改动 | `MENU_META` 增加 `entitlements`、`role-access`；路由用 `RequirePermission permission="page:entitlements" platformOnly` 与 `permission="page:role-access" tenantOnly`（组件 `frontend/admin/src/auth/RequirePermission.tsx` 已支持 `platformOnly`/`tenantOnly`） |
| 注意 | 菜单实际由后端 `/admin/context` 驱动，前端 `MENU_META` 只负责图标/分组元信息，需与 P1-4 权限码一致 |
| 测试 | 平台 / 租户角色登录后的菜单断言 |
| DoD | 平台只见租户开通，租户只见角色授权；越界访问 403 |
| 依赖 | P1-4、P2-1、P2-2　**预估**：0.5 |

#### P2-4 资源页双视角 + 审核

| 项 | 内容 |
| --- | --- |
| 修改文件 | `frontend/admin/src/pages/apps/ResourcesPage.tsx` |
| 复用 API | `frontend/admin/src/api/apps.ts`（`listResources` / `grantResource` / `revokeResourceGrant` / `listResourceGrants` 已在此，**不存在 `api/resources.ts`**）；资源审核接口新增到 `api/apps.ts` |
| 具体改动 | ① 去掉硬编码 `owner_type: 'platform'`，平台/租户按上下文决定；② 平台视角增加"审核状态"列与审核/拒绝按钮（仅 `button:resource:review` 可见）；③ 租户视角调用 `/admin/my-resources`，展示已开通 + 自建；④ 自建资源显示审核状态与"提交审核"（重新提交置 pending） |
| 测试 | 审核通过/拒绝；租户视角可见性；无权限不显示按钮 |
| DoD | 资源页不再只有平台视角 |
| 依赖 | P1-9　**预估**：1.0 |

#### P2-5 反查 Tab

| 项 | 内容 |
| --- | --- |
| 修改文件 | `frontend/admin/src/pages/apps/AppListPage.tsx`、`frontend/admin/src/pages/apps/ResourcesPage.tsx` |
| 具体改动 | 详情抽屉增加"已开通租户"Tab，调用 `GET /admin/entitlements/objects/{object_type}/{object_id}/tenants`，支持跳转到该租户开通页 |
| 测试 | 双向跳转定位正确 |
| DoD | 从资源可查到租户，从租户可查到资源 |
| 依赖 | P1-6　**预估**：0.5 |

#### P2-6 申请审批工作台（应用）

| 项 | 内容 |
| --- | --- |
| 新增页面 | `frontend/admin/src/pages/entitlements/ApplyWorkbench.tsx` |
| 新增 API | 申请审批方法新增到 `frontend/admin/src/api/entitlements.ts`（已确认 `api/apps.ts` 未封装 `/applies`，**不存在 `api/applies.ts`**） |
| 具体改动 | 待审批列表（`GET /applies/ops/pending`）、详情（`ops/dashboard`）、通过（填 grant 参数 → `POST /applies/{id}/pass`）、拒绝（填原因 → `POST /applies/{id}/reject`） |
| 测试 | 通过后生成权益；拒绝后状态正确 |
| DoD | 审批闭环 |
| 依赖 | P1-7、P0-6　**预估**：0.75 |

#### P2-7 前端回归

```bash
cd frontend/admin && pnpm typecheck && pnpm lint && pnpm test && pnpm e2e
```

- 补双入口用例；确认现有页面无回归。
- **DoD**：全绿。　**预估**：0.25

---

### 3.4 P3 — 运营增强（7–11 人日，按需）

| ID | 任务 | 落地文件 | 要点 | 预估 |
| --- | --- | --- | --- | --- |
| P3-1 | 权益生命周期定时任务 | `internal/infrastructure/tasks/auth_tasks.py`；`internal/domain/auth/grant_service.py:180-238` 已有 `process_wait_effective/process_expired` | 资源权益复用同一调度：`resource_grant` 的 `wait_effect→active`、`active→expired`；需在仓储补 `list_wait_effective` / `list_expired` | 0.75 |
| P3-2 | 到期提醒 | 新增 `internal/application/entitlement_notify.py` + 调度任务 | 扫描 7/3/1 天内到期；去重键 `(tenant_id, object_type, object_id, days)` | 0.75 |
| P3-3 | 套餐模板 | 新增迁移 `0059_entitlement_plan.py`、`domain/entity/entitlement_plan.py`、`EntitlementService.apply_plan` | 模板 = 条目集合 + 默认 auth_type/期限；开通复用 `apply_batch` | 1.0 |
| P3-4 | 表重命名 | 迁移把 `resource_grant` 改为 `tenant_resource_entitlement` | 同步 `apps/resource_repository.py` 原生 SQL、ORM、Protocol；建议保留兼容视图一个周期 | 0.5 |
| P3-5 | 类型注册表 | 新增 `resource_type_catalog` 表 + 迁移 | CHECK 改外键或应用校验，新增类型免改迁移 | 1.0 |
| P3-6 | 权益清除（purge） | `EntitlementService.purge` + `POST /admin/entitlements/purge` | 仅平台 superadmin；二次确认；先写审计快照再物理删除 `resource_grant` 与关联 `resource_grants`；返回 `audit_id` | 0.75 |
| P3-7 | 取消开通通知 | 复用 P3-2 通知管道 | 撤销/恢复时通知租户管理员 | 0.5 |
| P3-8 | 幂等与并发控制 | `entitlement_request_log` 表（`request_id` 唯一）+ `version` 列；`POST /batch` 读取 `Idempotency-Key` | 重放返回首次结果；并发写冲突返回 409 `VERSION_CONFLICT` | 1.0 |
| P3-9 | 对账作业 | 新增 `internal/infrastructure/tasks/entitlement_reconcile.py` | 扫描"有 `resource_grants` 但无 active entitlement"与"权益指向已删除对象"，输出告警与清理建议 | 0.75 |
| P3-10 | 配额执行点 | `EntitlementService.check_quota` + 调用方（运行入口/席位分配） | 明确 `quota_json` 语义（席位/次数），超限返回 422 `QUOTA_EXCEEDED` | 1.25 |
| P3-11 | 宽限期 | `settings.entitlement_grace_days` + `expired` 后只读窗口 | 到期后 N 天内允许恢复且保留配置；超期转 `revoked` | 0.5 |

---

## 4. API 契约

### 4.1 产品级 `/admin/entitlements`

**GET `/admin/entitlements/tenants/{tenant_id}`**

```json
// query: object_type?, status?, keyword?, page=1, page_size=20
{
  "items": [
    {
      "object_type": "app",
      "object_id": "uuid",
      "name": "报销审批流",
      "status": "active",
      "auth_source": "OPS",
      "auth_type": "FORMAL",
      "start_time": "2026-11-01T00:00:00Z",
      "expire_time": null,
      "quota": {},
      "remark": "",
      "granted_at": "2026-11-01T00:00:00Z"
    }
  ],
  "total": 1, "page": 1, "page_size": 20
}
```

**GET `/admin/entitlements/objects/{object_type}/{object_id}/tenants`**

```json
// query: status?, keyword?, page=1, page_size=20（上限 100；租户量大时必须分页）
{ "items": [{ "tenant_id": "uuid", "tenant_name": "示例租户", "status": "active", "auth_source": "OPS" }],
  "total": 1, "page": 1, "page_size": 20 }
```

**POST `/admin/entitlements/preview`**（dry-run）

```json
// req
{ "tenant_id": "uuid", "mode": "grant", "items": [{"object_type": "tool", "object_id": "uuid"}] }
// resp
{ "add": [{"object_type":"tool","object_id":"uuid","name":"搜索"}], "remove": [], "unchanged": [] }
```

**POST `/admin/entitlements/batch`**

```json
// req
{
  "tenant_id": "uuid",
  "mode": "grant",              // grant | revoke
  "items": [{"object_type": "tool", "object_id": "uuid"}],
  "reason": "合同 2026-1103 开通",
  "auth_type": "FORMAL",        // grant 时可选
  "start_time": null,
  "expire_time": null
}
// resp
// revoke 时 affected_role_grants 表示软失效影响的角色授权数（D-3）
{ "updated": 1, "failed": [], "affected_role_grants": 3 }
```

**批次契约**：`items` 上限 200，超出 400；整个批次在单事务内执行，任一项失败整体回滚，`failed` 仅在 `preview` 等只读场景返回明细；`tenant_id` 必须存在且未停用。幂等键（`Idempotency-Key`）本轮不实现，见 §7.3。

**POST `/admin/entitlements/applications/{application_id}/grant`**

```json
{ "tenant_id": "uuid", "auth_type": "FORMAL", "start_time": null, "expire_time": null, "remark": "" }
```

**POST `/admin/entitlements/purge`**（D-3b，仅退租/合规；P3 实现）

```json
// req
{ "tenant_id": "uuid", "items": [{"object_type": "tool", "object_id": "uuid"}], "confirm": true, "reason": "租户退租 2026-1103" }
// resp：物理删除 entitlement 与关联角色授权，返回删除条数与审计快照 ID
{ "purged": 1, "removed_role_grants": 3, "audit_id": "uuid" }
```

### 4.2 租户级（复用现有 roles 路由，增加约束）

| 方法/路径 | 变化 |
| --- | --- |
| `GET /admin/roles/{role_id}/grants/summary` | 计数只统计已开通+已审核；tenant 档计入每个角色 |
| `GET /admin/roles/{role_id}/grants?resource_type=` | 候选过滤；返回 `entitled`/`approved`/`is_tenant_wide` 标记 |
| `PUT/POST/DELETE /admin/roles/{role_id}/grants/{resource_type}` | 写入前校验 entitlement + review；写 `subject_type='role'` |
| `PUT /admin/roles/{role_id}/grants/{resource_type}/tenant-wide` | 把资源设为全员可见（`subject_type='tenant'`）；需 `button:role-access:manage` |
| `DELETE /admin/roles/{role_id}/grants/{resource_type}/{resource_id}/tenant-wide` | 取消全员可见并按需降级为其余角色授权 |

**错误码：**

| HTTP | code | 场景 |
| --- | --- | --- |
| 422 | `RESOURCE_NOT_ENTITLED` | 资源未对租户开通 |
| 422 | `RESOURCE_NOT_APPROVED` | 租户自建资源未审核通过 |
| 409 | `ENTITLEMENT_EXISTS` | 重复开通 |
| 200 | — | 取消开通默认软失效（D-3），只置 `revoked` 并返回 `affected_role_grants`；不返回 409 |
| 409 | `ENTITLEMENT_IN_USE` | 仅严格模式（配置开启）下使用；需在全局异常处理器把该业务错误映射为 409，否则当前返回 422 |
| 403 | `SCOPE_FORBIDDEN` | 跨作用域操作 |

### 4.3 审核

| 方法/路径 | 说明 |
| --- | --- |
| `GET /admin/resources?review_status=pending` | 平台审核队列 |
| `POST /admin/resources/{id}/review` | `{decision: "approve"|"reject", remark}` |
| `GET /admin/my-resources` | 租户侧返回 `review_status/review_remark` |

审核错误：`403 SELF_REVIEW_FORBIDDEN`（创建人不得审核自己创建的资源）、`403`（无 `button:resource:review`）、`404`（资源不存在）、`422`（`decision` 非法）。

---

## 5. 测试计划

### 5.1 单元测试（新增）

| 文件 | 覆盖 | 对应任务 |
| --- | --- | --- |
| `test_resource_types.py` | 五类常量、单一来源、无遗留类型 | P0-1 |
| `test_resource_repository_types.py` | 四类资源仓储隔离 | P0-2 |
| `test_grant_service_types.py` | app/资源仓储路由 | P0-3 |
| `test_application_subscribe.py` | sale_mode、失效实例 | P0-4 |
| `test_applies_auth.py` | 运营端点 403、销售归属、重复 claim | P0-6 |
| `test_grant_subject_migration.py` | 0057 回填、两档唯一性、CHECK、旧索引删除、downgrade | P1-3 |
| `test_entitlement_service.py` | 统一视图、预览、批量原子回滚、软失效/恢复、严格模式、读时有效期计算、弃用资源、缓存失效调用 | P1-5 |
| `test_entitlements_api.py` | 列表/反查/预览/批量/权限 | P1-6 |
| `test_ops_grant_application.py` | OPS 直开、wait_effect、重复开通 | P1-7 |
| `test_role_grant_constraints.py` | 未开通/未审核拒绝 | P1-8 |
| `test_resource_review.py` | 创建默认状态、审核流转、租户建资源 | P1-9 |
| `test_role_grant_subject.py` | tenant/role 两档读侧一致性 | P1-10 |
| `test_entitlement_audit.py` | 批量审计可还原 | P1-11 |
| `test_permission_catalog.py`（扩充） | 权限目录与迁移一致、内置角色默认权限 | P1-4 |

**测试夹具**：统一复用 `backend/tests/conftest.py` 的 `ADMIN_APP` / `USER_APP` 与 `backend/tests/helpers.py`（若存在 `create_tenant` / `tenant_admin_client` / `grant_resource` 等辅助函数，优先复用，不要重复造）。新增测试文件不得改动 conftest 的库重建策略。

### 5.2 集成测试

| 场景 | 断言 |
| --- | --- |
| 平台直开应用 → 租户角色授权 → 用户可见 | 全链路 200；用户端列表出现 |
| 平台开通工具 → 租户角色授权 | 候选可见；授权成功 |
| 未开通工具 → 租户角色授权 | 422 `RESOURCE_NOT_ENTITLED` |
| 租户自建资源 pending → 角色授权 | 422 `RESOURCE_NOT_APPROVED` |
| 审核通过 → 角色授权 | 200 |
| 市场申请 → 平台审批 → 权益生效 | instance active + 来源 MARKET_APPLY |
| 取消开通时仍有角色授权（默认软失效） | 200；entitlement=revoked；`resource_grants` 保留；`affected_role_grants` 正确 |
| 取消开通时仍有角色授权（严格模式） | 409 `ENTITLEMENT_IN_USE`（未做全局映射时为 422） |
| 取消开通 → 重新开通 | 角色授权自动恢复可见，无需重新配置 |
| purge 清除 | entitlement 与角色授权物理删除；审计快照可还原 |
| 整租户授权迁移 | 迁移后原 `role_id IS NULL` 记录变为 `subject_type='tenant'`；记录数不变；新建角色自动可见 |
| 停机窗口发布 | 停写后迁移 → 发代码 → 恢复写；迁移期间无旧写入路径，0057 的 CHECK 不会误拦 |
| 弃用资源 | 不可新开通/新授权（422）；已授权用户仍可见至有效期结束 |
| 批量原子性 | 批次中一项未开通 → 整体回滚，无部分写入 |
| 职责分离 | 创建人审核自己的资源 → 403 `SELF_REVIEW_FORBIDDEN` |

### 5.3 前端 E2E（Playwright）

1. 平台登录 → 租户开通 → 选择租户 → 批量开通 → 预览 → 确认 → 列表出现。
2. 平台登录 → 资源审核 → 通过租户自建资源。
3. 租户登录 → 角色授权 → 未开通项置灰 → 已开通项批量授权 → 保存。
4. 用户端登录 → 对应角色用户可见应用/资源。
5. 跨作用域访问：租户访问 `/entitlements` → 403；平台访问 `/role-access` → 403。

### 5.4 回归基线

```bash
cd backend
python -m pytest -q                     # 基线 ≥ 460 passed（P0 完成后）
ruff check internal web tests
mypy internal web
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

- 现有 pytest 全量（P0 完成后 460 个）必须全绿。
- ruff / mypy 不新增错误。
- DDD 结构符合性测试（`tests/test_apps_protocols_conformance.py`）通过。
- 迁移在空库 + 存量库各跑一次 upgrade/downgrade；0057 还需在**含 `role_id IS NULL` 记录**的库上验证回填。

---

## 6. 发布与回滚

### 6.1 发布顺序

```text
1. 通知停写（维护窗口开始）
2. 备份 resource_grants / resource_grant / tenant_application_instance
3. 执行 0055 → 0056 → 0057（单次迁移，含 CHECK 与索引重建）
4. 发布 P0 + P1 后端代码
5. 恢复写流量
6. 执行 0058 权限码
7. 发布 P2 前端
8. 验证 → 打开前端入口
```

> 本计划按**停机维护窗口**发布：0057 含 `ck_resource_grants_subject` 且删除旧索引，与旧代码不兼容，故必须在停写期间与代码同步切换。窗口长度取决于 0057 的回填耗时（`resource_grants` 数据量 × 索引重建），需在预发环境实测。
> 若未来改为无停机滚动发布，须拆为 expand → 发代码 → contract 两次迁移（见 §2.4），窗口顺序不再适用。

### 6.2 灰度建议

- P1 后端在维护窗口内与迁移同步上线，不暴露菜单；窗口结束后通过接口测试验证。
- P2 前端入口可用配置开关 `FEATURE_ENTITLEMENT_CENTER` 控制，先对内部租户开放。
- 旧入口（`/resources/{id}/grants`、`/grants/batch`）保留一个版本周期，标记废弃，P3 删除。

### 6.3 回滚

| 场景 | 操作 |
| --- | --- |
| P2 前端异常 | 关闭开关，回退前端版本；后端 API 保留 |
| P1 代码异常 | 回滚后端；迁移 0055/0056 可 downgrade |
| 0057 数据异常 | 可 downgrade（删除 `subject_type`、恢复旧索引、去掉 CHECK）；D-1 孤儿属 0054 删除，如需恢复用 0054 发布前备份 |
| 0058 权限码异常 | 删除新增权限码与 role_permissions 关联（幂等脚本） |

---

## 7. 风险与待确认

### 7.1 风险

| # | 风险 | 等级 | 缓解 |
| --- | --- | --- | --- |
| R1 | 存量 `agent/component` 授权无对应对象（0037 已 DROP 旧表且未迁移授权，0028 未迁入 application） | 高 | 迁移前盘点；确认后删除；保留备份 |
| R2 | `subject_type` 判定分支遗漏，导致 tenant 档资源在部分查询（列表/运行入口/计数）不可见 | 中 | 统一收敛到仓储方法；新增 `test_role_grant_subject.py` 覆盖全部读取路径；grep 禁止直接拼 `role_id IS NULL` |
| R3 | 前端/旧接口仍按 `role_id IS NULL` 语义处理，与 `subject_type` 双写不一致 | 中 | P0-3/P1-10 一次性改造全部读写路径；旧接口保留期间加兼容层并记日志 |
| R4 | 两套存储不一致（instance vs grant） | 中 | 统一走 `EntitlementService`；禁止业务层直连两套表 |
| R5 | 批量取消导致角色授权悬挂 | 中 | D-3 已确认软失效：entitlement 置 `revoked`，角色授权保留并自动失效；恢复开通后自动恢复 |
| R6 | 前端一次上线认知负担 | 低 | 开关灰度；保留旧入口一个周期 |
| R7 | 迁移不可逆 | 高 | 强制备份；迁移脚本 dry-run 模式 |
| R8 | 0057 与旧代码不兼容（旧代码插入 `role_id NULL` 会触发新 CHECK；`on_conflict` 依赖旧索引） | 高 | 采用停机维护窗口，停写后迁移+发代码同步切换（§6.1）；如需滚动发布须改 expand/contract（§2.4） |
| R9 | 状态流转依赖调度：P1 直开/批量开通允许 `start_time`，但 `resource_grant` 的 `wait_effect→active` 任务在 P3 | 高 | 读侧按 `[start_time, expire_time)` 实时计算，不依赖持久化 status；调度只做展示收敛 |
| R10 | 权益直写 `tenant_application_instance` 绕过 `domain/auth/grant_service.py`，若启用 AuthCache 则回收不生效 | 中 | EntitlementService 写后调用 `AuthService.invalidate`；补缓存启用用例测试 |
| R11 | `resource` 无 `created_by` 时无法做职责分离（自审） | 中 | 0056 增加 `created_by`；P1-9 校验；存量 NULL 放行 |
| R12 | 弃用资源（`is_deprecated`）与权益/授权关系未定义，可能出现对已弃用对象继续开通 | 中 | P1-5/P1-8 明确：不可新开通/新授权，已有授权保留 |
| R13 | 批量写接口无幂等键，重试会重复写入或报唯一冲突 | 中 | 本轮以唯一索引兜底（重复即 unchanged）；幂等键列入 P3 |
| R14 | 审计表支持清空（`button:audit:clear`），与合规保留要求冲突 | 中 | 生产环境限制清空权限；保留期与归档策略单独评审 |

### 7.2 决策记录（P1 前，已收敛）

以下 6 项会改变迁移脚本与业务语义，逐项给出事实、选项、判断依据与结论；结论日期均为 2026-11-03。

#### D-1 存量 `agent/component` 授权如何处理

**事实**：0037 迁移直接 `DROP TABLE agents/components/... CASCADE`，文件头注明"历史数据不保留"；0028 创建 `application` 时没有 `INSERT FROM agents`。因此 `resource_grants` 中 `resource_type IN ('agent','component')` 的 `resource_id` 全部指向已不存在的对象，属于孤儿记录；新 CHECK 也不允许这两类值。

**选项**：

| 选项 | 做法 | 优点 | 缺点 |
| --- | --- | --- | --- |
| A 删除（推荐） | 备份后 `DELETE` | 干净，与 0037 语义一致 | 审计链断裂 |
| B 映射到 application | 人工建立 agents.id → application.id | 保留授权 | 旧数据已删，无法自动映射，成本高且不可靠 |
| C 归档到历史表 | 迁移到 `resource_grants_legacy` | 保留审计 | 多一张表与维护成本 |
| D 放宽 CHECK 保留 | 允许 `agent/component` | 不改数据 | 运行时仍无对象，只是延后问题 |

**盘点 SQL**：

```sql
SELECT resource_type, count(*) FROM resource_grants
WHERE resource_type IN ('agent','component') GROUP BY 1;

-- 预期全部为孤儿：结果应等于上一条的总数
SELECT count(*) FROM resource_grants rg
WHERE rg.resource_type = 'agent'
  AND NOT EXISTS (SELECT 1 FROM application a WHERE a.id = rg.resource_id);
```

**判断依据**：
- 第一条为 0 → 无需处理，直接删 CHECK。
- 第二条等于总数 → 全部孤儿，删除。
- 存在可匹配记录 → 单独人工处理，不要批量删。

**结论（2026-11-03）**：选择 A。已由 `0054_grant_resource_type_unify`（P0-1 交付）删除 `resource_type IN ('agent','component')` 的孤儿记录；删除前已要求备份 `resource_grants`。

> 依据：0037 已 DROP 旧表且未迁移授权，0028 也未迁入 `application`，这些记录无对应对象，保留只会阻塞新 CHECK。

#### D-2 整租户授权的去向

**事实**：`role_id IS NULL` 的语义是"该资源对租户内所有角色可见，包括未来新增角色"，通常用于公共工具/知识库的全员可用。

**盘点 SQL**：

```sql
-- 整租户授权总量与涉及租户
SELECT tenant_id, count(*) AS tenant_wide_rows
FROM resource_grants
WHERE role_id IS NULL
GROUP BY tenant_id;

-- 若走拆分路线：预计记录数（本次不采纳，仅作对照）
SELECT sum(x.active_roles) AS estimated_rows
FROM (
  SELECT rg.tenant_id, count(r.id) AS active_roles
  FROM resource_grants rg
  JOIN roles r ON r.tenant_id = rg.tenant_id AND r.is_active
  WHERE rg.role_id IS NULL
  GROUP BY rg.tenant_id
) x;
```

**行业分析（2026-11-03 补充）**：

- "全员/整个租户可见"本身是行业通用授权范围：钉钉/飞书/企业微信的应用可见范围支持"全员/部门/人员"；Microsoft Entra ID 的 Enterprise App 可设为 All Users（Assignment required = No）；Google Workspace 可按 OU 开放。
- 但行业标准建模通常用**显式的 subject/scope 类型**表达，例如 `subject_type = tenant | role | user | group`，而不是在角色授权表里用 `role_id IS NULL` 隐式表示。
- 因此：**语义（全员可见、未来新增自动继承）是通用的；用 nullable `role_id` 承载它是实现技巧，不是标准建模。**

**结论（2026-11-03）：选择路线 1 — 显式 `subject_type`。**

| 路线 | 做法 | 结论 |
| --- | --- | --- |
| **路线 1：显式 tenant scope（采纳）** | `resource_grants` 增加 `subject_type ('tenant','role')`；`role_id IS NULL` 回填为 `tenant` 档；`tenant` 档允许 `role_id NULL`，但语义显式；运行时按 `subject_type` 分支 | 保留全员能力与新增角色自动继承；符合行业显式 subject 建模；迁移不丢数据、可逆 |
| 路线 2：拆成角色（不采纳） | 拆给所有启用角色 + P3 默认角色模板 | 语义变化，新增角色需手动补授权；运营负担 |

> 依据：业务确认存在"公共资源全员可用 + 新角色自动可见"场景（2026-11-03）。

#### D-3 取消开通的级联策略

**事实**：运行时判定链为 `entitlement ∩ 角色授权 ∩ approved ∩ enabled`。entitlement 置为 `revoked` 后，即使 `resource_grants` 记录还在，用户也不可见。

**选项**：

| 选项 | 行为 | 操作体验 | 可恢复 | 一致性 |
| --- | --- | --- | --- | --- |
| A 409 拒绝 | 要求先移除角色授权 | 差（批量易卡） | 是 | 强 |
| B 物理级联删除 | 同时删 `resource_grants` | 好 | 否 | 强 |
| C 软失效（推荐） | 只改 entitlement 状态 | 好 | 是 | 最终一致 |
| D C + 定时清理 | C 后异步清理 | 好 | 保留期内可恢复 | 最终一致 |

**行业对照（2026-11-03 补充）**：

| 平台 | 取消权益时对下游授权/配置的处理 | 模式 |
| --- | --- | --- |
| Salesforce | 收回 Permission Set License 后，Permission Set 分配记录仍保留；因 license 缺失而失效，重新分配 license 即恢复 | 软失效（C） |
| Microsoft Entra ID / Azure AD | 禁用 Enterprise App（服务主体）即阻断登录，用户/组分配关系保留；删除应用分配才物理清除 | 软失效（C）；物理清除属于卸载流程 |
| Microsoft 365 | 收回许可证 → 服务进入"宽限期/已禁用"状态，数据与配置保留 30 天；超期才物理清理 | 软失效 + 保留期（C/D） |
| AWS Marketplace / Azure SaaS Fulfillment | 订阅取消 → entitlement 置为不可用；客户侧 IAM 策略与集成配置保留，调用被拒绝 | 软失效（C） |
| Stripe Entitlements | revoke → feature active flag 翻转为 false；历史与集成配置保留；重新授权恢复 | 软失效（C） |
| Google Workspace | 按 OU 关闭服务 → 服务关闭但用户数据与配置保留；重新开启即恢复 | 软失效（C） |
| 钉钉/飞书/企业微信 | 停用应用 → 可见范围配置保留，用户端入口消失；重新启用即恢复 | 软失效（C） |

**行业结论**：
- **"配置保留 + 运行时求交失效"是 B2B SaaS 的主流做法**（C），因为角色授权是昂贵的配置资产，恢复开通应零手工。
- A（RESTRICT/409）是数据库参照完整性思路，SaaS 运营侧少见，会造成批量取消卡死。
- B（CASCADE 物理删除）只在**租户退租/合规清除**等离职流程出现，通常还有保留期与审批，不属于日常取消开通。
- 物理清除并不消失，而是独立为**下架/清除（purge）**动作，且需要 before/after 快照审计。

**补充设计（在 C 基础上补齐行业常见能力）**：

1. **状态机分层**：`active → suspended → revoked`（手动，需恢复操作）、`active → expired`（到期，自动）、`wait_effect → active`（到期生效）。
   - `suspended`（欠费/临时停用）与 `expired`（到期）可自动恢复；
   - `revoked`（合同终止）必须**人工重新开通**，不自动恢复。
2. **即时性**：`revoked` 对**新请求立即生效**；已在执行中的运行默认放行到结束（可配置 `ENTITLEMENT_REVOKE_KILL_RUNNING=false`），避免中途截断产出。
3. **影响面反馈**：取消前 `preview` 返回受影响的角色授权数与涉及角色名；取消后返回 `affected_role_grants`。
4. **通知**：取消开通后向租户管理员发站内信/Webhook（行业常见）。
5. **可选严格模式**：配置 `ENTITLEMENT_REVOKE_STRICT=true` 时恢复 A 的 409 行为，供合规场景使用（默认关闭）。
6. **物理清除（D-3b，新增独立动作）**：`POST /admin/entitlements/purge` 才真正删除 `resource_grant` + 关联 `resource_grants`，要求二次确认与审计快照；仅用于退租/合规，不用于日常取消。

**结论（2026-11-03，修订）**：D-3 仍为 **C（软失效）**，并补齐状态机、影响面反馈、通知、可选严格模式与独立 purge 动作。取消开通只把 entitlement 置为 `revoked`，保留 `resource_grants`；恢复开通后自动恢复。UI 明确提示"取消开通后相关角色授权将失效；恢复开通后自动恢复；如需彻底清除请使用下架/清除"。

#### D-4 审核权限

**事实**：`/admin/resources` 目前只有 `require_platform_admin`，没有细分按钮权限；平台 viewer 也拥有 `menu:resources/page:resources`。若直接加审核接口，viewer 也可能调用。

**选项**：

| 选项 | 控制方式 | 默认谁能审 | 成本 | 适用场景 |
| --- | --- | --- | --- | --- |
| A 不新增 | 所有平台管理员 | superadmin/admin/viewer | 最低 | 小团队，无岗位分离 |
| B 新增 button（推荐） | `button:resource:review` | 持有该码的平台角色 | 低 | 有运营/审核分工 |
| C 独立审核员角色 | 新建角色 + 该码 | 审核员 | 中 | 强合规、职责分离 |

**判断依据**：
- 是否有独立审核岗位？有 → C；没有但希望 viewer 不能审 → B；小团队 → A。
- 平台自建资源可直接 `approved`；租户自建必须平台审。
- 是否需要"提交人不能审核自己的资源"？租户提交/平台审核天然分离；若平台也能创建租户资源，需额外校验。

**结论（2026-11-03）**：选择 B。新增 `button:resource:review`；平台 superadmin/admin 默认授予，viewer 不授予；租户管理员只能提交、不能审核。
**职责分离（2026-11-03 补充）**：平台也可能创建租户资源，因此按行业通用做法强制「创建人不得审核自己创建的资源」——0056 增加 `resource.created_by`，P1-9 校验 `created_by != reviewer_id`，违者 403 `SELF_REVIEW_FORBIDDEN`；历史资源 `created_by IS NULL` 放行，避免一次性清空审核队列。

#### D-5 资源被拒绝后的处理（补充）

**选项**：允许修改后重新提交 / 必须新建资源。
**结论（2026-11-03）**：允许修改后重新提交，重置为 `pending`，保留历史审核记录到审计日志；避免租户反复新建。

#### D-6 命名

产品级「租户开通」`/entitlements`、租户级「角色授权」`/role-access`。

**结论（2026-11-03）**：确认采用。P1 按此实现。

#### D-7 复核补充确认（2026-11-03）

| # | 事项 | 结论 | 落地位置 |
| --- | --- | --- | --- |
| 1 | 租户自建资源的按钮权限码 | 接受新增 `button:resource:create`，不复用 `button:app:create` | §1.2 种子数 8、§1.4、§2.5、P1-4、P1-9 |
| 2 | `EntitlementService` 目录 | 放 `internal/application/apps/`，组合根 `web/deps/entitlement_services.py` | P1-5、P1-6 |
| 3 | 前端申请/开通接口封装 | 新建 `frontend/admin/src/api/entitlements.ts`，应用申请沿用 `api/apps.ts` | P2-1、P2-6 |

---

### 7.3 行业对标与差距取舍

| 能力 | 行业通用做法 | 本计划现状 | 处理 |
| --- | --- | --- | --- |
| 权益分层 | Catalog → Plan/Offer → Entitlement → Provisioning（Salesforce/AWS/Stripe） | 只有 Catalog + Entitlement，无 Plan | P3 套餐模板；本轮 D1 明确资源不做市场 |
| 权益主体显式化 | Entra ID `subjectType`、Stripe `customer`、SCIM `group` | `subject_type = tenant｜role` | ✅ 已采纳（D-2） |
| 有效期与生效窗口 | effective-dated，查询时求值 | `start_time/expire_time` + 读时计算 | ✅ 已补（P1-5） |
| 撤销策略 | 软失效 + 独立 purge/卸载流程 | 软失效 + purge（P3） | ✅ 已采纳（D-3） |
| 宽限期 / 试用 | M365 grace、Stripe trial → 转换 | `auth_type=TRIAL`，无 grace 状态 | P3：到期提醒 + 宽限期配置；本轮 `expired` 可直接重新开通恢复 |
| 席位/用量配额 | Stripe metered、AWS 用量计量 | `quota_json` 仅存储 | 明确本轮不参与判定（§0.3）；P3 定义执行点 |
| 变更幂等 | `Idempotency-Key` + 请求去重表 | ❌ | 本轮靠唯一索引兜底；P3 增加键与去重表 |
| 乐观并发 | ETag / `If-Match` / `version` 列 | ❌ | 批量操作以单事务 + 唯一索引保证；高并发场景 P3 补 `version` |
| 职责分离（SoD） | 提交人 ≠ 审核人，双人审批 purge | 缺 `created_by` | ✅ 0056 补列 + P1-9 校验；purge 二次确认，P3 补双人审批 |
| 变更历史 | 专门的 entitlement 事件流（before/after 结构化） | 复用 `audit_logs.detail` | 可接受；P3 若需回放再抽事件表 |
| 对账 / 漂移检测 | SCIM 定期 reconciliation，告警悬挂授权 | ❌ | P3：扫描"有角色授权但无权益/无审核"并告警 |
| 委派管理 | Entra delegated admin、MSP 多租户 | ❌ 单层租户 | 明确本轮不做（§0.3） |
| 审计不可篡改 | WORM / 保留期 / 分区归档 | `button:audit:clear` 可清空 | 生产限制清空权限；保留策略单独评审（R14） |
| 发布兼容 | SaaS 首选 expand → migrate → contract；维护窗口也可 | 停机维护窗口一次迁移 | ✅ 已确认采用停机窗口（§6.1）；滚动发布时按 §2.4 拆分 |

> 结论：核心判定模型（Entitlement ∩ Role ∩ Approved ∩ Enabled）与行业一致；差异集中在 P3 运营增强项与发布工程细节，已在上表标注处理方式。

---

## 8. 关键路径与排期

```text
P0-1 → P0-2 → P0-3 ─┐
P0-4 ───────────────┤
P0-6 ───────────────┼→ P1-1 → P1-3 → P1-5 → P1-6 → P2-1
                    │            ↘ P1-8 → P1-10 → P2-2
                    └→ P1-2 → P1-9 → P2-4
P1-4 → P2-3
P1-7 → P2-6
P1-11 依赖 P1-5
发布节点：0055–0057 迁移 + P1 代码在停机窗口内同步生效
```

> P0-5 已并入 P1-1，不再单列节点。P1-10 必须在 P2-2 之前完成（前端 consume `is_tenant_wide`）；`P1-8 → P2-2` 的读侧一致性由 P1-10 收口。
> P1 后端不在窗口内单独先行上线：0057 与旧代码不兼容，必须与代码同步切换（§6.1）。P2 前端仍可开关灰度。

| 阶段 | 内容 | 人日 | 可独立发版 |
| --- | --- | --- | --- |
| P0 | 类型/仓储/状态/鉴权修正 | 1–2 | 是 |
| P1 | 迁移 0055–0057 + EntitlementService + API + 约束 | 4.5–6 | 是（停机窗口内与迁移同步） |
| P2 | 双入口前端 + 审核 + 审批 | 4–6 | 是（开关灰度） |
| P3 | 生命周期/套餐/清除/通知/重命名/幂等/对账/配额/宽限期 | 7–11 | 按需 |

**总计：13–21 人日**（不含联调与业务验收，不含维护窗口时长）。

---

## 9. 交付物清单

| 类型 | 交付物 |
| --- | --- |
| 迁移 | `0055`–`0058` 四个迁移脚本 + 回滚脚本（0057 需附回填统计输出；停机窗口内单次执行） |
| 后端 | `EntitlementService`（application/apps + infra 仓储 + Protocol）、`/admin/entitlements`、`/admin/resources/{id}/review`、`POST /my-resources`、角色授权约束、`subject_type` 读写适配 |
| 前端 | `pages/entitlements/*`、`pages/roleAccess/*`、`api/entitlements.ts`、资源页双视角与审核、反查 Tab、审批工作台 |
| 测试 | 13 个新单测文件（见 §5.1）+ 集成场景 + 5 条 E2E |
| 文档 | 本文件 + 更新 `docs/features.md`、`docs/architecture.md` |
| 运维 | 备份/回滚手册、灰度开关说明 |
