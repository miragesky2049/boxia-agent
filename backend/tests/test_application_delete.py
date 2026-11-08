"""应用删除 / 批量删除：权限门槛、二次确认、全量级联清理与部分成功语义。"""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from tests.helpers import create_department, create_tenant, tenant_admin_client

APPS_URL = "/api/v1/admin/apps"
OPERATOR_PASSWORD = "Operator-pass-123"


# ========== 辅助 ==========
def _new_uow() -> SqlAlchemyUnitOfWork:
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    return uow


def _scalar(sql: str, **params) -> int:
    uow = _new_uow()
    try:
        value = uow.session.execute(text(sql), params).scalar()
        assert value is not None
        return int(value)
    finally:
        uow.close()


def _role_id(client: TestClient, headers: dict[str, str], code: str) -> str:
    roles = client.get("/api/v1/admin/roles", headers=headers).json()
    return next(item["id"] for item in roles if item["code"] == code)


def _create_operator(
    client: TestClient, headers: dict[str, str], role_code: str, username: str
) -> dict[str, str]:
    response = client.post(
        "/api/v1/admin/admin-users",
        json={
            "username": username,
            "password": OPERATOR_PASSWORD,
            "display_name": f"{role_code} 运营",
            "role_id": _role_id(client, headers, role_code),
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    login = client.post(
        "/api/v1/admin/auth/login",
        json={"username": username, "password": OPERATOR_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_app(client: TestClient, headers: dict[str, str], name: str) -> str:
    """通过管理端接口创建平台应用（同时生成初始画布与版本）。"""
    response = client.post(
        APPS_URL,
        json={"name": name, "flow_type": "workflow"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["application_id"]


def _seed_app_related_data(app_id: str, tenant_id: str, department_id: str) -> dict[str, str]:
    """为平台应用构造覆盖全部清理路径的关联数据，返回关键行 id 供删除后断言。"""
    uow = _new_uow()
    ids: dict[str, str] = {}
    try:
        user_id = uow.session.execute(
            text("SELECT id FROM users WHERE tenant_id = :tid ORDER BY created_at LIMIT 1"),
            {"tid": tenant_id},
        ).scalar_one()
        ids["user"] = str(user_id)

        # 租户开通实例 + 租户级配置覆盖
        uow.session.execute(
            text(
                "INSERT INTO tenant_application_instance "
                "(id, tenant_id, application_id, status, source, overrides) "
                "VALUES (:id, :tid, :aid, 'active', 'granted', '{}'::jsonb)"
            ),
            {"id": uuid4(), "tid": tenant_id, "aid": app_id},
        )
        uow.session.execute(
            text(
                "INSERT INTO tenant_application_config "
                "(id, tenant_id, application_id, config_key, config_value) "
                "VALUES (:id, :tid, :aid, 'graph.nodes.n1.config.x', '\"v\"'::jsonb)"
            ),
            {"id": uuid4(), "tid": tenant_id, "aid": app_id},
        )

        # 可见范围 v2：(应用, 租户) scope + 白名单（部门 + 指定用户）
        scope_id = uuid4()
        uow.session.execute(
            text(
                "INSERT INTO app_visibility_scope "
                "(id, application_id, tenant_id, visibility) "
                "VALUES (:id, :aid, :tid, 'whitelist')"
            ),
            {"id": scope_id, "aid": app_id, "tid": tenant_id},
        )
        uow.session.execute(
            text(
                "INSERT INTO app_visibility_whitelist "
                "(id, scope_id, subject_type, subject_id, include_subtree) "
                "VALUES (:id, :sid, 'DEPARTMENT', :did, TRUE), "
                "       (:id2, :sid, 'USER', :uid, FALSE)"
            ),
            {
                "id": uuid4(),
                "id2": uuid4(),
                "sid": scope_id,
                "did": department_id,
                "uid": user_id,
            },
        )

        # 0072 起 resource_grants 的 CHECK 收紧，无法再播种 app 档授权；
        # 清理器仍保留 app 档 DELETE 作为存量兜底（删除行数恒为 0）。

        # 权益套餐项（多态 object_type='app'）
        plan_id = uuid4()
        uow.session.execute(
            text("INSERT INTO entitlement_plan (id, code, name) VALUES (:id, :code, '测试套餐')"),
            {"id": plan_id, "code": f"plan-{plan_id.hex[:8]}"},
        )
        uow.session.execute(
            text(
                "INSERT INTO entitlement_plan_item (id, plan_id, object_type, object_id) "
                "VALUES (:id, :plan_id, 'app', :aid)"
            ),
            {"id": uuid4(), "plan_id": plan_id, "aid": app_id},
        )
        ids["plan"] = str(plan_id)

        # 运行记录 + 节点执行（workflow_id RESTRICT 路径）
        run_id = uuid4()
        uow.session.execute(
            text(
                "INSERT INTO run (id, tenant_id, workflow_id, graph_snapshot, input, execute_status, "
                "thread_id, started_at) "
                "VALUES (:id, :tid, :aid, '{}'::jsonb, '{}'::jsonb, 'success', :thread, NOW())"
            ),
            {"id": run_id, "tid": tenant_id, "aid": app_id, "thread": f"th-{run_id.hex[:8]}"},
        )
        ids["run"] = str(run_id)
        uow.session.execute(
            text(
                "INSERT INTO run_node_execution (id, execute_id, node_id, node_type, started_at) "
                "VALUES (:id, :run_id, 'node-1', 'llm', NOW())"
            ),
            {"id": uuid4(), "run_id": run_id},
        )

        # 无 FK 裸列表
        uow.session.execute(
            text(
                "INSERT INTO tenant_usage_ledger "
                "(id, tenant_id, application_id, run_id, node_id, model_id) "
                "VALUES (:id, :tid, :aid, :run_id, 'node-1', 'gpt-test')"
            ),
            {"id": uuid4(), "tid": tenant_id, "aid": app_id, "run_id": run_id},
        )
        uow.session.execute(
            text(
                "INSERT INTO event_webhook (id, tenant_id, application_id, event_type, url) "
                "VALUES (:id, :tid, :aid, 'run.finished', 'https://example.com/hook')"
            ),
            {"id": uuid4(), "tid": tenant_id, "aid": app_id},
        )
        uow.session.execute(
            text(
                "INSERT INTO application_apply (id, tenant_id, application_id, apply_type) "
                "VALUES (:id, :tid, :aid, 'TRIAL')"
            ),
            {"id": uuid4(), "tid": tenant_id, "aid": app_id},
        )
        uow.session.execute(
            text(
                "INSERT INTO application_user_variable "
                "(id, application_id, user_id, variable_key, value) "
                "VALUES (:id, :aid, :uid, 'k', '\"v\"'::jsonb)"
            ),
            {"id": uuid4(), "aid": app_id, "uid": user_id},
        )

        # 会话与消息（conversation CASCADE 路径）
        conversation_id = uuid4()
        uow.session.execute(
            text(
                "INSERT INTO conversation (id, tenant_id, user_id, application_id, title) "
                "VALUES (:id, :tid, :uid, :aid, '会话')"
            ),
            {"id": conversation_id, "tid": tenant_id, "uid": user_id, "aid": app_id},
        )
        uow.session.execute(
            text(
                "INSERT INTO message (id, conversation_id, tenant_id, user_id, application_id, role) "
                "VALUES (:id, :cid, :tid, :uid, :aid, 'user')"
            ),
            {
                "id": uuid4(),
                "cid": conversation_id,
                "tid": tenant_id,
                "uid": user_id,
                "aid": app_id,
            },
        )

        uow.commit()
        return ids
    finally:
        uow.close()


def _app_related_counts(app_id: str) -> dict[str, int]:
    return {
        "application": _scalar("SELECT count(*) FROM application WHERE id = :aid", aid=app_id),
        "graphs": _scalar(
            "SELECT count(*) FROM application_graph WHERE application_id = :aid", aid=app_id
        ),
        "graph_versions": _scalar(
            "SELECT count(*) FROM application_graph_version WHERE application_id = :aid",
            aid=app_id,
        ),
        "instances": _scalar(
            "SELECT count(*) FROM tenant_application_instance WHERE application_id = :aid",
            aid=app_id,
        ),
        "tenant_config": _scalar(
            "SELECT count(*) FROM tenant_application_config WHERE application_id = :aid",
            aid=app_id,
        ),
        "visibility_scope": _scalar(
            "SELECT count(*) FROM app_visibility_scope WHERE application_id = :aid",
            aid=app_id,
        ),
        "visibility_whitelist": _scalar(
            "SELECT count(*) FROM app_visibility_whitelist w "
            "JOIN app_visibility_scope s ON s.id = w.scope_id "
            "WHERE s.application_id = :aid",
            aid=app_id,
        ),
        "conversations": _scalar(
            "SELECT count(*) FROM conversation WHERE application_id = :aid", aid=app_id
        ),
        "messages": _scalar("SELECT count(*) FROM message WHERE application_id = :aid", aid=app_id),
        "runs": _scalar("SELECT count(*) FROM run WHERE workflow_id = :aid", aid=app_id),
        "node_executions": _scalar(
            "SELECT count(*) FROM run_node_execution ne JOIN run r ON r.id = ne.execute_id "
            "WHERE r.workflow_id = :aid",
            aid=app_id,
        ),
        "usage_ledger": _scalar(
            "SELECT count(*) FROM tenant_usage_ledger WHERE application_id = :aid",
            aid=app_id,
        ),
        "webhooks": _scalar(
            "SELECT count(*) FROM event_webhook WHERE application_id = :aid", aid=app_id
        ),
        "apply": _scalar(
            "SELECT count(*) FROM application_apply WHERE application_id = :aid",
            aid=app_id,
        ),
        "user_variables": _scalar(
            "SELECT count(*) FROM application_user_variable WHERE application_id = :aid",
            aid=app_id,
        ),
        "resource_grants": _scalar(
            "SELECT count(*) FROM resource_grants WHERE resource_type = 'app' "
            "AND resource_id = :aid",
            aid=app_id,
        ),
        "plan_items": _scalar(
            "SELECT count(*) FROM entitlement_plan_item WHERE object_type = 'app' "
            "AND object_id = :aid",
            aid=app_id,
        ),
    }


# ========== 校验与权限 ==========
def test_delete_requires_confirm(client: TestClient, auth_headers: dict[str, str]) -> None:
    app_id = _create_app(client, auth_headers, "确认位应用")

    missing = client.delete(f"{APPS_URL}/{app_id}", headers=auth_headers)
    assert missing.status_code == 422, missing.text

    rejected = client.delete(f"{APPS_URL}/{app_id}?confirm=false", headers=auth_headers)
    assert rejected.status_code == 422, rejected.text


def test_delete_requires_permission_code(client: TestClient, auth_headers: dict[str, str]) -> None:
    app_id = _create_app(client, auth_headers, "权限应用")
    # 0071：viewer 出厂已无「管理端访问」，无法再绑定为管理员，仅以 admin 验证权限码门槛
    headers = _create_operator(client, auth_headers, "admin", "op-admin-delete")
    response = client.delete(f"{APPS_URL}/{app_id}?confirm=true", headers=headers)
    assert response.status_code == 403, response.text
    assert client.get(f"{APPS_URL}/{app_id}", headers=auth_headers).status_code == 200


def test_delete_requires_login(client: TestClient, auth_headers: dict[str, str]) -> None:
    app_id = _create_app(client, auth_headers, "匿名应用")
    response = client.delete(f"{APPS_URL}/{app_id}?confirm=true")
    assert response.status_code == 401, response.text


def test_delete_forbidden_in_tenant_scope(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers, code="scope-acme", name="作用域租户")
    app_id = _create_app(client, auth_headers, "作用域应用")
    site, headers, _ = tenant_admin_client(tenant_client, "scope-acme")
    response = site.delete(f"{APPS_URL}/{app_id}?confirm=true", headers=headers)
    assert response.status_code == 403, response.text
    assert _scalar("SELECT count(*) FROM tenants WHERE id = :tid", tid=tenant["id"]) == 1


def test_delete_unknown_app_returns_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.delete(f"{APPS_URL}/{uuid4()}?confirm=true", headers=auth_headers)
    assert response.status_code == 404, response.text


def test_delete_tenant_owned_app_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    tenant = create_tenant(client, auth_headers, code="owned-acme", name="租户应用租户")
    uow = _new_uow()
    owned_app = uuid4()
    try:
        uow.session.execute(
            text(
                "INSERT INTO application (id, owner_type, owner_id, name, description, is_enabled, "
                "is_listed_in_market) "
                "VALUES (:id, 'tenant', :tid, '租户自有应用', '', TRUE, FALSE)"
            ),
            {"id": owned_app, "tid": tenant["id"]},
        )
        uow.commit()
    finally:
        uow.close()

    response = client.delete(f"{APPS_URL}/{owned_app}?confirm=true", headers=auth_headers)
    assert response.status_code == 422, response.text
    assert _scalar("SELECT count(*) FROM application WHERE id = :aid", aid=owned_app) == 1


# ========== 级联与审计 ==========
def test_delete_cascades_all_related_data(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers, code="app-victim", name="待删应用租户")
    site, headers, _ = tenant_admin_client(tenant_client, "app-victim")
    department = create_department(site, headers, "应用部门")
    app_id = _create_app(client, auth_headers, "待删应用")
    ids = _seed_app_related_data(app_id, tenant["id"], department["id"])

    response = client.delete(f"{APPS_URL}/{app_id}?confirm=true", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "待删应用"
    assert body["deleted"]["run"] >= 1
    # 0072：app 档授权已不可播种，兜底 DELETE 恒为 0 行
    assert body["deleted"]["resource_grants"] == 0
    assert body["deleted"]["entitlement_plan_item"] >= 1

    counts = _app_related_counts(app_id)
    assert all(value == 0 for value in counts.values()), counts

    # 节点执行记录随 run CASCADE
    assert (
        _scalar(
            "SELECT count(*) FROM run_node_execution WHERE execute_id = :rid",
            rid=ids["run"],
        )
        == 0
    )
    # 套餐本体保留，仅关联项被清
    assert _scalar("SELECT count(*) FROM entitlement_plan WHERE id = :id", id=ids["plan"]) == 1
    # 租户与租户用户不受影响
    assert _scalar("SELECT count(*) FROM tenants WHERE id = :tid", tid=tenant["id"]) == 1
    assert _scalar("SELECT count(*) FROM users WHERE id = :uid", uid=ids["user"]) == 1


def test_delete_writes_platform_side_audit(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers, code="app-audit", name="审计租户")
    site, headers, _ = tenant_admin_client(tenant_client, "app-audit")
    department = create_department(site, headers)
    app_id = _create_app(client, auth_headers, "审计应用")
    _seed_app_related_data(app_id, tenant["id"], department["id"])

    response = client.delete(f"{APPS_URL}/{app_id}?confirm=true", headers=auth_headers)
    assert response.status_code == 200, response.text
    audit_id = response.json()["audit_id"]

    row = (
        _new_uow()
        .session.execute(
            text(
                "SELECT tenant_id, action, resource_type, resource_id, actor_username "
                "FROM audit_logs WHERE id = :id"
            ),
            {"id": audit_id},
        )
        .one()
    )
    assert str(row[0]) == str(PLATFORM_TENANT_ID)
    assert row[1] == "app.deleted"
    assert row[2] == "app"
    assert str(row[3]) == app_id
    assert row[4] == "admin"


# ========== 批量 ==========
def test_batch_delete_partial_success(client: TestClient, auth_headers: dict[str, str]) -> None:
    app_id = _create_app(client, auth_headers, "批量待删应用")
    missing_id = str(uuid4())

    response = client.post(
        f"{APPS_URL}/batch",
        json={"application_ids": [app_id, missing_id], "confirm": True},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert body["succeeded"] == 1
    assert body["failed"] == 1

    by_id = {item["application_id"]: item for item in body["items"]}
    assert by_id[app_id]["success"] is True
    assert by_id[app_id]["name"] == "批量待删应用"
    missing_item = by_id[missing_id]
    assert missing_item["success"] is False
    assert missing_item["error_code"] == "NOT_FOUND"

    assert _scalar("SELECT count(*) FROM application WHERE id = :aid", aid=app_id) == 0
    assert (
        _scalar(
            "SELECT count(*) FROM audit_logs WHERE action = 'app.deleted' AND resource_id = :rid",
            rid=app_id,
        )
        == 1
    )


def test_batch_delete_deduplicates_ids(client: TestClient, auth_headers: dict[str, str]) -> None:
    app_id = _create_app(client, auth_headers, "去重应用")
    response = client.post(
        f"{APPS_URL}/batch",
        json={"application_ids": [app_id, app_id], "confirm": True},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["succeeded"] == 1
    assert body["failed"] == 0


def test_batch_delete_validation(client: TestClient, auth_headers: dict[str, str]) -> None:
    app_id = _create_app(client, auth_headers, "校验应用")

    without_confirm = client.post(
        f"{APPS_URL}/batch",
        json={"application_ids": [app_id], "confirm": False},
        headers=auth_headers,
    )
    assert without_confirm.status_code == 422, without_confirm.text

    empty = client.post(
        f"{APPS_URL}/batch",
        json={"application_ids": [], "confirm": True},
        headers=auth_headers,
    )
    assert empty.status_code == 422, empty.text

    too_many = client.post(
        f"{APPS_URL}/batch",
        json={"application_ids": [str(uuid4()) for _ in range(101)], "confirm": True},
        headers=auth_headers,
    )
    assert too_many.status_code == 422, too_many.text

    headers = _create_operator(client, auth_headers, "admin", "op-app-batch-admin")
    forbidden = client.post(
        f"{APPS_URL}/batch",
        json={"application_ids": [app_id], "confirm": True},
        headers=headers,
    )
    assert forbidden.status_code == 403, forbidden.text
    assert _scalar("SELECT count(*) FROM application WHERE id = :aid", aid=app_id) == 1
