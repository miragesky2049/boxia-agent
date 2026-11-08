"""租户删除 / 批量删除：权限门槛、二次确认、全量级联清理与部分成功语义。"""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from tests.helpers import create_tenant, tenant_admin_client

TENANTS_URL = "/api/v1/admin/tenants"
OPERATOR_PASSWORD = "Operator-pass-123"


# ========== 辅助 ==========
def _new_uow() -> SqlAlchemyUnitOfWork:
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    return uow


def _scalar(sql: str, **params) -> int:
    uow = _new_uow()
    try:
        return int(uow.session.execute(text(sql), params).scalar())
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


def _seed_related_data(tenant_id: str) -> dict[str, str]:
    """为租户构造覆盖全部清理路径的关联数据，返回关键行 id 供删除后断言。"""
    uow = _new_uow()
    ids: dict[str, str] = {}
    try:
        admin_id = uow.session.execute(
            text("SELECT id FROM users WHERE tenant_id = :tid ORDER BY created_at LIMIT 1"),
            {"tid": tenant_id},
        ).scalar_one()
        ids["admin_user"] = str(admin_id)
        role_id = uow.session.execute(
            text("SELECT id FROM roles WHERE tenant_id = :tid AND code = 'superadmin'"),
            {"tid": tenant_id},
        ).scalar_one()

        platform_app = uuid4()
        uow.session.execute(
            text(
                "INSERT INTO application (id, owner_type, name, description, is_enabled, "
                "is_listed_in_market, sale_mode, support_trial, doc_url, ext_json) "
                "VALUES (:id, 'platform', '平台公共应用', '', TRUE, FALSE, 1, FALSE, '', '{}'::jsonb)"
            ),
            {"id": platform_app},
        )
        ids["platform_app"] = str(platform_app)

        owned_app = uuid4()
        uow.session.execute(
            text(
                "INSERT INTO application (id, owner_type, owner_id, name, description, is_enabled, "
                "is_listed_in_market, sale_mode, support_trial, doc_url, ext_json) "
                "VALUES (:id, 'tenant', :tid, '租户自有应用', '', TRUE, FALSE, 1, FALSE, '', '{}'::jsonb)"
            ),
            {"id": owned_app, "tid": tenant_id},
        )
        ids["owned_app"] = str(owned_app)

        # 租户开通平台应用的实例关系（平台应用不删，实例随租户 CASCADE）
        uow.session.execute(
            text(
                "INSERT INTO tenant_application_instance "
                "(id, tenant_id, application_id, status, source, overrides) "
                "VALUES (:id, :tid, :aid, 'active', 'granted', '{}'::jsonb)"
            ),
            {"id": uuid4(), "tid": tenant_id, "aid": platform_app},
        )

        platform_resource = uuid4()
        uow.session.execute(
            text(
                "INSERT INTO resource (id, type, owner_type, name, config) "
                "VALUES (:id, 'tool', 'platform', '平台工具', '{}'::jsonb)"
            ),
            {"id": platform_resource},
        )
        ids["platform_resource"] = str(platform_resource)

        owned_resource = uuid4()
        uow.session.execute(
            text(
                "INSERT INTO resource (id, type, owner_type, owner_id, name, config) "
                "VALUES (:id, 'skill', 'tenant', :tid, '租户技能', '{}'::jsonb)"
            ),
            {"id": owned_resource, "tid": tenant_id},
        )
        ids["owned_resource"] = str(owned_resource)

        for resource_id in (platform_resource, owned_resource):
            uow.session.execute(
                text(
                    "INSERT INTO tenant_resource_entitlement "
                    "(id, resource_id, tenant_id, granted_at, status, auth_source, auth_type, "
                    "quota_json, remark) "
                    "VALUES (:id, :rid, :tid, NOW(), 'active', 'OPS', 'FORMAL', '{}'::jsonb, '')"
                ),
                {"id": uuid4(), "rid": resource_id, "tid": tenant_id},
            )

        # RBAC 角色资源授权（随租户 CASCADE）
        uow.session.execute(
            text(
                "INSERT INTO resource_grants (id, resource_type, resource_id, tenant_id, role_id, "
                "subject_type) VALUES (:id, 'skill', :rid, :tid, :role_id, 'role')"
            ),
            {"id": uuid4(), "rid": owned_resource, "tid": tenant_id, "role_id": role_id},
        )

        run_id = uuid4()
        uow.session.execute(
            text(
                "INSERT INTO run (id, tenant_id, workflow_id, graph_snapshot, input, execute_status, "
                "thread_id, started_at) "
                "VALUES (:id, :tid, :aid, '{}'::jsonb, '{}'::jsonb, 'success', :thread, NOW())"
            ),
            {"id": run_id, "tid": tenant_id, "aid": owned_app, "thread": f"th-{run_id.hex[:8]}"},
        )
        ids["run"] = str(run_id)
        uow.session.execute(
            text(
                "INSERT INTO run_node_execution (id, execute_id, node_id, node_type, started_at) "
                "VALUES (:id, :run_id, 'node-1', 'llm', NOW())"
            ),
            {"id": uuid4(), "run_id": run_id},
        )

        uow.session.execute(
            text(
                "INSERT INTO tenant_usage_ledger "
                "(id, tenant_id, application_id, run_id, node_id, model_id) "
                "VALUES (:id, :tid, :aid, :run_id, 'node-1', 'gpt-test')"
            ),
            {"id": uuid4(), "tid": tenant_id, "aid": owned_app, "run_id": run_id},
        )
        uow.session.execute(
            text(
                "INSERT INTO event_webhook (id, tenant_id, application_id, event_type, url) "
                "VALUES (:id, :tid, :aid, 'run.finished', 'https://example.com/hook')"
            ),
            {"id": uuid4(), "tid": tenant_id, "aid": owned_app},
        )
        uow.session.execute(
            text(
                "INSERT INTO application_apply (id, tenant_id, application_id, apply_type) "
                "VALUES (:id, :tid, :aid, 'TRIAL')"
            ),
            {"id": uuid4(), "tid": tenant_id, "aid": platform_app},
        )
        uow.session.execute(
            text(
                "INSERT INTO entitlement_request_log "
                "(id, request_id, tenant_id, action, status, version, payload) "
                "VALUES (:id, :req, :tid, 'batch', 'completed', 1, '{}'::jsonb)"
            ),
            {"id": uuid4(), "req": f"req-{uuid4().hex}", "tid": tenant_id},
        )
        uow.session.execute(
            text(
                "INSERT INTO application_user_variable "
                "(id, application_id, user_id, variable_key, value) "
                "VALUES (:id, :aid, :uid, 'k', '\"v\"'::jsonb)"
            ),
            {"id": uuid4(), "aid": owned_app, "uid": admin_id},
        )

        document_id = uuid4()
        uow.session.execute(
            text("INSERT INTO documents (id, tenant_id, title) VALUES (:id, :tid, '租户文档')"),
            {"id": document_id, "tid": tenant_id},
        )
        uow.session.execute(
            text(
                "INSERT INTO document_chunks (id, document_id, tenant_id, chunk_index, content) "
                "VALUES (:id, :doc_id, :tid, 0, 'chunk content')"
            ),
            {"id": uuid4(), "doc_id": document_id, "tid": tenant_id},
        )

        conversation_id = uuid4()
        uow.session.execute(
            text(
                "INSERT INTO conversation (id, tenant_id, user_id, application_id, title) "
                "VALUES (:id, :tid, :uid, :aid, '会话')"
            ),
            {"id": conversation_id, "tid": tenant_id, "uid": admin_id, "aid": owned_app},
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
                "uid": admin_id,
                "aid": owned_app,
            },
        )

        # 一条租户自身历史审计（模拟租户内操作留痕）
        uow.session.execute(
            text(
                "INSERT INTO audit_logs (id, tenant_id, actor_id, actor_username, action, "
                "resource_type, resource_id, detail) "
                "VALUES (:id, :tid, :uid, 'someone', 'user.login', 'user', :uid, '{}'::jsonb)"
            ),
            {"id": uuid4(), "tid": tenant_id, "uid": admin_id},
        )
        uow.commit()
        return ids
    finally:
        uow.close()


def _tenant_related_counts(tenant_id: str) -> dict[str, int]:
    return {
        "tenants": _scalar("SELECT count(*) FROM tenants WHERE id = :tid", tid=tenant_id),
        "users": _scalar("SELECT count(*) FROM users WHERE tenant_id = :tid", tid=tenant_id),
        "roles": _scalar("SELECT count(*) FROM roles WHERE tenant_id = :tid", tid=tenant_id),
        "user_roles": _scalar(
            "SELECT count(*) FROM user_roles WHERE tenant_id = :tid", tid=tenant_id
        ),
        "departments": _scalar(
            "SELECT count(*) FROM departments WHERE tenant_id = :tid", tid=tenant_id
        ),
        "hr_dictionaries": _scalar(
            "SELECT count(*) FROM hr_dictionaries WHERE tenant_id = :tid", tid=tenant_id
        ),
        "resource_grants": _scalar(
            "SELECT count(*) FROM resource_grants WHERE tenant_id = :tid", tid=tenant_id
        ),
        "instances": _scalar(
            "SELECT count(*) FROM tenant_application_instance WHERE tenant_id = :tid",
            tid=tenant_id,
        ),
        "entitlements": _scalar(
            "SELECT count(*) FROM tenant_resource_entitlement WHERE tenant_id = :tid",
            tid=tenant_id,
        ),
        "runs": _scalar("SELECT count(*) FROM run WHERE tenant_id = :tid", tid=tenant_id),
        "usage_ledger": _scalar(
            "SELECT count(*) FROM tenant_usage_ledger WHERE tenant_id = :tid", tid=tenant_id
        ),
        "webhooks": _scalar(
            "SELECT count(*) FROM event_webhook WHERE tenant_id = :tid", tid=tenant_id
        ),
        "apply": _scalar(
            "SELECT count(*) FROM application_apply WHERE tenant_id = :tid", tid=tenant_id
        ),
        "request_logs": _scalar(
            "SELECT count(*) FROM entitlement_request_log WHERE tenant_id = :tid",
            tid=tenant_id,
        ),
        "documents": _scalar(
            "SELECT count(*) FROM documents WHERE tenant_id = :tid", tid=tenant_id
        ),
        "chunks": _scalar(
            "SELECT count(*) FROM document_chunks WHERE tenant_id = :tid", tid=tenant_id
        ),
        "conversations": _scalar(
            "SELECT count(*) FROM conversation WHERE tenant_id = :tid", tid=tenant_id
        ),
        "messages": _scalar("SELECT count(*) FROM message WHERE tenant_id = :tid", tid=tenant_id),
        "audit_logs": _scalar(
            "SELECT count(*) FROM audit_logs WHERE tenant_id = :tid", tid=tenant_id
        ),
        "owned_apps": _scalar(
            "SELECT count(*) FROM application WHERE owner_type = 'tenant' AND owner_id = :tid",
            tid=tenant_id,
        ),
        "owned_resources": _scalar(
            "SELECT count(*) FROM resource WHERE owner_type = 'tenant' AND owner_id = :tid",
            tid=tenant_id,
        ),
    }


# ========== 校验与权限 ==========
def test_delete_requires_confirm(client: TestClient, auth_headers: dict[str, str]) -> None:
    tenant = create_tenant(client, auth_headers, code="del-confirm", name="确认位租户")

    missing = client.delete(f"{TENANTS_URL}/{tenant['id']}", headers=auth_headers)
    assert missing.status_code == 422, missing.text

    rejected = client.delete(f"{TENANTS_URL}/{tenant['id']}?confirm=false", headers=auth_headers)
    assert rejected.status_code == 422, rejected.text


def test_delete_requires_permission_code(client: TestClient, auth_headers: dict[str, str]) -> None:
    tenant = create_tenant(client, auth_headers, code="del-perm", name="权限租户")
    # 0071：viewer 出厂已无「管理端访问」，无法再绑定为管理员，仅以 admin 验证权限码门槛
    headers = _create_operator(client, auth_headers, "admin", "op-admin-delete")
    response = client.delete(f"{TENANTS_URL}/{tenant['id']}?confirm=true", headers=headers)
    assert response.status_code == 403, response.text
    assert client.get(f"{TENANTS_URL}/{tenant['id']}", headers=auth_headers).status_code == 200


def test_delete_requires_login(client: TestClient, auth_headers: dict[str, str]) -> None:
    tenant = create_tenant(client, auth_headers, code="del-anon", name="匿名租户")
    response = client.delete(f"{TENANTS_URL}/{tenant['id']}?confirm=true")
    assert response.status_code == 401, response.text


def test_delete_forbidden_in_tenant_scope(
    client: TestClient, auth_headers: dict[str, str], tenant_client
) -> None:
    tenant = create_tenant(client, auth_headers, code="scope-acme", name="作用域租户")
    site, headers, _ = tenant_admin_client(tenant_client, "scope-acme")
    response = site.delete(f"{TENANTS_URL}/{tenant['id']}?confirm=true", headers=headers)
    assert response.status_code == 403, response.text


def test_delete_platform_tenant_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.delete(
        f"{TENANTS_URL}/{PLATFORM_TENANT_ID}?confirm=true", headers=auth_headers
    )
    assert response.status_code == 403, response.text
    assert _scalar("SELECT count(*) FROM tenants WHERE id = :tid", tid=PLATFORM_TENANT_ID) == 1


def test_delete_unknown_tenant_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.delete(f"{TENANTS_URL}/{uuid4()}?confirm=true", headers=auth_headers)
    assert response.status_code == 404, response.text


# ========== 级联与审计 ==========
def test_delete_cascades_all_related_data(client: TestClient, auth_headers: dict[str, str]) -> None:
    victim = create_tenant(client, auth_headers, code="del-victim", name="待删租户")
    other = create_tenant(client, auth_headers, code="del-other", name="留存租户")
    ids = _seed_related_data(victim["id"])

    response = client.delete(f"{TENANTS_URL}/{victim['id']}?confirm=true", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "del-victim"
    assert body["deleted"]["application"] >= 1
    assert body["deleted"]["run"] >= 1
    assert body["deleted"]["audit_logs"] >= 1

    counts = _tenant_related_counts(victim["id"])
    assert all(value == 0 for value in counts.values()), counts

    # 无外键的节点执行记录随 run CASCADE
    assert (
        _scalar(
            "SELECT count(*) FROM run_node_execution WHERE execute_id = :rid",
            rid=ids["run"],
        )
        == 0
    )
    # 租户自有应用上的用户变量被清
    assert (
        _scalar(
            "SELECT count(*) FROM application_user_variable WHERE application_id = :aid",
            aid=ids["owned_app"],
        )
        == 0
    )
    # 平台应用 / 平台资源本体保留
    assert _scalar("SELECT count(*) FROM application WHERE id = :aid", aid=ids["platform_app"]) == 1
    assert (
        _scalar("SELECT count(*) FROM resource WHERE id = :rid", rid=ids["platform_resource"]) == 1
    )
    # 其他租户不受影响（初始化的角色/超管/字典仍在）
    assert _scalar("SELECT count(*) FROM tenants WHERE id = :tid", tid=other["id"]) == 1
    assert _scalar("SELECT count(*) FROM users WHERE tenant_id = :tid", tid=other["id"]) == 1
    assert _scalar("SELECT count(*) FROM roles WHERE tenant_id = :tid", tid=other["id"]) >= 3


def test_delete_writes_platform_side_audit(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    tenant = create_tenant(client, auth_headers, code="del-audit", name="审计租户")
    _seed_related_data(tenant["id"])

    response = client.delete(
        f"{TENANTS_URL}/{tenant['id']}?confirm=true",
        headers=auth_headers,
    )
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
    assert row[1] == "tenant.deleted"
    assert row[2] == "tenant"
    assert row[3] == tenant["id"]
    assert row[4] == "admin"


# ========== 批量 ==========
def test_batch_delete_partial_success(client: TestClient, auth_headers: dict[str, str]) -> None:
    victim = create_tenant(client, auth_headers, code="batch-victim", name="批量待删")
    _seed_related_data(victim["id"])
    missing_id = str(uuid4())

    response = client.post(
        f"{TENANTS_URL}/batch",
        json={
            "tenant_ids": [victim["id"], str(PLATFORM_TENANT_ID), missing_id],
            "confirm": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert body["succeeded"] == 1
    assert body["failed"] == 2

    by_id = {item["tenant_id"]: item for item in body["items"]}
    assert by_id[victim["id"]]["success"] is True
    assert by_id[victim["id"]]["code"] == "batch-victim"
    platform_item = by_id[str(PLATFORM_TENANT_ID)]
    assert platform_item["success"] is False
    assert platform_item["error_code"] == "FORBIDDEN"
    missing_item = by_id[missing_id]
    assert missing_item["success"] is False
    assert missing_item["error_code"] == "NOT_FOUND"

    assert _scalar("SELECT count(*) FROM tenants WHERE id = :tid", tid=victim["id"]) == 0
    assert (
        _scalar(
            "SELECT count(*) FROM audit_logs WHERE action = 'tenant.deleted' "
            "AND resource_id = :rid",
            rid=victim["id"],
        )
        == 1
    )


def test_batch_delete_deduplicates_ids(client: TestClient, auth_headers: dict[str, str]) -> None:
    tenant = create_tenant(client, auth_headers, code="batch-dup", name="去重租户")
    response = client.post(
        f"{TENANTS_URL}/batch",
        json={"tenant_ids": [tenant["id"], tenant["id"]], "confirm": True},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["succeeded"] == 1
    assert body["failed"] == 0


def test_batch_delete_validation(client: TestClient, auth_headers: dict[str, str]) -> None:
    tenant = create_tenant(client, auth_headers, code="batch-val", name="校验租户")

    without_confirm = client.post(
        f"{TENANTS_URL}/batch",
        json={"tenant_ids": [tenant["id"]], "confirm": False},
        headers=auth_headers,
    )
    assert without_confirm.status_code == 422, without_confirm.text

    empty = client.post(
        f"{TENANTS_URL}/batch",
        json={"tenant_ids": [], "confirm": True},
        headers=auth_headers,
    )
    assert empty.status_code == 422, empty.text

    too_many = client.post(
        f"{TENANTS_URL}/batch",
        json={"tenant_ids": [str(uuid4()) for _ in range(101)], "confirm": True},
        headers=auth_headers,
    )
    assert too_many.status_code == 422, too_many.text

    headers = _create_operator(client, auth_headers, "admin", "op-batch-admin")
    forbidden = client.post(
        f"{TENANTS_URL}/batch",
        json={"tenant_ids": [tenant["id"]], "confirm": True},
        headers=headers,
    )
    assert forbidden.status_code == 403, forbidden.text
    assert _scalar("SELECT count(*) FROM tenants WHERE id = :tid", tid=tenant["id"]) == 1
