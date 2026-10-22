"""不透明刷新令牌的生成与哈希。"""

import hashlib
import secrets

REFRESH_TOKEN_PREFIX = "bxt_"


def generate_refresh_token() -> str:
    """生成高熵刷新令牌明文（仅返回给客户端一次）。"""
    return f"{REFRESH_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_refresh_token(token: str) -> str:
    """计算刷新令牌的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
