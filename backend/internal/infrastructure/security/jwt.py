"""JWT 访问令牌签发与校验。"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from internal.application.errors import UnauthorizedError
from internal.infrastructure.config.settings import get_settings


def create_access_token(
    user_id: int,
    username: str,
    role: str,
    session_id: uuid.UUID,
    token_version: int,
    tenant_id: int | None = None,
) -> tuple[str, int]:
    """签发管理端访问令牌，返回 (token, 有效期秒数)。

    ``tid`` 为租户 ID，0 表示产品级平台账号；令牌只能在签发时对应的作用域使用。
    """
    settings = get_settings()
    expires_in = settings.access_token_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "scope": "admin",
        "tid": tenant_id or 0,
        "sid": str(session_id),
        "ver": token_version,
        "jti": uuid.uuid4().hex,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """校验令牌并返回 payload，失败时抛出 UnauthorizedError。"""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=5,
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("身份凭证无效") from exc

    if (
        payload.get("scope") != "admin"
        or payload.get("type") != "access"
        or not payload.get("sub")
        or not payload.get("sid")
    ):
        raise UnauthorizedError("身份凭证无效")
    return payload
