"""SSRF 防护：校验出站 URL，拒绝 loopback / 云元数据 / link-local / multicast / reserved。

租户内网 MCP server（RFC1918 私网地址）是合法部署形态，因此本模块**不**禁止私网地址；
但强制拒绝以下高风险目标：
  - loopback（127.0.0.0/8, ::1）
  - 链路本地（169.254.0.0/16, fe80::/10）——含云元数据 169.254.169.254
  - 组播（224.0.0.0/4, ff00::/8）
  - 保留（240.0.0.0/4）
  - 未指定（0.0.0.0, ::）
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from internal.application.errors import ValidationError

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}


def validate_outbound_url(raw_url: str) -> str:
    """校验 URL 可安全发起出站请求；返回规范化后的 URL。

    拒绝非 http(s) scheme、非 IP 字面值的 host 解析到高风险地址。
    私网地址（RFC1918）允许——租户内网 MCP 是合法部署形态。
    """
    parsed = urlparse(raw_url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValidationError(f"仅支持 http/https 协议，当前为 {parsed.scheme or '（空）'}")
    if not parsed.hostname:
        raise ValidationError("URL 缺少主机名")

    host = parsed.hostname
    _validate_host_safe(host)
    return raw_url


def _validate_host_safe(host: str) -> None:
    """解析 host 到所有 IP，拒绝任意一个落在高风险网段。"""
    try:
        # 如果 host 本身就是 IP 字面值，getaddrinfo 也能处理
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValidationError(f"域名解析失败：{host}") from exc

    seen: set[ipaddress._BaseAddress] = set()
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip in seen:
            continue
        seen.add(ip)
        if _is_dangerous(ip):
            logger.warning(
                "ssrf blocked host=%s resolved_ip=%s",
                host,
                ip_str,
            )
            raise ValidationError(
                f"目标地址 {ip_str} 属于禁止访问的网段（loopback/链路本地/组播/保留）"
            )


def _is_dangerous(ip: ipaddress._BaseAddress) -> bool:
    """判断 IP 是否为高风险目标。"""
    return (
        ip.is_loopback
        or ip.is_link_local  # 含 169.254.169.254 云元数据
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
