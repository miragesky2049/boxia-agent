"""资源可见范围枚举：对齐 coze / 多租户 SaaS 常见可见性模型。

- PRIVATE: 仅创建者本人可见
- TENANT: 同租户内任意成员可见（再由 ResourceGrant 收敛到具体角色）
- TENANT_GROUP: 同租户组（多租户共享空间）内可见
- WHITELIST: 显式白名单（通过 ResourceGrant 授权给指定租户/角色）
"""

from __future__ import annotations

from enum import Enum


class Visibility(str, Enum):
    PRIVATE = "private"
    TENANT = "tenant"
    TENANT_GROUP = "tenant_group"
    WHITELIST = "whitelist"

    @classmethod
    def default(cls) -> "Visibility":
        return cls.PRIVATE
