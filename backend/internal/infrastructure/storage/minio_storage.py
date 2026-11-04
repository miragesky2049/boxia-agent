"""MinIO / S3 兼容对象存储实现。

用官方 `minio` SDK；首次使用时懒加载，避免未配置时强制依赖。
endpoint 留空时调用方应改用 InMemoryObjectStorage 或不启用对象存储。
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from internal.domain.storage.object_storage import ObjectStorage

logger = logging.getLogger(__name__)


class MinioObjectStorage(ObjectStorage):
    """MinIO / S3 兼容对象存储。

    URI 格式：`minio://<bucket>/<key>`。
    """

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        if not endpoint:
            raise ValueError("MinIO endpoint 不能为空")
        self._endpoint = endpoint
        self._bucket = bucket
        self._secure = secure
        self._access_key = access_key
        self._secret_key = secret_key
        self._client = None  # 懒加载

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from minio import Minio  # type: ignore[import-not-found]

        self._client = Minio(
            self._endpoint,
            access_key=self._access_key,
            secret_key=self._secret_key,
            secure=self._secure,
        )
        # 启动时确保 bucket 存在（不存在则创建）
        found = self._client.bucket_exists(self._bucket)
        if not found:
            self._client.make_bucket(self._bucket)
            logger.info("MinIO bucket 已创建: %s", self._bucket)
        return self._client

    async def put(self, key: str, data: bytes, content_type: str = "application/json") -> str:
        import io

        client = self._ensure_client()
        # minio SDK 是同步的；这里直接在事件循环里跑（对象通常 <10MB，阻塞可接受）
        client.put_object(
            self._bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return f"minio://{self._bucket}/{key}"

    async def get(self, uri: str) -> bytes:
        client = self._ensure_client()
        bucket, key = self._parse_uri(uri)
        response = None
        try:
            response = client.get_object(bucket, key)
            return response.read()
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    async def delete(self, uri: str) -> None:
        client = self._ensure_client()
        bucket, key = self._parse_uri(uri)
        try:
            client.remove_object(bucket, key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除 MinIO 对象失败 uri=%s err=%s", uri, exc)

    @staticmethod
    def _parse_uri(uri: str) -> tuple[str, str]:
        """`minio://bucket/key` → (bucket, key)。"""
        parsed = urllib.parse.urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"非法 MinIO URI: {uri}")
        return bucket, key
