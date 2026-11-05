"""pytest 全局夹具：独立测试库 + Alembic 迁移 + 用例级数据隔离。

环境变量必须在导入 web.app 之前设置，因为 Settings / Engine 均为进程级缓存。
"""

import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PG_BASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432"
TEST_DB_NAME = "boxia_agent_test"

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DB_NAME}"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef0123456789abcdef"
os.environ["ACCESS_TOKEN_MINUTES"] = "60"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ROOT_DOMAIN"] = "example.com"
os.environ["PLATFORM_ADMIN_SUBDOMAIN"] = "adminsystem"
# 本机 Windows + Docker 环境下 TRUNCATE 全库偶发超过默认 5s，测试环境放宽等待上限
os.environ["STATEMENT_TIMEOUT_MS"] = "60000"
os.environ["LOCK_TIMEOUT_MS"] = "30000"
# 部署环境只按域名识别租户；集成用例统一使用 tenant_client 的子域名访问
os.environ["ALLOW_TENANT_HEADER"] = "false"

PLATFORM_HOST = "adminsystem.example.com"
TENANT_HEADER = "X-Tenant-Code"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from internal.domain.constants import PLATFORM_TENANT_ID  # noqa: E402
from internal.domain.entity.access import RESOURCE_TABLE_TYPES  # noqa: E402
from internal.domain.entity.permission import (  # noqa: E402
    PERMISSION_CATALOG,
    PLATFORM_ADMIN_CODES,
    PLATFORM_SUPERADMIN_CODES,
    PLATFORM_VIEWER_CODES,
)
from internal.infrastructure.cache.factory import set_kv_cache_override  # noqa: E402
from internal.infrastructure.cache.redis_kv_cache import InMemoryKvCache  # noqa: E402
from internal.infrastructure.id.uuid7 import new_uuid  # noqa: E402
from internal.infrastructure.model.database import dispose_engine, get_engine  # noqa: E402
from internal.infrastructure.security.password import hash_password  # noqa: E402
from internal.infrastructure.trace.exporter import get_tracer_provider  # noqa: E402
from web.app import create_app  # noqa: E402

# TestClient 每请求/每客户端使用不同事件循环，redis.asyncio 连接池绑定首个循环，
# 跨循环复用必炸；测试进程统一用内存缓存（无跨进程广播诉求）
set_kv_cache_override(InMemoryKvCache())

ADMIN_APP = create_app("admin")
USER_APP = create_app("user")

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Admin-password-123"
ADMIN_HASH = hash_password(ADMIN_PASSWORD)

# 资源类型目录展示名（与迁移 0061 种子一致），供用例级重建
_TYPE_CATALOG_NAMES = {"tool": "工具", "skill": "技能", "prompt": "提示词", "knowledge": "知识库"}


def _recreate_test_database() -> None:
    """强制重建测试库，保证每次会话从迁移得到干净结构。"""
    with psycopg.connect(f"{PG_BASE_URL}/postgres", autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')


def _run_migrations() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    _recreate_test_database()
    _run_migrations()
    yield
    # 先同步关闭 exporter，避免后台线程在 pytest 捕获流关闭后仍写控制台
    get_tracer_provider().shutdown()
    dispose_engine()


@pytest.fixture(autouse=True)
def _reset_data():
    with get_engine().begin() as conn:
        existing = set(
            conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            ).scalars()
        )
        tables = ", ".join(sorted(existing))
        if tables:
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        # TRUNCATE 会清掉迁移种子，需重建产品级平台租户、权限目录、资源类型目录、平台系统角色与角色权限关系。
        # 主键已改为应用层 UUID v7，原生 INSERT 必须显式写入 id。
        conn.execute(
            text(
                "INSERT INTO tenants (id, code, name, is_active) "
                "VALUES (:id, 'platform', '产品级平台', TRUE) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": str(PLATFORM_TENANT_ID)},
        )
        conn.execute(
            text(
                "INSERT INTO permission_resources "
                "(id, code, name, category, action, description, sort_order, is_active) "
                "VALUES (:id, :code, :name, :category, :action, :description, :sort_order, TRUE)"
            ),
            [
                {
                    "id": new_uuid(),
                    "code": item.code,
                    "name": item.name,
                    "category": item.category,
                    "action": item.action,
                    "description": item.description,
                    "sort_order": item.sort_order,
                }
                for item in PERMISSION_CATALOG
            ],
        )
        conn.execute(
            text(
                "INSERT INTO resource_type_catalog (code, name, sort_order) "
                "VALUES (:code, :name, :sort_order)"
            ),
            [
                {
                    "code": code,
                    "name": _TYPE_CATALOG_NAMES[code],
                    "sort_order": order,
                }
                for order, code in enumerate(RESOURCE_TABLE_TYPES, start=1)
            ],
        )
        conn.execute(
            text(
                "INSERT INTO roles "
                "(id, tenant_id, code, name, description, is_system, is_active) "
                "VALUES (:id, :tenant_id, :code, :name, :description, TRUE, TRUE)"
            ),
            [
                {
                    "id": new_uuid(),
                    "tenant_id": str(PLATFORM_TENANT_ID),
                    "code": code,
                    "name": name,
                    "description": description,
                }
                for code, name, description in (
                    ("superadmin", "超级管理员", "平台最高权限，可访问全部平台级资源"),
                    ("admin", "管理员", "可读写被授权的平台级资源"),
                    ("viewer", "只读成员", "只读访问被授权的平台级资源"),
                )
            ],
        )
        role_ids = {
            code: role_id
            for code, role_id in conn.execute(
                text("SELECT code, id FROM roles WHERE tenant_id = :tenant_id"),
                {"tenant_id": str(PLATFORM_TENANT_ID)},
            ).tuples()
        }
        permission_ids = {
            code: permission_id
            for code, permission_id in conn.execute(
                text("SELECT code, id FROM permission_resources")
            ).tuples()
        }
        grant_stmt = text(
            "INSERT INTO role_permissions (id, role_id, permission_id) "
            "VALUES (:id, :role_id, :permission_id)"
        )
        for role_code, codes in (
            ("superadmin", PLATFORM_SUPERADMIN_CODES),
            ("admin", PLATFORM_ADMIN_CODES),
            ("viewer", PLATFORM_VIEWER_CODES),
        ):
            for permission_code in sorted(codes):
                conn.execute(
                    grant_stmt,
                    {
                        "id": new_uuid(),
                        "role_id": role_ids[role_code],
                        "permission_id": permission_ids[permission_code],
                    },
                )
        conn.execute(
            text(
                "INSERT INTO admin_users "
                "(id, username, password_hash, display_name, role_id, must_change_password) "
                "VALUES (:id, :username, :password_hash, :display_name, :role_id, FALSE)"
            ),
            {
                "id": new_uuid(),
                "username": ADMIN_USERNAME,
                "password_hash": ADMIN_HASH,
                "display_name": "系统管理员",
                "role_id": role_ids["superadmin"],
            },
        )
    yield


@pytest.fixture(scope="session")
def client():
    """管理站点客户端：默认以产品级平台域名访问，与生产 adminsystem 子域名一致。"""
    with TestClient(ADMIN_APP, base_url=f"http://{PLATFORM_HOST}") as test_client:
        yield test_client


@pytest.fixture(scope="session")
def tenant_client():
    """管理站点租户客户端：以租户子域名访问，用于验证租户级隔离。"""

    def _factory(tenant_code: str) -> TestClient:
        return TestClient(ADMIN_APP, base_url=f"http://{tenant_code}.example.com")

    return _factory


@pytest.fixture(scope="session")
def user_client():
    """用户站点客户端：站点仅挂载 user 路由，不含 admin / public。"""
    with TestClient(USER_APP, base_url=f"http://{PLATFORM_HOST}") as test_client:
        yield test_client


@pytest.fixture(scope="session")
def user_tenant_client():
    """用户站点租户客户端：以租户子域名访问。"""

    def _factory(tenant_code: str) -> TestClient:
        return TestClient(USER_APP, base_url=f"http://{tenant_code}.example.com")

    return _factory


@pytest.fixture(scope="session")
def persistent_user_tenant_client():
    """会话级常驻用户站点客户端：同一租户子域名全程共享一个事件循环。

    工厂版 user_tenant_client 未进入 with，每个请求新建 portal/循环，
    无法承载绑定首个循环的进程级 AsyncPostgresSaver；真实图执行类用例必须用本夹具。
    """
    clients: dict[str, TestClient] = {}

    def _factory(tenant_code: str) -> TestClient:
        if tenant_code not in clients:
            # 仅让该客户端的 portal 跑在 SelectorEventLoop 上（psycopg async 要求）；
            # 切回默认策略，避免影响依赖 ProactorEventLoop 子进程能力的 code node 用例
            if sys.platform == "win32":
                previous_policy = asyncio.get_event_loop_policy()
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            try:
                managed = TestClient(
                    USER_APP, base_url=f"http://{tenant_code}.example.com"
                )
                managed.__enter__()
            finally:
                if sys.platform == "win32":
                    asyncio.set_event_loop_policy(previous_policy)
            clients[tenant_code] = managed
        return clients[tenant_code]

    yield _factory

    for managed in clients.values():
        managed.__exit__(None, None, None)


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def user_login_headers(user_tenant_client):
    """最终用户登录：返回按租户子域名登录后的 Bearer 头。"""

    def _login(
        tenant_code: str,
        username: str,
        password: str,
    ) -> dict[str, str]:
        client = user_tenant_client(tenant_code)
        response = client.post(
            "/api/v1/user/auth/login",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login
