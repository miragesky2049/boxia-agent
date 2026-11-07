"""0074 智能体应用端到端：flow_type=agent 建应用（DB CHECK）、配置面 API、运行闸门。

平台侧走 apps-admin 的 agent-config 读写；用户侧验证可见范围继承（0068 机制
与 flow_type 无关）与 workflow 运行接口对 agent 的拒绝。真实 Postgres。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.model.database import get_engine
from tests.helpers import (
    USER_PASSWORD,
    create_tenant,
    create_user,
    list_roles,
    tenant_admin_client,
)

API = "/api/v1/user"
ADMIN_APPS = "/api/v1/admin/apps"


def _platform_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "Admin-password-123"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_app(client: TestClient, headers: dict[str, str], name: str, flow_type: str) -> str:
    """平台建应用（默认画布）→ 上架 → 自助订阅。agent 的默认画布由服务端生成。"""
    resp = client.post(
        ADMIN_APPS,
        json={"name": name, "description": "0074 测试", "flow_type": flow_type},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    app_id = resp.json()["application_id"]
    assert client.post(f"{ADMIN_APPS}/{app_id}/listing", json={"listed": True}, headers=headers).status_code == 200
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE application SET sale_mode = 2 WHERE id = :aid"), {"aid": app_id})
    return app_id


def _agent_config_form(**overrides) -> dict:
    form = {
        "systemPrompt": "你是产品顾问",
        "modleName": "gpt-4o",
        "maxToolRounds": 8,
        "tools": [],
        "datasets": [{"datasetId": "d1", "name": "产品库", "mode": "always", "topK": 4}],
        "memory": {"shortTerm": {"windowTurns": 6}},
        "openingRemarks": "你好，我可以帮你查产品资料。",
        "suggestedQuestions": ["退款政策"],
    }
    form.update(overrides)
    return form


def test_agent_app_default_graph_and_config_roundtrip(
    client: TestClient,
) -> None:
    platform = _platform_headers(client)
    app_id = _create_app(client, platform, "产品顾问", "agent")

    graph_pack = client.get(f"{ADMIN_APPS}/{app_id}/graph", headers=platform).json()
    assert graph_pack["flow_type"] == "agent"
    node_types = {n["type"] for n in graph_pack["graph"]["nodes"]}
    assert node_types == {"1", "2", "100"}

    # 默认配置读出：配置面永远拿到完整表单
    defaults = client.get(f"{ADMIN_APPS}/{app_id}/agent-config", headers=platform)
    assert defaults.status_code == 200, defaults.text
    base = defaults.json()
    assert base["modleName"] and base["systemPrompt"]
    assert base["maxToolRounds"] == 10
    assert base["memory"]["shortTerm"]["enabled"] is True

    saved = client.put(
        f"{ADMIN_APPS}/{app_id}/agent-config",
        json=_agent_config_form(),
        headers=platform,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["datasets"][0]["datasetId"] == "d1"

    reread = client.get(f"{ADMIN_APPS}/{app_id}/agent-config", headers=platform).json()
    assert reread["systemPrompt"] == "你是产品顾问"
    assert reread["openingRemarks"] == "你好，我可以帮你查产品资料。"
    assert reread["suggestedQuestions"] == ["退款政策"]


def test_agent_config_rejects_invalid_and_wrong_flow_type(
    client: TestClient,
) -> None:
    platform = _platform_headers(client)
    agent_id = _create_app(client, platform, "配置校验", "agent")
    workflow_id = _create_app(client, platform, "普通工作流", "workflow")

    bad = client.put(
        f"{ADMIN_APPS}/{agent_id}/agent-config",
        json=_agent_config_form(systemPrompt="", modleName=""),
        headers=platform,
    )
    assert bad.status_code == 422, bad.text
    assert "systemPrompt" in bad.text and "modleName" in bad.text

    reserved = client.put(
        f"{ADMIN_APPS}/{agent_id}/agent-config",
        json=_agent_config_form(tools=[{"name": "knowledge_search_1"}]),
        headers=platform,
    )
    assert reserved.status_code == 422, reserved.text

    wrong = client.get(f"{ADMIN_APPS}/{workflow_id}/agent-config", headers=platform)
    assert wrong.status_code == 422, wrong.text
    assert "不是智能体类型" in wrong.text


def test_agent_app_user_side_visibility_and_workflow_gate(
    client: TestClient, tenant_client, persistent_user_tenant_client,
) -> None:
    """可见范围继承：agent 与 workflow 走同一 0068 订阅链路出现在用户列表；
    workflow 运行接口闸门必须拒绝 agent（防绕道固定流程执行）。"""
    platform = _platform_headers(client)
    agent_id = _create_app(client, platform, "产品顾问2", "agent")
    client.put(
        f"{ADMIN_APPS}/{agent_id}/agent-config",
        json=_agent_config_form(),
        headers=platform,
    )

    create_tenant(client, platform, code="agco", name="Agent 公司")
    admin_site, admin_headers, _ = tenant_admin_client(tenant_client, "agco")
    resp = admin_site.post(
        "/api/v1/admin/marketplace/subscribe",
        json={"application_id": agent_id},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    viewer_role_id = list_roles(admin_site, admin_headers)["viewer"]["id"]
    create_user(admin_site, admin_headers, username="ag-owner", role_id=viewer_role_id)

    site = persistent_user_tenant_client("agco")
    login = site.post(
        "/api/v1/user/auth/login",
        json={"username": "ag-owner", "password": USER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    listed = site.get(f"{API}/agents", headers=headers).json()
    items = listed["items"] if isinstance(listed, dict) else listed
    assert agent_id in {item["id"] for item in items}

    detail = site.get(f"{API}/agents/{agent_id}", headers=headers).json()
    assert detail["flow_type"] == "agent"
    assert detail["config"]["opening_remarks"] == "你好，我可以帮你查产品资料。"
    assert detail["config"]["suggested_questions"] == ["退款政策"]
    assert detail["config"]["datasets"][0]["dataset_id"] == "d1"

    blocked = site.get(f"{API}/agents/{agent_id}/workflow/schema", headers=headers)
    assert blocked.status_code == 422, blocked.text


def test_unified_conversation_endpoint_validation(
    client: TestClient, tenant_client, persistent_user_tenant_client,
) -> None:
    """0074 PRD M3 端点收敛：统一对话入口参数错误须在 SSE 之前以 JSON 4xx 返回。"""
    from uuid import uuid4

    platform = _platform_headers(client)
    agent_id = _create_app(client, platform, "统一入口", "agent")
    chatflow_id = _create_app(client, platform, "统一入口流", "chatflow")

    create_tenant(client, platform, code="univo", name="统一入口公司")
    admin_site, admin_headers, _ = tenant_admin_client(tenant_client, "univo")
    for app_id in (agent_id, chatflow_id):
        assert admin_site.post(
            "/api/v1/admin/marketplace/subscribe",
            json={"application_id": app_id},
            headers=admin_headers,
        ).status_code == 200
    viewer_role_id = list_roles(admin_site, admin_headers)["viewer"]["id"]
    create_user(admin_site, admin_headers, username="univ-owner", role_id=viewer_role_id)
    site = persistent_user_tenant_client("univo")
    login = site.post(
        "/api/v1/user/auth/login",
        json={"username": "univ-owner", "password": USER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # 空消息且无 resume：chat 与 chatflow 管线均 422
    resp = site.post(f"{API}/agents/{agent_id}/chatflow/run/stream", json={}, headers=headers)
    assert resp.status_code == 422, resp.text
    resp = site.post(f"{API}/agents/{chatflow_id}/chatflow/run/stream", json={}, headers=headers)
    assert resp.status_code == 422, resp.text
    # agent 续跑缺 conversation_id / 缺 approved：422（F10 预检收口在 prepare_chat_run）
    resp = site.post(
        f"{API}/agents/{agent_id}/chatflow/run/stream",
        json={"resume": {"approved": True}}, headers=headers,
    )
    assert resp.status_code == 422, resp.text
    resp = site.post(
        f"{API}/agents/{agent_id}/chatflow/run/stream",
        json={"conversation_id": str(uuid4()), "resume": {"comment": "x"}}, headers=headers,
    )
    assert resp.status_code == 422, resp.text
    # 旧端点已退役：路由层 405/404 均视为收敛达成（FastAPI 对已知前缀未注册方法返回 405）
    retired = site.post(f"{API}/agents/{agent_id}/run/stream", json={"message": "hi"}, headers=headers)
    assert retired.status_code in (404, 405), retired.text
