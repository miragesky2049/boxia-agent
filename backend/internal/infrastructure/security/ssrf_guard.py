"""兼容 shim：实现已迁移至 internal.domain.security.ssrf_guard（DDD 一期搬迁）。

保留旧路径 re-export 以便灰度回滚；调用点全部切换后下个迭代删除本文件。
"""

from internal.domain.security.ssrf_guard import (  # noqa: F401
    ALLOWED_SCHEMES,
    validate_outbound_url,
)
