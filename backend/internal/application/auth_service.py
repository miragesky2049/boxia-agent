"""管理员认证用例：登录、刷新、登出、改密与会话校验。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from internal.application.audit import record_audit
from internal.application.errors import (
    AccountLockedError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from internal.domain.entity.admin_user import AdminUser
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.security.jwt import create_access_token, decode_access_token
from internal.infrastructure.security.password import (
    dummy_password_hash,
    hash_password,
    validate_password_strength,
    verify_password,
)
from internal.infrastructure.security.tokens import generate_refresh_token, hash_refresh_token


@dataclass(frozen=True)
class TokenPair:
    """登录/刷新成功后返回的令牌组。"""

    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: AdminUser


@dataclass(frozen=True)
class AccessContext:
    """已通过校验的访问上下文。"""

    user: AdminUser
    session_id: UUID


class AuthService:
    """管理员认证与应用会话管理。"""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow
        self._settings = get_settings()

    def login(
        self,
        username: str,
        password: str,
        tenant_id: int | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        """校验账号密码并创建会话；账号仅在当前作用域内查找。"""
        normalized = username.strip()
        user = self._uow.admin_users.get_by_username_for_update(normalized, tenant_id)
        now = datetime.now(UTC)

        if user is not None and user.locked_until and user.locked_until > now:
            retry_after = max(int((user.locked_until - now).total_seconds()), 1)
            raise AccountLockedError(
                "登录失败次数过多，账号已临时锁定",
                headers={"Retry-After": str(retry_after)},
            )

        if user is None:
            verify_password(password, dummy_password_hash())
            self._record_login_failure(
                None, normalized, ip, user_agent, reason="unknown_user", tenant_id=tenant_id
            )
            raise UnauthorizedError("用户名或密码错误")

        if not verify_password(password, user.password_hash):
            locked_until = self._uow.admin_users.record_failed_login(
                user.id, self._settings.login_max_attempts, self._settings.login_lock_minutes
            )
            self._record_login_failure(
                user.id, user.username, ip, user_agent, reason="bad_password", tenant_id=tenant_id
            )
            if locked_until:
                retry_after = max(int((locked_until - now).total_seconds()), 1)
                raise AccountLockedError(
                    "登录失败次数过多，账号已临时锁定",
                    headers={"Retry-After": str(retry_after)},
                )
            raise UnauthorizedError("用户名或密码错误")

        if not user.is_active:
            self._record_login_failure(
                user.id, user.username, ip, user_agent, reason="disabled", tenant_id=tenant_id
            )
            raise ForbiddenError("账号已被禁用")

        self._uow.admin_users.mark_login_success(user.id)
        pair = self._issue_session(user, ip, user_agent)
        record_audit(
            self._uow,
            action="auth.login",
            actor_id=user.id,
            actor_username=user.username,
            ip=ip,
            user_agent=user_agent,
            tenant_id=tenant_id,
        )
        self._uow.commit()
        return pair

    def refresh(
        self,
        refresh_token: str,
        tenant_id: int | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        """轮换刷新令牌；令牌归属作用域与当前子域名不一致时拒绝。"""
        token_hash = hash_refresh_token(refresh_token)
        row = self._uow.refresh_tokens.get_by_hash_for_update(token_hash)
        now = datetime.now(UTC)

        if row is None:
            raise UnauthorizedError("登录状态已失效，请重新登录")

        if row.revoked_at is not None or row.rotated_at is not None:
            self._uow.refresh_tokens.revoke_family(row.family_id)
            replay_user = self._uow.admin_users.get_by_id(row.user_id)
            record_audit(
                self._uow,
                action="auth.refresh_replay",
                actor_id=row.user_id,
                ip=ip,
                user_agent=user_agent,
                tenant_id=replay_user.tenant_id if replay_user else tenant_id,
            )
            self._uow.commit()
            raise UnauthorizedError("登录状态已失效，请重新登录")

        if row.expires_at <= now:
            self._uow.refresh_tokens.revoke_family(row.family_id)
            self._uow.commit()
            raise UnauthorizedError("登录已过期，请重新登录")

        user = self._uow.admin_users.get_by_id(row.user_id)
        if (
            user is None
            or not user.is_active
            or user.token_version != row.token_version
            or user.tenant_id != tenant_id
        ):
            self._uow.refresh_tokens.revoke_family(row.family_id)
            self._uow.commit()
            raise UnauthorizedError("登录状态已失效，请重新登录")

        pair = self._issue_session(
            user, ip, user_agent, family_id=row.family_id, rotated_from=row.id
        )
        self._uow.commit()
        return pair

    def logout(
        self,
        user: AdminUser,
        session_id: UUID,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """撤销当前会话族，使 Access Token 立即失效。"""
        self._uow.refresh_tokens.revoke_family(session_id)
        record_audit(
            self._uow,
            action="auth.logout",
            actor_id=user.id,
            actor_username=user.username,
            ip=ip,
            user_agent=user_agent,
            tenant_id=user.tenant_id,
        )
        self._uow.commit()

    def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """修改密码并撤销全部会话。"""
        user = self._uow.admin_users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("管理员不存在")
        if not verify_password(current_password, user.password_hash):
            raise UnauthorizedError("当前密码不正确")
        validate_password_strength(new_password, user.username)
        if verify_password(new_password, user.password_hash):
            raise UnauthorizedError("新密码不能与当前密码相同")

        self._uow.admin_users.update_password(
            user.id, hash_password(new_password), False, datetime.now(UTC)
        )
        self._uow.refresh_tokens.revoke_all_for_user(user.id)
        record_audit(
            self._uow,
            action="auth.password_changed",
            actor_id=user.id,
            actor_username=user.username,
            ip=ip,
            user_agent=user_agent,
            tenant_id=user.tenant_id,
        )
        self._uow.commit()

    def authenticate_access_token(self, token: str) -> AccessContext:
        """校验访问令牌并确认会话、账号状态仍有效。"""
        payload = decode_access_token(token)
        try:
            user_id = int(payload["sub"])
            token_version = int(payload["ver"])
            session_id = UUID(str(payload["sid"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise UnauthorizedError("身份凭证无效") from exc

        user = self._uow.admin_users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("账号不存在或已被禁用")
        token_tenant_id = int(payload.get("tid") or 0) or None
        if token_tenant_id != user.tenant_id:
            raise UnauthorizedError("身份凭证无效")
        if user.token_version != token_version:
            raise UnauthorizedError("登录状态已失效，请重新登录")
        if not self._uow.refresh_tokens.is_family_active(session_id):
            raise UnauthorizedError("登录状态已失效，请重新登录")
        return AccessContext(user=user, session_id=session_id)

    def get_profile(self, user_id: int) -> AdminUser:
        """查询当前管理员信息。"""
        user = self._uow.admin_users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("管理员不存在")
        return user

    def _issue_session(
        self,
        user: AdminUser,
        ip: str | None,
        user_agent: str | None,
        family_id: UUID | None = None,
        rotated_from: int | None = None,
    ) -> TokenPair:
        """创建刷新令牌（轮换场景保留同一 family）并签发访问令牌。"""
        family = family_id or uuid4()
        refresh_token = generate_refresh_token()
        expires_at = datetime.now(UTC) + timedelta(days=self._settings.refresh_token_days)
        new_row = self._uow.refresh_tokens.create(
            {
                "user_id": user.id,
                "token_hash": hash_refresh_token(refresh_token),
                "family_id": family,
                "token_version": user.token_version,
                "expires_at": expires_at,
                "ip": ip,
                "user_agent": (user_agent or "")[:255] or None,
            }
        )
        if rotated_from is not None:
            self._uow.refresh_tokens.rotate(rotated_from, new_row.id)

        access_token, expires_in = create_access_token(
            user.id, user.username, user.role, family, user.token_version, user.tenant_id
        )
        return TokenPair(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=refresh_token,
            refresh_expires_in=int((expires_at - datetime.now(UTC)).total_seconds()),
            user=user,
        )

    def _record_login_failure(
        self,
        user_id: int | None,
        username: str,
        ip: str | None,
        user_agent: str | None,
        reason: str,
        tenant_id: int | None = None,
    ) -> None:
        """记录登录失败审计（与失败计数同事务提交）。"""
        record_audit(
            self._uow,
            action="auth.login_failed",
            actor_id=user_id,
            actor_username=username,
            ip=ip,
            user_agent=user_agent,
            detail={"reason": reason},
            tenant_id=tenant_id,
        )
        self._uow.commit()
