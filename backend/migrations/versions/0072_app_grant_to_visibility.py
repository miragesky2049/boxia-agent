"""功能收敛：应用不再走资源授权（resource_grants），存量折算进可见范围（app_visibility_scope）。

背景：0068 起应用的用户端闸门（list_visible_for_user / assert_user_can_view）只读
app_visibility_scope / app_visibility_whitelist，不再消费 resource_grants
(resource_type='app')；「角色授权 → 资源授权 → 应用」页签写入的授权没有任何生效点，
造成"两处配置、只有一处生效"的误导。域模型同步：access.py 的 RESOURCE_TYPES
已剔除 app，服务层拒绝 app 类型的授权读写。

折算规则（按 (应用, 租户) 聚合）：
- 仅对尚无 scope 行的租户生成新 scope——租户在 0068 后显式配置过的可见范围优先；
- 存在 tenant 档授权（subject_type='tenant'，全员）→ visibility='all'；
- 否则 visibility='whitelist'，每条 role 档授权落一条 subject_type='ROLE' 白名单；
- 平台域（_PLATFORM_TENANT_IDS）的 app 授权不折算——平台管理端不受可见范围约束，直接清理；
- 应用行已不存在（孤儿授权）的不折算，随最终 DELETE 一并清理。

downgrade 不可逆：app grants 已无消费方，回滚旧版本代码后应用页签显示为未授权，
不影响实际访问控制（闸门一直是可见范围）。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0072_app_grant_to_visibility"
down_revision: str | None = "0071_viewer_no_console_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 平台租户 UUID 双字面量：全零旧值（0067 前）+ 新配置默认值（0067 后）；迁移不得 import 业务代码
_PLATFORM_TENANT_IDS = (
    "00000000-0000-0000-0000-000000000000",
    "00000000-0000-0000-0000-000000100000",
)


def _platform_tenant_array() -> str:
    return "ARRAY[" + ", ".join(f"'{item}'::uuid" for item in _PLATFORM_TENANT_IDS) + "]"


def upgrade() -> None:
    # 1) 为「有 app 授权但没有 scope 行」的 (应用, 租户) 生成 scope，并把 role 档授权折算为 ROLE 白名单。
    #    单条语句内用 CTE 圈定本次新建的 scope，避免污染租户已显式配置的可见范围。
    op.execute(
        f"""
        WITH grant_pairs AS (
            SELECT g.resource_id, g.tenant_id,
                   MAX(CASE WHEN g.subject_type = 'tenant' THEN 1 ELSE 0 END) AS has_tenant_wide
            FROM resource_grants g
            WHERE g.resource_type = 'app'
              AND g.tenant_id <> ALL({_platform_tenant_array()})
            GROUP BY g.resource_id, g.tenant_id
        ),
        new_scopes AS (
            INSERT INTO app_visibility_scope (id, application_id, tenant_id, visibility)
            SELECT gen_random_uuid(), p.resource_id, p.tenant_id,
                   CASE WHEN p.has_tenant_wide = 1 THEN 'all' ELSE 'whitelist' END
            FROM grant_pairs p
            JOIN tenants t ON t.id = p.tenant_id
            JOIN application a ON a.id = p.resource_id
            WHERE NOT EXISTS (
                SELECT 1 FROM app_visibility_scope s
                WHERE s.application_id = p.resource_id AND s.tenant_id = p.tenant_id
            )
            RETURNING id, application_id, tenant_id, visibility
        )
        INSERT INTO app_visibility_whitelist (id, scope_id, subject_type, subject_id, include_subtree)
        SELECT gen_random_uuid(), s.id, 'ROLE', g.role_id, FALSE
        FROM resource_grants g
        JOIN new_scopes s ON s.application_id = g.resource_id AND s.tenant_id = g.tenant_id
        WHERE g.resource_type = 'app'
          AND g.subject_type = 'role'
          AND s.visibility = 'whitelist'
        GROUP BY s.id, g.role_id
        """
    )
    # 2) 清理全部 app 授权行（含平台域与孤儿应用），写入口已在服务层关闭。
    #    类型约束不在本迁移处理：0061 已 DROP ck_resource_grants_type，resource_grants
    #    的类型合法性由服务层 RESOURCE_TYPES（domain 单一来源）把关；此处若重新添加
    #    静态 CHECK，会与 resource_type_catalog「新增类型免 DDL」机制冲突。
    op.execute("DELETE FROM resource_grants WHERE resource_type = 'app'")


def downgrade() -> None:
    # 不可逆数据清理：app grants 无消费方，不重建授权行（见模块 docstring）；
    # 无 schema 变更可回滚，本 downgrade 为空操作。
    pass
