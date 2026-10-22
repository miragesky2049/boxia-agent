"""多租户隔离测试：子域名识别、账号隔离与产品级资源只读复用。"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from internal.application.errors import NotFoundError
from internal.domain.entity.request_context import PLATFORM_SCOPE, TENANT_SCOPE
from internal.domain.entity.tenant import Tenant
from internal.infrastructure.config.settings import Settings
from web.deps import tenant as tenant_deps
from web.deps.tenant import get_request_context

TENANT_ADMIN_PASSWORD = "Tenant-password-123"
TENANT_HEADER = "X-Tenant-Code"
TENANT_A = "acme"
TENANT_B = "globex"


def _create_tenant(client: TestClient, headers: dict[str, str], code: str, name: str) -> dict:
    response = client.post(
        "/api/v1/admin/tenants",
        json={
            "code": code,
            "name": name,
            "admin_username": f"{code}-admin",
            "admin_password": TENANT_ADMIN_PASSWORD,
            "admin_display_name": f"{name}管理员",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(tenant_client: TestClient, username: str, password: str = TENANT_ADMIN_PASSWORD) -> dict:
    response = tenant_client.post(
        "/api/v1/admin/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _skill_payload(name: str) -> dict:
    return {"name": name, "description": "", "content": "", "config": {}}


def test_platform_context(client: TestClient) -> None:
    response = client.get("/api/v1/public/context")

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "platform"
    assert body["tenant"] is None
    assert body["app_env"] == "test"
    assert body["tenant_resolution"] == "host"
    assert body["tenant_switch_mode"] == "none"
    assert body["root_domain"] == "example.com"
    assert body["platform_admin_subdomain"] == "adminsystem"
    assert body["platform_admin_host"] == "adminsystem.example.com"
    assert body["platform_name"] == "Agent运营管理平台"


def test_tenant_context_and_login(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    created = _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)

    public_context = acme.get("/api/v1/public/context")
    assert public_context.status_code == 200
    assert public_context.json()["scope"] == "tenant"
    assert public_context.json()["tenant"]["code"] == TENANT_A

    tokens = _login(acme, f"{TENANT_A}-admin")
    assert tokens["user"]["tenant_id"] == created["id"]
    assert tokens["user"]["is_platform"] is False

    context = acme.get("/api/v1/admin/context", headers=_bearer(tokens["access_token"]))
    assert context.status_code == 200, context.text
    assert context.json()["scope"] == "tenant"
    assert context.json()["user"]["username"] == f"{TENANT_A}-admin"


def test_platform_account_cannot_login_on_tenant_domain(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)

    response = acme.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "Admin-password-123"},
    )
    assert response.status_code == 401


def test_tenant_admin_cannot_manage_tenants(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)
    tokens = _login(acme, f"{TENANT_A}-admin")
    headers = _bearer(tokens["access_token"])

    assert acme.get("/api/v1/admin/tenants", headers=headers).status_code == 403
    response = acme.post(
        "/api/v1/admin/tenants",
        json={
            "code": "other",
            "name": "Other",
            "admin_username": "other-admin",
            "admin_password": TENANT_ADMIN_PASSWORD,
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_cross_scope_token_rejected(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    _create_tenant(client, auth_headers, TENANT_B, "Globex 公司")
    acme = tenant_client(TENANT_A)
    globex = tenant_client(TENANT_B)
    acme_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])

    assert globex.get("/api/v1/admin/auth/me", headers=acme_headers).status_code == 401


def test_platform_resource_visible_but_readonly_for_tenant(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)
    tenant_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])

    platform_skill = client.post(
        "/api/v1/admin/skills", json=_skill_payload("产品级技能"), headers=auth_headers
    )
    assert platform_skill.status_code == 201
    platform_id = platform_skill.json()["id"]
    assert platform_skill.json()["is_platform"] is True

    listed = acme.get("/api/v1/admin/skills?page_size=100", headers=tenant_headers)
    assert listed.status_code == 200
    assert platform_id in [item["id"] for item in listed.json()["items"]]

    assert (
        acme.get(f"/api/v1/admin/skills/{platform_id}", headers=tenant_headers).status_code == 200
    )
    update = acme.put(
        f"/api/v1/admin/skills/{platform_id}",
        json=_skill_payload("篡改"),
        headers=tenant_headers,
    )
    assert update.status_code == 403
    assert (
        acme.delete(f"/api/v1/admin/skills/{platform_id}", headers=tenant_headers).status_code
        == 403
    )

    # 产品级列表只展示产品级资源
    platform_listed = client.get("/api/v1/admin/skills?page_size=100", headers=auth_headers)
    assert [item["id"] for item in platform_listed.json()["items"]] == [platform_id]


def test_tenant_resources_isolated(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    acme_tenant = _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    _create_tenant(client, auth_headers, TENANT_B, "Globex 公司")
    acme = tenant_client(TENANT_A)
    globex = tenant_client(TENANT_B)
    acme_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])
    globex_headers = _bearer(_login(globex, f"{TENANT_B}-admin")["access_token"])

    created = acme.post(
        "/api/v1/admin/skills", json=_skill_payload("租户技能"), headers=acme_headers
    )
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]
    assert created.json()["tenant_id"] == acme_tenant["id"]
    assert created.json()["is_platform"] is False

    assert globex.get(f"/api/v1/admin/skills/{skill_id}", headers=globex_headers).status_code == 404
    assert (
        globex.get("/api/v1/admin/skills?page_size=100", headers=globex_headers).json()["total"]
        == 0
    )


def test_same_name_across_tenants(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    _create_tenant(client, auth_headers, TENANT_B, "Globex 公司")
    acme = tenant_client(TENANT_A)
    globex = tenant_client(TENANT_B)
    acme_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])
    globex_headers = _bearer(_login(globex, f"{TENANT_B}-admin")["access_token"])

    assert (
        acme.post(
            "/api/v1/admin/skills", json=_skill_payload("同名技能"), headers=acme_headers
        ).status_code
        == 201
    )
    assert (
        globex.post(
            "/api/v1/admin/skills", json=_skill_payload("同名技能"), headers=globex_headers
        ).status_code
        == 201
    )
    # 租户仍不能与产品级资源重名
    assert (
        client.post(
            "/api/v1/admin/skills", json=_skill_payload("同名技能"), headers=auth_headers
        ).status_code
        == 201
    )
    assert (
        acme.post(
            "/api/v1/admin/skills", json=_skill_payload("同名技能"), headers=acme_headers
        ).status_code
        == 409
    )


def test_tenant_users_scoped(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)
    tenant_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])

    created = acme.post(
        "/api/v1/admin/users",
        json={
            "username": "operator",
            "password": "Strong-password-456",
            "display_name": "运营",
            "role": "admin",
        },
        headers=tenant_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["tenant_id"] is not None

    listed = acme.get("/api/v1/admin/users?page_size=100", headers=tenant_headers)
    assert {item["username"] for item in listed.json()["items"]} == {
        f"{TENANT_A}-admin",
        "operator",
    }
    assert (
        acme.get("/api/v1/admin/users?all_tenants=true", headers=tenant_headers).status_code == 403
    )

    all_users = client.get(
        "/api/v1/admin/users?all_tenants=true&page_size=100", headers=auth_headers
    )
    assert all_users.status_code == 200
    assert all_users.json()["total"] == 3


def test_create_user_with_unknown_tenant_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/admin/users",
        json={
            "username": "ghost-admin",
            "password": "Strong-password-456",
            "display_name": "幽灵账号",
            "role": "admin",
            "tenant_id": 999999,
        },
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_tenant_login_failure_audited_in_tenant_scope(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)
    failed = acme.post(
        "/api/v1/admin/auth/login",
        json={"username": f"{TENANT_A}-admin", "password": "Wrong-password-999"},
    )
    assert failed.status_code == 401

    tenant_headers = _bearer(_login(acme, f"{TENANT_A}-admin")["access_token"])
    logs = acme.get(
        "/api/v1/admin/audit-logs?action=auth.login_failed&page_size=100",
        headers=tenant_headers,
    )
    assert logs.status_code == 200, logs.text
    assert logs.json()["total"] == 1


def _build_settings(**overrides) -> Settings:
    """构造独立 Settings，避免受进程级环境变量与 .env 影响。"""
    values = {
        "app_env": "test",
        "root_domain": "example.com",
        "database_url": "postgresql+psycopg://localhost/boxia_agent",
        "jwt_secret": "unit-test-secret-0123456789abcdef0123456789abcdef",
        "allow_tenant_header": False,
    }
    values.update(overrides)
    return Settings(**values)


def _fake_tenant(code: str) -> Tenant:
    """构造租户实体，避免单元测试依赖数据库。"""
    now = datetime(2026, 1, 1)
    return Tenant(
        id=1,
        code=code,
        name=f"{code} 公司",
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _request(host: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(b"host", host.encode())]
    for key, value in (headers or {}).items():
        # ASGI 服务器下发的小写头部名；Starlette 不额外做大小写归一
        raw_headers.append((key.lower().encode(), value.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": raw_headers,
            "server": (host.split(":")[0], 8000),
            "scheme": "http",
        }
    )


def _patch_tenant_loader(monkeypatch: pytest.MonkeyPatch, tenants: dict[str, Tenant]) -> None:
    """替换数据库加载，让单元测试只校验作用域解析分支。"""

    def _load(code: str) -> Tenant:
        tenant = tenants.get(code)
        if tenant is None:
            raise NotFoundError(f"租户不存在：{code}")
        return tenant

    monkeypatch.setattr(tenant_deps, "_load_tenant", _load)


def test_local_defaults_to_platform_without_root_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本地不配置 ROOT_DOMAIN 时，localhost 默认进入产品级平台。"""
    settings = _build_settings(app_env="local", root_domain="", allow_tenant_header=True)
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)

    context = get_request_context(_request("localhost:5173"))

    assert context.scope == PLATFORM_SCOPE
    assert context.tenant is None
    assert context.resolution == "default"


def test_deployed_environment_ignores_tenant_header_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """部署环境默认关闭请求头覆盖，作用域只由二级域名决定。"""
    settings = _build_settings(
        app_env="test",
        root_domain="example.com",
        allow_tenant_header=False,
    )
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)

    request = _request("adminsystem.example.com", {"X-Tenant-Code": "acme"})

    context = get_request_context(request)

    assert context.scope == PLATFORM_SCOPE
    assert context.tenant is None
    assert context.resolution == "host"


def test_prod_requires_root_domain() -> None:
    """生产环境未配置 ROOT_DOMAIN 时拒绝启动。"""
    with pytest.raises(ValidationError, match="ROOT_DOMAIN"):
        _build_settings(app_env="prod", root_domain="")


def test_prod_forbids_tenant_header() -> None:
    """生产环境必须通过二级域名识别租户，不允许开启请求头切换。"""
    with pytest.raises(ValidationError, match="ALLOW_TENANT_HEADER"):
        _build_settings(
            app_env="prod",
            root_domain="example.com",
            allow_tenant_header=True,
        )


def test_prod_rejects_localhost_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产环境使用 localhost 等非子域名 Host 时拒绝访问。"""
    settings = _build_settings(app_env="prod", root_domain="example.com")
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)

    with pytest.raises(NotFoundError):
        get_request_context(_request("localhost:5173"))


def test_prod_requires_subdomain(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产环境访问根域名（未配置默认租户）时要求改用二级域名。"""
    settings = _build_settings(
        app_env="prod",
        root_domain="example.com",
        default_tenant_code="",
    )
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)

    with pytest.raises(NotFoundError, match="租户子域名"):
        get_request_context(_request("example.com"))


def test_disabled_tenant_blocked(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    created = _create_tenant(client, auth_headers, TENANT_A, "Acme 公司")
    acme = tenant_client(TENANT_A)
    tokens = _login(acme, f"{TENANT_A}-admin")

    disabled = client.patch(
        f"/api/v1/admin/tenants/{created['id']}", json={"is_active": False}, headers=auth_headers
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    assert acme.get("/api/v1/public/context").status_code == 403
    assert (
        acme.get("/api/v1/admin/auth/me", headers=_bearer(tokens["access_token"])).status_code
        == 403
    )


def test_local_subdomain_resolves_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """本地 acme.localhost 按域名进入租户作用域。"""
    settings = _build_settings(app_env="local", root_domain="", allow_tenant_header=True)
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)
    _patch_tenant_loader(monkeypatch, {TENANT_A: _fake_tenant(TENANT_A)})

    context = get_request_context(_request("acme.localhost:5173"))

    assert context.scope == TENANT_SCOPE
    assert context.tenant is not None
    assert context.tenant.code == TENANT_A
    assert context.resolution == "host"


def test_local_subdomain_wins_over_tenant_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """域名优先：访问 acme.localhost 时请求头不能切到其他租户。"""
    settings = _build_settings(app_env="local", root_domain="", allow_tenant_header=True)
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)
    _patch_tenant_loader(
        monkeypatch,
        {TENANT_A: _fake_tenant(TENANT_A), TENANT_B: _fake_tenant(TENANT_B)},
    )

    context = get_request_context(_request("acme.localhost:5173", {TENANT_HEADER: TENANT_B}))

    assert context.tenant is not None
    assert context.tenant.code == TENANT_A
    assert context.resolution == "host"


def test_local_bootstrap_host_allows_header_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """本地回环主机保留请求头切换，用于快速调试。"""
    settings = _build_settings(app_env="local", root_domain="", allow_tenant_header=True)
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)
    _patch_tenant_loader(monkeypatch, {TENANT_B: _fake_tenant(TENANT_B)})

    context = get_request_context(_request("localhost:5173", {TENANT_HEADER: TENANT_B}))

    assert context.scope == TENANT_SCOPE
    assert context.tenant is not None
    assert context.tenant.code == TENANT_B
    assert context.resolution == "header"


def test_local_bootstrap_host_allows_platform_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """本地通过 platform 请求头值切回产品级平台。"""
    settings = _build_settings(app_env="local", root_domain="", allow_tenant_header=True)
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)

    context = get_request_context(_request("localhost:5173", {TENANT_HEADER: "platform"}))

    assert context.scope == PLATFORM_SCOPE
    assert context.tenant is None
    assert context.resolution == "header"


def test_local_default_tenant_code_applies_to_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本地回环主机无请求头时回退到默认租户。"""
    settings = _build_settings(
        app_env="local",
        root_domain="",
        allow_tenant_header=True,
        default_tenant_code=TENANT_A,
    )
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)
    _patch_tenant_loader(monkeypatch, {TENANT_A: _fake_tenant(TENANT_A)})

    context = get_request_context(_request("localhost:5173"))

    assert context.scope == TENANT_SCOPE
    assert context.tenant is not None
    assert context.tenant.code == TENANT_A
    assert context.resolution == "default"


def test_local_unknown_subdomain_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """本地访问不存在的租户子域名直接 404，不回退平台。"""
    settings = _build_settings(app_env="local", root_domain="", allow_tenant_header=True)
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)
    _patch_tenant_loader(monkeypatch, {})

    with pytest.raises(NotFoundError):
        get_request_context(_request("unknown.localhost:5173"))


def test_tenant_switch_mode_by_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """切换模式：本地回环主机=header，本地子域名=host，部署环境=none。"""
    local_settings = _build_settings(app_env="local", root_domain="", allow_tenant_header=True)
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: local_settings)
    _patch_tenant_loader(monkeypatch, {TENANT_A: _fake_tenant(TENANT_A)})

    bootstrap_context = get_request_context(_request("localhost:5173"))
    subdomain_context = get_request_context(_request("acme.localhost:5173"))

    assert tenant_deps.tenant_switch_mode(local_settings, bootstrap_context) == "header"
    assert tenant_deps.tenant_switch_mode(local_settings, subdomain_context) == "host"

    deployed_settings = _build_settings()
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: deployed_settings)
    deployed_context = get_request_context(_request("adminsystem.example.com"))
    assert tenant_deps.tenant_switch_mode(deployed_settings, deployed_context) == "none"


def test_non_local_unknown_host_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """部署环境未知域名与多级子域名均 404，不静默回退产品级平台。"""
    settings = _build_settings()
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)
    _patch_tenant_loader(monkeypatch, {})

    with pytest.raises(NotFoundError):
        get_request_context(_request("unknown.example.com"))
    with pytest.raises(NotFoundError):
        get_request_context(_request("a.b.example.com"))


def test_host_normalized_with_case_port_and_trailing_dot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host 的大小写、端口与尾点不影响作用域解析。"""
    settings = _build_settings()
    monkeypatch.setattr(tenant_deps, "get_settings", lambda: settings)

    context = get_request_context(_request("ADMINSYSTEM.Example.COM.:443"))

    assert context.scope == PLATFORM_SCOPE
    assert context.tenant is None
    assert context.resolution == "host"


def test_dev_requires_root_domain() -> None:
    """开发环境未配置 ROOT_DOMAIN 时拒绝启动。"""
    with pytest.raises(ValidationError, match="ROOT_DOMAIN"):
        _build_settings(app_env="dev", root_domain="")


def test_dev_forbids_tenant_header() -> None:
    """开发/测试环境只认域名，开启请求头切换即启动失败。"""
    with pytest.raises(ValidationError, match="ALLOW_TENANT_HEADER"):
        _build_settings(
            app_env="dev",
            root_domain="dev.example.com",
            allow_tenant_header=True,
        )
    with pytest.raises(ValidationError, match="ALLOW_TENANT_HEADER"):
        _build_settings(
            app_env="test",
            root_domain="test.example.com",
            allow_tenant_header=True,
        )


def test_public_tenant_list_hidden_outside_local(client: TestClient) -> None:
    """部署环境登录页不暴露租户列表。"""
    assert client.get("/api/v1/public/tenants").status_code == 403
