"""对象存储抽象：A12 大 graph 超出内联阈值时落对象存储。

domain 层只依赖 ABC，不直接 import minio / boto3。
infrastructure 层提供 MinIO 实现和 Fake 实现（测试用）。

URI 约定：`<scheme>://<bucket>/<key>`，如 `minio://boxia-graphs/app_xxx/v3.json`。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ObjectStorage(ABC):
    """对象存储接口。"""

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "application/json") -> str:
        """写入对象，返回可反查的 URI（如 `minio://bucket/key`）。"""

    @abstractmethod
    async def get(self, uri: str) -> bytes:
        """按 URI 读取对象内容。"""

    @abstractmethod
    async def delete(self, uri: str) -> None:
        """按 URI 删除对象；不存在时静默忽略。"""
