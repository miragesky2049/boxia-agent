-- Boxia Agent 管理端数据库结构（历史脚本）
-- 已由 Alembic 取代：migrations/0001_baseline.py 是当前唯一事实来源。
-- 仅保留用于早期手工初始化与对照；新环境请执行 `uv run alembic upgrade head`。
-- 说明：脚本幂等，重复执行不会报错；不负责删除既有数据。

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 管理员账号
CREATE TABLE IF NOT EXISTS admin_users (
    id              BIGSERIAL PRIMARY KEY,
    username        VARCHAR(64)  NOT NULL UNIQUE,
    password_hash   VARCHAR(100) NOT NULL,
    display_name    VARCHAR(64)  NOT NULL DEFAULT '',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 智能体
CREATE TABLE IF NOT EXISTS agents (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    avatar_url      VARCHAR(500) NOT NULL DEFAULT '',
    description     TEXT         NOT NULL DEFAULT '',
    config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_agents_config_object CHECK (jsonb_typeof(config) = 'object')
);

-- 技能
CREATE TABLE IF NOT EXISTS skills (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    description     TEXT         NOT NULL DEFAULT '',
    content         TEXT         NOT NULL DEFAULT '',
    config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_skills_config_object CHECK (jsonb_typeof(config) = 'object')
);

-- 工具
CREATE TABLE IF NOT EXISTS tools (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    description     TEXT         NOT NULL DEFAULT '',
    type            VARCHAR(32)  NOT NULL DEFAULT 'http',
    config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_tools_config_object CHECK (jsonb_typeof(config) = 'object')
);

-- 组件
CREATE TABLE IF NOT EXISTS components (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    description     TEXT         NOT NULL DEFAULT '',
    type            VARCHAR(32)  NOT NULL DEFAULT 'card',
    config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_components_config_object CHECK (jsonb_typeof(config) = 'object')
);

-- 提示词
CREATE TABLE IF NOT EXISTS prompts (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    description     TEXT         NOT NULL DEFAULT '',
    content         TEXT         NOT NULL DEFAULT '',
    variables       JSONB        NOT NULL DEFAULT '[]'::jsonb,
    category        VARCHAR(32)  NOT NULL DEFAULT '',
    is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_prompts_variables_array CHECK (jsonb_typeof(variables) = 'array')
);

-- 智能体与工具、技能的多对多关联
CREATE TABLE IF NOT EXISTS agent_tools (
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    tool_id  BIGINT NOT NULL REFERENCES tools(id)  ON DELETE CASCADE,
    PRIMARY KEY (agent_id, tool_id)
);

CREATE TABLE IF NOT EXISTS agent_skills (
    agent_id BIGINT NOT NULL REFERENCES agents(id)  ON DELETE CASCADE,
    skill_id BIGINT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY (agent_id, skill_id)
);

-- 名称唯一（忽略大小写）
CREATE UNIQUE INDEX IF NOT EXISTS ux_agents_name_lower     ON agents (lower(name));
CREATE UNIQUE INDEX IF NOT EXISTS ux_skills_name_lower     ON skills (lower(name));
CREATE UNIQUE INDEX IF NOT EXISTS ux_tools_name_lower      ON tools (lower(name));
CREATE UNIQUE INDEX IF NOT EXISTS ux_components_name_lower ON components (lower(name));
CREATE UNIQUE INDEX IF NOT EXISTS ux_prompts_name_lower    ON prompts (lower(name));

-- 列表排序与关联反向查询
CREATE INDEX IF NOT EXISTS ix_agents_updated_at     ON agents (updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_skills_updated_at     ON skills (updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_tools_updated_at      ON tools (updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_components_updated_at ON components (updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_prompts_updated_at    ON prompts (updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_agent_tools_tool_id   ON agent_tools (tool_id);
CREATE INDEX IF NOT EXISTS ix_agent_skills_skill_id ON agent_skills (skill_id);

-- updated_at 自动维护
DROP TRIGGER IF EXISTS trg_admin_users_updated_at ON admin_users;
CREATE TRIGGER trg_admin_users_updated_at BEFORE UPDATE ON admin_users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_agents_updated_at ON agents;
CREATE TRIGGER trg_agents_updated_at BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_skills_updated_at ON skills;
CREATE TRIGGER trg_skills_updated_at BEFORE UPDATE ON skills
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tools_updated_at ON tools;
CREATE TRIGGER trg_tools_updated_at BEFORE UPDATE ON tools
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_components_updated_at ON components;
CREATE TRIGGER trg_components_updated_at BEFORE UPDATE ON components
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_prompts_updated_at ON prompts;
CREATE TRIGGER trg_prompts_updated_at BEFORE UPDATE ON prompts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
