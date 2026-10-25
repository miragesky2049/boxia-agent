"""技能用例：通用 CRUD 之上保持 skills.content 与包内 SKILL.md 一致。"""

from collections.abc import Sequence

from internal.application.errors import ConflictError, NotFoundError
from internal.application.resource_service import ResourceService
from internal.domain.entity.resource import Skill

ENTRY_PATH = "SKILL.md"


class SkillService(ResourceService[Skill]):
    """技能 CRUD；content 是入口文件的镜像，文件表是包内容的唯一来源。"""

    def create(self, values: dict, actor_role_ids: Sequence[int] = ()) -> Skill:
        """创建技能，content 非空时同步生成 SKILL.md，并授权给创建者角色。"""
        if self._repository.name_exists(values["name"]):
            raise ConflictError("技能名称已存在")
        payload = self._with_validated_agent(values)
        skill = self._repository.create(payload)
        content = payload.get("content", "")
        if content:
            self._uow.skill_files.upsert(skill.id, ENTRY_PATH, content)
        self._grant_actor(skill, actor_role_ids)
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
        payload = self._with_validated_agent(values)
        updated = self._repository.update(resource_id, payload)
        if updated is None:
            raise NotFoundError("技能不存在")
        if "content" in payload:
            if payload["content"]:
                self._uow.skill_files.upsert(resource_id, ENTRY_PATH, payload["content"])
            else:
                self._uow.skill_files.delete(resource_id, ENTRY_PATH)
        self._uow.commit()
        return updated

    def _after_clone(self, source: Skill, clone: Skill) -> None:
        """克隆技能时同步复制技能包内全部文件。"""
        files = self._uow.skill_files.list_by_skill(source.id, include_content=True)
        if files:
            self._uow.skill_files.replace_all(
                clone.id, [(file.path, file.content) for file in files]
            )
