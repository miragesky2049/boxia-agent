"""prompt 优化服务：调 LLM 把粗糙的 system prompt 改写成结构化、可执行的版本。"""

from __future__ import annotations

import json
import logging
import re

from internal.application.errors import ValidationError
from internal.application.apps.model_service import ModelService

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """你是一名资深 Prompt Engineering 专家。给定用户提供的原始 system prompt 和（可选的）任务描述，你需要输出一份优化后的 system prompt。

优化目标：
1. **角色清晰**：明确模型扮演的角色、专业领域、语气风格。
2. **任务明确**：把模糊意图拆成可执行的步骤或输出要求。
3. **约束具体**：列出必须遵守的规则（长度、格式、禁止事项、输入变量约定）。
4. **示例锚点**：如原始 prompt 已有示例则保留；否则可在末尾加 1-2 个简短示例占位。
5. **保留原意**：不要改变业务意图，不要加入原始 prompt 没有要求的能力。

输出严格 JSON，不要任何额外解释：
{"optimized_prompt": "优化后的完整 system prompt 文本", "suggestions": ["改动点1", "改动点2"]}

要求：
- optimized_prompt 必须是可直接复制粘贴使用的完整文本，不要用占位符；
- suggestions 最多 3 条，每条一句话说明改了什么、为什么；
- 如果原始 prompt 已经足够好，optimized_prompt 可与原文基本一致，但建议仍补充结构化分段；
- 输出必须是合法 JSON，不要 markdown 代码块包裹。"""


class PromptOptimizeService:
    """调用 LLM 优化用户输入的 system prompt；不做持久化，由前端决定是否写回 graph。"""

    def __init__(self, model_service: ModelService) -> None:
        self._model_service = model_service

    async def optimize(
        self,
        *,
        model_id: str,
        current_prompt: str,
        task_description: str = "",
    ) -> dict:
        """返回 {"optimized_prompt": str, "suggestions": list[str]}。"""
        if not current_prompt or not current_prompt.strip():
            raise ValidationError("current_prompt 不能为空")
        if not model_id or not model_id.strip():
            raise ValidationError("model_id 不能为空")

        client = self._model_service.get_client(model_id)

        user_content_parts = ["【原始 system prompt】", current_prompt.strip()]
        if task_description and task_description.strip():
            user_content_parts.append("")
            user_content_parts.append("【任务描述（可选）】")
            user_content_parts.append(task_description.strip())
        user_content_parts.append("")
        user_content_parts.append("请输出 JSON：")
        user_content = "\n".join(user_content_parts)

        try:
            response = await client.chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=2000,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("prompt optimize llm call failed")
            raise ValidationError(f"调用模型失败: {exc}") from exc

        parsed = self._parse_json(response.content)
        if not parsed:
            raise ValidationError("模型返回无法解析，请重试或更换模型")

        optimized = (parsed.get("optimized_prompt") or "").strip()
        if not optimized:
            raise ValidationError("模型未返回 optimized_prompt")

        suggestions_raw = parsed.get("suggestions") or []
        suggestions = [str(s).strip() for s in suggestions_raw if str(s).strip()][:3]
        return {"optimized_prompt": optimized, "suggestions": suggestions}

    @staticmethod
    def _parse_json(content: str) -> dict | None:
        """从 LLM 输出中提取 JSON 对象；容忍 ```json 包裹与前后杂文本。"""
        if not content:
            return None
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            logger.warning("prompt optimize json parse failed content_len=%d", len(content or ""))
        return None
