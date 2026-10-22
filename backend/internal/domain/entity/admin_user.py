"""管理员领域实体。"""

from dataclasses import dataclass
from datetime import datetime

ROLES = ("superadmin", "admin", "viewer")
EDITOR_ROLES = ("superadmin", "admin")


@dataclass(frozen=True)
class AdminUser:
    """管理后台账号。"""

    id: int
    username: str
    password_hash: str
    display_name: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    role: str = "admin"
    token_version: int = 1
    failed_login_count: int = 0
    locked_until: datetime | None = None
    must_change_password: bool = False
    password_changed_at: datetime | None = None
    tenant_id: int | None = None

    @property
    def is_platform(self) -> bool:
        """是否为产品级平台账号。"""
        return self.tenant_id is None
