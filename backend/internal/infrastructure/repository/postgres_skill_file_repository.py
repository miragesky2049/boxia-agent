"""技能包文件 PostgreSQL 仓储实现。"""

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, load_only

from internal.domain.entity.resource import SkillFile
from internal.infrastructure.model.resource import SkillFileModel

_MEDIA_TYPES = {
    ".md": "text/markdown",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".xml": "application/xml",
    ".html": "text/html",
}


def media_type_for(path: str) -> str:
    """按扩展名推断文本文件媒体类型。"""
    lower = path.lower()
    for suffix, media_type in _MEDIA_TYPES.items():
        if lower.endswith(suffix):
            return media_type
    return "text/plain"


def content_hash(content: str) -> str:
    """计算 UTF-8 内容的 SHA-256，用于乐观并发与去重校验。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class PostgresSkillFileRepository:
    """技能包文件仓储；作用域校验由应用层基于所属技能完成。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _to_entity(self, row: SkillFileModel, include_content: bool = True) -> SkillFile:
        return SkillFile(
            id=row.id,
            skill_id=row.skill_id,
            path=row.path,
            content=row.content if include_content else "",
            content_hash=row.content_hash,
            size_bytes=row.size_bytes,
            media_type=row.media_type,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _payload(self, path: str, content: str) -> dict[str, Any]:
        return {
            "content": content,
            "content_hash": content_hash(content),
            "size_bytes": len(content.encode("utf-8")),
            "media_type": media_type_for(path),
        }

    def list_by_skill(
        self, skill_id: UUID, prefix: str | None = None, include_content: bool = False
    ) -> list[SkillFile]:
        """按路径排序列出技能包文件；默认不加载正文，避免列表接口搬运整包。"""
        stmt = select(SkillFileModel).where(SkillFileModel.skill_id == skill_id)
        if prefix:
            stmt = stmt.where(SkillFileModel.path.startswith(prefix, autoescape=True))
        if not include_content:
            stmt = stmt.options(
                load_only(
                    SkillFileModel.id,
                    SkillFileModel.skill_id,
                    SkillFileModel.path,
                    SkillFileModel.content_hash,
                    SkillFileModel.size_bytes,
                    SkillFileModel.media_type,
                    SkillFileModel.created_at,
                    SkillFileModel.updated_at,
                )
            )
        rows = self._session.scalars(stmt.order_by(SkillFileModel.path.asc())).all()
        return [self._to_entity(row, include_content=include_content) for row in rows]

    def get(self, skill_id: UUID, path: str) -> SkillFile | None:
        """按相对路径查询文件。"""
        row = self._session.scalar(
            select(SkillFileModel).where(
                SkillFileModel.skill_id == skill_id, SkillFileModel.path == path
            )
        )
        return self._to_entity(row) if row else None

    def upsert(self, skill_id: UUID, path: str, content: str) -> SkillFile:
        """新增或覆盖文件。"""
        row = self._session.scalar(
            select(SkillFileModel).where(
                SkillFileModel.skill_id == skill_id, SkillFileModel.path == path
            )
        )
        payload = self._payload(path, content)
        if row is None:
            row = SkillFileModel(skill_id=skill_id, path=path, **payload)
            self._session.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        self._session.flush()
        self._session.refresh(row)
        return self._to_entity(row)

    def delete(self, skill_id: UUID, path: str) -> bool:
        """删除文件。"""
        result = self._session.execute(
            delete(SkillFileModel).where(
                SkillFileModel.skill_id == skill_id, SkillFileModel.path == path
            )
        )
        return bool(getattr(result, "rowcount", 0))

    def replace_all(self, skill_id: UUID, files: list[tuple[str, str]]) -> list[SkillFile]:
        """事务内全量替换技能包文件。"""
        self._session.execute(delete(SkillFileModel).where(SkillFileModel.skill_id == skill_id))
        rows = [
            SkillFileModel(skill_id=skill_id, path=path, **self._payload(path, content))
            for path, content in files
        ]
        self._session.add_all(rows)
        self._session.flush()
        for row in rows:
            self._session.refresh(row)
        return [self._to_entity(row) for row in sorted(rows, key=lambda item: item.path)]

    def stats(self, skill_id: UUID) -> tuple[int, int]:
        """返回文件数与总字节数。"""
        count, total = self._session.execute(
            select(
                func.count(SkillFileModel.id), func.coalesce(func.sum(SkillFileModel.size_bytes), 0)
            ).where(SkillFileModel.skill_id == skill_id)
        ).one()
        return int(count), int(total)
