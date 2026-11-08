"""应用会话管理接口（B-N9-05）端到端测试：列表 / 消息 / 删除 / 跨租户隔离。"""

from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.id.uuid7 import new_uuid
from internal.infrastructure.model.database import get_engine
from tests.helpers import create_tenant, create_user, list_roles, tenant_admin_client


def _login_platform(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "Admin-password-123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_app(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post(
        "/api/v1/admin/apps",
        json={"name": name, "description": "会话测试应用"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["application_id"]


def _insert_conversation(
    *,
    tenant_id: str,
    user_id: str,
    application_id: str,
    title: str,
    messages: list[tuple[str, str]],
) -> str:
    """直接落库造会话与消息，避免依赖用户端 chat 全链路。"""
    conversation_id = new_uuid()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO conversation (id, tenant_id, user_id, application_id, title) "
                "VALUES (:id, :tid, :uid, :aid, :title)"
            ),
            {
                "id": conversation_id,
                "tid": UUID(tenant_id),
                "uid": UUID(user_id),
                "aid": UUID(application_id),
                "title": title,
            },
        )
        for role, content in messages:
            conn.execute(
                text(
                    "INSERT INTO message "
                    "(id, conversation_id, tenant_id, user_id, application_id, role, content) "
                    "VALUES (:id, :cid, :tid, :uid, :aid, :role, :content)"
                ),
                {
                    "id": new_uuid(),
                    "cid": conversation_id,
                    "tid": UUID(tenant_id),
                    "uid": UUID(user_id),
                    "aid": UUID(application_id),
                    "role": role,
                    "content": content,
                },
            )
    return str(conversation_id)


def _seed_tenant_conversations(
    client: TestClient,
    auth_headers: dict[str, str],
    tenant_client,
    *,
    code: str,
    application_id: str,
    messages: list[tuple[str, str]],
) -> tuple[dict, str]:
    """建租户 + 用户 + 一条会话，返回 (tenant, conversation_id)。"""
    tenant = create_tenant(client, auth_headers, code=code, name=f"{code} 公司")
    site, tenant_headers, _ = tenant_admin_client(tenant_client, code)
    role = list_roles(site, tenant_headers)["viewer"]
    user = create_user(
        site,
        tenant_headers,
        username=f"{code}-user",
        role_id=role["id"],
    )
    conversation_id = _insert_conversation(
        tenant_id=tenant["id"],
        user_id=user["id"],
        application_id=application_id,
        title=f"{code} 会话",
        messages=messages,
    )
    return tenant, conversation_id


def test_conversations_list_messages_and_delete(
    client: TestClient,
    auth_headers: dict[str, str],
    tenant_client,
) -> None:
    app_id = _create_app(client, auth_headers, "会话管理测试")
    tenant, conv_id = _seed_tenant_conversations(
        client,
        auth_headers,
        tenant_client,
        code="conv",
        application_id=app_id,
        messages=[("user", "你好"), ("assistant", "你好，有什么可以帮你")],
    )

    # 1. 指定租户查列表：能看到会话与所属用户
    listed = client.get(
        f"/api/v1/admin/apps/{app_id}/conversations",
        params={"tenant_id": tenant["id"]},
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [item["conversation_id"] for item in body] == [conv_id]
    assert body[0]["username"] == "conv-user"
    assert body[0]["title"] == "conv 会话"

    # 2. 默认作用域是平台租户，业务租户的会话不可见
    default = client.get(
        f"/api/v1/admin/apps/{app_id}/conversations",
        headers=auth_headers,
    )
    assert default.status_code == 200
    assert default.json() == []

    # 3. 消息列表按时间升序
    msgs = client.get(
        f"/api/v1/admin/apps/conversations/{conv_id}/messages",
        params={"tenant_id": tenant["id"]},
        headers=auth_headers,
    )
    assert msgs.status_code == 200, msgs.text
    assert [item["role"] for item in msgs.json()] == ["user", "assistant"]

    # 4. 跨租户删除按不存在处理
    other_tenant, _ = _seed_tenant_conversations(
        client,
        auth_headers,
        tenant_client,
        code="other",
        application_id=app_id,
        messages=[("user", "别的租户")],
    )
    denied = client.delete(
        f"/api/v1/admin/apps/conversations/{conv_id}",
        params={"tenant_id": other_tenant["id"]},
        headers=auth_headers,
    )
    assert denied.status_code == 404

    # 5. 删除单条消息
    message_id = msgs.json()[0]["message_id"]
    deleted_msg = client.delete(
        f"/api/v1/admin/apps/conversations/{conv_id}/messages/{message_id}",
        params={"tenant_id": tenant["id"]},
        headers=auth_headers,
    )
    assert deleted_msg.status_code == 200, deleted_msg.text
    remaining = client.get(
        f"/api/v1/admin/apps/conversations/{conv_id}/messages",
        params={"tenant_id": tenant["id"]},
        headers=auth_headers,
    )
    assert [item["role"] for item in remaining.json()] == ["assistant"]

    # 6. 删除会话后列表只剩其他租户那条
    deleted_conv = client.delete(
        f"/api/v1/admin/apps/conversations/{conv_id}",
        params={"tenant_id": tenant["id"]},
        headers=auth_headers,
    )
    assert deleted_conv.status_code == 200, deleted_conv.text
    after = client.get(
        f"/api/v1/admin/apps/{app_id}/conversations",
        params={"tenant_id": tenant["id"]},
        headers=auth_headers,
    )
    assert after.json() == []


def test_conversations_reject_tenant_admin(
    client: TestClient,
    auth_headers: dict[str, str],
    tenant_client,
) -> None:
    """会话管理是平台运营能力，租户子域名管理员无权调用。"""
    app_id = _create_app(client, auth_headers, "会话权限测试")
    create_tenant(client, auth_headers, code="perm", name="权限公司")
    site, tenant_headers, _ = tenant_admin_client(tenant_client, "perm")

    response = site.get(
        f"/api/v1/admin/apps/{app_id}/conversations",
        headers=tenant_headers,
    )
    assert response.status_code == 403
