"""技能包虚拟目录：入口同步、文件 CRUD、路径校验、配额、导入导出与克隆。"""

import io
import zipfile
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.application import skill_package_service as package_module
from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.database import get_engine

TENANT_ADMIN_PASSWORD = "Tenant-password-123"
TENANT_CODE = "acme"


def _create_skill(
    client: TestClient, headers: dict[str, str], name: str = "技能包", content: str = ""
) -> dict:
    response = client.post(
        "/api/v1/admin/skills",
        json={"name": name, "description": "", "content": content, "config": {}},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _write_file(
    client: TestClient,
    headers: dict[str, str],
    skill_id: UUID,
    path: str,
    content: str,
    expected_hash: str | None = None,
):
    payload: dict = {"path": path, "content": content}
    if expected_hash is not None:
        payload["expected_hash"] = expected_hash
    return client.put(f"/api/v1/admin/skills/{skill_id}/files", json=payload, headers=headers)


def _list_files(
    client: TestClient, headers: dict[str, str], skill_id: UUID, query: str = ""
) -> dict:
    response = client.get(f"/api/v1/admin/skills/{skill_id}/files{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _create_tenant(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/v1/admin/tenants",
        json={
            "code": TENANT_CODE,
            "name": "Acme 公司",
            "admin_username": f"{TENANT_CODE}-admin",
            "admin_password": TENANT_ADMIN_PASSWORD,
            "admin_display_name": "Acme 管理员",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _grant_to_tenant(
    client: TestClient,
    headers: dict[str, str],
    tenant_id: UUID,
    resource_type: str,
    resource_id: UUID,
) -> None:
    """平台把资源授权给整租户，租户内全部角色可见。"""
    response = client.put(
        "/api/v1/admin/grants",
        params={"resource_type": resource_type, "resource_id": resource_id},
        json={"grants": [{"tenant_id": tenant_id, "role_id": None}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _tenant_client_with_headers(tenant_client) -> tuple[TestClient, dict[str, str]]:
    """构造租户站点客户端并返回其管理员的鉴权头。"""
    acme = tenant_client(TENANT_CODE)
    response = acme.post(
        "/api/v1/admin/auth/login",
        json={"username": f"{TENANT_CODE}-admin", "password": TENANT_ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return acme, {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_create_skill_syncs_entry_file(client: TestClient, auth_headers) -> None:
    skill = _create_skill(client, auth_headers, content="# 入口\n正文")

    listed = _list_files(client, auth_headers, skill["id"])
    assert listed["total"] == 1
    entry = listed["items"][0]
    assert entry["path"] == "SKILL.md"
    assert entry["media_type"] == "text/markdown"
    assert entry["size_bytes"] == len("# 入口\n正文".encode())
    assert listed["total_bytes"] == entry["size_bytes"]

    content = client.get(
        f"/api/v1/admin/skills/{skill['id']}/files/content",
        params={"path": "SKILL.md"},
        headers=auth_headers,
    )
    assert content.status_code == 200
    assert content.json()["content"] == "# 入口\n正文"


def test_update_skill_syncs_entry_file(client: TestClient, auth_headers) -> None:
    skill = _create_skill(client, auth_headers, content="旧入口")

    updated = client.put(
        f"/api/v1/admin/skills/{skill['id']}",
        json={"name": "技能包", "description": "", "content": "新入口", "config": {}},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text

    content = client.get(
        f"/api/v1/admin/skills/{skill['id']}/files/content",
        params={"path": "SKILL.md"},
        headers=auth_headers,
    )
    assert content.json()["content"] == "新入口"

    cleared = client.put(
        f"/api/v1/admin/skills/{skill['id']}",
        json={"name": "技能包", "description": "", "content": "", "config": {}},
        headers=auth_headers,
    )
    assert cleared.status_code == 200
    assert _list_files(client, auth_headers, skill["id"])["total"] == 0


def test_file_write_read_delete(client: TestClient, auth_headers) -> None:
    skill = _create_skill(client, auth_headers)

    written = _write_file(client, auth_headers, skill["id"], "references/faq.md", "问答")
    assert written.status_code == 200, written.text
    body = written.json()
    assert body["path"] == "references/faq.md"
    assert body["content"] == "问答"
    assert len(body["content_hash"]) == 64

    listed = _list_files(client, auth_headers, skill["id"], "?prefix=references")
    assert [item["path"] for item in listed["items"]] == ["references/faq.md"]
    assert _list_files(client, auth_headers, skill["id"], "?prefix=other")["total"] == 0

    removed = client.delete(
        f"/api/v1/admin/skills/{skill['id']}/files",
        params={"path": "references/faq.md"},
        headers=auth_headers,
    )
    assert removed.status_code == 204
    assert (
        client.get(
            f"/api/v1/admin/skills/{skill['id']}/files/content",
            params={"path": "references/faq.md"},
            headers=auth_headers,
        ).status_code
        == 404
    )


def test_write_skill_md_via_file_updates_entry(client: TestClient, auth_headers) -> None:
    skill = _create_skill(client, auth_headers)

    _write_file(client, auth_headers, skill["id"], "SKILL.md", "文件写入入口")

    detail = client.get(f"/api/v1/admin/skills/{skill['id']}", headers=auth_headers)
    assert detail.json()["content"] == "文件写入入口"

    client.delete(
        f"/api/v1/admin/skills/{skill['id']}/files",
        params={"path": "SKILL.md"},
        headers=auth_headers,
    )
    detail = client.get(f"/api/v1/admin/skills/{skill['id']}", headers=auth_headers)
    assert detail.json()["content"] == ""


def test_expected_hash_optimistic_lock(client: TestClient, auth_headers) -> None:
    skill = _create_skill(client, auth_headers)
    created = _write_file(client, auth_headers, skill["id"], "notes.md", "v1").json()

    stale = _write_file(client, auth_headers, skill["id"], "notes.md", "v2", expected_hash="0" * 64)
    assert stale.status_code == 409
    assert stale.json()["code"] == "CONFLICT"

    fresh = _write_file(
        client,
        auth_headers,
        skill["id"],
        "notes.md",
        "v2",
        expected_hash=created["content_hash"],
    )
    assert fresh.status_code == 200
    assert fresh.json()["content"] == "v2"


@pytest.mark.parametrize(
    "path",
    [
        "../escape.md",
        "/absolute.md",
        "a\\b.md",
        "a/./b.md",
        "a//b.md",
        "a/../b.md",
        "a:b.md",
        "trailing.",
        "dir/ padded.md",
    ],
)
def test_invalid_path_rejected(client: TestClient, auth_headers, path: str) -> None:
    skill = _create_skill(client, auth_headers)

    response = _write_file(client, auth_headers, skill["id"], path, "x")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_skill_package_requires_auth(client: TestClient, auth_headers) -> None:
    skill = _create_skill(client, auth_headers)

    assert client.get(f"/api/v1/admin/skills/{skill['id']}/files").status_code == 401
    assert (
        client.put(
            f"/api/v1/admin/skills/{skill['id']}/files",
            json={"path": "a.md", "content": "x"},
        ).status_code
        == 401
    )
    assert client.get(f"/api/v1/admin/skills/{skill['id']}/export").status_code == 401


def test_zip_import_and_export_roundtrip(client: TestClient, auth_headers) -> None:
    skill = _create_skill(client, auth_headers)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pkg/SKILL.md", "# 入口")
        archive.writestr("pkg/references/guide.md", "指南")
        archive.writestr("pkg/__MACOSX/._guide.md", "垃圾文件")

    imported = client.post(
        f"/api/v1/admin/skills/{skill['id']}/import",
        content=buffer.getvalue(),
        headers={**auth_headers, "Content-Type": "application/zip"},
    )
    assert imported.status_code == 200, imported.text
    assert [item["path"] for item in imported.json()] == ["SKILL.md", "references/guide.md"]

    exported = client.get(f"/api/v1/admin/skills/{skill['id']}/export", headers=auth_headers)
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert sorted(archive.namelist()) == ["SKILL.md", "references/guide.md"]
        assert archive.read("references/guide.md").decode("utf-8") == "指南"
        assert archive.getinfo("SKILL.md").date_time == (1980, 1, 1, 0, 0, 0)

    detail = client.get(f"/api/v1/admin/skills/{skill['id']}", headers=auth_headers)
    assert detail.json()["content"] == "# 入口"


def test_zip_import_rejects_binary(client: TestClient, auth_headers) -> None:
    skill = _create_skill(client, auth_headers)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", b"\xff\xfe\x00binary")

    response = client.post(
        f"/api/v1/admin/skills/{skill['id']}/import",
        content=buffer.getvalue(),
        headers={**auth_headers, "Content-Type": "application/zip"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert _list_files(client, auth_headers, skill["id"])["total"] == 0


def test_file_count_quota(
    client: TestClient, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings().model_copy(update={"skill_package_max_files": 2})
    monkeypatch.setattr(package_module, "get_settings", lambda: settings)
    skill = _create_skill(client, auth_headers)

    assert _write_file(client, auth_headers, skill["id"], "a.md", "a").status_code == 200
    assert _write_file(client, auth_headers, skill["id"], "b.md", "b").status_code == 200
    # 覆盖已有文件不占用新配额
    assert _write_file(client, auth_headers, skill["id"], "b.md", "b2").status_code == 200
    exceeded = _write_file(client, auth_headers, skill["id"], "c.md", "c")
    assert exceeded.status_code == 422
    assert exceeded.json()["code"] == "VALIDATION_ERROR"


def test_file_size_quota(client: TestClient, auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(
        update={"skill_package_max_file_bytes": 8, "skill_package_max_total_bytes": 10}
    )
    monkeypatch.setattr(package_module, "get_settings", lambda: settings)
    skill = _create_skill(client, auth_headers)

    assert _write_file(client, auth_headers, skill["id"], "small.md", "12345678").status_code == 200
    # 单文件超过 8 字节
    assert _write_file(client, auth_headers, skill["id"], "big.md", "123456789").status_code == 422
    # 单文件合规，但 8 + 5 字节超过总大小 10 字节
    assert _write_file(client, auth_headers, skill["id"], "more.md", "12345").status_code == 422


def test_delete_skill_cascades_files(client: TestClient, auth_headers) -> None:
    skill = _create_skill(client, auth_headers, content="入口")
    _write_file(client, auth_headers, skill["id"], "references/a.md", "a")

    assert (
        client.delete(f"/api/v1/admin/skills/{skill['id']}", headers=auth_headers).status_code
        == 204
    )

    with get_engine().connect() as conn:
        remaining = conn.execute(
            text("SELECT count(*) FROM skill_files WHERE skill_id = :skill_id"),
            {"skill_id": UUID(skill["id"])},
        ).scalar_one()
    assert remaining == 0


def test_tenant_reads_platform_skill_but_cannot_write_and_can_clone(
    client: TestClient, auth_headers, tenant_client
) -> None:
    created = _create_tenant(client, auth_headers)
    acme, tenant_headers = _tenant_client_with_headers(tenant_client)
    platform = _create_skill(client, auth_headers, content="产品级入口")
    _write_file(client, auth_headers, platform["id"], "references/p.md", "产品级资料")

    # 未授权前租户不可见
    invisible = acme.get(
        f"/api/v1/admin/skills/{platform['id']}", headers=tenant_headers
    )
    assert invisible.status_code == 404

    _grant_to_tenant(client, auth_headers, created["id"], "skill", platform["id"])

    listed = acme.get(f"/api/v1/admin/skills/{platform['id']}/files", headers=tenant_headers)
    assert listed.status_code == 200
    assert [item["path"] for item in listed.json()["items"]] == ["SKILL.md", "references/p.md"]

    forbidden = _write_file(acme, tenant_headers, platform["id"], "SKILL.md", "篡改")
    assert forbidden.status_code == 403
    assert (
        acme.delete(
            f"/api/v1/admin/skills/{platform['id']}/files",
            params={"path": "SKILL.md"},
            headers=tenant_headers,
        ).status_code
        == 403
    )

    cloned = acme.post(
        f"/api/v1/admin/skills/{platform['id']}/clone",
        json={"name": "租户副本"},
        headers=tenant_headers,
    )
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["tenant_id"] == created["id"]
    clone_id = cloned.json()["id"]

    clone_files = _list_files(acme, tenant_headers, clone_id)
    assert [item["path"] for item in clone_files["items"]] == ["SKILL.md", "references/p.md"]
    content = acme.get(
        f"/api/v1/admin/skills/{clone_id}/files/content",
        params={"path": "references/p.md"},
        headers=tenant_headers,
    )
    assert content.json()["content"] == "产品级资料"

    # 修改副本不影响产品级技能
    assert (
        _write_file(acme, tenant_headers, clone_id, "references/p.md", "租户资料").status_code
        == 200
    )
    platform_content = client.get(
        f"/api/v1/admin/skills/{platform['id']}/files/content",
        params={"path": "references/p.md"},
        headers=auth_headers,
    )
    assert platform_content.json()["content"] == "产品级资料"


def test_platform_cannot_clone(client: TestClient, auth_headers) -> None:
    skill = _create_skill(client, auth_headers)

    response = client.post(
        f"/api/v1/admin/skills/{skill['id']}/clone", json={}, headers=auth_headers
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_clone_duplicate_name_conflict(client: TestClient, auth_headers, tenant_client) -> None:
    tenant = _create_tenant(client, auth_headers)
    acme, tenant_headers = _tenant_client_with_headers(tenant_client)
    platform = _create_skill(client, auth_headers, name="平台技能")
    _write_file(client, auth_headers, platform["id"], "notes.md", "x")
    _grant_to_tenant(client, auth_headers, tenant["id"], "skill", platform["id"])

    first = acme.post(
        f"/api/v1/admin/skills/{platform['id']}/clone",
        json={"name": "同名副本"},
        headers=tenant_headers,
    )
    assert first.status_code == 201
    second = acme.post(
        f"/api/v1/admin/skills/{platform['id']}/clone",
        json={"name": "同名副本"},
        headers=tenant_headers,
    )
    assert second.status_code == 409
