"""多模态消息内容构建（0074 PRD F9，20261107）。

从 graph/nodes/llm.py 抽出的纯函数，供 LLM 节点与 agent_loop 节点共用：
图片 URL 归一化 + OpenAI multi-modal content part 数组组装。
"""

from __future__ import annotations

from typing import Any


def normalize_image_urls(raw: Any) -> list[str]:
    """把 inputs/config 里的 images 原始值归一化为 URL 字符串列表。

    兼容形态：逗号分隔字符串（前端多图拼接）、字符串列表；其余返回空列表。
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        # 前端把多图拼成 "url1,url2,data:..." 形式；逗号分隔
        return [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if isinstance(x, str) and str(x).strip()]


def build_multimodal_content(text: str, images: list[str]) -> list[dict[str, Any]]:
    """把纯文本 + 图片 URL 列表组装成 OpenAI multi-modal content part 数组。"""
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    for url in images:
        parts.append({
            "type": "image_url",
            "image_url": {"url": url},
        })
    return parts
