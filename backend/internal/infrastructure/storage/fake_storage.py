"""内存对象存储：测试用，进程内 dict 模拟 bucket。"""

from __future__ import annotations

from internal.domain.storage.object_storage import ObjectStorage


class InMemoryObjectStorage(ObjectStorage):
    """测试用：所有数据存在 dict 里，按 URI 索引。"""

    def __init__(self, scheme: str = "memory") -> None:
        self._store: dict[str, bytes] = {}
        self._scheme = scheme

    async def put(self, key: str, data: bytes, content_type: str = "application/json") -> str:
        uri = f"{self._scheme}://fake-bucket/{key}"
        self._store[uri] = data
        return uri

    async def get(self, uri: str) -> bytes:
        if uri not in self._store:
            raise FileNotFoundError(f"对象不存在: {uri}")
        return self._store[uri]

    async def delete(self, uri: str) -> None:
        self._store.pop(uri, None)
