"""Alembic 迁移环境：URL 来自应用配置，迁移前加 advisory lock 防止并发。"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from internal.infrastructure.config.settings import get_settings  # noqa: E402
from internal.infrastructure.model import (  # noqa: E402,F401
    access,
    admin_user,
    audit_log,
    department,
    document,
    employment,
    hr_dictionary,
    mgmt_unit,
    refresh_token,
    resource,
    tenant,
)
from internal.infrastructure.model.base import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# 迁移锁：同一数据库上的并发 alembic 实例串行执行
_ADVISORY_LOCK_KEY = 0x626F7869


def _database_url() -> str:
    """环境变量优先（测试/CI），否则读取应用配置。"""
    return os.environ.get("DATABASE_URL") or get_settings().database_url


def include_object(
    object_: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """索引、函数、触发器由迁移脚本显式维护，不参与 autogenerate 比对。"""
    return type_ != "index"


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL。"""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库并在 advisory lock 保护下执行迁移。"""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url().replace("%", "%%")
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                include_object=include_object,
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY})
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
