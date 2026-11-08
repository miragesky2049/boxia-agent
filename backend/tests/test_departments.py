"""部门管理：树形 CRUD、编码/重名/层级约束、移动子树、停用与删除保护、多租户隔离。"""

from fastapi.testclient import TestClient

from tests.helpers import (
    create_tenant,
    create_user,
    list_roles,
    tenant_admin_client,
)

DEPTS_URL = "/api/v1/admin/departments"


def _create_dept(
    site: TestClient,
    headers: dict[str, str],
    *,
    name: str,
    parent_id: str | None = None,
    code: str | None = None,
    sort_order: int = 0,
    expected: int = 201,
) -> dict:
    response = site.post(
        DEPTS_URL,
        json={
            "name": name,
            "parent_id": parent_id,
            "code": code,
            "sort_order": sort_order,
        },
        headers=headers,
    )
    assert response.status_code == expected, response.text
    return response.json()


def _update_dept(
    site: TestClient,
    headers: dict[str, str],
    department_id: str,
    payload: dict,
    *,
    expected: int = 200,
) -> dict:
    response = site.patch(f"{DEPTS_URL}/{department_id}", json=payload, headers=headers)
    assert response.status_code == expected, response.text
    return response.json() if expected == 200 else {}


def _chain(site: TestClient, headers: dict[str, str], prefix: str, depth: int) -> list[dict]:
    """创建从根开始的 depth 级部门链，返回按层级排序的节点。"""
    nodes: list[dict] = []
    parent_id: str | None = None
    for index in range(depth):
        node = _create_dept(site, headers, name=f"{prefix}-{index + 1}", parent_id=parent_id)
        nodes.append(node)
        parent_id = node["id"]
    return nodes


def test_department_tree_and_path(client: TestClient, auth_headers, tenant_client) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    root = _create_dept(site, headers, name="总经办", code="HQ")
    assert root["level"] == 1
    assert root["path"] == f"/{root['id']}/"
    assert root["code"] == "hq"

    child = _create_dept(site, headers, name="研发组", parent_id=root["id"])
    assert child["level"] == 2
    assert child["path"] == f"{root['path']}{child['id']}/"

    tree = site.get(DEPTS_URL, headers=headers)
    assert tree.status_code == 200, tree.text
    roots = tree.json()
    assert len(roots) == 1
    assert roots[0]["id"] == root["id"]
    assert [item["id"] for item in roots[0]["children"]] == [child["id"]]

    renamed = _update_dept(
        site,
        headers,
        child["id"],
        {"parent_id": root["id"], "name": "研发中心", "code": None, "sort_order": 0},
    )
    assert renamed["name"] == "研发中心"
    assert renamed["parent_id"] == root["id"]


def test_code_and_same_parent_name_conflict(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    _create_dept(site, headers, name="研发部", code="RD")
    duplicate_code = site.post(
        DEPTS_URL,
        json={"name": "研究部", "code": "rd"},
        headers=headers,
    )
    assert duplicate_code.status_code == 409

    duplicate_name = site.post(
        DEPTS_URL,
        json={"name": "研发部"},
        headers=headers,
    )
    assert duplicate_name.status_code == 409

    bad_code = site.post(
        DEPTS_URL,
        json={"name": "市场部", "code": "bad code"},
        headers=headers,
    )
    assert bad_code.status_code == 422

    # 不同父级下允许同名
    root = _create_dept(site, headers, name="总部")
    same_name_child = site.post(
        DEPTS_URL,
        json={"name": "研发部", "parent_id": root["id"]},
        headers=headers,
    )
    assert same_name_child.status_code == 201, same_name_child.text


def test_level_limit_ten(client: TestClient, auth_headers, tenant_client) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    nodes = _chain(site, headers, "层级", 10)
    assert nodes[-1]["level"] == 10

    response = site.post(
        DEPTS_URL,
        json={"name": "第11级", "parent_id": nodes[-1]["id"]},
        headers=headers,
    )
    assert response.status_code == 422


def test_move_subtree_path_and_level(client: TestClient, auth_headers, tenant_client) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    node_a = _create_dept(site, headers, name="A")
    node_a1 = _create_dept(site, headers, name="A1", parent_id=node_a["id"])
    node_a1x = _create_dept(site, headers, name="A1x", parent_id=node_a1["id"])
    node_b = _create_dept(site, headers, name="B")

    # A（带子树）整体移到 B 下：path 前缀替换、level 整体 +1
    moved = _update_dept(
        site,
        headers,
        node_a["id"],
        {"parent_id": node_b["id"], "name": "A", "code": None, "sort_order": 0},
    )
    assert moved["level"] == 2
    assert moved["path"] == f"/{node_b['id']}/{node_a['id']}/"

    tree = site.get(DEPTS_URL, headers=headers).json()
    assert [item["id"] for item in tree] == [node_b["id"]]
    under_b = tree[0]["children"]
    assert [item["id"] for item in under_b] == [node_a["id"]]
    under_a = under_b[0]["children"]
    assert under_a[0]["id"] == node_a1["id"]
    assert under_a[0]["level"] == 3
    assert under_a[0]["path"] == f"/{node_b['id']}/{node_a['id']}/{node_a1['id']}/"
    assert under_a[0]["children"][0]["id"] == node_a1x["id"]
    assert under_a[0]["children"][0]["level"] == 4

    # 不能移动到自身下级（此时 A 已是 B 的子级，把 B 移到 A 下构成环）
    cycle = site.patch(
        f"{DEPTS_URL}/{node_b['id']}",
        json={"parent_id": node_a["id"], "name": "B", "code": None, "sort_order": 0},
        headers=headers,
    )
    assert cycle.status_code == 422


def test_move_cannot_exceed_level_limit(client: TestClient, auth_headers, tenant_client) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    deep = _chain(site, headers, "深", 9)
    node_d = _create_dept(site, headers, name="D")
    node_d1 = _create_dept(site, headers, name="D1", parent_id=node_d["id"])

    # D1 移动后将达 11 级，整棵移动必须被拒绝且保持原状
    response = site.patch(
        f"{DEPTS_URL}/{node_d['id']}",
        json={"parent_id": deep[-1]["id"], "name": "D", "code": None, "sort_order": 0},
        headers=headers,
    )
    assert response.status_code == 422

    unchanged = site.get(DEPTS_URL, headers=headers).json()
    d_roots = [item for item in unchanged if item["id"] == node_d["id"]]
    assert len(d_roots) == 1
    assert d_roots[0]["children"][0]["id"] == node_d1["id"]


def test_delete_protection(client: TestClient, auth_headers, tenant_client) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")
    roles = list_roles(site, headers)

    root = _create_dept(site, headers, name="总部")
    child = _create_dept(site, headers, name="小组", parent_id=root["id"])

    assert site.delete(f"{DEPTS_URL}/{root['id']}", headers=headers).status_code == 409
    assert site.delete(f"{DEPTS_URL}/{child['id']}", headers=headers).status_code == 204

    # 存在任职记录时禁止删除（含历史记录）
    user = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])
    employment = site.post(
        "/api/v1/admin/employments",
        json={"user_id": user["id"], "department_id": root["id"], "position": "工程师"},
        headers=headers,
    )
    assert employment.status_code == 201, employment.text
    assert site.delete(f"{DEPTS_URL}/{root['id']}", headers=headers).status_code == 409
    assert (
        site.delete(
            f"/api/v1/admin/employments/{employment.json()['id']}", headers=headers
        ).status_code
        == 204
    )
    assert site.delete(f"{DEPTS_URL}/{root['id']}", headers=headers).status_code == 204


def test_disable_blocks_create_and_move(client: TestClient, auth_headers, tenant_client) -> None:
    create_tenant(client, auth_headers)
    site, headers, _ = tenant_admin_client(tenant_client, "acme")

    root = _create_dept(site, headers, name="总部")
    disabled = site.post(
        f"{DEPTS_URL}/{root['id']}/status",
        json={"is_active": False},
        headers=headers,
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    assert (
        site.post(
            DEPTS_URL,
            json={"name": "停用下子部门", "parent_id": root["id"]},
            headers=headers,
        ).status_code
        == 422
    )

    enabled = site.post(
        f"{DEPTS_URL}/{root['id']}/status",
        json={"is_active": True},
        headers=headers,
    )
    assert enabled.json()["is_active"] is True
    child = site.post(
        DEPTS_URL,
        json={"name": "恢复后子部门", "parent_id": root["id"]},
        headers=headers,
    )
    assert child.status_code == 201, child.text

    # 不能移入已停用部门
    other = _create_dept(site, headers, name="停用根")
    assert (
        site.post(
            f"{DEPTS_URL}/{other['id']}/status",
            json={"is_active": False},
            headers=headers,
        ).status_code
        == 200
    )
    moved = site.patch(
        f"{DEPTS_URL}/{child.json()['id']}",
        json={"parent_id": other["id"], "name": "恢复后子部门", "code": None, "sort_order": 0},
        headers=headers,
    )
    assert moved.status_code == 422


def test_platform_forbidden_and_tenant_isolation(
    client: TestClient, auth_headers, tenant_client
) -> None:
    create_tenant(client, auth_headers, "acme", "Acme 公司")
    create_tenant(client, auth_headers, "globex", "Globex 公司")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    globex_site, globex_headers, _ = tenant_admin_client(tenant_client, "globex")

    # 产品级平台不可维护组织架构
    assert client.get(DEPTS_URL, headers=auth_headers).status_code == 403

    acme_dept = _create_dept(acme_site, acme_headers, name="Acme 部门")
    globex_dept = _create_dept(globex_site, globex_headers, name="Globex 部门")

    acme_tree = acme_site.get(DEPTS_URL, headers=acme_headers).json()
    assert [item["name"] for item in acme_tree] == ["Acme 部门"]

    # 跨租户引用目标部门：按不存在处理
    cross_parent = acme_site.post(
        DEPTS_URL,
        json={"name": "挂靠", "parent_id": globex_dept["id"]},
        headers=acme_headers,
    )
    assert cross_parent.status_code == 404

    cross_update = globex_site.patch(
        f"{DEPTS_URL}/{acme_dept['id']}",
        json={"parent_id": None, "name": "被 Globex 改名", "code": None, "sort_order": 0},
        headers=globex_headers,
    )
    assert cross_update.status_code == 404
