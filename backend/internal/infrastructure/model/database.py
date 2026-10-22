"""数据库引擎与会话工厂。"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from internal.infrastructure.config.settings import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """创建数据库引擎（连接池、探活、语句超时）。"""
    settings = get_settings()
    options = (
        f"-c statement_timeout={settings.statement_timeout_ms} "
        f"-c lock_timeout={settings.lock_timeout_ms}"
    )
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_recycle=settings.database_pool_recycle,
        connect_args={"options": options},
        future=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """创建会话工厂。"""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def dispose_engine() -> None:
    """释放连接池并清空缓存（应用关闭或测试切换库时调用）。"""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
