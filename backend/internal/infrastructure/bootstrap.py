"""应用启动时的数据库初始化引导：产品级平台管理员自动初始化。"""

from __future__ import annotations

import logging

from sqlalchemy import text

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.infrastructure.config.settings import Settings
from internal.infrastructure.id.uuid7 import new_uuid
from internal.infrastructure.model.database import get_engine
from internal.infrastructure.security.password import hash_password, validate_password_strength

logger = logging.getLogger(__name__)


def ensure_platform_admin(settings: Settings) -> None:
    """部署时自动初始化首个平台管理员账号。

    仅当 admin_auto_init_enabled（开关开启 + 密码已配置）且 admin_users 表为空时执行：
    1. 校验初始密码强度
    2. 查找配置的平台角色（默认 superadmin）
    3. 插入首个平台管理员账号
    """
    if not settings.admin_auto_init_enabled:
        if settings.admin_auto_init:
            logger.info("ADMIN_AUTO_INIT 已开启但未配置 ADMIN_INITIAL_PASSWORD，跳过自动初始化")
        return

    raw_password = settings.admin_initial_password.get_secret_value()
    username = settings.admin_initial_username.strip()
    role_code = settings.admin_initial_role.strip()
    display_name = settings.admin_initial_display_name.strip() or username
    must_change = settings.admin_initial_must_change_password

    try:
        validate_password_strength(raw_password, username)
    except Exception as exc:
        logger.warning("初始管理员密码不符合策略，跳过自动初始化: %s", exc)
        return

    engine = get_engine()
    with engine.begin() as conn:
        role_id = conn.execute(
            text(
                "SELECT id FROM roles WHERE tenant_id = :tid AND code = :code "
                "AND is_active = TRUE"
            ),
            {"code": role_code, "tid": str(PLATFORM_TENANT_ID)},
        ).scalar()
        if role_id is None:
            logger.warning("平台角色 %s 不存在或已停用，跳过自动初始化", role_code)
            return

        existing = conn.execute(
            text("SELECT 1 FROM admin_users LIMIT 1")
        ).first()
        if existing is not None:
            logger.info("admin_users 表已有账号，跳过自动初始化")
            return

        password_hash = hash_password(raw_password)
        conn.execute(
            text(
                "INSERT INTO admin_users "
                "(id, username, password_hash, display_name, role_id, is_active, "
                "must_change_password, password_changed_at) "
                "VALUES (:id, :username, :hash, :name, :role_id, TRUE, :must_change, now())"
            ),
            {
                "id": new_uuid(),
                "username": username,
                "hash": password_hash,
                "name": display_name,
                "role_id": role_id,
                "must_change": must_change,
            },
        )
        logger.info("自动初始化平台管理员账号成功: %s", username)
