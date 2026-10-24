"""技能用例：通用 CRUD 之上保持 skills.content 与包内 SKILL.md 一致。"""

from internal.application.errors import ConflictError, NotFoundError
from internal.application.resource_service import ResourceService
from internal.domain.entity.resource import Skill

ENTRY_PATH = "SKILL.md"


class SkillService(ResourceService[Skill]):
    """技能 CRUD；content 是入口文件的镜像，文件表是包内容的唯一来源。"""

    def create(self, values: dict) -> Skill:
        """创建技能，content 非空时同步生成 SKILL.md。"""
        if self._repository.name_exists(values["name"]):
            raise ConflictError("技能名称已存在")
        skill = self._repository.create(values)
        content = values.get("content", "")
        if content:
            self._uow.skill_files.upsert(skill.id, ENTRY_PATH, content)
        self._uow.commit()
        return skill

    def update(self, resource_id: int, values: dict) -> Skill:
        """全量更新，content 变更时同步 SKILL.md。"""
        existing = self._repository.get(resource_id)
        if existing is None:
            raise NotFoundError("技能不存在")
        self._ensure_manageable(existing)
        if self._repository.name_exists(values["name"], exclude_id=resource_id):
            raise ConflictError("技能名称已存在")
        updated = self._repository.update(resource_id, values)
        if updated is None:
            raise NotFoundError("技能不存在")
        if "content" in values:
            if values["content"]:
                self._uow.skill_files.upsert(resource_id, ENTRY_PATH, values["content"])
            else:
                self._uow.skill_files.delete(resource_id, ENTRY_PATH)
        self._uow.commit()
        return updated
