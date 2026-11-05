"""领域层共享常量。"""

from __future__ import annotations

import os
from uuid import UUID

# 产品级租户 UUID 默认值：部署后通过 PLATFORM_TENANT_ID 环境变量指定，不可更改。
# 默认避开全零 UUID（全零通常被 ORM/框架保留），使用 00000000-0000-0000-0000-000000100000。
DEFAULT_PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000100000"

# 业务模块普遍在 import 时绑定该常量，因此这里必须在模块加载阶段直接读取环境变量。
PLATFORM_TENANT_ID: UUID = UUID(
    os.environ.get("PLATFORM_TENANT_ID", DEFAULT_PLATFORM_TENANT_ID).strip()
)


def init_platform_tenant_id(platform_tenant_id: str) -> None:
    """测试或特殊启动场景下同步覆盖模块级常量。"""
    global PLATFORM_TENANT_ID
    PLATFORM_TENANT_ID = UUID(platform_tenant_id)
