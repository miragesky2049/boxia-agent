"""管理员领域实体。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class AdminUser:
    """管理后台账号。"""

    id: UUID
    username: str
    password_hash: str
    display_name: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    token_version: int = 1
    failed_login_count: int = 0
    locked_until: datetime | None = None
    must_change_password: bool = False
    password_changed_at: datetime | None = None
    tenant_id: UUID | None = None
    role_id: UUID | None = None
    role_code: str = ""
    role_name: str = ""

    @property
    def is_platform(self) -> bool:
        """是否为产品级平台账号。"""
        return self.tenant_id is None
