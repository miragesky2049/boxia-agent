-- Boxia Agent 管理端种子数据（历史脚本，仅本地演示）
-- 已由 Alembic 迁移 + scripts/create_admin.py + scripts/seed_demo.py 取代。
-- 管理员账号请通过 scripts.create_admin 按密码策略创建，本文件不再预置任何默认凭据。

INSERT INTO skills (name, description, content, config)
VALUES
    ('智能创建剧本技能', '根据业务信息自动生成陪练剧本', '根据输入的业务场景与角色信息，生成结构化的陪练剧本。', '{"scene":"script"}'),
    ('剧本生成v8', '剧本生成技能第八版', '按照标准化模板输出剧本，包含场景、角色、对话目标。', '{"version":"v8"}')
ON CONFLICT DO NOTHING;

INSERT INTO tools (name, description, type, config)
VALUES
    ('保存剧本对话环节数据到数据库', '自动保存对话环节的数据到数据库', 'http', '{"method":"POST"}'),
    ('获取剧本未评分对话信息', '自动获取未评分的对话信息', 'http', '{"method":"GET"}'),
    ('保存剧本评分评价维度', '自动保存评分评价维度', 'http', '{"method":"POST"}'),
    ('获取剧本未生成内容', '自动获取尚未生成的剧本内容', 'http', '{"method":"GET"}'),
    ('保存剧本场景特色背景', '自动保存场景特色背景', 'http', '{"method":"POST"}')
ON CONFLICT DO NOTHING;

INSERT INTO components (name, description, type, config)
VALUES
    ('欢迎语卡片', '对话开场的欢迎卡片组件', 'card', '{}'),
    ('常见问题组件', '展示常见问题的列表组件', 'panel', '{}'),
    ('输入框增强组件', '带快捷输入的输入框组件', 'input', '{}')
ON CONFLICT DO NOTHING;

INSERT INTO prompts (name, description, content, variables, category)
VALUES
    ('角色设定模板', '用于生成角色设定的提示词模板', '你是一名{{role}}，需要完成{{task}}。', '["role","task"]', 'agent'),
    ('兜底回复模板', '无法处理问题时的兜底话术', '我暂时无法处理这个问题，请尝试换个问法。', '[]', 'conversation')
ON CONFLICT DO NOTHING;

INSERT INTO agents (name, avatar_url, description, config, is_enabled)
VALUES (
    '陪练剧本生成智能体',
    '',
    '根据业务场景、已有剧本或模板，引导用户分步创建标准化 AI 陪练对话剧本。',
    '{
        "model": {
            "model": "glm-5",
            "temperature": 0.2,
            "max_output_tokens": 8192,
            "reasoning_effort": "medium",
            "context_window": 65536,
            "max_thinking_tokens": 2000
        },
        "prompt": {
            "role_setting": "你是陪练剧本生成助手，负责引导用户完成剧本创建。",
            "persona": "",
            "user_prompt": "",
            "memory_count": 20,
            "memory_model": "glm-5"
        },
        "memory": {
            "enabled": false,
            "task_memory_prompt": "",
            "long_term_enabled": false,
            "long_term_prompt": ""
        },
        "conversation": {
            "welcome": "你好，我是陪练剧本生成助手，请告诉我你的业务场景。",
            "fallback": "我暂时无法处理这个问题，请尝试换个问法。",
            "input_placeholder": "请输入你的业务场景或剧本需求",
            "common_questions_enabled": false,
            "faqs": []
        },
        "channel": {
            "type": "web",
            "enabled": true
        },
        "knowledge": {
            "enabled": false,
            "dataset_ids": []
        },
        "other": {
            "system_prompt_template": "default",
            "max_turns": 30,
            "deep_thinking": true,
            "show_reasoning": true,
            "web_search": false,
            "create_task": true,
            "history_task": true,
            "scheduled_task": false,
            "artifacts": false,
            "upload_attachment": true,
            "task_list": false
        },
        "extensions": {
            "welcome": null,
            "welcome_footer": null,
            "faq": null,
            "input_top": null,
            "artifacts": null,
            "knowledge": null
        }
    }'::jsonb,
    TRUE
)
ON CONFLICT DO NOTHING;
