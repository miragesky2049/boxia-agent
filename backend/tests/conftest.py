"""pytest 全局夹具：独立测试库 + Alembic 迁移 + 用例级数据隔离。

环境变量必须在导入 web.app 之前设置，因为 Settings / Engine 均为进程级缓存。
"""

import os
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
from sqlalchemy import bindparam, text  # noqa: E402

from internal.domain.entity.permission import (  # noqa: E402
    PERMISSION_CATALOG,
    PLATFORM_ADMIN_CODES,
    PLATFORM_SUPERADMIN_CODES,
    PLATFORM_VIEWER_CODES,
)
from internal.infrastructure.model.database import dispose_engine, get_engine  # noqa: E402
from internal.infrastructure.security.password import hash_password  # noqa: E402
from internal.infrastructure.trace.exporter import get_tracer_provider  # noqa: E402
from web.app import create_app  # noqa: E402

ADMIN_APP = create_app("admin")
USER_APP = create_app("user")

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Admin-password-123"
ADMIN_HASH = hash_password(ADMIN_PASSWORD)


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
        # TRUNCATE 会清掉迁移种子，需重建权限目录、平台系统角色与角色权限关系
        conn.execute(
            text(
                "INSERT INTO permission_resources "
                "(code, name, category, action, description, sort_order, is_active) "
                "VALUES (:code, :name, :category, :action, :description, :sort_order, TRUE)"
            ),
            [
                {
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
                "INSERT INTO roles "
                "(tenant_id, code, name, description, is_system, is_active) "
                "VALUES "
                "(NULL, 'superadmin', '超级管理员', '平台最高权限，可访问全部平台级资源', TRUE, TRUE), "
                "(NULL, 'admin', '管理员', '可读写被授权的平台级资源', TRUE, TRUE), "
                "(NULL, 'viewer', '只读成员', '只读访问被授权的平台级资源', TRUE, TRUE)"
            )
        )
        grant_stmt = text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permission_resources p "
            "WHERE r.tenant_id IS NULL AND r.code = :role_code AND p.code IN :codes"
        ).bindparams(bindparam("codes", expanding=True))
        for role_code, codes in (
            ("superadmin", PLATFORM_SUPERADMIN_CODES),
            ("admin", PLATFORM_ADMIN_CODES),
            ("viewer", PLATFORM_VIEWER_CODES),
        ):
            conn.execute(grant_stmt, {"role_code": role_code, "codes": sorted(codes)})
        conn.execute(
            text(
                "INSERT INTO admin_users "
                "(username, password_hash, display_name, role_id, must_change_password) "
                "VALUES (:username, :password_hash, :display_name, "
                "        (SELECT id FROM roles WHERE tenant_id IS NULL AND code = 'superadmin'), "
                "        FALSE)"
            ),
            {
                "username": ADMIN_USERNAME,
                "password_hash": ADMIN_HASH,
                "display_name": "系统管理员",
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
