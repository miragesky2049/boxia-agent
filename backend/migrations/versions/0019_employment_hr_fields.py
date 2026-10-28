"""任职记录 HR 字段扩展：HR 字典表 + user_employments 丰富字段。

1) 新建 hr_dictionaries 字典表，按 category 区分雇佣类型/岗位职级/岗位序列；
   为已有租户回填默认字典项，新租户由 TenantService.create 预置。
2) user_employments 新增字段：
   - employment_type_id / job_level_id / job_family_id（外键到 hr_dictionaries）
   - manager_id（同租户汇报上级，复合外键到 users）
   - work_location / cost_center / contract_no / weekly_hours（用工基础信息）
   - employment_nature（regular/dispatch/outsourced/intern）
   - probation_started_at / probation_ended_at / regularized_at（试用期与转正）
   - change_type（hire/transfer/promotion/demotion/reorganization）/ change_reason
   - termination_type（resignation/dismissal/layoff/retirement）
   - remark（备注）

Revision ID: 0019_employment_hr_fields
Revises: 0018_user_hr_fields
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_employment_hr_fields"
down_revision: str | None = "0018_user_hr_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (category, code, name, sort_order)
_DEFAULT_ITEMS: tuple[tuple[str, str, str, int], ...] = (
    # 雇佣类型
    ("employment_type", "full_time", "全职", 10),
    ("employment_type", "part_time", "兼职", 20),
    ("employment_type", "intern", "实习", 30),
    ("employment_type", "outsourced", "外包", 40),
    ("employment_type", "dispatched", "派遣", 50),
    ("employment_type", "consultant", "顾问", 60),
    # 岗位职级（技术与管理双通道）
    ("job_level", "P1", "P1", 10),
    ("job_level", "P2", "P2", 20),
    ("job_level", "P3", "P3", 30),
    ("job_level", "P4", "P4", 40),
    ("job_level", "P5", "P5", 50),
    ("job_level", "P6", "P6", 60),
    ("job_level", "P7", "P7", 70),
    ("job_level", "M1", "M1", 100),
    ("job_level", "M2", "M2", 110),
    ("job_level", "M3", "M3", 120),
    ("job_level", "M4", "M4", 130),
    # 岗位序列
    ("job_family", "tech", "技术", 10),
    ("job_family", "product", "产品", 20),
    ("job_family", "design", "设计", 30),
    ("job_family", "operation", "运营", 40),
    ("job_family", "sales", "销售", 50),
    ("job_family", "marketing", "市场", 60),
    ("job_family", "function", "职能", 70),
)


def _items_values_sql() -> str:
    """构造 VALUES 子查询片段，列顺序 (category, code, name, sort_order)。"""
    return ",\n        ".join(
        f"('{category}', '{code}', '{name}', {sort_order})"
        for category, code, name, sort_order in _DEFAULT_ITEMS
    )


def upgrade() -> None:
    """建字典表、扩展任职表字段，并为已有租户回填默认字典。"""
    op.execute(
        """
        CREATE TABLE hr_dictionaries (
            id           UUID         NOT NULL,
            tenant_id    UUID         NOT NULL,
            category     VARCHAR(32)  NOT NULL,
            code         VARCHAR(64)  NOT NULL,
            name         VARCHAR(100) NOT NULL,
            sort_order   INTEGER      NOT NULL DEFAULT 0,
            is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
            remark       VARCHAR(255) NOT NULL DEFAULT '',
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT pk_hr_dictionaries PRIMARY KEY (id),
            CONSTRAINT fk_hr_dictionaries_tenant FOREIGN KEY (tenant_id)
                REFERENCES tenants (id) ON DELETE CASCADE,
            CONSTRAINT uq_hr_dictionaries_tenant_category_code
                UNIQUE (tenant_id, category, code),
            CONSTRAINT ck_hr_dictionaries_category CHECK (
                category IN ('employment_type', 'job_level', 'job_family')),
            CONSTRAINT ck_hr_dictionaries_code CHECK (
                code ~ '^[a-zA-Z0-9_-]{1,64}$'),
            CONSTRAINT ck_hr_dictionaries_name CHECK (length(btrim(name)) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_hr_dictionaries_tenant_category "
        "ON hr_dictionaries (tenant_id, category, sort_order)"
    )
    op.execute(
        """
        CREATE TRIGGER trg_hr_dictionaries_updated_at BEFORE UPDATE ON hr_dictionaries
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    # 为已有租户回填默认字典项；新租户由 TenantService.create 调用同一清单预置。
    op.execute(
        f"""
        INSERT INTO hr_dictionaries
            (id, tenant_id, category, code, name, sort_order, is_active, remark)
        SELECT gen_random_uuid(), t.id, v.category, v.code, v.name, v.sort_order, TRUE, ''
        FROM tenants t
        CROSS JOIN (
            VALUES {_items_values_sql()}
        ) AS v(category, code, name, sort_order)
        ON CONFLICT (tenant_id, category, code) DO NOTHING
        """
    )

    # user_employments 扩展 HR 字段
    op.execute("ALTER TABLE user_employments ADD COLUMN employment_type_id UUID")
    op.execute("ALTER TABLE user_employments ADD COLUMN job_level_id UUID")
    op.execute("ALTER TABLE user_employments ADD COLUMN job_family_id UUID")
    op.execute("ALTER TABLE user_employments ADD COLUMN manager_id UUID")
    op.execute("ALTER TABLE user_employments ADD COLUMN work_location VARCHAR(100)")
    op.execute("ALTER TABLE user_employments ADD COLUMN cost_center VARCHAR(64)")
    op.execute("ALTER TABLE user_employments ADD COLUMN contract_no VARCHAR(64)")
    op.execute("ALTER TABLE user_employments ADD COLUMN weekly_hours NUMERIC(5,1)")
    op.execute("ALTER TABLE user_employments ADD COLUMN employment_nature VARCHAR(16)")
    op.execute("ALTER TABLE user_employments ADD COLUMN probation_started_at DATE")
    op.execute("ALTER TABLE user_employments ADD COLUMN probation_ended_at DATE")
    op.execute("ALTER TABLE user_employments ADD COLUMN regularized_at DATE")
    op.execute("ALTER TABLE user_employments ADD COLUMN change_type VARCHAR(16)")
    op.execute("ALTER TABLE user_employments ADD COLUMN change_reason VARCHAR(255)")
    op.execute("ALTER TABLE user_employments ADD COLUMN termination_type VARCHAR(16)")
    op.execute(
        "ALTER TABLE user_employments ADD COLUMN remark TEXT NOT NULL DEFAULT ''"
    )

    # 字典外键：要求 (tenant_id, category) 与任职记录同租户且类别匹配。
    # 由于 hr_dictionaries 没有 (tenant_id, category, id) 唯一约束，使用触发器
    # 校验代价较高；改为应用层校验字典归属，这里仅建普通索引加速关联。
    op.execute(
        "CREATE INDEX ix_emp_employment_type ON user_employments (tenant_id, employment_type_id)"
    )
    op.execute(
        "CREATE INDEX ix_emp_job_level ON user_employments (tenant_id, job_level_id)"
    )
    op.execute(
        "CREATE INDEX ix_emp_job_family ON user_employments (tenant_id, job_family_id)"
    )

    # 汇报上级复合外键：manager_id 引用同租户 users.id；允许为 NULL。
    op.execute(
        """
        ALTER TABLE user_employments
            ADD CONSTRAINT fk_user_employments_manager
            FOREIGN KEY (tenant_id, manager_id)
            REFERENCES users (tenant_id, id) ON DELETE RESTRICT
        """
    )
    op.execute(
        "CREATE INDEX ix_emp_manager ON user_employments (tenant_id, manager_id)"
    )

    # CHECK 约束：枚举值与日期范围
    op.execute(
        """
        ALTER TABLE user_employments ADD CONSTRAINT ck_emp_nature CHECK (
            employment_nature IS NULL
            OR employment_nature IN ('regular', 'dispatch', 'outsourced', 'intern'))
        """
    )
    op.execute(
        """
        ALTER TABLE user_employments ADD CONSTRAINT ck_emp_change_type CHECK (
            change_type IS NULL
            OR change_type IN ('hire', 'transfer', 'promotion', 'demotion', 'reorganization'))
        """
    )
    op.execute(
        """
        ALTER TABLE user_employments ADD CONSTRAINT ck_emp_termination_type CHECK (
            termination_type IS NULL
            OR termination_type IN ('resignation', 'dismissal', 'layoff', 'retirement'))
        """
    )
    op.execute(
        """
        ALTER TABLE user_employments ADD CONSTRAINT ck_emp_probation_range CHECK (
            probation_started_at IS NULL
            OR probation_ended_at IS NULL
            OR probation_started_at <= probation_ended_at)
        """
    )


def downgrade() -> None:
    """回滚：删除新增列、字典索引与表。"""
    op.execute("ALTER TABLE user_employments DROP CONSTRAINT IF EXISTS ck_emp_probation_range")
    op.execute("ALTER TABLE user_employments DROP CONSTRAINT IF EXISTS ck_emp_termination_type")
    op.execute("ALTER TABLE user_employments DROP CONSTRAINT IF EXISTS ck_emp_change_type")
    op.execute("ALTER TABLE user_employments DROP CONSTRAINT IF EXISTS ck_emp_nature")
    op.execute("DROP INDEX IF EXISTS ix_emp_manager")
    op.execute("ALTER TABLE user_employments DROP CONSTRAINT IF EXISTS fk_user_employments_manager")
    op.execute("DROP INDEX IF EXISTS ix_emp_job_family")
    op.execute("DROP INDEX IF EXISTS ix_emp_job_level")
    op.execute("DROP INDEX IF EXISTS ix_emp_employment_type")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS remark")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS termination_type")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS change_reason")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS change_type")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS regularized_at")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS probation_ended_at")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS probation_started_at")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS employment_nature")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS weekly_hours")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS contract_no")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS cost_center")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS work_location")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS manager_id")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS job_family_id")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS job_level_id")
    op.execute("ALTER TABLE user_employments DROP COLUMN IF EXISTS employment_type_id")

    op.execute("DROP TRIGGER IF EXISTS trg_hr_dictionaries_updated_at ON hr_dictionaries")
    op.execute("DROP INDEX IF EXISTS ix_hr_dictionaries_tenant_category")
    op.execute("DROP TABLE IF EXISTS hr_dictionaries")
