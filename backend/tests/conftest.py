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
os.environ["USER_API_TOKEN"] = "test-user-token-0123456789abcdef"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ROOT_DOMAIN"] = "example.com"
os.environ["PLATFORM_ADMIN_SUBDOMAIN"] = "adminsystem"
os.environ["ALLOW_TENANT_HEADER"] = "true"

PLATFORM_HOST = "adminsystem.example.com"
TENANT_HEADER = "X-Tenant-Code"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from internal.infrastructure.model.database import dispose_engine, get_engine  # noqa: E402
from internal.infrastructure.security.password import hash_password  # noqa: E402
from internal.infrastructure.trace.exporter import get_tracer_provider  # noqa: E402
from web.app import app  # noqa: E402

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
        conn.execute(
            text(
                "INSERT INTO admin_users "
                "(username, password_hash, display_name, role, must_change_password) "
                "VALUES (:username, :password_hash, :display_name, 'superadmin', FALSE)"
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
    """默认以产品级平台域名访问，与生产 adminsystem 子域名一致。"""
    with TestClient(app, base_url=f"http://{PLATFORM_HOST}") as test_client:
        yield test_client


@pytest.fixture(scope="session")
def tenant_client():
    """以租户子域名访问的客户端，用于验证租户级隔离。"""

    def _factory(tenant_code: str) -> TestClient:
        return TestClient(app, base_url=f"http://{tenant_code}.example.com")

    return _factory


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
