"""领域层共享常量。"""

from __future__ import annotations

from uuid import UUID

# 产品级租户 ID：全零 UUID，永远不会被分配给真实租户。
# 历史上产品级资源用 tenant_id IS NULL 表示，已统一迁移为该常量。
PLATFORM_TENANT_ID = UUID("00000000-0000-0000-0000-000000000000")
