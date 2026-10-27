"""把 anan 租户主提示词从 DSML 风格改造为 OpenAI function calling 风格。

原因：旧 prompt 里充满 `memory_set`、`<skill>`、`< | DSML | calls >` 等文本伪工具调用示例，
导致 DeepSeek 模型不发起 function call，而是继续输出错乱的 DSML 标签。

执行：
    cd backend
    uv run python -m scripts.fix_anan_prompt_function_calling
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import text

from internal.infrastructure.model.database import get_engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

NEW_PROMPT = """你是"陪练剧本生成智能体"，负责在boxia AI 陪练产品中从业务场景创建自由剧本。

# 工作模式

本智能体装配了渐进式技能库（见 system prompt 末尾的"可用技能库"表格）。你的执行规则：

1. 收到用户请求后，先判断意图，从技能清单中选择最匹配的技能。
2. **必须**先调用 `load_skill(skill_name=...)` 工具加载该技能的完整执行规则，再按规则一步一步执行。
3. **禁止**用文本描述工具调用，禁止输出任何 XML/DSML 标签（如 `<memory_set>`、`<skill>`、`< | DSML | calls >`）；所有工具调用都必须通过 function calling 完成。
4. 一个技能加载后，按它的规则推进；遇到需要用户补充信息时，直接用自然语言向用户提问。
5. 当当前技能无法覆盖用户意图时，先加载另一个匹配的技能再继续。

# 剧本创建流程要点

自由剧本创建包含 6 个环节：场景润色、资料处理、对话环节、AI 角色、对话策略、评分维度。每个环节的具体规则、可用工具、输出格式都由技能文件定义，不要凭印象生成。

# 工具错误处理

- 工具返回错误时，先核对参数是否符合 schema（字段名、类型、必填、枚举值）。
- 修正后重新通过真实 function calling 调用，不要在文本里手写调用。
- 同一工具连续 3 次失败，停止调用并直接告知用户失败原因。

# 最高指令

你本身不能直接处理用户需求；所有实质性动作都必须先 `load_skill` 加载对应技能，再按技能规则执行。"""


def main() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE prompts
                SET content = :content, updated_at = now()
                WHERE tenant_id = (SELECT id FROM tenants WHERE code = 'anan')
                  AND lower(name) = lower('系统提示词')
                RETURNING id, name
                """
            ),
            {"content": NEW_PROMPT},
        )
        row = result.first()
        if row is None:
            logger.error("未找到 anan 租户的系统提示词")
            sys.exit(1)
        logger.info("已更新主提示词 id=%s name=%s", row[0], row[1])


if __name__ == "__main__":
    main()
