# 产品级 / 租户级授权体系评估与落地计划

> 评估对象：产品级运营管理平台与租户级运营管理平台的授权模型、信息架构与交互设计。
> 评估依据：当前仓库 `backend/`、`frontend/` 的实际实现（2026-11-03 核对）。
> 结论有效期：架构决策在 P1 落地前仍可调整。
> 细化执行计划：见 `docs/authorization-execution-plan.md`（含 DDL、迁移顺序、任务 WBS、API 契约）。

---

## 0. 结论速览

| 问题 | 结论 |
| --- | --- |
| 这套设计是否行业通用 | **主干通用**：双平面运营（平台/租户）+ 应用市场 + 申请审批 + 后台直开 + 租户内 RBAC，符合主流 SaaS 模式 |
| 是否需要改进 | **需要，3 处关键改进**：① 严格区分「开通权益（Entitlement）」与「角色授权（Permission）」；② 租户角色授权必须受「已开通集合」约束；③ 授权对象需要统一抽象，支持未来新增类型 |
| 产品级统一授权入口 | **方向正确，但要改造成「租户开通中心」**，不是把所有东西塞进一个叫"授权"的菜单 |
| 租户级统一角色授权入口 | **正确**，但应与"用户授权"（给人授角色）保持职责分离 |
| 推荐落地节奏 | P0 修正存量缺陷 → P1 后端统一抽象 → P2 前端双入口 → P3 运营增强 |

一句话：**你的思路是对的，但行业标准做法是把「租户能拥有什么」和「用户/角色能使用什么」拆成两层、两个中心。当前代码已经有两层的雏形，只是入口和数据类型太分散。**

---

## 1. 现状盘点（代码事实）

### 1.1 已具备的能力

| 能力 | 现有实现 |
| --- | --- |
| 平台/租户双作用域 | 平台以哨兵租户 `PLATFORM_TENANT_ID = 00000000-...` 表示；Host 子域名解析；`admin_users` 平台专用、`users` 租户级；单一管理端前端按作用域渲染 |
| 应用统一模型 | `application` 表，`owner_type = platform/tenant`，`flow_type = workflow/chatflow`，`sale_mode`（1=仅后台开通，2=市场可见）、`is_listed_in_market`、`published_graph_version` |
| 应用开通与申请 | `tenant_application_instance`（状态/来源/授权类型/有效期/合同/配额）+ `application_apply`（SUBMITTED→HANDLING→PASS→FINISH / REJECT） |
| 应用市场 | `/admin/marketplace/*`：浏览、自助开通、我的应用、运行 |
| 统一资源模型 | `resource` 表，`type = tool/prompt/skill/knowledge`，`owner_type/owner_id` |
| 资源授权（两层雏形） | 单数 `resource_grant`：平台→租户，无角色；复数 `resource_grants`：租户或角色维度 |
| RBAC | `roles`、`role_permissions`、`users.role_id` + `user_roles`；功能权限码 + 数据资源授权 |
| 审计 | `audit_logs` 复用，授权变更写 before/after |

### 1.2 关键缺口

| # | 缺口 | 影响 |
| --- | --- | --- |
| G1 | 「开通」与「授权」概念混用，入口分散在 `resources/{id}/grants`、`grants/batch`、`roles/{id}/grants`、`marketplace/subscribe`、`applies/*` 五处 | 运营人员无法在一个地方看清"某租户拥有什么" |
| G2 | 租户角色授权不校验该资源是否已对该租户开通 | 可能出现"未开通却能给角色授权"的越权/脏数据 |
| G3 | 资源授权只有租户维度（`resource_grant`），没有状态、有效期、来源、审批、备注 | 资源无法像应用一样走试用/合同/到期回收 |
| G4 | 应用 `sale_mode` 未被强制执行：`subscribe` 直接写 ACTIVE，市场申请与自助开通并存 | 可能绕过审批开通 |
| G5 | 产品级「OPS 直接开通」只有领域服务 `GrantService`，没有 HTTP API/UI | 你描述的"后台直接开通"路径不可用 |
| G6 | 资源类型枚举三方不一致 | 见 1.3，会导致授权写入失败或查错表 |
| G7 | 申请单 `claim/pass/reject` 仅用 `AdminAuthDep`，未校验平台/租户归属 | 任意租户管理员可能操作他人申请 |
| G8 | 前端资源页硬编码 `owner_type=platform`，租户视角未落地；无申请/开通工作台 | 产品级与租户级信息架构不完整 |
| G9 | 应用实例 `get_instance` 不过滤状态；`wait_effect/expired` 与 DB CHECK 不一致 | 失效实例可能仍被判定可用 |

### 1.3 P0 缺陷：资源类型枚举三方冲突

| 位置 | 允许的类型 |
| --- | --- |
| `internal/domain/entity/access.py:16` `RESOURCE_TYPES` | `tool`, `app` |
| `internal/infrastructure/model/access.py:27` + 迁移 0006 CHECK | `agent`, `skill`, `tool`, `component`, `prompt` |
| `resource` 表 CHECK（迁移 0028） | `tool`, `prompt`, `skill`, `knowledge` |
| `GrantService._resource_repository` (`grant_service.py:371-375`) | 无论传入什么类型，**都返回 `uow.tools`（固定 type=tool）** |

后果：`app` 授权查不到应用表、`knowledge` 不在 CHECK 中、`GrantService` 对非 tool 类型实际在操作 tool 仓储。**任何统一授权入口都必须先修这里。**

---

## 2. 行业通用模型对标

主流 SaaS（Salesforce、AWS Marketplace、Azure Marketplace、Stripe Entitlements、Microsoft 365 等）在"平台能力如何到达最终用户"上，普遍采用六层模型：

```text
① Catalog 产品目录        可售/可开通的对象：应用、工具、技能、Prompt、知识包
        ↓
② Offer/Plan 报价与套餐   如何组合售卖：试用、正式、赠送、配额
        ↓
③ Entitlement 权益        租户实际拥有什么：对象 + 状态 + 有效期 + 来源 + 配额
        ↓  （市场申请 / 合同 / 后台直开 都汇入这一层）
④ Provisioning 开通       审批通过或后台直开后，权益生效
        ↓
⑤ RBAC 角色权限           租户内把"已拥有"的权益分配给角色/用户
        ↓
⑥ Audit 审计              所有变更留痕、可追溯
```

### 2.1 与现状映射

| 行业层 | 现状 | 评价 |
| --- | --- | --- |
| ① Catalog | 应用：`application`；资源：`resource` | 有，但两套对象模型不统一 |
| ② Offer/Plan | `auth_type`（试用/正式/赠送）、`quota_json` | 有字段，无套餐模板 |
| ③ Entitlement | 应用：`tenant_application_instance`；资源：`resource_grant` | **应用完整、资源太薄**，两套生命周期不一致 |
| ④ Provisioning | 市场申请 + 后台直开（后者无 API） | 有，但自助开通绕过审批 |
| ⑤ RBAC | `resource_grants` + `role_permissions` | 有，但未受 ③ 约束 |
| ⑥ Audit | `audit_logs` | 有基础 |

### 2.2 结论

- **整体架构方向是行业通用的**，不需要推翻。
- 真正需要补的是 **③ 的统一性与 ③→⑤ 的约束关系**，而不是重做 RBAC。
- 行业里最常见的错误正是你担心的："授权项越来越多、入口越来越散"——标准解法不是合并成一个超大授权页，而是**固定两层语义**：
  - **Entitlement（产品级→租户）**：租户能拥有什么。
  - **Permission（租户内角色→用户）**：谁能使用已拥有的什么。
  两层各自有统一入口，但数据与操作严格分层。

---

## 3. 目标架构

### 3.1 两层两中心

```text
┌─────────────────────────────────────────────────────────────┐
│ 产品级运营管理平台（Platform Plane）                          │
│                                                             │
│  应用管理   资源管理   租户开通中心 ★   应用市场   租户管理     │
│                              │                              │
│                              ├─ 权益清单（按租户 / 按对象）   │
│                              ├─ 批量开通 / 取消               │
│                              ├─ 市场申请审批                  │
│                              └─ 有效期 / 回收 / 审计          │
└──────────────────────────────┬──────────────────────────────┘
                               │ 写入 Entitlement
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 租户级运营管理平台（Tenant Plane）                            │
│                                                             │
│  我的应用   我的资源   角色授权中心 ★   用户授权   组织架构     │
│                              │                              │
│                              ├─ 角色 × 资源类型矩阵          │
│                              ├─ 候选 = 本租户已开通集合       │
│                              └─ 批量授权 / 取消               │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
                        用户端只展示"角色可见"的应用与资源
```

### 3.2 统一对象模型

所有可开通对象统一用 `object_type + object_id` 表达，避免每新增一种资源就改表/改接口：

```text
object_type ∈ { application, tool, skill, prompt, knowledge, ... }
object_id   = 对应主键
```

**渐进式存储策略（推荐）**：

| 对象 | 存储 | 原因 |
| --- | --- | --- |
| application | 继续用 `tenant_application_instance` | 已有完整生命周期、申请、版本钉住，迁移风险大 |
| tool/skill/prompt/knowledge | 扩展现有单数 `resource_grant` 表 | 表已存在、唯一约束 `(resource_id, tenant_id)` 正好匹配；仅需补生命周期字段 |
| 服务层 | 新增 `EntitlementService` 适配器，把两种存储映射为统一 `EntitlementView` | 统一发生在 API/服务层，不物理搬表 |

`resource_grant` 建议补齐字段（对齐 `tenant_application_instance` 的核心子集）：

```text
status         active / suspended / revoked / wait_effect / expired
auth_source    OPS / MARKET_APPLY
auth_type      FORMAL / TRIAL / GIFT
start_time
expire_time
apply_id
quota_json
remark
granted_by / granted_at
```

> 命名提醒：单数 `resource_grant` 是 Entitlement 层，复数 `resource_grants` 是 RBAC 层，极易混淆。P1 可在代码与注释中明确标注；P2 可评估是否重命名为 `tenant_resource_entitlement`（低风险 DDL，但需同步仓储）。

### 3.3 核心约束（必须写进服务层）

1. **开通是授权的前置条件**：租户角色只能从"本租户已生效的 Entitlement"中选择；未开通对象不可选。
2. **失效即收回**：Entitlement 过期/回收后，角色上的对应授权自动失效（查询时 join entitlement 状态，或定时清理）。
3. **应用与资源同一套规则**：应用走 `tenant_application_instance`，资源走 `resource_grant`，但在 `EntitlementService` 中暴露一致的状态与操作语义。
4. **市场申请与后台直开同一终点**：两者最终都落为 ACTIVE Entitlement，只是 `auth_source` 不同。
5. **所有变更留痕**：批量操作必须记录 before/after 与操作原因。

### 3.4 运行时判定链（目标态）

```text
用户登录 → 角色集合
        → 功能权限（role_permissions，控制菜单/按钮）
        → 已开通集合（Entitlement，租户级）
        → 角色资源授权（resource_grants，角色级）
        → 最终可见 = 已开通 ∩ 角色授权 ∩ 资源启用 ∩ 应用可见性
```

现状缺的是中间"已开通集合"对角色资源授权的约束（G2）。

---

## 4. 对你方案的三点评估

### 4.1 产品级统一入口：正确，但应命名为「租户开通中心」

你的原话是"一个开通授权的菜单，里边有已授权的项和类型列表，然后批量授权"。

- **正确**：把三类对象收进一个入口，避免运营在应用市场、资源管理、租户管理之间来回跳。
- **需要调整**：
  - 名称不要叫"授权"，叫 **「租户开通」** 或 **「开通与权益」**。因为这里操作的是"给租户开通产品能力"，不是"给角色分配权限"。术语混用会让用户和运营都分不清两层。
  - 主视角应是 **租户**（选中租户 → 看它拥有什么），而不是对象。对象视角作为反查（某应用开通给了哪些租户）保留在详情页。
  - 必须支持 **按类型分组 + 跨类型批量**，但批量操作要有"差异预览"。
  - 市场申请审批应并入这个中心，作为"待办"入口，而不是单独一个找不到的页面。

### 4.2 租户级统一入口：正确，但要和「用户授权」分离

- **「角色授权」** = 给角色分配"已开通"的应用/工具/技能/Prompt/知识。统一入口正确。
- **「用户授权」** = 给人分配角色（以及管理单元）。这是两件事，不能合并。
- 现有 `roles/:id` 已经用「功能权限 + 数据授权」两个 Tab 表达，方向对；只需把"数据授权"升级为"资源授权中心"，支持五类对象与批量。
- 必须增加"未开通置灰 + 引导"：租户管理员看到某工具不可选时，应提示"该资源未由产品级开通，请联系平台运营"。

### 4.3 未来扩展性

用 `object_type/object_id` 后，新增"模型""插件""Agent 模板"等只需要：
1. 在对象目录注册新 type；
2. 提供列表/详情适配器；
3. 不需要改 Entitlement 表结构，也不需要新增授权 API。
这是你"未来可能还有其他项"诉求的标准解法。

---

## 5. 产品设计与交互设计

### 5.1 信息架构调整

**产品级菜单（调整后）**

```text
应用管理          /apps
资源管理          /resources
租户开通 ★新增     /entitlements        ← 替代分散在各处的授权入口
应用市场          /marketplace
租户管理          /tenants
角色管理          /roles
管理员账号        /admin-users
审计日志          /audit
```

**租户级菜单（调整后）**

```text
我的应用          /apps
我的资源          /resources            ← 从只读列表升级为"已开通 + 自建"
角色授权 ★新增     /role-access          ← 或复用 /roles/:id 的资源 Tab
用户授权          /grants
用户管理          /users
角色管理          /roles
组织架构          /departments | /employments | /mgmt-units
管理员账号        /admin-users
审计日志          /audit
```

> 如果不想新增一级菜单，租户级也可以把「角色授权」放在角色详情页内，但必须提供跨角色的批量入口，否则运营效率低。建议新增一级菜单，角色详情页保留单角色精调。

### 5.2 产品级「租户开通」页

**布局：三栏 + 顶部批量条**

```text
┌──────────────────────────────────────────────────────────────┐
│ 租户：[搜索/选择租户 ▾]   状态：[全部▾]   来源：[全部▾]        │
│ 已选 N 项   [批量开通] [批量取消] [导出]                        │
├────────────┬─────────────────────────────────────────────────┤
│ 类型导航    │ 权益清单                                         │
│            │ ┌────┬────────┬──────┬──────┬────────┬────────┐ │
│ 全部 (42)  │ │ ☐  │ 名称    │ 类型  │ 状态  │ 有效期  │ 来源   │ │
│ 应用 (8)   │ ├────┼────────┼──────┼──────┼────────┼────────┤ │
│ 工具 (12)  │ │ ☐  │ 报销流  │ 应用  │ 生效  │ 2027-.. │ 市场申请│ │
│ 技能 (6)   │ │ ☑  │ 搜索工具│ 工具  │ 生效  │ 永久    │ 后台直开│ │
│ Prompt(9)  │ │ ☐  │ 摘要技能│ 技能  │ 待生效│ 2026-.. │ 后台直开│ │
│ 知识 (7)   │ │ ☐  │ 客服知识│ 知识  │ 已过期│ 2026-10 │ 试用    │ │
│            │ └────┴────────┴──────┴──────┴────────┴────────┘ │
│ 待审批 (3) │  [分页]                                          │
└────────────┴─────────────────────────────────────────────────┘
```

**关键交互**

1. **租户选择器**：支持搜索、最近访问；切换租户后整页刷新。
2. **类型导航**：显示各类型已开通数量；"全部"聚合视图。
3. **批量开通**：
   - 只展示"该租户尚未开通"的候选对象（或全量但已开通项置灰）。
   - 点击后弹 **差异预览**：`新增 3 项 / 移除 0 项 / 无变化 2 项`，并列出对象名称。
   - 必填"操作原因"，确认后提交；返回结果逐项展示成功/失败。
4. **批量取消**：同样差异预览 + 二次确认，提示"取消后租户角色上的授权将同步失效"。
5. **行内操作**：查看详情、调整有效期、续期、回收。
6. **反查视角**：资源详情/应用详情页增加"已开通租户"Tab，可跳转到本页并定位。
7. **待审批入口**：左上角"待审批 (N)"，点击进入申请队列；通过即生成 ACTIVE 权益，拒绝需填原因。
8. **状态与来源筛选**：运营最常用的是"待生效/即将到期/试用"，默认提供快捷筛选。

**空状态**：无权益时提示"该租户尚未开通任何应用或资源"，并提供"从应用市场/资源库选择"的主按钮。

### 5.3 租户级「角色授权」页

**布局：角色选择 + 类型导航 + 候选矩阵**

```text
┌──────────────────────────────────────────────────────────────┐
│ 角色：[产品运营 ▾]   搜索：[____________]   筛选：[已授权▾]    │
│ 已选 N 项   [批量授权] [批量取消] [整租户授权]                  │
├────────────┬─────────────────────────────────────────────────┤
│ 类型导航    │ 候选清单（仅本租户已开通）                        │
│            │ ┌────┬────────┬────────┬──────────┬──────────┐  │
│ 应用 (5)   │ │ ☑  │ 名称    │ 类型   │ 授权状态  │ 操作     │  │
│ 工具 (8)   │ ├────┼────────┼────────┼──────────┼──────────┤  │
│ 技能 (3)   │ │ ☑  │ 报销流  │ 应用   │ 已授权    │ 移除     │  │
│ Prompt(4)  │ │ ☐  │ 合同审核│ 应用   │ 未授权    │ 授权     │  │
│ 知识 (6)   │ │ 🔒 │ 外部搜索│ 工具   │ 未开通    │ 置灰     │  │
│            │ └────┴────────┴────────┴──────────┴──────────┘  │
│            │  注：🔒 表示该资源未由产品级开通，无法授权          │
└────────────┴─────────────────────────────────────────────────┘
```

**关键交互**

1. **候选集合 = 本租户已开通**：这是与现状最大的差异，必须在服务层强制，前端置灰只是提示。
2. **整租户授权 vs 指定角色**：保留"全员可见（含未来新增角色）"语义，但改为显式 `subject_type='tenant'` 表达；界面提供"设为全员可见 / 取消全员可见"，并解释"全员可见 = 本租户所有当前及未来角色默认可见"。
3. **批量授权/取消**：按类型勾选，支持"全选当前页/全部"；差异预览 + 确认。
4. **功能权限与资源授权分 Tab**：保留现有设计（`功能权限` / `资源授权`），避免把菜单权限和资源权限混在一起。
5. **未开通提示**：悬浮或行内提示"请联系平台运营在产品级『租户开通』中开通"。
6. **授权来源说明**：区分"角色显式授权"与"整租户默认"，避免运营误删整租户授权导致全角色失效。

### 5.4 通用交互规则

| 规则 | 说明 |
| --- | --- |
| 批量优先 | 运营场景以批量为主，单条操作为辅；批量上限沿用现有 100（资源）/200（用户） |
| 差异预览 | 所有批量开通/取消/替换操作先 dry-run，展示新增/移除/无变化 |
| 二次确认 + 原因 | 取消授权、回收、批量替换必须填原因，写入审计 |
| 作用域隔离 | 产品级只能操作平台对象与目标租户；租户级只能操作本租户角色与已开通对象 |
| 失败可定位 | 批量结果逐项返回成功/失败原因，不因单项失败整体回滚（或提供"全部回滚"开关） |
| 审计可查 | 每次变更记录操作人、对象、before/after、原因、IP/UA |

---

## 6. 落地计划

> 原则：先修数据正确性，再做统一入口；先服务层统一，再前端统一。避免在缺陷未修时扩大入口暴露面。

### P0 — 前置修正（1–2 人日）

| # | 任务 | 涉及文件 | 验收 |
| --- | --- | --- | --- |
| P0-1 | 统一资源类型枚举为 `tool/skill/prompt/knowledge/application`（或保留 `app` 但全链路一致） | `internal/domain/entity/access.py:16`、`internal/infrastructure/model/access.py:27`、迁移 0006 CHECK | 新增单测：各类型均可正确读写；迁移在测试库通过 |
| P0-2 | 修 `GrantService._resource_repository`，按类型返回应用/资源仓储 | `internal/application/grant_service.py:371-375` | `resource_type=application` 查 `application` 表；其余查 `resource` 表 |
| P0-3 | 修 `RoleGrantService` 的 app 分支写表一致性 | `internal/application/role_grant_service.py:343-347` 及 replace/add/remove | 授权 app 不再写错表 / 违反 CHECK |
| P0-4 | 修 `tenant_application_instance.status` DB CHECK 与枚举不一致 | 新迁移 + `GrantService` | `wait_effect/expired` 可正常写入 |
| P0-5 | `get_instance` 增加状态过滤；`subscribe` 强制校验 `sale_mode` 与 `is_enabled` | `infrastructure/repository/apps/application_repository.py:383-415`、`application_service.py:304-321` | 失效实例不可运行；sale_mode=1 不能被市场自助开通 |
| P0-6 | `claim/pass/reject` 补平台/租户归属鉴权 | `web/admin/routers/applies.py:103-178` | 跨租户操作返回 403 |
| P0-7 | 统一 `claim` 持久化 `sales_user_id` | `internal/domain/auth/apply_service.py:102-123` | 认领后申请单可查到销售归属 |

> P0 不改变产品形态，只修正确性与一致性，可独立发版。

### P1 — 后端统一 Entitlement（4–6 人日）

| # | 任务 | 涉及文件 | 验收 |
| --- | --- | --- | --- |
| P1-1 | 新增 `EntitlementService`：统一 `application`（instance）与 `resource`（grant）的查询/开通/取消/预览 | 新增 `internal/application/entitlement_service.py` | 返回统一 `EntitlementView(object_type, object_id, status, auth_source, auth_type, start/expire, ...)` |
| P1-2 | 扩展 `resource_grant` 生命周期字段（status/auth_source/auth_type/start/expire/apply_id/quota/remark/granted_by） | 新迁移 + `infrastructure/repository/apps/resource_repository.py` | 资源权益支持状态与有效期 |
| P1-3 | 新增产品级统一路由 `/admin/entitlements`：按租户查询、按对象反查、批量开通/取消、dry-run 预览 | 新增 `web/admin/routers/entitlements.py` | 覆盖 app + 四类资源；dry-run 返回 diff |
| P1-4 | 暴露 OPS 直接开通 API（不依赖申请单） | `internal/domain/auth/grant_service.py` + 新路由 | 后台直开生成 ACTIVE 权益，`auth_source=OPS` |
| P1-5 | 市场申请统一接入：审批通过生成 ENTITLEMENT，不再只依赖 instance | `internal/domain/auth/apply_service.py` | app 与资源均可走申请→审批 |
| P1-6 | 租户角色授权增加"已开通"校验 | `internal/application/role_grant_service.py` replace/add | 未开通对象返回 422 并提示 |
| P1-7 | 新增权限码与迁移 | `internal/domain/entity/permission.py`、新迁移 | 平台：`menu:entitlements/page:entitlements/button:entitlement:manage`；租户：`menu:role-access/page:role-access/button:role-access:manage` |
| P1-8 | 审计补全：批量开通/取消写 before/after + reason | `internal/application/audit.py` 调用处 | 审计日志可还原一次批量操作 |

### P2 — 前端双入口（4–6 人日）

| # | 任务 | 涉及文件 | 验收 |
| --- | --- | --- | --- |
| P2-1 | 产品级「租户开通」页 | 新增 `frontend/admin/src/pages/entitlements/`、`router.tsx` | 租户切换、类型筛选、批量、diff 预览、待审批 |
| P2-2 | 租户级「角色授权」页 | 新增 `frontend/admin/src/pages/roleAccess/` 或升级 `pages/roles/RoleDetailPage.tsx` | 五类对象、已开通约束、置灰提示、批量 |
| P2-3 | 菜单与权限接入 | `frontend/admin/src/layouts/AdminLayout.tsx:31-58`、`router.tsx` | 菜单由 `menus` 驱动，路由有 `RequirePermission` |
| P2-4 | 资源页支持平台/租户双视角 | `frontend/admin/src/pages/apps/ResourcesPage.tsx:81` | 去掉硬编码 `owner_type=platform`，租户视角调用 `/my-resources` |
| P2-5 | 应用/资源详情增加"已开通租户"反查 Tab | `AppListPage`/`ResourcesPage` | 可跳转并定位到租户开通页 |
| P2-6 | 申请/审批工作台 | 新增页面或并入 P2-1 | 待审批、通过、拒绝、原因 |
| P2-7 | 路由权限守卫补齐 | `router.tsx:53-58` | `/apps`、`/marketplace`、`/resources` 增加 `RequirePermission` |

### P3 — 运营增强（可选，3–5 人日）

| # | 任务 | 价值 |
| --- | --- | --- |
| P3-1 | 权益生命周期定时任务：待生效→生效、到期→过期、回收 | 与应用现有任务对齐，避免资源权益长期滞留 |
| P3-2 | 到期提醒（站内信/邮件/Webhook） | 运营续费闭环 |
| P3-3 | 套餐模板（Plan）：预置一组应用+资源，一键开通给租户 | 规模化后减少重复勾选 |
| P3-4 | 申请单与销售归属报表、运营仪表盘 | 经营分析 |
| P3-5 | 资源类型注册表化（避免新增类型改 CHECK/接口） | 长期扩展性 |
| P3-6 | 将单数 `resource_grant` 重命名为 `tenant_resource_entitlement` | 消除命名歧义（需评估仓储/迁移成本） |

### 依赖与关键路径

```text
P0-1 → P0-2 → P0-3 → P1-1 → P1-3 → P2-1
                          ↘ P1-6 → P2-2
P0-4/P0-5/P0-6 可与 P0-1~3 并行
P1-7 → P2-3
P1-2 → P1-3
```

关键路径：**P0-1 → P0-2 → P1-1 → P1-3 → P2-1**。P0-1/P0-2 不完成，统一入口会把错误类型暴露给运营，风险更高。

---

## 7. 风险与兼容

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 两套存储长期并存 | 应用用 instance、资源用 grant，服务层适配器复杂度上升 | 统一 `EntitlementService` 接口；禁止业务层直接访问两套表 |
| 存量数据缺状态/有效期 | `resource_grant` 老数据没有 status | 迁移默认 `status=active`、`auth_type=FORMAL`、`auth_source=OPS` |
| 角色授权失效级联 | 权益过期后角色授权是否物理删除 | 查询时 join 权益状态（软失效），不物理删除，保留审计 |
| 批量误操作 | 一次取消大量权益 | dry-run + 二次确认 + 原因 + 可回滚（保留 before 快照） |
| 命名混淆 | 单数/复数 grant 表 | P1 代码注释显式区分；P3 评估重命名 |
| 权限码扩展 | 新增菜单需迁移种子数据 | 跟随 P1-7 一次性补齐平台/租户内置角色 |

---

## 8. 决策状态

### 8.1 已确认（2026-11-03）

1. **资源开通渠道**：工具/技能/Prompt/知识**仅产品级直开**，不做市场申请；市场只处理应用。
2. **整租户授权**：保留"全员可见（含未来新增角色）"语义，改为显式 `subject_type='tenant'`；角色授权用 `subject_type='role'`。存量 `role_id IS NULL` 回填为 `tenant` 档，不拆分。
3. **租户自建资源**：**需要产品级审核**（`review_status=approved`）后才能被角色授权。
4. **存量 `agent/component` 授权**：确认全部为孤儿记录，迁移时删除（升级前备份）。
5. **取消开通的级联策略**：默认软失效（entitlement 置 `revoked`，保留角色授权，恢复开通自动恢复）；严格模式可配置；物理清除作为独立 purge 动作。
6. **审核角色限制**：新增 `button:resource:review`，平台 superadmin/admin 默认授予，viewer 不授予。
7. **命名**：产品级「租户开通」`/entitlements`、租户级「角色授权」`/role-access`。

### 8.2 仍待确认（P1 前）

- 无。剩余实现级细节见执行计划 §7.2 的 D-5（资源被拒后重新提交，已给出推荐默认值）。

---

## 附：落地任务总览

| 阶段 | 目标 | 人日 | 可独立发版 |
| --- | --- | --- | --- |
| P0 | 修正资源类型/仓储/鉴权/状态一致性 | 1–2 | 是 |
| P1 | 后端统一 Entitlement + 约束 + API | 4–6 | 是（API 先行，前端未接不影响） |
| P2 | 产品级「租户开通」+ 租户级「角色授权」 | 4–6 | 是 |
| P3 | 生命周期、套餐、清除、通知、扩展性 | 4–7 | 按需 |
