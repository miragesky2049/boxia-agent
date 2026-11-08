"""用户任职：单一主任职约束、调岗归档、结束任职、部门子树筛选、跨租户隔离。"""

from fastapi.testclient import TestClient

from tests.helpers import (
    create_tenant,
    create_user,
    list_roles,
    tenant_admin_client,
)

DEPTS_URL = "/api/v1/admin/departments"
EMP_URL = "/api/v1/admin/employments"
USERS_URL = "/api/v1/admin/users"


def _create_dept(
    site: TestClient, headers: dict[str, str], name: str, parent_id: str | None = None
) -> dict:
    response = site.post(
        DEPTS_URL,
        json={"name": name, "parent_id": parent_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_employment(
    site: TestClient,
    headers: dict[str, str],
    *,
    user_id: str,
    department_id: str,
    position: str = "",
    started_at: str | None = None,
    expected: int = 201,
) -> dict:
    payload: dict = {
        "user_id": user_id,
        "department_id": department_id,
        "position": position,
    }
    if started_at is not None:
        payload["started_at"] = started_at
    response = site.post(EMP_URL, json=payload, headers=headers)
    assert response.status_code == expected, response.text
    return response.json() if expected == 201 else {}


def _setup_tenant(client, auth_headers, tenant_client, code: str = "acme"):
    create_tenant(client, auth_headers, code, f"{code} 公司")
    site, headers, _ = tenant_admin_client(tenant_client, code)
    roles = list_roles(site, headers)
    return site, headers, roles


def test_single_current_and_user_department_link(
    client: TestClient, auth_headers, tenant_client
) -> None:
    site, headers, roles = _setup_tenant(client, auth_headers, tenant_client)
    department = _create_dept(site, headers, "研发部")
    user = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    employment = _create_employment(
        site,
        headers,
        user_id=user["id"],
        department_id=department["id"],
        position="工程师",
        started_at="2026-01-01",
    )
    assert employment["is_current"] is True
    assert employment["ended_at"] is None
    assert employment["department_name"] == "研发部"
    assert employment["user_name"] == "alice"

    # 同一用户只能有一条当前生效任职
    _create_employment(
        site,
        headers,
        user_id=user["id"],
        department_id=department["id"],
        expected=409,
    )

    # 用户列表回填当前部门，并支持按部门（含下级）筛选
    users = site.get(USERS_URL, headers=headers).json()["items"]
    alice = next(item for item in users if item["username"] == "alice")
    assert alice["current_department_id"] == department["id"]
    assert alice["current_department_name"] == "研发部"

    filtered = site.get(
        USERS_URL, params={"department_id": department["id"]}, headers=headers
    ).json()
    assert [item["username"] for item in filtered["items"]] == ["alice"]

    updated = site.patch(
        f"{EMP_URL}/{employment['id']}",
        json={"position": "高级工程师"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["position"] == "高级工程师"


def test_transfer_archives_old_employment(client: TestClient, auth_headers, tenant_client) -> None:
    site, headers, roles = _setup_tenant(client, auth_headers, tenant_client)
    dept_one = _create_dept(site, headers, "一部")
    dept_two = _create_dept(site, headers, "二部")
    user = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    current = _create_employment(
        site,
        headers,
        user_id=user["id"],
        department_id=dept_one["id"],
        position="工程师",
        started_at="2026-01-01",
    )

    transferred = site.post(
        f"{EMP_URL}/{current['id']}/transfer",
        json={"department_id": dept_two["id"], "position": "主管", "started_at": "2026-02-01"},
        headers=headers,
    )
    assert transferred.status_code == 200, transferred.text
    new_current = transferred.json()
    assert new_current["department_id"] == dept_two["id"]
    assert new_current["is_current"] is True

    records = site.get(
        EMP_URL, params={"user_id": user["id"], "page_size": 50}, headers=headers
    ).json()
    assert records["total"] == 2
    old = next(item for item in records["items"] if item["id"] == current["id"])
    assert old["is_current"] is False
    assert old["ended_at"] == "2026-01-31"
    assert records["items"][0]["is_current"] is True

    # 历史记录不能再次调岗
    assert (
        site.post(
            f"{EMP_URL}/{current['id']}/transfer",
            json={"department_id": dept_one["id"]},
            headers=headers,
        ).status_code
        == 422
    )

    # 同部门调岗只更新岗位与生效日期，不产生新记录
    same_dept = site.post(
        f"{EMP_URL}/{new_current['id']}/transfer",
        json={"department_id": dept_two["id"], "started_at": "2026-03-01"},
        headers=headers,
    )
    assert same_dept.status_code == 200
    assert site.get(EMP_URL, params={"user_id": user["id"]}, headers=headers).json()["total"] == 2

    # 调岗生效日期不能早于原任职生效日期
    too_early = site.post(
        f"{EMP_URL}/{new_current['id']}/transfer",
        json={"department_id": dept_one["id"], "started_at": "2025-12-01"},
        headers=headers,
    )
    assert too_early.status_code == 422


def test_archive_then_rejoin_and_delete(client: TestClient, auth_headers, tenant_client) -> None:
    site, headers, roles = _setup_tenant(client, auth_headers, tenant_client)
    department = _create_dept(site, headers, "研发部")
    user = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])
    current = _create_employment(
        site,
        headers,
        user_id=user["id"],
        department_id=department["id"],
        started_at="2026-01-01",
    )

    archived = site.post(
        f"{EMP_URL}/{current['id']}/archive",
        json={"ended_at": "2026-05-01"},
        headers=headers,
    )
    assert archived.status_code == 200
    assert archived.json()["is_current"] is False
    assert archived.json()["ended_at"] == "2026-05-01"

    # 结束后用户无当前部门，且可重新入职
    users = site.get(USERS_URL, headers=headers).json()["items"]
    alice = next(item for item in users if item["username"] == "alice")
    assert alice["current_department_id"] is None
    assert (
        site.post(
            f"{EMP_URL}/{current['id']}/archive",
            json={},
            headers=headers,
        ).status_code
        == 422
    )

    rejoined = _create_employment(site, headers, user_id=user["id"], department_id=department["id"])
    assert rejoined["is_current"] is True

    # 删除当前任职后用户再次变为无部门
    assert site.delete(f"{EMP_URL}/{rejoined['id']}", headers=headers).status_code == 204
    assert site.delete(f"{EMP_URL}/{current['id']}", headers=headers).status_code == 204
    users = site.get(USERS_URL, headers=headers).json()["items"]
    alice = next(item for item in users if item["username"] == "alice")
    assert alice["current_department_id"] is None


def test_list_filters_subtree_and_status(client: TestClient, auth_headers, tenant_client) -> None:
    site, headers, roles = _setup_tenant(client, auth_headers, tenant_client)
    dept_one = _create_dept(site, headers, "一部")
    dept_child = _create_dept(site, headers, "一组", dept_one["id"])
    dept_two = _create_dept(site, headers, "二部")
    user_one = create_user(site, headers, username="user1", role_id=roles["viewer"]["id"])
    user_two = create_user(site, headers, username="user2", role_id=roles["viewer"]["id"])
    user_three = create_user(site, headers, username="user3", role_id=roles["viewer"]["id"])

    emp_one = _create_employment(
        site,
        headers,
        user_id=user_one["id"],
        department_id=dept_one["id"],
        position="后端工程师",
    )
    _create_employment(site, headers, user_id=user_two["id"], department_id=dept_child["id"])
    _create_employment(site, headers, user_id=user_three["id"], department_id=dept_two["id"])

    subtree = site.get(
        EMP_URL, params={"department_id": dept_one["id"], "page_size": 50}, headers=headers
    ).json()
    assert subtree["total"] == 2
    assert {item["user_name"] for item in subtree["items"]} == {"user1", "user2"}

    only_two = site.get(EMP_URL, params={"department_id": dept_two["id"]}, headers=headers).json()
    assert [item["user_name"] for item in only_two["items"]] == ["user3"]

    by_keyword = site.get(EMP_URL, params={"keyword": "后端"}, headers=headers).json()
    assert [item["id"] for item in by_keyword["items"]] == [emp_one["id"]]

    by_user = site.get(EMP_URL, params={"user_id": user_two["id"]}, headers=headers).json()
    assert by_user["total"] == 1

    # 归档后 is_current 筛选只剩 2 条当前记录
    assert (
        site.post(f"{EMP_URL}/{emp_one['id']}/archive", json={}, headers=headers).status_code == 200
    )
    current_only = site.get(
        EMP_URL, params={"is_current": "true", "page_size": 50}, headers=headers
    ).json()
    assert current_only["total"] == 2
    history_only = site.get(EMP_URL, params={"is_current": "false"}, headers=headers).json()
    assert history_only["total"] == 1


def test_employment_validation_rules(client: TestClient, auth_headers, tenant_client) -> None:
    site, headers, roles = _setup_tenant(client, auth_headers, tenant_client)
    department = _create_dept(site, headers, "研发部")
    user = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    # 停用部门不能新增任职
    assert (
        site.post(
            f"{DEPTS_URL}/{department['id']}/status",
            json={"is_active": False},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        site.post(
            EMP_URL,
            json={"user_id": user["id"], "department_id": department["id"]},
            headers=headers,
        ).status_code
        == 422
    )

    assert (
        site.post(
            f"{DEPTS_URL}/{department['id']}/status",
            json={"is_active": True},
            headers=headers,
        ).status_code
        == 200
    )

    # 不存在的用户
    assert (
        site.post(
            EMP_URL,
            json={
                "user_id": "00000000-0000-0000-0000-000000000000",
                "department_id": department["id"],
            },
            headers=headers,
        ).status_code
        == 422
    )

    # 历史任职生效日期不能晚于结束日期
    employment = _create_employment(
        site,
        headers,
        user_id=user["id"],
        department_id=department["id"],
        started_at="2026-01-01",
    )
    assert (
        site.post(
            f"{EMP_URL}/{employment['id']}/archive",
            json={"ended_at": "2026-02-01"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        site.patch(
            f"{EMP_URL}/{employment['id']}",
            json={"started_at": "2026-03-01"},
            headers=headers,
        ).status_code
        == 422
    )


def test_platform_forbidden_and_tenant_isolation(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers, "acme", "Acme 公司")
    create_tenant(client, auth_headers, "globex", "Globex 公司")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    globex_site, globex_headers, _ = tenant_admin_client(tenant_client, "globex")
    acme_roles = list_roles(acme_site, acme_headers)
    globex_roles = list_roles(globex_site, globex_headers)

    assert client.get(EMP_URL, headers=auth_headers).status_code == 403

    acme_dept = _create_dept(acme_site, acme_headers, "Acme 部门")
    globex_dept = _create_dept(globex_site, globex_headers, "Globex 部门")
    globex_user = create_user(
        globex_site, globex_headers, username="guser", role_id=globex_roles["viewer"]["id"]
    )
    acme_user = create_user(
        acme_site, acme_headers, username="auser", role_id=acme_roles["viewer"]["id"]
    )

    # 不能引用其他租户的部门或用户
    assert (
        acme_site.post(
            EMP_URL,
            json={"user_id": acme_user["id"], "department_id": globex_dept["id"]},
            headers=acme_headers,
        ).status_code
        == 422
    )
    assert (
        acme_site.post(
            EMP_URL,
            json={"user_id": globex_user["id"], "department_id": acme_dept["id"]},
            headers=acme_headers,
        ).status_code
        == 422
    )

    _create_employment(
        acme_site,
        acme_headers,
        user_id=acme_user["id"],
        department_id=acme_dept["id"],
    )
    listed = acme_site.get(EMP_URL, headers=acme_headers).json()
    assert listed["total"] == 1
    assert globex_site.get(EMP_URL, headers=globex_headers).json()["total"] == 0
