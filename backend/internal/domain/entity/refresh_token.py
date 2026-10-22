"""刷新令牌领域实体。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class RefreshToken:
    """服务端持久化的刷新令牌（仅存哈希）。"""

    id: int
    user_id: int
    token_hash: str
    family_id: UUID
    token_version: int
    issued_at: datetime
    expires_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    replaced_by_id: int | None = None
    ip: str | None = None
    user_agent: str | None = None
