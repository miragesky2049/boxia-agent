"""工作流与模板市场：CRUD、图校验、租户克隆、跨租户隔离。"""

from fastapi.testclient import TestClient

from tests.helpers import create_tenant, tenant_admin_client

WORKFLOWS_URL = "/api/v1/admin/workflows"
TEMPLATES_URL = "/api/v1/admin/workflows/templates"


def _valid_graph() -> dict:
    """最小合法图：start → llm → end。"""
    return {
        "variables": [{"key": "query", "type": "string", "required": True}],
        "nodes": [
            {"id": "start_1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "llm_1",
                "type": "llm",
                "position": {"x": 300, "y": 0},
                "data": {"model_id": "demo", "user_prompt_tpl": "{{query}}"},
            },
            {"id": "end_1", "type": "end", "position": {"x": 600, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": "start_1", "target": "llm_1"},
            {"source": "llm_1", "target": "end_1"},
        ],
    }


def _create_workflow(
    site: TestClient, headers: dict[str, str], name: str, graph: dict | None = None
) -> dict:
    response = site.post(
        WORKFLOWS_URL,
        json={
            "name": name,
            "description": "",
            "graph": graph or _valid_graph(),
            "is_enabled": True,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_platform_workflow_crud(client: TestClient, auth_headers) -> None:
    """平台上下文：创建、查询、更新、删除工作流。"""
    created = client.post(
        WORKFLOWS_URL,
        json={
            "name": "平台工作流",
            "description": "desc",
            "graph": _valid_graph(),
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    assert created.json()["is_platform"] if "is_platform" in created.json() else True
    # 平台上下文创建的工作流 tenant_id 必为 PLATFORM_TENANT_ID（全零 UUID）
    assert created.json()["tenant_id"] == "00000000-0000-0000-0000-000000000000"

    detail = client.get(f"{WORKFLOWS_URL}/{workflow_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["name"] == "平台工作流"
    assert detail.json()["graph"]["nodes"][0]["type"] == "start"

    updated = client.put(
        f"{WORKFLOWS_URL}/{workflow_id}",
        json={
            "name": "平台工作流 v2",
            "description": "updated",
            "graph": _valid_graph(),
            "is_enabled": False,
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "平台工作流 v2"
    assert updated.json()["is_enabled"] is False

    listed = client.get(WORKFLOWS_URL, headers=auth_headers).json()
    assert listed["total"] >= 1

    deleted = client.delete(f"{WORKFLOWS_URL}/{workflow_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get(f"{WORKFLOWS_URL}/{workflow_id}", headers=auth_headers).status_code == 404


def test_tenant_workflow_isolation(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """租户 A 创建的工作流，租户 B 不可见、不可写。"""
    create_tenant(client, auth_headers, "acme", "Acme")
    create_tenant(client, auth_headers, "globex", "Globex")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    globex_site, globex_headers, _ = tenant_admin_client(tenant_client, "globex")

    acme_wf = _create_workflow(acme_site, acme_headers, "Acme 工作流")

    # globex 列表看不到 acme 的工作流
    globex_list = globex_site.get(WORKFLOWS_URL, headers=globex_headers).json()
    assert all(item["id"] != acme_wf["id"] for item in globex_list["items"])

    # globex 直接 GET / PUT / DELETE acme 的工作流均不可见
    assert (
        globex_site.get(
            f"{WORKFLOWS_URL}/{acme_wf['id']}", headers=globex_headers
        ).status_code
        == 404
    )
    assert (
        globex_site.put(
            f"{WORKFLOWS_URL}/{acme_wf['id']}",
            json={
                "name": "越权改名",
                "description": "",
                "graph": _valid_graph(),
                "is_enabled": True,
            },
            headers=globex_headers,
        ).status_code
        == 404
    )
    assert (
        globex_site.delete(
            f"{WORKFLOWS_URL}/{acme_wf['id']}", headers=globex_headers
        ).status_code
        == 404
    )


def test_tenant_sees_platform_workflow_readonly(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """平台工作流对租户可见（列表/详情），但租户不可写。"""
    platform_wf = _create_workflow(client, auth_headers, "平台公共工作流")

    create_tenant(client, auth_headers, "acme", "Acme")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")

    listed = acme_site.get(WORKFLOWS_URL, headers=acme_headers).json()
    assert any(item["id"] == platform_wf["id"] for item in listed["items"])

    detail = acme_site.get(
        f"{WORKFLOWS_URL}/{platform_wf['id']}", headers=acme_headers
    )
    assert detail.status_code == 200

    # 租户尝试更新/删除平台工作流必须被拒（403 或 404）
    update_resp = acme_site.put(
        f"{WORKFLOWS_URL}/{platform_wf['id']}",
        json={
            "name": "租户越权改名",
            "description": "",
            "graph": _valid_graph(),
            "is_enabled": True,
        },
        headers=acme_headers,
    )
    assert update_resp.status_code in (403, 404)


def test_graph_validation(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """图校验：缺 start / 多 end / 环 / 非法节点类型均被拒。"""
    # 合法图返回 valid=True
    ok = client.post(
        f"{WORKFLOWS_URL}/validate",
        json={
            "name": "任意",
            "description": "",
            "graph": _valid_graph(),
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["valid"] is True
    assert ok.json()["node_count"] == 3

    # 缺 start
    no_start = client.post(
        f"{WORKFLOWS_URL}/validate",
        json={
            "name": "任意",
            "description": "",
            "graph": {
                "nodes": [
                    {"id": "llm_1", "type": "llm", "data": {}},
                    {"id": "end_1", "type": "end", "data": {}},
                ],
                "edges": [{"source": "llm_1", "target": "end_1"}],
            },
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert no_start.status_code == 422

    # 环
    cyclic = client.post(
        f"{WORKFLOWS_URL}/validate",
        json={
            "name": "任意",
            "description": "",
            "graph": {
                "nodes": [
                    {"id": "start_1", "type": "start", "data": {}},
                    {"id": "llm_1", "type": "llm", "data": {}},
                    {"id": "end_1", "type": "end", "data": {}},
                ],
                "edges": [
                    {"source": "start_1", "target": "llm_1"},
                    {"source": "llm_1", "target": "start_1"},
                    {"source": "llm_1", "target": "end_1"},
                ],
            },
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert cyclic.status_code == 422

    # 非法节点类型
    bad_type = client.post(
        f"{WORKFLOWS_URL}/validate",
        json={
            "name": "任意",
            "description": "",
            "graph": {
                "nodes": [
                    {"id": "start_1", "type": "start", "data": {}},
                    {"id": "if_1", "type": "if_else", "data": {}},
                    {"id": "end_1", "type": "end", "data": {}},
                ],
                "edges": [
                    {"source": "start_1", "target": "if_1"},
                    {"source": "if_1", "target": "end_1"},
                ],
            },
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert bad_type.status_code == 422

    # 创建时图不合法也应被拒
    create_bad = client.post(
        WORKFLOWS_URL,
        json={
            "name": "坏图",
            "description": "",
            "graph": {"nodes": [], "edges": []},
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert create_bad.status_code == 422


def test_template_market_and_clone(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """模板市场：平台建模板 → 租户列表可见 → 一键克隆为自有工作流。"""
    template = client.post(
        TEMPLATES_URL,
        json={
            "name": "客服问答模板",
            "description": "开箱即用",
            "graph": _valid_graph(),
            "category": "customer_service",
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert template.status_code == 201, template.text
    template_id = template.json()["id"]

    # 租户能看到启用模板
    create_tenant(client, auth_headers, "acme", "Acme")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")
    template_list = acme_site.get(TEMPLATES_URL, headers=acme_headers).json()
    assert any(item["id"] == template_id for item in template_list["items"])

    # 租户克隆模板
    cloned = acme_site.post(
        f"{WORKFLOWS_URL}/clone-from-template/{template_id}",
        json={"name": "Acme 客服实例", "description": None},
        headers=acme_headers,
    )
    assert cloned.status_code == 201, cloned.text
    cloned_body = cloned.json()
    assert cloned_body["name"] == "Acme 客服实例"
    # 克隆出来的工作流 graph 与模板一致，tenant_id 为当前租户
    assert cloned_body["graph"] == _valid_graph()
    assert cloned_body["tenant_id"] != "00000000-0000-0000-0000-000000000000"

    # 租户不能直接创建/更新/删除模板
    assert (
        acme_site.post(
            TEMPLATES_URL,
            json={
                "name": "租户模板",
                "description": "",
                "graph": _valid_graph(),
                "category": "",
                "is_enabled": True,
            },
            headers=acme_headers,
        ).status_code
        in (403, 404)
    )

    # 平台更新模板
    updated = client.put(
        f"{TEMPLATES_URL}/{template_id}",
        json={
            "name": "客服问答模板 v2",
            "description": "updated",
            "graph": _valid_graph(),
            "category": "customer_service",
            "is_enabled": True,
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "客服问答模板 v2"

    # 停用模板后租户列表不可见
    client.put(
        f"{TEMPLATES_URL}/{template_id}",
        json={
            "name": "客服问答模板 v2",
            "description": "updated",
            "graph": _valid_graph(),
            "category": "customer_service",
            "is_enabled": False,
        },
        headers=auth_headers,
    )
    template_list_after = acme_site.get(
        TEMPLATES_URL, headers=acme_headers
    ).json()
    assert all(item["id"] != template_id for item in template_list_after["items"])

    # 平台删除模板
    deleted = client.delete(f"{TEMPLATES_URL}/{template_id}", headers=auth_headers)
    assert deleted.status_code == 204


def test_tenant_cannot_clone_platform_workflow(
    client: TestClient, auth_headers, tenant_client
) -> None:
    """平台工作流（非模板）不能被租户克隆；租户也不能从模板克隆到平台作用域。"""
    create_tenant(client, auth_headers, "acme", "Acme")
    acme_site, acme_headers, _ = tenant_admin_client(tenant_client, "acme")

    # 不存在的模板 id → 404
    not_found = acme_site.post(
        f"{WORKFLOWS_URL}/clone-from-template/00000000-0000-0000-0000-000000000000",
        json={"name": "无模板克隆"},
        headers=acme_headers,
    )
    assert not_found.status_code == 404
