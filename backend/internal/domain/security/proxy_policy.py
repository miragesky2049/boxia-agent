"""环回地址代理策略：发往本机回环地址的 HTTP 请求必须直连，不得走系统/环境代理。

背景（20261124）：httpx 默认 trust_env=True，在 Windows 上会读取注册表里的系统代理；
开发机开启代理软件（系统代理/TUN 模式）后，发往 127.0.0.1 的本地 MCP server、
本地 HTTP 工具请求也会被送进代理，导致连接被重置或返回代理错误页，
表现为 test_mcp_session 等本地用例在无 NO_PROXY 时成片失败。
回环目标是"进程自己所在机器"，走代理既无意义也不安全，因此一律直连。
"""

from __future__ import annotations

from urllib.parse import urlsplit

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_loopback_url(url: str) -> bool:
    """判断 URL 的主机是否为本机回环地址（127.0.0.0/8、localhost、::1）。

    :param url: 完整 URL；解析不出主机时按"非环回"处理（保持默认代理行为）。
    :return: 主机为环回地址返回 True。
    """
    host = (urlsplit(url).hostname or "").lower()
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def httpx_trust_env(url: str) -> bool:
    """返回构造 httpx 客户端时应使用的 trust_env 取值。

    环回目标返回 False（忽略环境/注册表代理，强制直连）；其余目标返回 True，
    保留企业代理环境下访问外部服务的既有行为。

    :param url: 请求目标 URL。
    :return: 是否允许 httpx 读取环境代理配置。
    """
    return not is_loopback_url(url)
