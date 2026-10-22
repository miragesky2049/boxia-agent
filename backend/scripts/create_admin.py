"""创建管理员账号（生产初始化使用，禁止提交密码）。

用法：
    ADMIN_USERNAME=admin ADMIN_PASSWORD='...' python -m scripts.create_admin
未提供 ADMIN_PASSWORD 时从标准输入读取（推荐）。
ADMIN_MUST_CHANGE_PASSWORD=false 可关闭首登改密，仅用于自动化环境。
"""

import getpass
import os
import sys

from sqlalchemy import text

from internal.infrastructure.model.database import dispose_engine, get_engine
from internal.infrastructure.security.password import hash_password, validate_password_strength


def _must_change_password() -> bool:
    """读取首登改密开关，自动化环境可显式关闭。"""
    raw = os.environ.get("ADMIN_MUST_CHANGE_PASSWORD", "true").strip().lower()
    return raw not in {"false", "0", "no"}


def main() -> int:
    """创建或更新管理员账号，并默认强制首次登录改密。"""
    username = os.environ.get("ADMIN_USERNAME", "admin").strip()
    display_name = os.environ.get("ADMIN_DISPLAY_NAME", "系统管理员").strip()
    role = os.environ.get("ADMIN_ROLE", "superadmin").strip()
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("管理员密码: ")
    if not password:
        print("密码不能为空", file=sys.stderr)
        return 2

    try:
        validate_password_strength(password, username)
    except Exception as exc:  # 密码策略错误直接反馈给初始化人员
        print(f"密码不符合策略: {exc}", file=sys.stderr)
        return 2

    password_hash = hash_password(password)
    must_change = _must_change_password()
    engine = get_engine()
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT id FROM admin_users WHERE username = :username"),
                {"username": username},
            ).first()
            if exists:
                conn.execute(
                    text(
                        "UPDATE admin_users SET password_hash = :hash, display_name = :name, "
                        "role = :role, is_active = TRUE, failed_login_count = 0, "
                        "locked_until = NULL, must_change_password = :must_change, "
                        "token_version = token_version + 1, password_changed_at = now() "
                        "WHERE id = :id"
                    ),
                    {
                        "hash": password_hash,
                        "name": display_name,
                        "role": role,
                        "must_change": must_change,
                        "id": exists[0],
                    },
                )
                print(f"管理员 {username} 已存在，密码已重置")
            else:
                conn.execute(
                    text(
                        "INSERT INTO admin_users "
                        "(username, password_hash, display_name, role, is_active, "
                        "must_change_password, password_changed_at) "
                        "VALUES (:username, :hash, :name, :role, TRUE, :must_change, now())"
                    ),
                    {
                        "username": username,
                        "hash": password_hash,
                        "name": display_name,
                        "role": role,
                        "must_change": must_change,
                    },
                )
                print(f"管理员 {username} 创建成功")
    finally:
        dispose_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
