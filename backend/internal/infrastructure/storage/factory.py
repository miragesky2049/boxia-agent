"""对象存储工厂：按 settings 决定用 MinIO 还是降级为 None（内联写 DB）。"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from internal.domain.storage.object_storage import ObjectStorage
from internal.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage | None:
    """全局单例：endpoint 为空时返回 None（调用方降级为内联）。"""
    settings = get_settings()
    if not settings.object_storage_endpoint:
        logger.info("对象存储未配置（object_storage_endpoint 为空），大 graph 降级为内联写 DB")
        return None
    try:
        from internal.infrastructure.storage.minio_storage import MinioObjectStorage

        return MinioObjectStorage(
            endpoint=settings.object_storage_endpoint,
            access_key=settings.object_storage_access_key,
            secret_key=settings.object_storage_secret_key.get_secret_value(),
            bucket=settings.object_storage_bucket,
            secure=settings.object_storage_secure,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("初始化 MinIO 失败，降级为内联: %s", exc)
        return None
