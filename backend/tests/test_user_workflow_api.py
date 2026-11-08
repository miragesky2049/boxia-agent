"""用户端 workflow 接口端到端：schema、SSE 运行、人审中断/续跑、历史与待审批、归属隔离。

平台建应用并上架市场，租户订阅后由租户子域名的用户站点访问；
用真实 Postgres checkpointer 验证 interrupt/resume 全链路。
"""

from __future__ import annotations

import json
from uuid import uuid4

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
from tests.workflow_canvas import (
    build_start_end_canvas,
    build_start_human_end_canvas,
)

API = "/api/v1/user"


def _platform_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "Admin-password-123"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_market_app(
    client: TestClient,
    headers: dict[str, str],
    name: str,
    graph: dict,
    *,
    flow_type: str = "workflow",
) -> str:
    """平台建应用 → 存图 → 上架 → 置为自助订阅（sale_mode=2）。"""
    resp = client.post(
        "/api/v1/admin/apps",
        json={"name": name, "description": "workflow 接口测试", "flow_type": flow_type},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    app_id = resp.json()["application_id"]

    saved = client.put(
        f"/api/v1/admin/apps/{app_id}/graph",
        json={"graph": graph, "changelog": "test init"},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    listed = client.post(
        f"/api/v1/admin/apps/{app_id}/listing",
        json={"listed": True},
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE application SET sale_mode = 2 WHERE id = :aid"),
            {"aid": app_id},
        )
    return app_id


def _subscribe(site: TestClient, headers: dict[str, str], app_id: str) -> None:
    resp = site.post(
        "/api/v1/admin/marketplace/subscribe",
        json={"application_id": app_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def _parse_sse(text: str) -> list[tuple[str, dict | None]]:
    events: list[tuple[str, dict | None]] = []
    for block in text.strip().split("\n\n"):
        name = ""
        data: dict | None = None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        if name:
            events.append((name, data))
    return events


def _setup_world(client: TestClient, tenant_client, persistent_user_tenant_client):
    """建 3 个市场应用（直出/人审/对话流）+ 租户订阅 + 三个不同角色用户。"""
    platform = _platform_headers(client)
    app_direct = _create_market_app(client, platform, "直出工作流", build_start_end_canvas())
    app_human = _create_market_app(
        client,
        platform,
        "人审工作流",
        build_start_human_end_canvas(assignee_role="leader", instructions="请审批"),
    )
    app_chatflow = _create_market_app(
        client,
        platform,
        "对话流应用",
        build_start_end_canvas(),
        flow_type="chatflow",
    )

    create_tenant(client, platform, code="wfco", name="Workflow 公司")
    admin_site, admin_headers, _ = tenant_admin_client(tenant_client, "wfco")
    for app_id in (app_direct, app_human, app_chatflow):
        _subscribe(admin_site, admin_headers, app_id)

    created_role = admin_site.post(
        "/api/v1/admin/roles",
        json={"code": "leader", "name": "审批人", "description": "人审测试角色"},
        headers=admin_headers,
    )
    assert created_role.status_code == 201, created_role.text
    leader_role_id = created_role.json()["id"]
    viewer_role_id = list_roles(admin_site, admin_headers)["viewer"]["id"]

    create_user(
        admin_site,
        admin_headers,
        username="wf-owner",
        role_id=viewer_role_id,
    )
    create_user(
        admin_site,
        admin_headers,
        username="wf-other",
        role_id=viewer_role_id,
    )
    create_user(
        admin_site,
        admin_headers,
        username="wf-leader",
        role_id=leader_role_id,
    )

    user_site = persistent_user_tenant_client("wfco")

    def login(username: str) -> dict[str, str]:
        resp = user_site.post(
            "/api/v1/user/auth/login",
            json={"username": username, "password": USER_PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return {
        "site": user_site,
        "app_direct": app_direct,
        "app_human": app_human,
        "app_chatflow": app_chatflow,
        "owner": login("wf-owner"),
        "other": login("wf-other"),
        "leader": login("wf-leader"),
    }


def test_schema_returns_start_inputs(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    world = _setup_world(client, tenant_client, persistent_user_tenant_client)
    site = world["site"]

    resp = site.get(
        f"{API}/agents/{world['app_direct']}/workflow/schema",
        headers=world["owner"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["flow_type"] == "workflow"
    assert [p["name"] for p in body["inputs"]] == ["input"]
    assert body["inputs"][0]["required"] is True
    assert body["has_human_approval"] is False

    human = site.get(
        f"{API}/agents/{world['app_human']}/workflow/schema",
        headers=world["owner"],
    ).json()
    assert human["has_human_approval"] is True
    assert [p["name"] for p in human["inputs"]] == ["content"]


def test_schema_rejects_chatflow(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    world = _setup_world(client, tenant_client, persistent_user_tenant_client)
    resp = world["site"].get(
        f"{API}/agents/{world['app_chatflow']}/workflow/schema",
        headers=world["owner"],
    )
    assert resp.status_code == 422


def test_run_stream_success(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    world = _setup_world(client, tenant_client, persistent_user_tenant_client)
    resp = world["site"].post(
        f"{API}/agents/{world['app_direct']}/workflow/run/stream",
        json={"inputs": {"input": "你好，工作流"}},
        headers=world["owner"],
    )
    assert resp.status_code == 200, resp.text
    events = _parse_sse(resp.text)
    names = [name for name, _ in events]
    assert "run_start" in names
    assert "node_start" in names
    assert "node_end" in names
    assert names[-1] == "final"

    result = next(data for name, data in events if name == "result")
    assert result["output"] == {"output": "你好，工作流"}
    assert result["thread_id"]
    assert result["run_id"]


def test_run_stream_rejects_missing_required(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    world = _setup_world(client, tenant_client, persistent_user_tenant_client)
    resp = world["site"].post(
        f"{API}/agents/{world['app_direct']}/workflow/run/stream",
        json={"inputs": {}},
        headers=world["owner"],
    )
    assert resp.status_code == 422
    assert "input" in resp.json()["detail"]


def test_human_flow_interrupt_role_gated_resume(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    world = _setup_world(client, tenant_client, persistent_user_tenant_client)
    site = world["site"]
    thread_id = str(uuid4())

    # 1. 发起人运行 → 中断
    run_resp = site.post(
        f"{API}/agents/{world['app_human']}/workflow/run/stream",
        json={"inputs": {"content": "待审批内容"}, "thread_id": thread_id},
        headers=world["owner"],
    )
    assert run_resp.status_code == 200, run_resp.text
    events = _parse_sse(run_resp.text)
    interrupted = next(data for name, data in events if name == "interrupted")
    assert interrupted["approval"]["assignee_role"] == "leader"
    run_id = interrupted["run_id"]
    assert interrupted["thread_id"] == thread_id

    # 2. 同线程重复发起 → 409
    conflict = site.post(
        f"{API}/agents/{world['app_human']}/workflow/run/stream",
        json={"inputs": {"content": "再跑一次"}, "thread_id": thread_id},
        headers=world["owner"],
    )
    assert conflict.status_code == 409

    # 3. 普通角色看不到这条待审批，审批角色能看到
    approvals_viewer = site.get(
        f"{API}/agents/{world['app_human']}/approvals",
        headers=world["owner"],
    ).json()
    assert approvals_viewer == []
    approvals_leader = site.get(
        f"{API}/agents/{world['app_human']}/approvals",
        headers=world["leader"],
    ).json()
    assert len(approvals_leader) == 1
    assert str(approvals_leader[0]["id"]) == run_id

    # 4. 普通角色续跑 → 403（JSON，在 SSE 之前拦截）
    forbidden = site.post(
        f"{API}/agents/{world['app_human']}/workflow/runs/{thread_id}/resume/stream",
        json={"approved": True, "comment": "越权"},
        headers=world["owner"],
    )
    assert forbidden.status_code == 403

    # 5. 审批角色批准续跑 → 成功，END 取人审 comment
    resume_resp = site.post(
        f"{API}/agents/{world['app_human']}/workflow/runs/{thread_id}/resume/stream",
        json={"approved": True, "comment": "同意执行"},
        headers=world["leader"],
    )
    assert resume_resp.status_code == 200, resume_resp.text
    resume_events = _parse_sse(resume_resp.text)
    result = next(data for name, data in resume_events if name == "result")
    assert result["output"] == {"output": "同意执行"}
    assert result["run_id"] == run_id
    assert [name for name, _ in resume_events][-1] == "final"

    # 6. 终态后待审批列表清空
    approvals_after = site.get(
        f"{API}/agents/{world['app_human']}/approvals",
        headers=world["leader"],
    ).json()
    assert approvals_after == []


def test_human_rejection_marks_run_error(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    world = _setup_world(client, tenant_client, persistent_user_tenant_client)
    site = world["site"]
    thread_id = str(uuid4())
    run_resp = site.post(
        f"{API}/agents/{world['app_human']}/workflow/run/stream",
        json={"inputs": {"content": "会被拒绝"}, "thread_id": thread_id},
        headers=world["owner"],
    )
    events = _parse_sse(run_resp.text)
    assert any(name == "interrupted" for name, _ in events)

    resume_resp = site.post(
        f"{API}/agents/{world['app_human']}/workflow/runs/{thread_id}/resume/stream",
        json={"approved": False, "comment": "资料不全"},
        headers=world["leader"],
    )
    assert resume_resp.status_code == 200, resume_resp.text
    resume_events = _parse_sse(resume_resp.text)
    error = next(data for name, data in resume_events if name == "error")
    assert "资料不全" in error["message"]


def test_run_history_and_detail_ownership(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    world = _setup_world(client, tenant_client, persistent_user_tenant_client)
    site = world["site"]
    run_resp = site.post(
        f"{API}/agents/{world['app_direct']}/workflow/run/stream",
        json={"inputs": {"input": "历史留痕"}},
        headers=world["owner"],
    )
    run_id = next(d for n, d in _parse_sse(run_resp.text) if n == "result")["run_id"]

    # 发起人看历史与详情
    runs = site.get(
        f"{API}/agents/{world['app_direct']}/runs",
        headers=world["owner"],
    ).json()
    assert len(runs) == 1
    assert runs[0]["execute_status"] == "success"

    detail = site.get(f"{API}/runs/{run_id}", headers=world["owner"])
    assert detail.status_code == 200
    detail_body = detail.json()
    assert str(detail_body["run"]["id"]) == run_id
    assert detail_body["node_executions"], "应包含节点执行明细"

    # 其他用户：历史为空，直读详情 404
    other_runs = site.get(
        f"{API}/agents/{world['app_direct']}/runs",
        headers=world["other"],
    ).json()
    assert other_runs == []
    other_detail = site.get(f"{API}/runs/{run_id}", headers=world["other"])
    assert other_detail.status_code == 404


def test_approver_can_read_interrupted_run_detail(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    world = _setup_world(client, tenant_client, persistent_user_tenant_client)
    site = world["site"]
    thread_id = str(uuid4())
    run_resp = site.post(
        f"{API}/agents/{world['app_human']}/workflow/run/stream",
        json={"inputs": {"content": "审批人可读"}, "thread_id": thread_id},
        headers=world["owner"],
    )
    run_id = next(d for n, d in _parse_sse(run_resp.text) if n == "interrupted")["run_id"]

    resp = site.get(f"{API}/runs/{run_id}", headers=world["leader"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["run"]["execute_status"] == "interrupted"


def test_resume_unknown_thread_404(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    world = _setup_world(client, tenant_client, persistent_user_tenant_client)
    resp = world["site"].post(
        f"{API}/agents/{world['app_human']}/workflow/runs/{uuid4()}/resume/stream",
        json={"approved": True, "comment": "x"},
        headers=world["leader"],
    )
    assert resp.status_code == 404


def test_non_stream_workflow_run_still_works(
    client: TestClient,
    tenant_client,
    persistent_user_tenant_client,
) -> None:
    """旧的非流式 /workflow/run 不回归。"""
    world = _setup_world(client, tenant_client, persistent_user_tenant_client)
    resp = world["site"].post(
        f"{API}/agents/{world['app_direct']}/workflow/run",
        json={"inputs": {"input": "非流式"}},
        headers=world["owner"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["output"] == {"output": "非流式"}
