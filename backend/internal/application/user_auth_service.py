"""最终用户认证用例：登录、刷新、登出与会话校验。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from internal.application.audit import record_audit
from internal.application.errors import (
    AccountLockedError,
    ForbiddenError,
    UnauthorizedError,
)
from internal.domain.entity.access import Role, User
from internal.domain.repository.protocols import UnitOfWork
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.security.jwt import (
    create_user_access_token,
    decode_user_access_token,
)
from internal.infrastructure.security.password import (
    dummy_password_hash,
    verify_password,
)
from internal.infrastructure.security.tokens import generate_refresh_token, hash_refresh_token


@dataclass(frozen=True)
class UserTokenPair:
    """最终用户登录/刷新成功后返回的令牌组。"""

    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: User


@dataclass(frozen=True)
class UserAccessContext:
    """已通过校验的最终用户访问上下文；role 为主角色，roles 为全部有效角色。"""

    user: User
    role: Role
    session_id: UUID
    roles: tuple[Role, ...] = ()

    @property
    def role_ids(self) -> tuple[UUID, ...]:
        """全部有效角色 ID，用于收敛资源可见范围。"""
        return tuple(role.id for role in self.roles) or (self.role.id,)


class UserAuthService:
    """最终用户认证与用户端会话管理。"""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow
        self._settings = get_settings()

    def login(
        self,
        username: str,
        password: str,
        tenant_id: UUID,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> UserTokenPair:
        """校验用户名密码并创建会话；账号按租户隔离。"""
        normalized = username.strip()
        user = self._uow.users.get_by_username_for_update(normalized, tenant_id)
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
                None, normalized, tenant_id, ip, user_agent, reason="unknown_user"
            )
            raise UnauthorizedError("用户名或密码错误")

        if not verify_password(password, user.password_hash):
            locked_until = self._uow.users.record_failed_login(
                user.id, self._settings.login_max_attempts, self._settings.login_lock_minutes
            )
            self._record_login_failure(
                user.id, user.username, tenant_id, ip, user_agent, reason="bad_password"
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
                user.id, user.username, tenant_id, ip, user_agent, reason="disabled"
            )
            raise ForbiddenError("账号已被禁用")

        roles = self._active_roles(user, ForbiddenError)
        self._uow.users.mark_login_success(user.id)
        pair = self._issue_session(user, roles, ip, user_agent)
        record_audit(
            self._uow,
            action="user_auth.login",
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
        tenant_id: UUID,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> UserTokenPair:
        """轮换刷新令牌；会话族与租户不一致时拒绝。"""
        token_hash = hash_refresh_token(refresh_token)
        row = self._uow.user_refresh_tokens.get_by_hash_for_update(token_hash)
        now = datetime.now(UTC)

        if row is None:
            raise UnauthorizedError("登录状态已失效，请重新登录")

        if row.revoked_at is not None or row.rotated_at is not None:
            self._uow.user_refresh_tokens.revoke_family(row.family_id)
            self._record_refresh_replay(row.user_id, tenant_id, ip, user_agent)
            raise UnauthorizedError("登录状态已失效，请重新登录")

        if row.expires_at <= now:
            self._uow.user_refresh_tokens.revoke_family(row.family_id)
            self._uow.commit()
            raise UnauthorizedError("登录已过期，请重新登录")

        user = self._uow.users.get_by_id(row.user_id)
        if (
            user is None
            or not user.is_active
            or user.token_version != row.token_version
            or user.tenant_id != tenant_id
        ):
            self._uow.user_refresh_tokens.revoke_family(row.family_id)
            self._uow.commit()
            raise UnauthorizedError("登录状态已失效，请重新登录")

        roles = self._active_roles(user, UnauthorizedError)
        pair = self._issue_session(
            user,
            roles,
            ip,
            user_agent,
            family_id=row.family_id,
            rotated_from=row.id,
        )
        self._uow.commit()
        return pair

    def logout(
        self,
        user_id: UUID,
        username: str,
        tenant_id: UUID,
        session_id: UUID,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """撤销当前会话族，使访问令牌立即失效。"""
        self._uow.user_refresh_tokens.revoke_family(session_id)
        record_audit(
            self._uow,
            action="user_auth.logout",
            actor_id=user_id,
            actor_username=username,
            ip=ip,
            user_agent=user_agent,
            tenant_id=tenant_id,
        )
        self._uow.commit()

    def authenticate_access_token(self, token: str) -> UserAccessContext:
        """校验用户令牌并确认账号、角色与会话仍有效。"""
        payload = decode_user_access_token(token)
        try:
            user_id = UUID(str(payload["sub"]))
            token_version = int(payload["ver"])
            session_id = UUID(str(payload["sid"]))
            token_tenant_id = UUID(str(payload["tid"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise UnauthorizedError("身份凭证无效") from exc

        user = self._uow.users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("账号不存在或已被禁用")
        if token_tenant_id != user.tenant_id:
            raise UnauthorizedError("身份凭证无效")
        if user.token_version != token_version:
            raise UnauthorizedError("登录状态已失效，请重新登录")
        if not self._uow.user_refresh_tokens.is_family_active(session_id):
            raise UnauthorizedError("登录状态已失效，请重新登录")
        roles = self._active_roles(user, UnauthorizedError)
        return UserAccessContext(
            user=user,
            role=self._primary_role(user, roles),
            session_id=session_id,
            roles=roles,
        )

    def _active_roles(
        self, user: User, error_cls: type[ForbiddenError] | type[UnauthorizedError]
    ) -> tuple[Role, ...]:
        """加载用户全部有效角色；没有可用角色时拒绝登录或访问。"""
        roles: list[Role] = []
        for role_id in user.effective_role_ids():
            role = self._uow.roles.get_by_id(role_id)
            if role is None or role.tenant_id != user.tenant_id or not role.is_active:
                continue
            roles.append(role)
        if not roles:
            raise error_cls("账号角色已失效，请联系管理员")
        return tuple(roles)

    @staticmethod
    def _primary_role(user: User, roles: tuple[Role, ...]) -> Role:
        for role in roles:
            if role.id == user.role_id:
                return role
        return roles[0]

    def _issue_session(
        self,
        user: User,
        roles: tuple[Role, ...],
        ip: str | None,
        user_agent: str | None,
        family_id: UUID | None = None,
        rotated_from: UUID | None = None,
    ) -> UserTokenPair:
        """创建刷新令牌（轮换场景保留同一 family）并签发访问令牌。"""
        family = family_id or uuid4()
        refresh_token = generate_refresh_token()
        expires_at = datetime.now(UTC) + timedelta(days=self._settings.refresh_token_days)
        new_row = self._uow.user_refresh_tokens.create(
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
            self._uow.user_refresh_tokens.rotate(rotated_from, new_row.id)

        access_token, expires_in = create_user_access_token(
            user.id,
            user.username,
            user.tenant_id,
            self._primary_role(user, roles).id,
            family,
            user.token_version,
        )
        return UserTokenPair(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=refresh_token,
            refresh_expires_in=int((expires_at - datetime.now(UTC)).total_seconds()),
            user=user,
        )

    def _record_login_failure(
        self,
        user_id: UUID | None,
        username: str,
        tenant_id: UUID,
        ip: str | None,
        user_agent: str | None,
        reason: str,
    ) -> None:
        """记录用户端登录失败审计（与失败计数同事务提交）。"""
        record_audit(
            self._uow,
            action="user_auth.login_failed",
            actor_id=user_id,
            actor_username=username,
            ip=ip,
            user_agent=user_agent,
            detail={"reason": reason},
            tenant_id=tenant_id,
        )
        self._uow.commit()

    def _record_refresh_replay(
        self, user_id: UUID, tenant_id: UUID, ip: str | None, user_agent: str | None
    ) -> None:
        """记录刷新令牌重放并撤销会话族。"""
        record_audit(
            self._uow,
            action="user_auth.refresh_replay",
            actor_id=user_id,
            ip=ip,
            user_agent=user_agent,
            tenant_id=tenant_id,
        )
        self._uow.commit()
