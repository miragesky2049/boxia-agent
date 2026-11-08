"""M4 PRD F16.6：用户端"我的记忆"管理 API 集成用例（真实 Postgres + 登录态）。

覆盖：作用域列表（只见本人）、越权删除 404、清空需 confirm、清空仅动本人、
未登录 401。记忆行直接 SQL 造数（抽取管线由 test_memory_extractor_service 覆盖）。
"""

from __future__ import annotations

from uuid import UUID, uuid4

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

USER_API = "/api/v1/user/memories"


def _insert_application(conn, app_id: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO application (id, owner_type, name, description, is_enabled, "
            "is_listed_in_market, sale_mode, support_trial, doc_url, ext_json) "
            "VALUES (:id, 'platform', '记忆应用', '', TRUE, FALSE, 1, FALSE, '', '{}'::jsonb)"
        ),
        {"id": app_id},
    )


def _insert_memory(conn, *, tenant_id: UUID, app_id: UUID, user_id: UUID, content: str) -> UUID:
    memory_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO agent_memory (id, tenant_id, application_id, user_id, kind, content, metadata) "
            "VALUES (:id, :tid, :aid, :uid, 'fact', :content, '{}'::jsonb)"
        ),
        {"id": memory_id, "tid": tenant_id, "aid": app_id, "uid": user_id, "content": content},
    )
    return memory_id


def _query_content(memory_id: UUID) -> str | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT content FROM agent_memory WHERE id = :id"), {"id": memory_id}
        ).first()
    return row[0] if row else None


class _Setup:
    def __init__(self) -> None:
        self.site: TestClient
        self.alice_headers: dict[str, str]
        self.app_id: UUID
        self.alice_ids: list[UUID] = []
        self.bob_id: UUID


def _setup(
    client: TestClient,
    auth_headers: dict[str, str],
    tenant_client,
    user_tenant_client,
    user_login_headers,
    code: str = "m4mem",
) -> _Setup:
    create_tenant(client, auth_headers, code, "记忆管理租户")
    site, headers, _ = tenant_admin_client(tenant_client, code)
    roles = list_roles(site, headers)
    alice = create_user(site, headers, username="alice", role_id=roles["viewer"]["id"])
    bob = create_user(site, headers, username="bob", role_id=roles["viewer"]["id"])
    app_id = uuid4()
    tenant_id = UUID(alice["tenant_id"])
    st = _Setup()
    st.site = user_tenant_client(code)
    st.app_id = app_id
    st.bob_id = bob["id"]
    with get_engine().begin() as conn:
        _insert_application(conn, app_id)
        st.alice_ids = [
            _insert_memory(
                conn,
                tenant_id=tenant_id,
                app_id=app_id,
                user_id=alice["id"],
                content="Alice 偏好中文回复",
            ),
            _insert_memory(
                conn,
                tenant_id=tenant_id,
                app_id=app_id,
                user_id=alice["id"],
                content="Alice 常问北京天气",
            ),
        ]
        _insert_memory(
            conn,
            tenant_id=tenant_id,
            app_id=app_id,
            user_id=bob["id"],
            content="Bob 的秘密号码",
        )
    st.alice_headers = user_login_headers(code, "alice", USER_PASSWORD)
    return st


def test_list_scoped_to_current_user(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    st = _setup(
        client, auth_headers, tenant_client, user_tenant_client, user_login_headers, "m4mem-a"
    )
    resp = st.site.get(
        USER_API, params={"application_id": str(st.app_id)}, headers=st.alice_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    contents = {item["content"] for item in body["items"]}
    assert "Bob 的秘密号码" not in contents
    assert {item["memory_id"] for item in body["items"]} == {str(i) for i in st.alice_ids}
    assert all(item["kind"] == "fact" for item in body["items"])


def test_single_delete_own_ok_and_idor_404(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    st = _setup(
        client, auth_headers, tenant_client, user_tenant_client, user_login_headers, "m4mem-b"
    )
    target, _other = st.alice_ids
    # 越权：alice 删 bob 的记忆 → 404，且行仍在
    with get_engine().connect() as conn:
        bob_row = conn.execute(
            text("SELECT id FROM agent_memory WHERE user_id = :uid"), {"uid": st.bob_id}
        ).first()
    denied = st.site.delete(
        f"{USER_API}/{bob_row[0]}",
        params={"application_id": str(st.app_id)},
        headers=st.alice_headers,
    )
    assert denied.status_code == 404, denied.text
    assert _query_content(bob_row[0]) is not None
    # 本人删除：200 且列表只剩 1 条
    ok = st.site.delete(
        f"{USER_API}/{target}",
        params={"application_id": str(st.app_id)},
        headers=st.alice_headers,
    )
    assert ok.status_code == 200, ok.text
    assert _query_content(target) is None
    listing = st.site.get(
        USER_API, params={"application_id": str(st.app_id)}, headers=st.alice_headers
    ).json()
    assert listing["total"] == 1


def test_clear_requires_confirm_and_keeps_other_user(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    st = _setup(
        client, auth_headers, tenant_client, user_tenant_client, user_login_headers, "m4mem-c"
    )
    without_confirm = st.site.delete(
        USER_API, params={"application_id": str(st.app_id)}, headers=st.alice_headers
    )
    assert without_confirm.status_code == 422, without_confirm.text
    assert (
        st.site.get(
            USER_API, params={"application_id": str(st.app_id)}, headers=st.alice_headers
        ).json()["total"]
        == 2
    )
    cleared = st.site.delete(
        USER_API,
        params={"application_id": str(st.app_id), "confirm": "true"},
        headers=st.alice_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["deleted"] == 2
    assert (
        st.site.get(
            USER_API, params={"application_id": str(st.app_id)}, headers=st.alice_headers
        ).json()["total"]
        == 0
    )
    # bob 的记忆不受影响
    assert _query_content(_bob_memory_id(st)) is not None


def _bob_memory_id(st: _Setup) -> UUID:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT id FROM agent_memory WHERE user_id = :uid"), {"uid": st.bob_id}
        ).first()
    assert row is not None
    return row[0]


def test_admin_search_by_app_keyword_and_status(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    """M4 PRD F16.7：平台管理端按应用检索（关键词/状态过滤），租户管理员无权。"""
    st = _setup(
        client, auth_headers, tenant_client, user_tenant_client, user_login_headers, "m4mem-e"
    )
    admin_api = "/api/v1/admin/agent-memories"
    resp = client.get(
        admin_api,
        params={"application_id": str(st.app_id), "keyword": "北京"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["content"] == "Alice 常问北京天气"
    assert body["items"][0]["status"] == "active"
    # 全量含 bob：status=all 不带关键词 → 3 条
    all_rows = client.get(
        admin_api,
        params={"application_id": str(st.app_id), "status": "all"},
        headers=auth_headers,
    ).json()
    assert all_rows["total"] == 3
    # 用户管理面删除后可见性一致（活跃 1 条）
    st.site.delete(
        f"{USER_API}/{st.alice_ids[0]}",
        params={"application_id": str(st.app_id)},
        headers=st.alice_headers,
    )
    after = client.get(
        admin_api, params={"application_id": str(st.app_id)}, headers=auth_headers
    ).json()
    # 默认 status=active：alice 剩 1 条 + bob 1 条
    assert after["total"] == 2


def test_admin_search_rejected_for_tenant_admin(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    st = _setup(
        client, auth_headers, tenant_client, user_tenant_client, user_login_headers, "m4mem-f"
    )
    site, headers, _ = tenant_admin_client(tenant_client, "m4mem-f")
    denied = site.get(
        "/api/v1/admin/agent-memories",
        params={"application_id": str(st.app_id)},
        headers=headers,
    )
    assert denied.status_code in (401, 403), denied.text


def test_anonymous_access_rejected(
    client, auth_headers, tenant_client, user_tenant_client, user_login_headers
) -> None:
    st = _setup(
        client, auth_headers, tenant_client, user_tenant_client, user_login_headers, "m4mem-d"
    )
    anon = st.site.get(USER_API, params={"application_id": str(st.app_id)})
    assert anon.status_code == 401, anon.text
