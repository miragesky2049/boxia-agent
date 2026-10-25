"""技能包用例：虚拟目录读写、zip 导入导出、平台技能克隆到租户。

存储模型：一个技能即一个虚拟目录，文件路径为技能根目录下的相对路径；
物理隔离完全由所属 skills.tenant_id 决定（None=平台级，非空=租户级），
文件表不额外冗余租户字段，避免与 skills 归属不一致。
"""

from __future__ import annotations

import copy
import io
import zipfile
from collections.abc import Sequence

from internal.application.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from internal.domain.entity.request_context import RequestContext
from internal.domain.entity.resource import Skill, SkillFile
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.config.settings import get_settings

ENTRY_PATH = "SKILL.md"
MAX_PATH_LENGTH = 512
MAX_SEGMENT_LENGTH = 255
_FORBIDDEN_PATH_CHARS = set(': *?"<>|')
_SKIP_DIRECTORIES = {"__MACOSX", ".git", ".svn", ".idea"}
_SKIP_FILENAMES = {".DS_Store", "Thumbs.db"}


def normalize_path(raw: str) -> str:
    """校验并规范化技能包内相对路径，拒绝穿越与不可移植字符。"""
    if not raw or len(raw) > MAX_PATH_LENGTH:
        raise ValidationError(f"文件路径长度需在 1-{MAX_PATH_LENGTH} 之间")
    path = raw.strip()
    if not path:
        raise ValidationError("文件路径不能为空")
    if path.startswith("/"):
        raise ValidationError("文件路径不能以 / 开头")
    if "\\" in path:
        raise ValidationError("文件路径统一使用 / 分隔")
    if any(ord(char) < 32 for char in path):
        raise ValidationError("文件路径包含控制字符")
    if any(char in _FORBIDDEN_PATH_CHARS for char in path):
        raise ValidationError("文件路径包含不可移植字符")
    parts = path.split("/")
    for part in parts:
        if not part or part in {".", ".."}:
            raise ValidationError("文件路径不能包含空段、. 或 ..")
        if part != part.strip() or part.endswith("."):
            raise ValidationError("文件路径分段不能以空格开头结尾或以 . 结尾")
        if len(part) > MAX_SEGMENT_LENGTH:
            raise ValidationError(f"单个路径分段不能超过 {MAX_SEGMENT_LENGTH} 个字符")
    return "/".join(parts)


def should_skip_import_path(path: str) -> bool:
    """跳过压缩包中的系统垃圾文件。"""
    parts = path.split("/")
    if any(part in _SKIP_DIRECTORIES for part in parts):
        return True
    filename = parts[-1]
    return filename in _SKIP_FILENAMES or filename.startswith("._")


class SkillPackageService:
    """技能包管理用例；所有文件操作先校验所属技能的可见/可维护范围。"""

    def __init__(self, uow: UnitOfWork, context: RequestContext):
        self._uow = uow
        self._context = context

    def list_files(self, skill_id: int, prefix: str | None = None) -> list[SkillFile]:
        """列出技能包文件元数据（不含正文）。"""
        skill = self._require_readable(skill_id)
        normalized_prefix = None
        if prefix and prefix.strip():
            normalized_prefix = normalize_path(prefix.strip().rstrip("/"))
        return self._uow.skill_files.list_by_skill(skill.id, normalized_prefix)

    def read_file(self, skill_id: int, path: str) -> SkillFile:
        """读取单个文件。"""
        skill = self._require_readable(skill_id)
        normalized = normalize_path(path)
        file = self._uow.skill_files.get(skill.id, normalized)
        if file is None:
            raise NotFoundError("技能文件不存在")
        return file

    def write_file(
        self,
        skill_id: int,
        *,
        path: str,
        content: str,
        expected_hash: str | None = None,
    ) -> SkillFile:
        """新增或覆盖文件；写入 SKILL.md 时同步 skills.content。"""
        skill = self._require_manageable(skill_id)
        normalized = normalize_path(path)
        self._validate_content(normalized, content)
        existing = self._uow.skill_files.get(skill.id, normalized)
        if expected_hash is not None:
            actual_hash = existing.content_hash if existing else None
            if actual_hash != expected_hash:
                raise ConflictError("文件已被修改，请刷新后重试")
        self._ensure_quota(skill.id, normalized, content)
        file = self._uow.skill_files.upsert(skill.id, normalized, content)
        if normalized == ENTRY_PATH:
            self._sync_entry(skill.id, content)
        self._uow.commit()
        return file

    def delete_file(self, skill_id: int, path: str) -> None:
        """删除文件；删除 SKILL.md 时清空入口 content。"""
        skill = self._require_manageable(skill_id)
        normalized = normalize_path(path)
        if not self._uow.skill_files.delete(skill.id, normalized):
            raise NotFoundError("技能文件不存在")
        if normalized == ENTRY_PATH:
            self._sync_entry(skill.id, "")
        self._uow.commit()

    def replace_files(self, skill_id: int, files: dict[str, str]) -> list[SkillFile]:
        """事务内全量替换技能包（目录导入与 zip 导入共用）。"""
        skill = self._require_manageable(skill_id)
        normalized_files: dict[str, str] = {}
        total_bytes = 0
        settings = get_settings()
        for raw_path, content in files.items():
            path = normalize_path(raw_path)
            if path in normalized_files:
                raise ValidationError(f"文件路径重复：{path}")
            self._validate_content(path, content)
            normalized_files[path] = content
            total_bytes += len(content.encode("utf-8"))
        if not normalized_files:
            raise ValidationError("技能包不能为空")
        if len(normalized_files) > settings.skill_package_max_files:
            raise ValidationError(f"技能包文件数不能超过 {settings.skill_package_max_files}")
        if total_bytes > settings.skill_package_max_total_bytes:
            raise ValidationError("技能包总大小超出限制")
        replaced = self._uow.skill_files.replace_all(skill.id, sorted(normalized_files.items()))
        self._sync_entry(skill.id, normalized_files.get(ENTRY_PATH, ""))
        self._uow.commit()
        return replaced

    def import_zip(self, skill_id: int, data: bytes) -> list[SkillFile]:
        """从 zip 压缩包导入并全量替换技能包。"""
        return self.replace_files(skill_id, self._parse_zip(data))

    def export_zip(self, skill_id: int) -> bytes:
        """导出技能包为确定性 zip（固定时间戳，便于比对）。"""
        skill = self._require_readable(skill_id)
        files = self._uow.skill_files.list_by_skill(skill.id, include_content=True)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                info = zipfile.ZipInfo(file.path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, file.content)
        return buffer.getvalue()

    def clone_to_current_tenant(
        self,
        skill_id: int,
        name: str | None = None,
        actor_role_ids: Sequence[int] = (),
    ) -> Skill:
        """把可见技能克隆到当前租户并授权给创建者角色；平台级技能保持只读。"""
        source = self._require_readable(skill_id)
        if self._context.is_platform:
            raise ValidationError("产品级平台无需克隆，请直接维护产品级技能")
        target_name = (name or f"{source.name}（副本）").strip()
        if not target_name:
            raise ValidationError("技能名称不能为空")
        if len(target_name) > 100:
            raise ValidationError("技能名称不能超过 100 个字符")
        if self._uow.skills.name_exists(target_name):
            raise ConflictError("技能名称已存在")
        files = self._uow.skill_files.list_by_skill(source.id, include_content=True)
        created = self._uow.skills.create(
            {
                "name": target_name,
                "description": source.description,
                "content": source.content,
                "config": copy.deepcopy(source.config),
                "is_enabled": source.is_enabled,
            }
        )
        if files:
            self._uow.skill_files.replace_all(
                created.id, [(file.path, file.content) for file in files]
            )
        tenant_id = getattr(created, "tenant_id", None)
        role_ids = sorted({int(role_id) for role_id in actor_role_ids})
        if tenant_id is not None:
            for role_id in role_ids:
                self._uow.resource_grants.add_for_role(
                    role_id, tenant_id, "skill", [created.id], None
                )
        self._uow.commit()
        return created

    def _require_readable(self, skill_id: int) -> Skill:
        skill = self._uow.skills.get(skill_id)
        if skill is None:
            raise NotFoundError("技能不存在")
        return skill

    def _require_manageable(self, skill_id: int) -> Skill:
        skill = self._require_readable(skill_id)
        if not self._context.can_manage(skill.tenant_id):
            raise ForbiddenError("产品级技能仅产品级平台可维护，租户可克隆后再修改")
        return skill

    def _sync_entry(self, skill_id: int, content: str) -> None:
        """skills.content 是 SKILL.md 的镜像，供列表与搜索使用。"""
        self._uow.skills.update(skill_id, {"content": content})

    def _validate_content(self, path: str, content: str) -> None:
        settings = get_settings()
        size = len(content.encode("utf-8"))
        if size > settings.skill_package_max_file_bytes:
            raise ValidationError(f"文件 {path} 超过单文件大小限制")
        if "\x00" in content:
            raise ValidationError(f"文件 {path} 包含二进制内容，技能包仅支持文本文件")

    def _ensure_quota(self, skill_id: int, path: str, content: str) -> None:
        settings = get_settings()
        count, total = self._uow.skill_files.stats(skill_id)
        existing = self._uow.skill_files.get(skill_id, path)
        if existing is None and count >= settings.skill_package_max_files:
            raise ValidationError(f"技能包文件数不能超过 {settings.skill_package_max_files}")
        new_total = total - (existing.size_bytes if existing else 0) + len(content.encode("utf-8"))
        if new_total > settings.skill_package_max_total_bytes:
            raise ValidationError("技能包总大小超出限制")

    def _parse_zip(self, data: bytes) -> dict[str, str]:
        settings = get_settings()
        if not data:
            raise ValidationError("压缩包为空")
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ValidationError("压缩包格式不正确") from exc
        files: dict[str, str] = {}
        total_bytes = 0
        with archive:
            for info in archive.infolist():
                if info.is_dir() or should_skip_import_path(info.filename):
                    continue
                path = normalize_path(info.filename)
                if len(files) >= settings.skill_package_max_files:
                    raise ValidationError(
                        f"技能包文件数不能超过 {settings.skill_package_max_files}"
                    )
                if info.file_size > settings.skill_package_max_file_bytes:
                    raise ValidationError(f"文件 {path} 超过单文件大小限制")
                raw = archive.read(info)
                if len(raw) > settings.skill_package_max_file_bytes:
                    raise ValidationError(f"文件 {path} 超过单文件大小限制")
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValidationError(f"文件 {path} 不是 UTF-8 文本") from exc
                self._validate_content(path, content)
                total_bytes += len(raw)
                if total_bytes > settings.skill_package_max_total_bytes:
                    raise ValidationError("技能包总大小超出限制")
                files[path] = content
        if not files:
            raise ValidationError("压缩包中没有可导入的文件")
        return _strip_common_root(files)


def _strip_common_root(files: dict[str, str]) -> dict[str, str]:
    """压缩包整体带一层技能目录时自动去掉，兼容 zip -r skill/ . 的常见打包方式。"""
    roots = {path.split("/", 1)[0] for path in files}
    if len(roots) != 1 or not all("/" in path for path in files):
        return files
    root = next(iter(roots))
    if root == ENTRY_PATH:
        return files
    return {path.split("/", 1)[1]: content for path, content in files.items()}
