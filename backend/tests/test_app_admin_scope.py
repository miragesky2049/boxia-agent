"""应用管理范围（0069 二期）：app_admin_scope 增删查、管理性鉴权、"我管理的应用"过滤。"""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from tests.helpers import (
    USER_PASSWORD,
    create_tenant,
    create_user,
    list_roles,
    tenant_admin_client,
)

APPS_URL = "/api/v1/admin/apps"
TENANT_APPS_URL = "/api/v1/admin/tenant/apps"


# ========== 辅助 ==========
def _new_uow() -> SqlAlchemyUnitOfWork:
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    return uow


def _create_enabled_platform_app(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post(APPS_URL, json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    app_id = response.json()["application_id"]
    enabled = client.post(f"{APPS_URL}/{app_id}/enabled", json={"enabled": True}, headers=headers)
    assert enabled.status_code == 200, enabled.text
    return app_id


def _set_admin_scope_mode(
    client: TestClient, headers: dict[str, str], app_id: str, mode: str
) -> None:
    response = client.patch(
        f"{APPS_URL}/{app_id}", json={"admin_scope_mode": mode}, headers=headers
    )
    assert response.status_code == 200, response.text


def _subscribe(tenant_id: str, app_id: str) -> None:
    uow = _new_uow()
    try:
        uow.session.execute(
            text(
                "INSERT INTO tenant_application_instance "
                "(id, tenant_id, application_id, status, source, overrides) "
                "VALUES (:id, :tid, :aid, 'active', 'granted', '{}'::jsonb)"
            ),
            {"id": uuid4(), "tid": tenant_id, "aid": app_id},
        )
        uow.commit()
    finally:
        uow.close()


def _setup_tenant(client, auth_headers, tenant_client, code: str):
    tenant = create_tenant(client, auth_headers, code=code, name=f"{code} 公司")
    site, headers, _ = tenant_admin_client(tenant_client, code)
    return site, headers, list_roles(site, headers), tenant["id"]


def _create_unit(site: TestClient, headers: dict[str, str], name: str, code: str) -> str:
    response = site.post(
        "/api/v1/admin/mgmt-units", json={"name": name, "code": code}, headers=headers
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def _admin_login(tenant_client, code: str, username: str, password: str):
    """租户管理端登录：返回 (site, bearer headers)。"""
    site = tenant_client(code)
    response = site.post(
        "/api/v1/admin/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return site, {"Authorization": f"Bearer {response.json()['access_token']}"}


def _grant_user_unit(
    site: TestClient, headers, user_id: str, role_id: str, unit_ids: list[str]
) -> None:
    response = site.post(
        "/api/v1/admin/grants/users",
        json={
            "user_ids": [user_id],
            "role_ids": [role_id],
            "mgmt_unit_ids": unit_ids,
            "mode": "replace",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text


# ========== 用例 1：超管 CRUD 幂等 ==========
def test_admin_scope_crud_idempotent_for_superadmin(client, auth_headers, tenant_client) -> None:
    site, headers, _roles, _tid = _setup_tenant(client, auth_headers, tenant_client, "adm-crud")
    app_id = _create_enabled_platform_app(client, auth_headers, "关联应用")
    unit_id = _create_unit(site, headers, "华东大区", "adm-crud-unit")

    empty = site.get(f"{TENANT_APPS_URL}/{app_id}/admin-scope", headers=headers)
    assert empty.status_code == 200, empty.text
    assert empty.json() == []

    for _ in range(2):
        added = site.post(
            f"{TENANT_APPS_URL}/{app_id}/admin-scope",
            json={"mgmt_unit_id": unit_id},
            headers=headers,
        )
        assert added.status_code == 200, added.text

    listed = site.get(f"{TENANT_APPS_URL}/{app_id}/admin-scope", headers=headers)
    assert [item["mgmt_unit_id"] for item in listed.json()] == [unit_id]
    assert listed.json()[0]["mgmt_unit_name"] == "华东大区"

    removed = site.delete(f"{TENANT_APPS_URL}/{app_id}/admin-scope/{unit_id}", headers=headers)
    assert removed.status_code == 200, removed.text
    after = site.get(f"{TENANT_APPS_URL}/{app_id}/admin-scope", headers=headers)
    assert after.json() == []

    # 解除不存在的关联：幂等静默
    again = site.delete(f"{TENANT_APPS_URL}/{app_id}/admin-scope/{unit_id}", headers=headers)
    assert again.status_code == 200, again.text


# ========== 用例 2：mgmt_unit 模式 assert_manageable ==========
def test_mgmt_unit_mode_requires_unit_grant_for_admin_role(
    client, auth_headers, tenant_client
) -> None:
    site, headers, roles, _tid = _setup_tenant(client, auth_headers, tenant_client, "adm-unit")
    app_id = _create_enabled_platform_app(client, auth_headers, "单元应用")
    _set_admin_scope_mode(client, auth_headers, app_id, "mgmt_unit")
    unit1 = _create_unit(site, headers, "单元一", "adm-unit-1")
    unit2 = _create_unit(site, headers, "单元二", "adm-unit-2")

    # 超管（app:admin:all）先把 unit1 关联到应用
    assert (
        site.post(
            f"{TENANT_APPS_URL}/{app_id}/admin-scope",
            json={"mgmt_unit_id": unit1},
            headers=headers,
        ).status_code
        == 200
    )

    # admin 角色用户：有 app:admin / app:admin_scope:write，但无 app:admin:all 且未获单元授权 → 403
    admin_role_id = roles["admin"]["id"]
    member = create_user(site, headers, username="unitops", role_id=admin_role_id)
    member_site, member_headers = _admin_login(tenant_client, "adm-unit", "unitops", USER_PASSWORD)
    denied = member_site.post(
        f"{TENANT_APPS_URL}/{app_id}/admin-scope",
        json={"mgmt_unit_id": unit2},
        headers=member_headers,
    )
    assert denied.status_code == 403, denied.text
    assert "无权管理此应用" in denied.json()["detail"]

    # 查看不做管理性鉴权：仍 200
    assert (
        member_site.get(
            f"{TENANT_APPS_URL}/{app_id}/admin-scope", headers=member_headers
        ).status_code
        == 200
    )

    # 授予 unit1 后可管理：新增 unit2 关联、解除 unit2 均成功
    _grant_user_unit(site, headers, member["id"], admin_role_id, [unit1])
    # replace 授权会提升 token_version，旧令牌失效，需重新登录
    member_site, member_headers = _admin_login(tenant_client, "adm-unit", "unitops", USER_PASSWORD)
    added = member_site.post(
        f"{TENANT_APPS_URL}/{app_id}/admin-scope",
        json={"mgmt_unit_id": unit2},
        headers=member_headers,
    )
    assert added.status_code == 200, added.text
    removed = member_site.delete(
        f"{TENANT_APPS_URL}/{app_id}/admin-scope/{unit2}", headers=member_headers
    )
    assert removed.status_code == 200, removed.text


# ========== 用例 3：scope=managed 过滤 ==========
def test_managed_scope_filter(client, auth_headers, tenant_client) -> None:
    site, headers, roles, tenant_id = _setup_tenant(client, auth_headers, tenant_client, "adm-mng")
    app_all = _create_enabled_platform_app(client, auth_headers, "全管应用")
    app_unit = _create_enabled_platform_app(client, auth_headers, "单元管控应用")
    _set_admin_scope_mode(client, auth_headers, app_unit, "mgmt_unit")
    unit = _create_unit(site, headers, "管控单元", "adm-mng-unit")
    _subscribe(tenant_id, app_all)
    _subscribe(tenant_id, app_unit)
    assert (
        site.post(
            f"{TENANT_APPS_URL}/{app_unit}/admin-scope",
            json={"mgmt_unit_id": unit},
            headers=headers,
        ).status_code
        == 200
    )

    # 超管：app:admin:all 直通，两个都可见
    both = site.get(f"{TENANT_APPS_URL}?scope=managed", headers=headers)
    assert both.status_code == 200, both.text
    assert {item["id"] for item in both.json()} == {app_all, app_unit}

    # admin 角色：仅 all_admin 应用
    member = create_user(site, headers, username="mngops", role_id=roles["admin"]["id"])
    member_site, member_headers = _admin_login(tenant_client, "adm-mng", "mngops", USER_PASSWORD)
    only_all = member_site.get(f"{TENANT_APPS_URL}?scope=managed", headers=member_headers)
    assert only_all.status_code == 200, only_all.text
    assert {item["id"] for item in only_all.json()} == {app_all}

    # 授予管控单元后两个都可见（replace 授权会提升 token_version，需重新登录）
    _grant_user_unit(site, headers, member["id"], roles["admin"]["id"], [unit])
    member_site, member_headers = _admin_login(tenant_client, "adm-mng", "mngops", USER_PASSWORD)
    both2 = member_site.get(f"{TENANT_APPS_URL}?scope=managed", headers=member_headers)
    assert {item["id"] for item in both2.json()} == {app_all, app_unit}

    # 默认 scope=all：返回全部订阅应用
    default_all = member_site.get(TENANT_APPS_URL, headers=member_headers)
    assert {item["id"] for item in default_all.json()} == {app_all, app_unit}


# ========== 用例 4：缺 app:admin_scope:write 时写接口 403 ==========
def test_write_endpoints_require_admin_scope_write(client, auth_headers, tenant_client) -> None:
    site, headers, _roles, _tid = _setup_tenant(client, auth_headers, tenant_client, "adm-nowrite")
    app_id = _create_enabled_platform_app(client, auth_headers, "无写权限应用")
    unit = _create_unit(site, headers, "单元", "adm-nowrite-unit")

    # 自定义角色：有入口 + app:admin，但没有 app:admin_scope:write
    created = site.post(
        "/api/v1/admin/roles",
        json={"code": "adm-nowrite-role", "name": "只读管理角色"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]
    granted = site.put(
        f"/api/v1/admin/roles/{role_id}/permissions",
        json={
            "codes": [
                "system:console:access",
                "menu:tenant-apps",
                "page:tenant-apps",
                "app:admin",
            ]
        },
        headers=headers,
    )
    assert granted.status_code == 200, granted.text

    create_user(site, headers, username="readonly01", role_id=role_id)
    member_site, member_headers = _admin_login(
        tenant_client, "adm-nowrite", "readonly01", USER_PASSWORD
    )

    assert (
        member_site.get(
            f"{TENANT_APPS_URL}/{app_id}/admin-scope", headers=member_headers
        ).status_code
        == 200
    )
    denied = member_site.post(
        f"{TENANT_APPS_URL}/{app_id}/admin-scope",
        json={"mgmt_unit_id": unit},
        headers=member_headers,
    )
    assert denied.status_code == 403, denied.text
    assert "缺少管理范围编辑权限" in denied.json()["detail"]

    # 可见范围写接口同理：缺 app:visibility:write → 403
    vis_denied = member_site.put(
        f"{TENANT_APPS_URL}/{app_id}/visibility",
        json={"visibility": "all", "whitelist": []},
        headers=member_headers,
    )
    assert vis_denied.status_code == 403, vis_denied.text
    assert "缺少可见范围编辑权限" in vis_denied.json()["detail"]


# ========== 用例 5：租户侧关联推导生效模式（回归：平台列仍 all_admin 时按管理单元收敛） ==========
def test_scope_rows_derive_mgmt_unit_without_platform_mode(
    client, auth_headers, tenant_client
) -> None:
    site, headers, roles, tenant_id = _setup_tenant(
        client, auth_headers, tenant_client, "adm-deriv"
    )
    app_id = _create_enabled_platform_app(client, auth_headers, "推导应用")
    _subscribe(tenant_id, app_id)
    nanjing = _create_unit(site, headers, "南京mou", "adm-deriv-nj")
    beijing = _create_unit(site, headers, "北京mou", "adm-deriv-bj")

    # 超管仅通过管理范围面板关联南京mou，不改平台侧 admin_scope_mode（保持 all_admin）
    assert (
        site.post(
            f"{TENANT_APPS_URL}/{app_id}/admin-scope",
            json={"mgmt_unit_id": nanjing},
            headers=headers,
        ).status_code
        == 200
    )

    # 超管视角：可见，且展示口径应推导为 mgmt_unit 而非库里默认 all_admin
    super_list = site.get(f"{TENANT_APPS_URL}?scope=managed", headers=headers)
    assert super_list.status_code == 200, super_list.text
    item = next(row for row in super_list.json() if row["id"] == app_id)
    assert item["admin_scope_mode"] == "mgmt_unit"

    # 已订阅 tab：全员可见，但 manageable 按管理范围标记（超管 True）
    super_all = site.get(TENANT_APPS_URL, headers=headers)
    assert next(row for row in super_all.json() if row["id"] == app_id)["manageable"] is True

    # admin 角色、仅授予北京mou：不应在"我管理的应用"中看到该应用
    member = create_user(site, headers, username="derivops", role_id=roles["admin"]["id"])
    _grant_user_unit(site, headers, member["id"], roles["admin"]["id"], [beijing])
    member_site, member_headers = _admin_login(
        tenant_client, "adm-deriv", "derivops", USER_PASSWORD
    )
    member_list = member_site.get(f"{TENANT_APPS_URL}?scope=managed", headers=member_headers)
    assert member_list.status_code == 200, member_list.text
    assert app_id not in {row["id"] for row in member_list.json()}

    # 白名单编辑器下拉：admin 角色无 page:roles/page:users，但持 app:visibility:write → 读取放行
    assert member_site.get("/api/v1/admin/roles", headers=member_headers).status_code == 200
    assert member_site.get("/api/v1/admin/users/options", headers=member_headers).status_code == 200

    # 已订阅 tab 仍可见，但 manageable=False（前端据此只读）
    member_all = member_site.get(TENANT_APPS_URL, headers=member_headers)
    assert next(row for row in member_all.json() if row["id"] == app_id)["manageable"] is False

    # 详情可见范围：manageable 标记同口径
    member_vis = member_site.get(f"{TENANT_APPS_URL}/{app_id}/visibility", headers=member_headers)
    assert member_vis.status_code == 200, member_vis.text
    assert member_vis.json()["manageable"] is False

    # 同口径鉴权：北京mou 管理员对该应用写管理范围应 403
    denied = member_site.post(
        f"{TENANT_APPS_URL}/{app_id}/admin-scope",
        json={"mgmt_unit_id": beijing},
        headers=member_headers,
    )
    assert denied.status_code == 403, denied.text

    # 可见范围写接口同样被管理范围拦截：北京mou 管理员 PUT → 403
    vis_denied = member_site.put(
        f"{TENANT_APPS_URL}/{app_id}/visibility",
        json={"visibility": "all", "whitelist": []},
        headers=member_headers,
    )
    assert vis_denied.status_code == 403, vis_denied.text
    assert "无权管理此应用" in vis_denied.json()["detail"]

    # 授予南京mou 后可见
    _grant_user_unit(site, headers, member["id"], roles["admin"]["id"], [beijing, nanjing])
    member_site, member_headers = _admin_login(
        tenant_client, "adm-deriv", "derivops", USER_PASSWORD
    )
    member_list2 = member_site.get(f"{TENANT_APPS_URL}?scope=managed", headers=member_headers)
    assert app_id in {row["id"] for row in member_list2.json()}

    # 授予南京mou 后可见范围写入放行
    vis_ok = member_site.put(
        f"{TENANT_APPS_URL}/{app_id}/visibility",
        json={"visibility": "all", "whitelist": []},
        headers=member_headers,
    )
    assert vis_ok.status_code == 200, vis_ok.text
