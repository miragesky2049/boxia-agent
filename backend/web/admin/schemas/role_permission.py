"""权限资源目录与角色权限请求/响应模型。"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PermissionResourceOut(BaseModel):
    """权限资源目录项。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    category: str
    action: str
    description: str
    sort_order: int


class RolePermissionListOut(BaseModel):
    """角色已授权限集合。"""

    items: list[PermissionResourceOut]
    codes: list[str]


class RolePermissionReplaceRequest(BaseModel):
    """整体替换角色权限请求。"""

    model_config = ConfigDict(extra="forbid")

    codes: list[str] = Field(default_factory=list, max_length=500)


class RolePermissionAddRequest(BaseModel):
    """追加角色权限请求。"""

    model_config = ConfigDict(extra="forbid")

    codes: list[str] = Field(min_length=1, max_length=500)
