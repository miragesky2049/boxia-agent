"""管理员认证用例：平台账号走 admin_users，租户账号走 users。"""

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
from internal.domain.entity.access import Role, User
from internal.domain.entity.admin_user import AdminUser
from internal.domain.entity.permission import CONSOLE_ACCESS, DATA_ALL
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
    """已通过校验的访问上下文；租户账号带全部有效角色。"""

    user: AdminUser
    session_id: UUID
    role: Role | None = None
    roles: tuple[Role, ...] = ()

    @property
    def role_ids(self) -> tuple[UUID, ...]:
        """全部有效角色 ID；平台账号退回主角色。"""
        if self.roles:
            return tuple(role.id for role in self.roles)
        return (self.user.role_id,) if self.user.role_id is not None else ()


class AuthService:
    """管理员认证与应用会话管理。"""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow
        self._settings = get_settings()

    def login(
        self,
        username: str,
        password: str,
        tenant_id: UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        """校验账号密码并创建会话；平台查 admin_users，租户查 users。"""
        if tenant_id is not None:
            return self._login_tenant(username, password, tenant_id, ip, user_agent)
        return self._login_platform(username, password, tenant_id, ip, user_agent)

    def refresh(
        self,
        refresh_token: str,
        tenant_id: UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        """轮换刷新令牌；令牌归属作用域与当前子域名不一致时拒绝。"""
        if tenant_id is not None:
            return self._refresh_tenant(refresh_token, tenant_id, ip, user_agent)
        return self._refresh_platform(refresh_token, tenant_id, ip, user_agent)

    def logout(
        self,
        user_id: UUID,
        username: str,
        session_id: UUID,
        tenant_id: UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """撤销当前会话族，使 Access Token 立即失效。"""
        if tenant_id is None:
            self._uow.refresh_tokens.revoke_family(session_id)
        else:
            self._uow.user_refresh_tokens.revoke_family(session_id)
        record_audit(
            self._uow,
            action="auth.logout",
            actor_id=user_id,
            actor_username=username,
            ip=ip,
            user_agent=user_agent,
            tenant_id=tenant_id,
        )
        self._uow.commit()

    def change_password(
        self,
        user_id: UUID,
        current_password: str,
        new_password: str,
        tenant_id: UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """修改密码并撤销全部会话。"""
        if tenant_id is not None:
            self._change_tenant_password(
                user_id, current_password, new_password, tenant_id, ip, user_agent
            )
            return
        self._change_platform_password(user_id, current_password, new_password, ip, user_agent)

    def authenticate_access_token(self, token: str) -> AccessContext:
        """校验访问令牌并确认会话、账号状态仍有效。"""
        payload = decode_access_token(token)
        try:
            user_id = UUID(str(payload["sub"]))
            token_version = int(payload["ver"])
            session_id = UUID(str(payload["sid"]))
            raw_tenant_id = payload.get("tid") or ""
            token_tenant_id = UUID(str(raw_tenant_id)) if raw_tenant_id else None
        except (KeyError, TypeError, ValueError) as exc:
            raise UnauthorizedError("身份凭证无效") from exc

        if token_tenant_id is not None:
            return self._authenticate_tenant(user_id, token_version, session_id, token_tenant_id)

        user = self._uow.admin_users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("账号不存在或已被禁用")
        if user.tenant_id is not None:
            raise UnauthorizedError("身份凭证无效")
        if user.token_version != token_version:
            raise UnauthorizedError("登录状态已失效，请重新登录")
        if not self._uow.refresh_tokens.is_family_active(session_id):
            raise UnauthorizedError("登录状态已失效，请重新登录")
        role = self._resolve_platform_role(user)
        self._assert_console_access((role,))
        return AccessContext(user=user, session_id=session_id, role=role, roles=(role,))

    def _resolve_platform_role(self, user: AdminUser) -> Role:
        """解析平台账号绑定的平台角色；账号必须绑定有效角色。"""
        if user.role_id is None:
            raise UnauthorizedError("账号角色已失效，请联系管理员")
        role = self._uow.roles.get_by_id(user.role_id)
        if role is None or role.tenant_id is not None or not role.is_active:
            raise UnauthorizedError("账号角色已失效，请联系管理员")
        return role

    def get_profile(self, user_id: UUID, tenant_id: UUID | None = None) -> AdminUser:
        """查询当前管理员信息；租户账号由 users + 角色映射。"""
        if tenant_id is None:
            platform_user = self._uow.admin_users.get_by_id(user_id)
            if platform_user is None:
                raise NotFoundError("管理员不存在")
            return platform_user
        tenant_user = self._uow.users.get_by_id(user_id)
        if tenant_user is None or tenant_user.tenant_id != tenant_id:
            raise NotFoundError("管理员不存在")
        roles = self._active_roles(tenant_user, UnauthorizedError)
        role_codes = self._role_codes(roles)
        return self._to_admin_user(tenant_user, self._primary_role(roles, role_codes))

    def _login_platform(
        self,
        username: str,
        password: str,
        tenant_id: UUID | None,
        ip: str | None,
        user_agent: str | None,
    ) -> TokenPair:
        normalized = username.strip()
        user = self._uow.admin_users.get_by_username_for_update(normalized)
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

        role = self._resolve_platform_role(user)
        if CONSOLE_ACCESS not in self._role_codes((role,))[role.id]:
            self._record_login_failure(
                user.id,
                user.username,
                ip,
                user_agent,
                reason="no_console_access",
                tenant_id=tenant_id,
            )
            raise ForbiddenError("账号未获得管理端访问权限")

        self._uow.admin_users.mark_login_success(user.id)
        pair = self._issue_session(user, role, ip, user_agent)
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

    def _login_tenant(
        self,
        username: str,
        password: str,
        tenant_id: UUID,
        ip: str | None,
        user_agent: str | None,
    ) -> TokenPair:
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
                None, normalized, ip, user_agent, reason="unknown_user", tenant_id=tenant_id
            )
            raise UnauthorizedError("用户名或密码错误")

        if not verify_password(password, user.password_hash):
            locked_until = self._uow.users.record_failed_login(
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

        roles = self._active_roles(user, ForbiddenError)
        role_codes = self._role_codes(roles)
        if not self._has_console_access(roles, role_codes):
            self._record_login_failure(
                user.id,
                user.username,
                ip,
                user_agent,
                reason="no_console_access",
                tenant_id=tenant_id,
            )
            raise ForbiddenError("账号未获得管理端访问权限")
        primary = self._primary_role(roles, role_codes)
        self._uow.users.mark_login_success(user.id)
        pair = self._issue_tenant_session(user, primary, ip, user_agent)
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

    def _refresh_platform(
        self,
        refresh_token: str,
        tenant_id: UUID | None,
        ip: str | None,
        user_agent: str | None,
    ) -> TokenPair:
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

        role = self._resolve_platform_role(user)
        if CONSOLE_ACCESS not in self._role_codes((role,))[role.id]:
            self._uow.refresh_tokens.revoke_family(row.family_id)
            self._uow.commit()
            raise ForbiddenError("账号未获得管理端访问权限")

        pair = self._issue_session(
            user, role, ip, user_agent, family_id=row.family_id, rotated_from=row.id
        )
        self._uow.commit()
        return pair

    def _refresh_tenant(
        self,
        refresh_token: str,
        tenant_id: UUID,
        ip: str | None,
        user_agent: str | None,
    ) -> TokenPair:
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
        role_codes = self._role_codes(roles)
        if not self._has_console_access(roles, role_codes):
            self._uow.user_refresh_tokens.revoke_family(row.family_id)
            self._uow.commit()
            raise ForbiddenError("账号未获得管理端访问权限")
        primary = self._primary_role(roles, role_codes)
        pair = self._issue_tenant_session(
            user,
            primary,
            ip,
            user_agent,
            family_id=row.family_id,
            rotated_from=row.id,
        )
        self._uow.commit()
        return pair

    def _authenticate_tenant(
        self,
        user_id: UUID,
        token_version: int,
        session_id: UUID,
        token_tenant_id: UUID,
    ) -> AccessContext:
        user = self._uow.users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("账号不存在或已被禁用")
        if user.tenant_id != token_tenant_id:
            raise UnauthorizedError("身份凭证无效")
        if user.token_version != token_version:
            raise UnauthorizedError("登录状态已失效，请重新登录")
        if not self._uow.user_refresh_tokens.is_family_active(session_id):
            raise UnauthorizedError("登录状态已失效，请重新登录")
        roles = self._active_roles(user, UnauthorizedError)
        role_codes = self._role_codes(roles)
        if not self._has_console_access(roles, role_codes):
            raise ForbiddenError("账号未获得管理端访问权限")
        primary = self._primary_role(roles, role_codes)
        return AccessContext(
            user=self._to_admin_user(user, primary),
            session_id=session_id,
            role=primary,
            roles=roles,
        )

    def _change_platform_password(
        self,
        user_id: UUID,
        current_password: str,
        new_password: str,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
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

    def _change_tenant_password(
        self,
        user_id: UUID,
        current_password: str,
        new_password: str,
        tenant_id: UUID,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
        user = self._uow.users.get_by_id(user_id)
        if user is None or user.tenant_id != tenant_id:
            raise NotFoundError("管理员不存在")
        if not verify_password(current_password, user.password_hash):
            raise UnauthorizedError("当前密码不正确")
        validate_password_strength(new_password, user.username)
        if verify_password(new_password, user.password_hash):
            raise UnauthorizedError("新密码不能与当前密码相同")

        self._uow.users.update_password(
            user.id, hash_password(new_password), False, datetime.now(UTC)
        )
        self._uow.user_refresh_tokens.revoke_all_for_user(user.id)
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

    def _issue_session(
        self,
        user: AdminUser,
        role: Role,
        ip: str | None,
        user_agent: str | None,
        family_id: UUID | None = None,
        rotated_from: UUID | None = None,
    ) -> TokenPair:
        """创建平台账号刷新令牌（轮换场景保留同一 family）。"""
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
            user.id, user.username, role.code, family, user.token_version, user.tenant_id
        )
        return TokenPair(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=refresh_token,
            refresh_expires_in=int((expires_at - datetime.now(UTC)).total_seconds()),
            user=user,
        )

    def _issue_tenant_session(
        self,
        user: User,
        primary: Role,
        ip: str | None,
        user_agent: str | None,
        family_id: UUID | None = None,
        rotated_from: UUID | None = None,
    ) -> TokenPair:
        """租户管理员复用用户刷新令牌表，签发管理端访问令牌。"""
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

        access_token, expires_in = create_access_token(
            user.id,
            user.username,
            primary.code,
            family,
            user.token_version,
            user.tenant_id,
        )
        return TokenPair(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=refresh_token,
            refresh_expires_in=int((expires_at - datetime.now(UTC)).total_seconds()),
            user=self._to_admin_user(user, primary),
        )

    def _active_roles(
        self, user: User, error_cls: type[ForbiddenError] | type[UnauthorizedError]
    ) -> tuple[Role, ...]:
        """加载用户全部有效角色；没有可用角色时拒绝访问。"""
        roles: list[Role] = []
        for role_id in user.effective_role_ids():
            role = self._uow.roles.get_by_id(role_id)
            if role is None or role.tenant_id != user.tenant_id or not role.is_active:
                continue
            roles.append(role)
        if not roles:
            raise error_cls("账号角色已失效，请联系管理员")
        return tuple(roles)

    def _role_codes(self, roles: tuple[Role, ...]) -> dict[UUID, set[str]]:
        """按角色读取权限编码，供主角色选择与登录准入判断使用。"""
        return {role.id: self._uow.role_permissions.list_codes_for_role(role.id) for role in roles}

    @staticmethod
    def _has_console_access(roles: tuple[Role, ...], role_codes: dict[UUID, set[str]]) -> bool:
        """任一有效角色授予管理端访问权限即可登录。"""
        return any(CONSOLE_ACCESS in role_codes.get(role.id, set()) for role in roles)

    def _assert_console_access(self, roles: tuple[Role, ...]) -> None:
        """访问令牌校验阶段再次确认管理端访问权限仍有效。"""
        if not self._has_console_access(roles, self._role_codes(roles)):
            raise ForbiddenError("账号未获得管理端访问权限")

    @staticmethod
    def _primary_role(roles: tuple[Role, ...], role_codes: dict[UUID, set[str]]) -> Role:
        """优先选择拥有全量数据权限的角色作为主角色，否则取首个有效角色。"""
        for role in roles:
            if DATA_ALL in role_codes.get(role.id, set()):
                return role
        return roles[0]

    @staticmethod
    def _to_admin_user(user: User, primary: Role) -> AdminUser:
        """把租户用户映射为管理端账号视图。"""
        return AdminUser(
            id=user.id,
            username=user.username,
            password_hash=user.password_hash,
            display_name=user.display_name,
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
            token_version=user.token_version,
            failed_login_count=user.failed_login_count,
            locked_until=user.locked_until,
            must_change_password=user.must_change_password,
            password_changed_at=user.password_changed_at,
            tenant_id=user.tenant_id,
            role_id=primary.id,
            role_code=primary.code,
            role_name=primary.name,
        )

    def _record_login_failure(
        self,
        user_id: UUID | None,
        username: str,
        ip: str | None,
        user_agent: str | None,
        reason: str,
        tenant_id: UUID | None = None,
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

    def _record_refresh_replay(
        self, user_id: UUID, tenant_id: UUID, ip: str | None, user_agent: str | None
    ) -> None:
        """记录刷新令牌重放并撤销会话族。"""
        record_audit(
            self._uow,
            action="auth.refresh_replay",
            actor_id=user_id,
            ip=ip,
            user_agent=user_agent,
            tenant_id=tenant_id,
        )
        self._uow.commit()
