"""把"陪练剧本生成智能体"的提示词与 v8 skill 录入 anan 租户。

执行：
    cd backend
    uv run python -m scripts.seed_anan_coach_agent
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import text

from internal.infrastructure.id.uuid7 import new_uuid
from internal.infrastructure.model.database import get_engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TENANT_CODE = "anan"
AGENT_NAME = "陪练剧本生成智能体"

SRC_ROOT = Path(r"D:\GitlabCode\面试资料\AI Agent\陪练剧本生成智能体")
PROMPT_FILE = SRC_ROOT / "陪练剧本生成智能体-提示词.md"
SKILL_DIR = SRC_ROOT / "free-script-creation-v8" / "free-script-creation-v8"
SKILL_MAIN = SKILL_DIR / "SKILL.md"
SKILL_REFS = [
    SKILL_DIR / "references" / "01_precheck" / "STEP.md",
    SKILL_DIR / "references" / "02_generate_save" / "STEP.md",
    SKILL_DIR / "references" / "03_complete" / "STEP.md",
]


def build_skill_content() -> str:
    parts = [SKILL_MAIN.read_text(encoding="utf-8").rstrip()]
    for ref in SKILL_REFS:
        parts.append("\n\n---\n\n")
        parts.append(ref.read_text(encoding="utf-8").rstrip())
    return "\n".join(parts)


def normalize_prompt_content(raw: str) -> str:
    """把主提示词原文适配到当前已录入的 skill 版本。

    源主提示词路由表写的是 free-script-creation-v7（从零创建分支），
    但我们录入的是 v8。这里把 v7 替换为 v8，保持路由表与已录 skill 一致。
    """
    return raw.replace("free-script-creation-v7", "free-script-creation-v8")


def main() -> None:
    engine = get_engine()

    with engine.begin() as conn:
        tenant_id = conn.execute(
            text("SELECT id FROM tenants WHERE code = :code"),
            {"code": TENANT_CODE},
        ).scalar_one()

        agent_id = conn.execute(
            text(
                "SELECT id FROM agents WHERE tenant_id = :tid AND lower(name) = lower(:name)"
            ),
            {"tid": tenant_id, "name": AGENT_NAME},
        ).scalar_one()
        logger.info("目标 agent: %s", agent_id)

        # ---- 1. 写入主提示词（category=system，运行时自动注入 system_prompt）----
        prompt_content = normalize_prompt_content(
            PROMPT_FILE.read_text(encoding="utf-8").strip()
        )
        prompt_id = conn.execute(
            text(
                "SELECT id FROM prompts WHERE tenant_id = :tid AND lower(name) = lower(:name)"
            ),
            {"tid": tenant_id, "name": "系统提示词"},
        ).scalar_one_or_none() or new_uuid()
        conn.execute(
            text(
                """
                INSERT INTO prompts (id, name, description, content, variables, category,
                                     is_enabled, tenant_id, agent_id)
                VALUES (:id, :name, :desc, :content, '[]'::jsonb, :category, TRUE, :tid, :aid)
                ON CONFLICT (id) DO UPDATE SET
                  content = EXCLUDED.content,
                  description = EXCLUDED.description,
                  category = EXCLUDED.category,
                  is_enabled = TRUE,
                  agent_id = EXCLUDED.agent_id,
                  updated_at = now()
                """
            ),
            {
                "id": prompt_id,
                "name": "系统提示词",
                "desc": "陪练剧本生成智能体的主提示词，定义 sceneMode 路由与最高指令",
                "content": prompt_content,
                "category": "system",
                "tid": tenant_id,
                "aid": agent_id,
            },
        )
        logger.info("已写入提示词: %s", prompt_id)

        # ---- 2. 写入 skill ----
        skill_content = build_skill_content()
        skill_id = conn.execute(
            text(
                "SELECT id FROM skills WHERE tenant_id = :tid AND lower(name) = lower(:name)"
            ),
            {"tid": tenant_id, "name": "free-script-creation-v8"},
        ).scalar_one_or_none() or new_uuid()
        conn.execute(
            text(
                """
                INSERT INTO skills (id, name, description, content, config, is_enabled,
                                    tenant_id, agent_id)
                VALUES (:id, :name, :desc, :content, '{}'::jsonb, TRUE, :tid, :aid)
                ON CONFLICT (id) DO UPDATE SET
                  content = EXCLUDED.content,
                  description = EXCLUDED.description,
                  is_enabled = TRUE,
                  agent_id = EXCLUDED.agent_id,
                  updated_at = now()
                """
            ),
            {
                "id": skill_id,
                "name": "free-script-creation-v8",
                "desc": (
                    "v8 前置问齐+一步生成：ask user question 收敛要素后一次性生成完整剧本"
                    "（场景/环节/角色/策略/评分）并落库，最后输出完成卡片"
                ),
                "content": skill_content,
                "tid": tenant_id,
                "aid": agent_id,
            },
        )
        logger.info("已写入 skill: %s", skill_id)

        # ---- 3. 关联 agent_skills ----
        conn.execute(
            text(
                """
                INSERT INTO agent_skills (agent_id, skill_id)
                VALUES (:aid, :sid)
                ON CONFLICT DO NOTHING
                """
            ),
            {"aid": agent_id, "sid": skill_id},
        )
        logger.info("已绑定 agent_skills: agent=%s skill=%s", agent_id, skill_id)

    logger.info("录入完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        logger.exception("录入失败: %s", exc)
        sys.exit(1)
