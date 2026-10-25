"""技能包文件读写模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SkillFileMetaOut(BaseModel):
    """技能包文件元数据。"""

    model_config = ConfigDict(from_attributes=True)

    path: str
    size_bytes: int
    content_hash: str
    media_type: str
    updated_at: datetime


class SkillFileOut(SkillFileMetaOut):
    """技能包文件内容。"""

    content: str


class SkillFileListOut(BaseModel):
    """技能包文件清单。"""

    items: list[SkillFileMetaOut]
    total: int
    total_bytes: int


class SkillFileWriteRequest(BaseModel):
    """写入单个文件请求。"""

    path: str = Field(min_length=1, max_length=512)
    content: str = Field(default="", max_length=1_048_576)
    expected_hash: str | None = Field(default=None, max_length=64)


class SkillCloneRequest(BaseModel):
    """克隆技能请求；指定 agent_id 时克隆到目标智能体，否则克隆到当前租户。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    agent_id: int | None = Field(default=None, ge=1)
