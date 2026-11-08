"""租户管理员保存用户授权：granted_by 引用 users.id 不应再触发外键冲突。"""

from tests.helpers import (
    create_tenant,
    create_user,
    tenant_admin_client,
)


def test_tenant_admin_grant_user_with_mgmt_unit(
    client,
    tenant_client,
    auth_headers,
):
    """租户管理员编辑用户授权并指定管理单元，granted_by 是 users.id，不应报 CONFLICT。"""
    create_tenant(client, auth_headers, code="acme")
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    # 列出角色：取 admin 角色
    roles = site.get("/api/v1/admin/roles", headers=headers).json()
    role_id = next(r["id"] for r in roles if r["code"] == "admin")

    # 创建管理单元
    unit_resp = site.post(
        "/api/v1/admin/mgmt-units",
        json={"name": "一部", "code": "dept-1"},
        headers=headers,
    )
    assert unit_resp.status_code in (200, 201), unit_resp.text
    unit_id = unit_resp.json()["id"]

    # 创建目标用户
    user = create_user(site, headers, username="alice", role_id=role_id)

    # 编辑授权：整体覆盖角色 + 管理单元
    resp = site.post(
        "/api/v1/admin/grants/users",
        json={
            "user_ids": [user["id"]],
            "role_ids": [role_id],
            "mgmt_unit_ids": [unit_id],
            "mode": "replace",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
