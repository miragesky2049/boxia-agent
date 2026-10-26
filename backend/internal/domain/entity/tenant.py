"""租户领域实体。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Tenant:
    """租户：一个独立的企业/组织空间，通过子域名访问。"""

    id: UUID
    code: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
