"""Alembic 迁移环境：URL 来自应用配置，迁移前加 advisory lock 防止并发。"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from alembic.operations.ops import (
    AlterColumnOp,
    CreateTableCommentOp,
    DropTableCommentOp,
    OpContainer,
)
from sqlalchemy import Column, String, Table, Uuid, engine_from_config, pool, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from internal.infrastructure.config.settings import get_settings  # noqa: E402
from internal.infrastructure.model import (  # noqa: E402,F401
    access,
    admin_user,
    agent_memory,
    audit_log,
    conversation,
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

# apps 域（application / run）与资源目录（resource_type_catalog）走 raw SQL、暂无 ORM
# 模型，但 conversation / agent_memory / application_auth / resource 等模型的外键引用了
# 它们的主键；autogenerate 解析外键需要目标表存在于 metadata，这里登记最小空壳仅供
# 解析，不参与比对（见 include_object）。后续补全模型时应删除对应空壳与排除项。
_RAW_SQL_STUBS: dict[str, tuple[str, object]] = {
    "application": ("id", Uuid(as_uuid=True)),
    "run": ("id", Uuid(as_uuid=True)),
    "resource_type_catalog": ("code", String(40)),
}
_RAW_SQL_TABLES = frozenset(_RAW_SQL_STUBS)
for _table_name, (_pk_column, _pk_type) in sorted(_RAW_SQL_STUBS.items()):
    if _table_name not in Base.metadata.tables:
        Table(
            _table_name,
            Base.metadata,
            Column(_pk_column, _pk_type, primary_key=True),
        )

# 迁移锁：同一数据库上的并发 alembic 实例串行执行
_ADVISORY_LOCK_KEY = 0x626F7869


def _database_url() -> str:
    """环境变量优先（测试/CI），否则读取应用配置。"""
    return os.environ.get("DATABASE_URL") or get_settings().database_url


def include_object(
    object_: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """索引、函数、触发器由迁移脚本显式维护，不参与 autogenerate 比对。

    表级额外排除两类：raw SQL 域表（如 application 空壳），以及数据库侧没有任何模型
    对应的表（reflected 且 compare_to 为 None），防止 drift 检查对未建模表误报。
    """
    if type_ == "index":
        return False
    if type_ == "table":
        if name in _RAW_SQL_TABLES:
            return False
        if reflected and compare_to is None:
            return False
    return True


def _remove_comment_ops(ops_list: list[object]) -> list[object]:
    """丢弃表注释与纯注释类列变更操作。

    迁移 0041 在库侧写入业务注释，模型侧并未逐列同步；注释差异对 autogenerate
    属纯噪音，统一过滤，保证 alembic check / revision 输出稳定。
    """
    kept: list[object] = []
    for op in ops_list:
        if isinstance(op, (CreateTableCommentOp, DropTableCommentOp)):
            continue
        if isinstance(op, AlterColumnOp):
            comment_only = (
                op.modify_comment is not False
                and op.modify_type is None
                and op.modify_nullable is None
                and op.modify_server_default is False
                and op.modify_name is None
            )
            if comment_only:
                continue
        if isinstance(op, OpContainer):
            op.ops = _remove_comment_ops(list(op.ops))
        kept.append(op)
    return kept


def _strip_comment_ops(ctx, revision, directives) -> None:
    """alembic 1.20 无 compare_comment 开关，在 directives 里事后过滤注释差异。"""
    for script in directives:
        if script.upgrade_ops is not None:
            script.upgrade_ops.ops = _remove_comment_ops(script.upgrade_ops.ops)
        if script.downgrade_ops is not None:
            script.downgrade_ops.ops = _remove_comment_ops(script.downgrade_ops.ops)


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL。"""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
        process_revision_directives=_strip_comment_ops,
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
                process_revision_directives=_strip_comment_ops,
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
