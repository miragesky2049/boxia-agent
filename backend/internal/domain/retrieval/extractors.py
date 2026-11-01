"""文档内容提取器：根据 source_type 把不同格式转成纯文本。"""

from __future__ import annotations

import io
import logging

from pypdf import PdfReader

logger = logging.getLogger(__name__)


class DocumentExtractError(Exception):
    """文档解析失败：ingestion 服务捕获后写入 document.ingest_error。"""


def extract_text(source_type: str, content: bytes | str) -> str:
    """按 source_type 提取纯文本。

    - text / markdown：直接解码 utf-8
    - pdf：用 pypdf 逐页抽取
    - docx：用 python-docx 遍历段落
    """
    st = (source_type or "").lower()
    if st in {"text", "markdown", "md"}:
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return content

    if isinstance(content, str):
        raise DocumentExtractError(f"{source_type} 需要传 bytes 内容")

    if st == "pdf":
        return _extract_pdf(content)
    if st == "docx":
        return _extract_docx(content)
    raise DocumentExtractError(f"不支持的文档类型: {source_type}")


def _extract_pdf(data: bytes) -> str:
    """PDF 逐页抽取文本。"""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
        return "\n\n".join(pages)
    except Exception as exc:  # noqa: BLE001 - pypdf 错误类型不统一
        raise DocumentExtractError(f"PDF 解析失败: {exc}") from exc


def _extract_docx(data: bytes) -> str:
    """DOCX 段落抽取；python-docx 只接受文件路径或类文件对象。"""
    try:
        from docx import Document as DocxDocument  # 延迟导入，避免纯文本场景强依赖

        document = DocxDocument(io.BytesIO(data))
        paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except Exception as exc:  # noqa: BLE001
        raise DocumentExtractError(f"DOCX 解析失败: {exc}") from exc


def sniff_source_type(filename: str, content_type: str | None = None) -> str:
    """根据文件名后缀与 Content-Type 推断 source_type。"""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".docx"):
        return "docx"
    if name.endswith(".md") or name.endswith(".markdown"):
        return "markdown"
    if content_type:
        ct = content_type.lower()
        if "pdf" in ct:
            return "pdf"
        if "wordprocessingml" in ct or "msword" in ct:
            return "docx"
    return "text"
