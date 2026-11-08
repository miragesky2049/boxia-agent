"""文档切分器：纯文本按段落滑窗；markdown 按标题层级切分并保留标题路径。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Chunk:
    """切分结果单元；heading_path 用于 markdown 场景标识所属章节路径。"""

    content: str
    heading_path: list[str] = field(default_factory=list)


def split_text(
    text: str,
    *,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> list[str]:
    """纯文本切分：段落聚合 + 字符滑窗（pdf/docx/无标题文本走这条路径）。"""
    if not text or not text.strip():
        return []

    normalized = re.sub(r"\r\n?", "\n", text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", normalized) if p.strip()]
    if not paragraphs:
        paragraphs = [normalized.strip()]

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if not current:
            current = para
            continue
        if len(current) + len(para) + 1 <= chunk_size:
            current = f"{current}\n{para}"
            continue
        chunks.append(current)
        tail = current[-chunk_overlap:] if chunk_overlap > 0 else ""
        current = f"{tail}\n{para}" if tail else para

    if current:
        chunks.append(current)

    return [c.strip() for c in chunks if c.strip()]


# 标题正则：# / ## / ### 开头，最多支持 6 级
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def split_markdown(
    text: str,
    *,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> list[Chunk]:
    """Markdown 切分：按 # 标题维护层级栈，每个 chunk 自带 heading_path。

    策略：
      1. 逐行扫描，遇到 #/##/### 时把上一 section 内容切分 flush；
      2. 普通行（含空行）累加到当前 section buffer；
      3. buffer 超过 chunk_size 时立即切分，保留 overlap；
      4. 标题本身不写入 chunk content，但 heading_path 挂在 Chunk 上。
    """
    if not text or not text.strip():
        return []

    normalized = re.sub(r"\r\n?", "\n", text)
    lines = normalized.split("\n")

    chunks: list[Chunk] = []
    heading_stack: list[str] = []
    current_heading_path: list[str] = []
    # 当前 section 累积的纯文本（段落间用 \n 连接）
    buffer_lines: list[str] = []
    # 已经切分出去的文本长度（用于控制 overlap）
    flushed_text = ""

    def flush_section(force: bool = False) -> None:
        """把当前 buffer 切成 chunk 并清空。force=True 时即使未超 chunk_size 也切。"""
        nonlocal buffer_lines, flushed_text
        section_text = "\n".join(buffer_lines).strip()
        if not section_text:
            buffer_lines = []
            return
        if not force and len(section_text) <= chunk_size:
            # section 还没到 chunk_size，继续累积
            return
        pieces = _sliding_window_split(section_text, chunk_size, chunk_overlap)
        for piece in pieces:
            piece = piece.strip()
            if piece:
                chunks.append(Chunk(content=piece, heading_path=list(current_heading_path)))
        # 保留尾部 overlap 作为下一段起点（跨 section 不保留，避免标题串味）
        flushed_text = section_text
        buffer_lines = []

    for raw_line in lines:
        line = raw_line.rstrip()
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            # 遇到新标题：先把上一 section 强制切完
            flush_section(force=True)
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(title)
            current_heading_path = list(heading_stack)
            continue

        stripped = line.strip()
        if not stripped:
            # 空行：作为段落分隔，但仍累加到 buffer（保留原文结构）
            if buffer_lines:
                buffer_lines.append("")
            continue

        buffer_lines.append(stripped)
        # 实时检查：buffer 长度超过 chunk_size 时立即切分
        current_text = "\n".join(buffer_lines)
        if len(current_text) > chunk_size:
            flush_section(force=False)

    # 文件末尾收尾
    flush_section(force=True)

    return [c for c in chunks if c.content]


def _sliding_window_split(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """对已聚合的 section 文本做滑窗切分（内部复用，不暴露给业务）。"""
    if len(text) <= chunk_size:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        pieces.append(text[start:end])
        if end == len(text):
            break
        start = end - chunk_overlap
    return pieces
