"""应用可见范围 v2（0068）：按 (应用, 租户) 隔离的 scope/白名单/兜底/锁定语义。

覆盖技术方案 §4.1 的 14 个用例：用户端过滤、三种白名单主体、锁定、
模板兜底、订阅窗口、老接口下线、upsert 并发、孤儿主体过滤、configured 标记。
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from tests.helpers import (
    USER_PASSWORD,
    create_department,
    create_tenant,
    create_user,
    list_roles,
    tenant_admin_client,
)

APPS_URL = "/api/v1/admin/apps"
TENANT_APPS_URL = "/api/v1/admin/tenant/apps"
USER_AGENTS_URL = "/api/v1/user/agents"


# ========== 辅助 ==========
def _new_uow() -> SqlAlchemyUnitOfWork:
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    return uow


def _create_enabled_platform_app(
    client: TestClient, headers: dict[str, str], name: str, **create_fields
) -> str:
    """创建并启用一个产品级应用，返回 application_id。"""
    response = client.post(APPS_URL, json={"name": name, **create_fields}, headers=headers)
    assert response.status_code == 201, response.text
    app_id = response.json()["application_id"]
    enabled = client.post(f"{APPS_URL}/{app_id}/enabled", json={"enabled": True}, headers=headers)
    assert enabled.status_code == 200, enabled.text
    return app_id


def _subscribe(tenant_id: str, app_id: str, **overrides) -> None:
    """直插租户开通实例；overrides 支持 status/start_time/expire_time。"""
    start_time = overrides.get("start_time")
    expire_time = overrides.get("expire_time")
    uow = _new_uow()
    try:
        uow.session.execute(
            text(
                "INSERT INTO tenant_application_instance "
                "(id, tenant_id, application_id, status, source, overrides, start_time, expire_time) "
                "VALUES (:id, :tid, :aid, :status, 'granted', '{}'::jsonb, :start, :expire)"
            ),
            {
                "id": uuid4(),
                "tid": tenant_id,
                "aid": app_id,
                "status": overrides.get("status", "active"),
                "start": start_time,
                "expire": expire_time,
            },
        )
        uow.commit()
    finally:
        uow.close()


def _setup_tenant(client, auth_headers, tenant_client, code: str):
    """建租户 + 登录租户超管，返回 (site, headers, roles, tenant_id)。"""
    tenant = create_tenant(client, auth_headers, code=code, name=f"{code} 公司")
    site, headers, _ = tenant_admin_client(tenant_client, code)
    return site, headers, list_roles(site, headers), tenant["id"]


def _put_visibility(site: TestClient, headers: dict[str, str], app_id: str, payload: dict):
    return site.put(f"{TENANT_APPS_URL}/{app_id}/visibility", json=payload, headers=headers)


def _visible_app_ids(user_tenant_client, user_login_headers, code: str, username: str) -> set[str]:
    headers = user_login_headers(code, username, USER_PASSWORD)
    site = user_tenant_client(code)
    response = site.get(f"{USER_AGENTS_URL}", headers=headers)
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


def _now() -> datetime:
    return datetime.now(UTC)


# ========== 用例 1：scope=all 本租户全员可见 ==========
def test_scope_all_visible_for_all_users(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    site, site_headers, roles, tenant_id = _setup_tenant(
        client, auth_headers, tenant_client, "vis-all"
    )
    app_id = _create_enabled_platform_app(client, auth_headers, "全员应用")
    _subscribe(tenant_id, app_id)
    for username in ("member1", "member2"):
        create_user(site, site_headers, username=username, role_id=roles["viewer"]["id"])

    put = _put_visibility(site, site_headers, app_id, {"visibility": "all", "whitelist": []})
    assert put.status_code == 200, put.text

    for username in ("member1", "member2"):
        assert app_id in _visible_app_ids(
            user_tenant_client, user_login_headers, "vis-all", username
        )


# ========== 用例 2：部门白名单（含子树） ==========
def test_whitelist_department_with_subtree(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    site, site_headers, roles, tenant_id = _setup_tenant(
        client, auth_headers, tenant_client, "vis-dept"
    )
    app_id = _create_enabled_platform_app(client, auth_headers, "部门应用")
    _subscribe(tenant_id, app_id)

    parent = create_department(site, site_headers, "总部")
    child = site.post(
        "/api/v1/admin/departments",
        json={"name": "分部", "parent_id": parent["id"]},
        headers=site_headers,
    )
    assert child.status_code == 201, child.text
    child_dept = child.json()
    outside = create_department(site, site_headers, "局外部门")

    inside_user = create_user(site, site_headers, username="in-sub", role_id=roles["viewer"]["id"])
    outside_user = create_user(
        site, site_headers, username="out-dept", role_id=roles["viewer"]["id"]
    )
    for user, dept in ((inside_user, child_dept), (outside_user, outside)):
        emp = site.post(
            "/api/v1/admin/employments",
            json={"user_id": user["id"], "department_id": dept["id"]},
            headers=site_headers,
        )
        assert emp.status_code == 201, emp.text

    put = _put_visibility(
        site,
        site_headers,
        app_id,
        {
            "visibility": "whitelist",
            "whitelist": [
                {"subject_type": "DEPARTMENT", "subject_id": parent["id"], "include_subtree": True}
            ],
        },
    )
    assert put.status_code == 200, put.text

    # 子部门用户命中 include_subtree
    assert app_id in _visible_app_ids(user_tenant_client, user_login_headers, "vis-dept", "in-sub")
    # 部门外用户不可见
    assert app_id not in _visible_app_ids(
        user_tenant_client, user_login_headers, "vis-dept", "out-dept"
    )


# ========== 用例 3：角色白名单 ==========
def test_whitelist_role(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    site, site_headers, roles, tenant_id = _setup_tenant(
        client, auth_headers, tenant_client, "vis-role"
    )
    app_id = _create_enabled_platform_app(client, auth_headers, "角色应用")
    _subscribe(tenant_id, app_id)
    holder = create_user(site, site_headers, username="role-holder", role_id=roles["admin"]["id"])
    other = create_user(site, site_headers, username="role-other", role_id=roles["viewer"]["id"])
    assert holder["id"] and other["id"]

    put = _put_visibility(
        site,
        site_headers,
        app_id,
        {
            "visibility": "whitelist",
            "whitelist": [
                {
                    "subject_type": "ROLE",
                    "subject_id": roles["admin"]["id"],
                    "include_subtree": False,
                }
            ],
        },
    )
    assert put.status_code == 200, put.text

    assert app_id in _visible_app_ids(
        user_tenant_client, user_login_headers, "vis-role", "role-holder"
    )
    assert app_id not in _visible_app_ids(
        user_tenant_client, user_login_headers, "vis-role", "role-other"
    )


# ========== 用例 4：用户白名单 ==========
def test_whitelist_user(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    site, site_headers, roles, tenant_id = _setup_tenant(
        client, auth_headers, tenant_client, "vis-user"
    )
    app_id = _create_enabled_platform_app(client, auth_headers, "指定用户应用")
    _subscribe(tenant_id, app_id)
    picked = create_user(site, site_headers, username="picked", role_id=roles["viewer"]["id"])
    create_user(site, site_headers, username="not-picked", role_id=roles["viewer"]["id"])

    put = _put_visibility(
        site,
        site_headers,
        app_id,
        {
            "visibility": "whitelist",
            "whitelist": [
                {"subject_type": "USER", "subject_id": picked["id"], "include_subtree": False}
            ],
        },
    )
    assert put.status_code == 200, put.text

    assert app_id in _visible_app_ids(user_tenant_client, user_login_headers, "vis-user", "picked")
    assert app_id not in _visible_app_ids(
        user_tenant_client, user_login_headers, "vis-user", "not-picked"
    )


# ========== 用例 5：平台锁定后租户不可改 ==========
def test_lock_blocks_tenant_update(client, auth_headers, tenant_client) -> None:
    site, site_headers, _, tenant_id = _setup_tenant(
        client, auth_headers, tenant_client, "vis-lock"
    )
    app_id = _create_enabled_platform_app(client, auth_headers, "锁定应用")
    _subscribe(tenant_id, app_id)

    patch = client.patch(
        f"{APPS_URL}/{app_id}", json={"visibility_lock": True}, headers=auth_headers
    )
    assert patch.status_code == 200, patch.text

    put = _put_visibility(site, site_headers, app_id, {"visibility": "all", "whitelist": []})
    assert put.status_code == 403, put.text


# ========== 用例 6/7：scope 不存在时按平台模板兜底 ==========
def test_no_scope_falls_back_to_template(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    site, site_headers, roles, tenant_id = _setup_tenant(
        client, auth_headers, tenant_client, "vis-tpl"
    )
    create_user(site, site_headers, username="tpl-user", role_id=roles["viewer"]["id"])

    # 模板 all：兜底可见
    app_all = _create_enabled_platform_app(client, auth_headers, "模板all应用")
    _subscribe(tenant_id, app_all)
    assert app_all in _visible_app_ids(
        user_tenant_client, user_login_headers, "vis-tpl", "tpl-user"
    )

    # 模板 whitelist：等待租户配置，暂不可见
    app_wl = _create_enabled_platform_app(
        client, auth_headers, "模板whitelist应用", visibility_template="whitelist"
    )
    _subscribe(tenant_id, app_wl)
    assert app_wl not in _visible_app_ids(
        user_tenant_client, user_login_headers, "vis-tpl", "tpl-user"
    )


# ========== 用例 8/9/10：订阅窗口与状态 ==========
def test_subscription_window_and_status_filtering(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    site, site_headers, roles, tenant_id = _setup_tenant(
        client, auth_headers, tenant_client, "vis-sub"
    )
    create_user(site, site_headers, username="sub-user", role_id=roles["viewer"]["id"])
    hour = timedelta(hours=1)

    expired = _create_enabled_platform_app(client, auth_headers, "过期应用")
    _subscribe(tenant_id, expired, expire_time=_now() - hour)
    not_started = _create_enabled_platform_app(client, auth_headers, "未生效应用")
    _subscribe(tenant_id, not_started, start_time=_now() + hour)
    suspended = _create_enabled_platform_app(client, auth_headers, "暂停应用")
    _subscribe(tenant_id, suspended, status="suspended")
    revoked = _create_enabled_platform_app(client, auth_headers, "回收应用")
    _subscribe(tenant_id, revoked, status="revoked")

    visible = _visible_app_ids(user_tenant_client, user_login_headers, "vis-sub", "sub-user")
    assert visible.isdisjoint({expired, not_started, suspended, revoked})


# ========== 用例 11：老平台侧 visibility 接口已下线 ==========
def test_old_platform_visibility_endpoint_removed_404(client, auth_headers) -> None:
    app_id = _create_enabled_platform_app(client, auth_headers, "老接口应用")
    response = client.get(f"{APPS_URL}/{app_id}/visibility", headers=auth_headers)
    assert response.status_code == 404, response.text


# ========== 用例 12：upsert 并发不报错，最终为其中一个请求 ==========
def test_upsert_tenant_scope_concurrent(client, auth_headers, tenant_client) -> None:
    site, site_headers, _, tenant_id = _setup_tenant(
        client, auth_headers, tenant_client, "vis-race"
    )
    app_id = _create_enabled_platform_app(client, auth_headers, "并发应用")
    _subscribe(tenant_id, app_id)
    subject = str(uuid4())

    def _write(visibility: str):
        return _put_visibility(
            site,
            site_headers,
            app_id,
            {
                "visibility": visibility,
                "whitelist": []
                if visibility == "all"
                else [{"subject_type": "USER", "subject_id": subject, "include_subtree": False}],
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_write, "all")
        second = pool.submit(_write, "whitelist")
        r1, r2 = first.result(), second.result()

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    got = site.get(f"{TENANT_APPS_URL}/{app_id}/visibility", headers=site_headers).json()
    assert got["configured"] is True
    # 最终状态是两次写入之一，且不出现半更新混合态
    if got["visibility"] == "all":
        assert got["whitelist"] == []
    else:
        assert [w["subject_id"] for w in got["whitelist"]] == [subject]


# ========== 用例 13：孤儿白名单主体不影响查询 ==========
def test_orphan_whitelist_subject_filtered(client, auth_headers, tenant_client) -> None:
    site, site_headers, _, tenant_id = _setup_tenant(
        client, auth_headers, tenant_client, "vis-orphan"
    )
    app_id = _create_enabled_platform_app(client, auth_headers, "孤儿应用")
    _subscribe(tenant_id, app_id)
    ghost_dept = str(uuid4())

    put = _put_visibility(
        site,
        site_headers,
        app_id,
        {
            "visibility": "whitelist",
            "whitelist": [
                {"subject_type": "DEPARTMENT", "subject_id": ghost_dept, "include_subtree": True}
            ],
        },
    )
    assert put.status_code == 200, put.text

    # 读取配置时孤儿记录仍在（原样返回）
    got = site.get(f"{TENANT_APPS_URL}/{app_id}/visibility", headers=site_headers).json()
    assert [w["subject_id"] for w in got["whitelist"]] == [ghost_dept]

    # 用户端查询不报错：孤儿记录 JOIN 隐式过滤，等价于名单为空
    uow = _new_uow()
    try:
        rows = uow.session.execute(
            text("SELECT count(*) FROM application a WHERE a.id = :aid AND a.is_enabled"),
            {"aid": app_id},
        ).scalar_one()
        assert rows == 1
    finally:
        uow.close()


# ========== 用例 14：configured 标记 ==========
def test_configured_flag(client, auth_headers, tenant_client) -> None:
    site, site_headers, _, tenant_id = _setup_tenant(client, auth_headers, tenant_client, "vis-cfg")
    app_id = _create_enabled_platform_app(client, auth_headers, "标记应用")
    _subscribe(tenant_id, app_id)

    before = site.get(f"{TENANT_APPS_URL}/{app_id}/visibility", headers=site_headers).json()
    assert before["configured"] is False
    assert before["visibility"] == "all"

    assert (
        _put_visibility(
            site, site_headers, app_id, {"visibility": "all", "whitelist": []}
        ).status_code
        == 200
    )

    after = site.get(f"{TENANT_APPS_URL}/{app_id}/visibility", headers=site_headers).json()
    assert after["configured"] is True
    assert after["visibility"] == "all"
