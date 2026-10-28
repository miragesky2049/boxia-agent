"""跨测试文件复用的租户、账号与资源构造工具。"""

from itertools import count
from uuid import UUID

from fastapi.testclient import TestClient

TENANT_ADMIN_PASSWORD = "Tenant-password-123"
USER_PASSWORD = "User-password-123"

_department_name_counter = count(1)


def create_department(
    site: TestClient, headers: dict[str, str], name: str | None = None
) -> dict:
    """创建租户部门并返回响应体；默认名带自增后缀避免同租户重名冲突。"""
    if name is None:
        name = f"默认部门-{next(_department_name_counter)}"
    response = site.post(
        "/api/v1/admin/departments", json={"name": name}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_tenant(
    client: TestClient,
    headers: dict[str, str],
    code: str = "acme",
    name: str = "Acme 公司",
) -> dict:
    """创建租户并返回响应体（含自动生成的系统角色与超管账号）。"""
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


def tenant_admin_client(tenant_client, code: str) -> tuple[TestClient, dict[str, str], dict]:
    """返回租户站点客户端、超管鉴权头与登录响应体。"""
    site = tenant_client(code)
    response = site.post(
        "/api/v1/admin/auth/login",
        json={"username": f"{code}-admin", "password": TENANT_ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return site, {"Authorization": f"Bearer {body['access_token']}"}, body


def list_roles(site: TestClient, headers: dict[str, str]) -> dict[str, dict]:
    """按编码索引当前租户角色。"""
    response = site.get("/api/v1/admin/roles", headers=headers)
    assert response.status_code == 200, response.text
    return {item["code"]: item for item in response.json()}


def create_user(
    site: TestClient,
    headers: dict[str, str],
    *,
    username: str = "acme-user",
    role_id: UUID,
    password: str = USER_PASSWORD,
    display_name: str = "用户",
    is_active: bool = True,
) -> dict:
    """创建最终用户。"""
    response = site.post(
        "/api/v1/admin/users",
        json={
            "username": username,
            "password": password,
            "display_name": display_name,
            "role_ids": [role_id],
            "is_active": is_active,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_agent(
    client: TestClient,
    headers: dict[str, str],
    name: str,
    is_enabled: bool = True,
    department_id: str | None = None,
) -> dict:
    """创建智能体（默认无关联资源）。

    租户站点调用时若未传 department_id，自动创建一个默认部门并挂上，
    以满足租户智能体"所属部门必填"的校验。
    """
    payload = {
        "name": name,
        "avatar_url": "",
        "description": "",
        "is_enabled": is_enabled,
        "config": {},
        "tool_ids": [],
        "skill_ids": [],
        "department_id": department_id,
    }
    response = client.post("/api/v1/admin/agents", json=payload, headers=headers)
    if response.status_code == 422 and department_id is None:
        dept = create_department(client, headers)
        payload["department_id"] = dept["id"]
        response = client.post("/api/v1/admin/agents", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def grant_resource(
    client: TestClient,
    headers: dict[str, str],
    *,
    resource_type: str,
    resource_id: UUID,
    grants: list[dict],
) -> dict:
    """平台或租户整体替换资源授权。"""
    response = client.put(
        "/api/v1/admin/grants",
        params={"resource_type": resource_type, "resource_id": resource_id},
        json={"grants": grants},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()
