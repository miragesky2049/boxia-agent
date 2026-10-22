"""健康检查端点：存活与就绪。"""

import logging
from functools import lru_cache

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from internal.infrastructure.config.settings import BACKEND_DIR
from internal.infrastructure.model.database import get_engine

logger = logging.getLogger("boxia.health")
router = APIRouter(tags=["ops"])


@lru_cache(maxsize=1)
def _expected_revision() -> str:
    """读取当前代码期望的 Alembic head。"""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    return heads[0] if heads else ""


def _database_status() -> tuple[bool, str]:
    """检查数据库连通性与迁移版本。"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    except Exception as exc:  # 就绪检查需要把失败原因返回给运维
        logger.warning("readiness database check failed: %s", exc)
        return False, "database_unavailable"

    current = row[0] if row else ""
    expected = _expected_revision()
    if expected and current != expected:
        logger.warning("migration mismatch current=%s expected=%s", current, expected)
        return False, "migration_outdated"
    return True, "ok"


@router.get("/health/live", include_in_schema=False)
def live() -> dict[str, str]:
    """进程存活检查。"""
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
def ready(response: Response) -> dict:
    """依赖就绪检查：数据库连通且迁移版本一致。"""
    database_ok, database_detail = _database_status()
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if database_ok else "unavailable",
        "components": {"database": database_detail},
        "version": _expected_revision(),
    }
