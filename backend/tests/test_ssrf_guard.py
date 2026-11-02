"""SSRF 防护单元测试：拒绝 loopback / 云元数据 / link-local / multicast / reserved。"""

from __future__ import annotations

import pytest

from internal.application.errors import ValidationError
from internal.domain.security.ssrf_guard import validate_outbound_url


def test_accepts_public_http_url() -> None:
    """公网 http(s) 地址应通过（用公网 IP 字面值，避免依赖 DNS）。"""
    url = validate_outbound_url("https://93.184.216.34/weather")
    assert "93.184.216.34" in url


def test_rejects_non_http_scheme() -> None:
    """非 http/https scheme 应被拒。"""
    with pytest.raises(ValidationError, match="仅支持 http"):
        validate_outbound_url("ftp://example.com/file")
    with pytest.raises(ValidationError, match="仅支持 http"):
        validate_outbound_url("file:///etc/passwd")


def test_rejects_loopback_ip() -> None:
    """127.0.0.1 应被拒。"""
    with pytest.raises(ValidationError, match="禁止访问的网段"):
        validate_outbound_url("http://127.0.0.1:8080/admin")


def test_rejects_cloud_metadata_ip() -> None:
    """169.254.169.254（云元数据）应被拒。"""
    with pytest.raises(ValidationError, match="禁止访问的网段"):
        validate_outbound_url("http://169.254.169.254/latest/meta-data/")


def test_rejects_link_local() -> None:
    """169.254.0.0/16 链路本地地址应被拒。"""
    with pytest.raises(ValidationError, match="禁止访问的网段"):
        validate_outbound_url("http://169.254.1.1/")


def test_rejects_multicast() -> None:
    """224.0.0.1 组播地址应被拒。"""
    with pytest.raises(ValidationError, match="禁止访问的网段"):
        validate_outbound_url("http://224.0.0.1/")


def test_rejects_reserved() -> None:
    """240.0.0.1 保留地址应被拒。"""
    with pytest.raises(ValidationError, match="禁止访问的网段"):
        validate_outbound_url("http://240.0.0.1/")


def test_accepts_private_rfc1918() -> None:
    """RFC1918 私网地址（10.x / 192.168.x / 172.16.x）应允许——租户内网 MCP 是合法场景。"""
    url = validate_outbound_url("http://192.168.1.100:8000/mcp")
    assert "192.168.1.100" in url
    url = validate_outbound_url("http://10.0.0.5:9000/sse")
    assert "10.0.0.5" in url
