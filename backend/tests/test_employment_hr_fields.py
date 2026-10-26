"""任职记录 HR 字段扩展：字典预置、字段写入、汇报上级、试用期、离职类型。"""

from fastapi.testclient import TestClient

from tests.helpers import (
    create_tenant,
    create_user,
    list_roles,
    tenant_admin_client,
)

DEPTS_URL = "/api/v1/admin/departments"
EMP_URL = "/api/v1/admin/employments"
DICT_URL = "/api/v1/admin/hr-dictionaries"


def _setup_tenant(client, auth_headers, tenant_client, code: str = "acme"):
    create_tenant(client, auth_headers, code, f"{code} 公司")
    site, headers, _ = tenant_admin_client(tenant_client, code)
    roles = list_roles(site, headers)
    return site, headers, roles


def _create_dept(site, headers, name, parent_id=None):
    response = site.post(
        DEPTS_URL,
        json={"name": name, "parent_id": parent_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_default_dictionaries_seeded_on_tenant_create(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """新租户创建时应自动预置雇佣类型/岗位职级/岗位序列字典。"""
    site, headers, _ = _setup_tenant(client, auth_headers, tenant_client, code="seed")

    for category, expected_min in (
        ("employment_type", 5),
        ("job_level", 10),
        ("job_family", 6),
    ):
        items = site.get(
            DICT_URL, params={"category": category}, headers=headers
        ).json()
        assert len(items) >= expected_min, f"{category} 默认字典项不足"
        # sort_order 升序
        orders = [item["sort_order"] for item in items]
        assert orders == sorted(orders)


def test_create_employment_with_hr_fields(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """新建任职应能写入字典外键、汇报上级、试用期与备注，并回填名称。"""
    site, headers, roles = _setup_tenant(client, auth_headers, tenant_client, code="hr")
    department = _create_dept(site, headers, "研发部")
    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])
    bob = create_user(site, headers, username="bob", role_id=roles["viewer"]["id"])

    employment_types = site.get(
        DICT_URL, params={"category": "employment_type"}, headers=headers
    ).json()
    job_levels = site.get(
        DICT_URL, params={"category": "job_level"}, headers=headers
    ).json()
    job_families = site.get(
        DICT_URL, params={"category": "job_family"}, headers=headers
    ).json()
    ft = next(item for item in employment_types if item["code"] == "full_time")
    p5 = next(item for item in job_levels if item["code"] == "P5")
    tech = next(item for item in job_families if item["code"] == "tech")

    response = site.post(
        EMP_URL,
        json={
            "user_id": alice["id"],
            "department_id": department["id"],
            "position": "后端工程师",
            "started_at": "2026-01-01",
            "employment_type_id": ft["id"],
            "job_level_id": p5["id"],
            "job_family_id": tech["id"],
            "manager_id": bob["id"],
            "work_location": "北京",
            "cost_center": "CC-001",
            "contract_no": "HT-2026-001",
            "weekly_hours": 40,
            "employment_nature": "regular",
            "probation_started_at": "2026-01-01",
            "probation_ended_at": "2026-04-01",
            "regularized_at": "2026-04-02",
            "change_type": "hire",
            "change_reason": "社招入职",
            "remark": "备注",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["employment_type_id"] == ft["id"]
    assert body["employment_type_name"] == "全职"
    assert body["job_level_name"] == "P5"
    assert body["job_family_name"] == "技术"
    assert body["manager_id"] == bob["id"]
    assert body["manager_name"] == "用户"  # helpers 中默认 display_name
    assert body["work_location"] == "北京"
    assert body["weekly_hours"] == 40
    assert body["employment_nature"] == "regular"
    assert body["probation_ended_at"] == "2026-04-01"
    assert body["regularized_at"] == "2026-04-02"
    assert body["change_type"] == "hire"
    assert body["change_reason"] == "社招入职"
    assert body["remark"] == "备注"


def test_create_employment_rejects_invalid_dictionary(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """引用其他租户或类别不匹配的字典项应被拒绝。"""
    site_a, headers_a, roles_a = _setup_tenant(client, auth_headers, tenant_client, code="ta")
    site_b, headers_b, roles_b = _setup_tenant(client, auth_headers, tenant_client, code="tb")
    dept_a = _create_dept(site_a, headers_a, "A 部门")
    dept_b = _create_dept(site_b, headers_b, "B 部门")
    user_a = create_user(site_a, headers_a, username="user_a", role_id=roles_a["viewer"]["id"])
    user_b = create_user(site_b, headers_b, username="user_b", role_id=roles_b["viewer"]["id"])

    # 租户 A 的字典项被租户 B 引用
    type_a = site_a.get(
        DICT_URL, params={"category": "employment_type"}, headers=headers_a
    ).json()[0]
    resp = site_b.post(
        EMP_URL,
        json={
            "user_id": user_b["id"],
            "department_id": dept_b["id"],
            "employment_type_id": type_a["id"],
        },
        headers=headers_b,
    )
    assert resp.status_code == 422, resp.text

    # 类别不匹配：用 job_level 的 id 当 employment_type_id
    level_a = site_a.get(
        DICT_URL, params={"category": "job_level"}, headers=headers_a
    ).json()[0]
    resp = site_a.post(
        EMP_URL,
        json={
            "user_id": user_a["id"],
            "department_id": dept_a["id"],
            "employment_type_id": level_a["id"],
        },
        headers=headers_a,
    )
    assert resp.status_code == 422, resp.text


def test_transfer_inherits_hr_fields_and_accepts_override(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """调岗时未显式传入的 HR 字段沿用原任职；显式传入则覆盖。"""
    site, headers, roles = _setup_tenant(client, auth_headers, tenant_client, code="t2")
    dept_one = _create_dept(site, headers, "一部")
    dept_two = _create_dept(site, headers, "二部")
    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    job_levels = site.get(
        DICT_URL, params={"category": "job_level"}, headers=headers
    ).json()
    p3 = next(item for item in job_levels if item["code"] == "P3")
    p5 = next(item for item in job_levels if item["code"] == "P5")

    created = site.post(
        EMP_URL,
        json={
            "user_id": alice["id"],
            "department_id": dept_one["id"],
            "position": "工程师",
            "started_at": "2026-01-01",
            "job_level_id": p3["id"],
            "work_location": "北京",
        },
        headers=headers,
    ).json()

    transferred = site.post(
        f"{EMP_URL}/{created['id']}/transfer",
        json={
            "department_id": dept_two["id"],
            "started_at": "2026-04-01",
            "job_level_id": p5["id"],
            "change_type": "promotion",
        },
        headers=headers,
    )
    assert transferred.status_code == 200, transferred.text
    body = transferred.json()
    # 显式覆盖：职级
    assert body["job_level_id"] == p5["id"]
    # 沿用原任职：工作地点
    assert body["work_location"] == "北京"
    assert body["change_type"] == "promotion"

    # 原历史记录保留原字段
    history = site.get(
        EMP_URL, params={"user_id": alice["id"]}, headers=headers
    ).json()
    old = next(item for item in history["items"] if item["id"] == created["id"])
    assert old["job_level_id"] == p3["id"]
    assert old["is_current"] is False


def test_archive_sets_termination_type(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """结束任职时应写入离职类型与原因。"""
    site, headers, roles = _setup_tenant(client, auth_headers, tenant_client, code="t3")
    department = _create_dept(site, headers, "研发部")
    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    current = site.post(
        EMP_URL,
        json={
            "user_id": alice["id"],
            "department_id": department["id"],
            "started_at": "2026-01-01",
        },
        headers=headers,
    ).json()

    archived = site.post(
        f"{EMP_URL}/{current['id']}/archive",
        json={
            "ended_at": "2026-05-01",
            "termination_type": "resignation",
            "change_reason": "个人原因",
        },
        headers=headers,
    )
    assert archived.status_code == 200
    body = archived.json()
    assert body["is_current"] is False
    assert body["termination_type"] == "resignation"
    assert body["change_reason"] == "个人原因"

    # 非法离职类型应被拒绝
    current2 = site.post(
        EMP_URL,
        json={"user_id": alice["id"], "department_id": department["id"]},
        headers=headers,
    ).json()
    bad = site.post(
        f"{EMP_URL}/{current2['id']}/archive",
        json={"termination_type": "invalid"},
        headers=headers,
    )
    assert bad.status_code == 422


def test_dictionary_delete_blocked_when_referenced(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """被任职记录引用的字典项不能删除；未被引用时可以删除。"""
    site, headers, roles = _setup_tenant(client, auth_headers, tenant_client, code="t4")
    department = _create_dept(site, headers, "研发部")
    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])

    # 新建一个自定义字典项
    created_dict = site.post(
        DICT_URL,
        json={
            "category": "employment_type",
            "code": "contractor",
            "name": "合同工",
            "sort_order": 70,
        },
        headers=headers,
    )
    assert created_dict.status_code == 201, created_dict.text
    dict_item = created_dict.json()

    # 未被引用时删除成功
    assert site.delete(
        f"{DICT_URL}/{dict_item['id']}", headers=headers
    ).status_code == 204

    # 新建并引用
    created_dict2 = site.post(
        DICT_URL,
        json={
            "category": "employment_type",
            "code": "contractor2",
            "name": "合同工2",
            "sort_order": 80,
        },
        headers=headers,
    ).json()
    site.post(
        EMP_URL,
        json={
            "user_id": alice["id"],
            "department_id": department["id"],
            "employment_type_id": created_dict2["id"],
        },
        headers=headers,
    )
    resp = site.delete(f"{DICT_URL}/{created_dict2['id']}", headers=headers)
    assert resp.status_code == 409, resp.text
