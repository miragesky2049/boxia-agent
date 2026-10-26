"""JWT 访问令牌签发与校验（管理端与用户端受众隔离）。"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from internal.application.errors import UnauthorizedError
from internal.infrastructure.config.settings import get_settings


def create_access_token(
    user_id: uuid.UUID,
    username: str,
    role: str,
    session_id: uuid.UUID,
    token_version: int,
    tenant_id: uuid.UUID | None = None,
) -> tuple[str, int]:
    """签发管理端访问令牌，返回 (token, 有效期秒数)。

    ``tid`` 为租户 ID，空字符串表示产品级平台账号；令牌只能在签发时对应的作用域使用。
    """
    settings = get_settings()
    payload = _base_payload(
        subject=str(user_id),
        username=username,
        scope="admin",
        tenant_id=str(tenant_id) if tenant_id else "",
        session_id=session_id,
        token_version=token_version,
    )
    payload["role"] = role
    return _encode(payload, settings.jwt_audience, settings.access_token_minutes)


def create_user_access_token(
    user_id: uuid.UUID,
    username: str,
    tenant_id: uuid.UUID,
    role_id: uuid.UUID,
    session_id: uuid.UUID,
    token_version: int,
) -> tuple[str, int]:
    """签发最终用户访问令牌；租户与角色写入令牌用于快速校验。"""
    settings = get_settings()
    payload = _base_payload(
        subject=str(user_id),
        username=username,
        scope="user",
        tenant_id=str(tenant_id),
        session_id=session_id,
        token_version=token_version,
    )
    payload["rid"] = str(role_id)
    return _encode(payload, settings.user_jwt_audience, settings.access_token_minutes)


def decode_access_token(token: str) -> dict[str, Any]:
    """校验管理端令牌并返回 payload，失败时抛出 UnauthorizedError。"""
    return _decode(token, get_settings().jwt_audience, "admin")


def decode_user_access_token(token: str) -> dict[str, Any]:
    """校验最终用户令牌并返回 payload。"""
    return _decode(token, get_settings().user_jwt_audience, "user")


def _base_payload(
    *,
    subject: str,
    username: str,
    scope: str,
    tenant_id: str,
    session_id: uuid.UUID,
    token_version: int,
) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(UTC)
    return {
        "sub": subject,
        "username": username,
        "scope": scope,
        "tid": tenant_id,
        "sid": str(session_id),
        "ver": token_version,
        "jti": uuid.uuid4().hex,
        "iss": settings.jwt_issuer,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_minutes * 60),
    }


def _encode(payload: dict[str, Any], audience: str, minutes: int) -> tuple[str, int]:
    settings = get_settings()
    payload["aud"] = audience
    token = jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return token, minutes * 60


def _decode(token: str, audience: str, scope: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=5,
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("身份凭证无效") from exc

    if (
        payload.get("scope") != scope
        or payload.get("type") != "access"
        or not payload.get("sub")
        or not payload.get("sid")
    ):
        raise UnauthorizedError("身份凭证无效")
    return payload
