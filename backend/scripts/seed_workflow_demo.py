"""用户端 Workflow 演示数据 seed（仅本地开发/验收使用，幂等）。

创建：平台市场三幅工作流应用（直出 / LLM / 人审）+ 演示租户 wfco +
leader 审批角色 + 两个最终用户（wf-owner 发起、wf-leader 审批）。

用法（backend 目录）：
    uv run python -m scripts.seed_workflow_demo

登录口令：租户管理员 wfco-admin / Tenant-password-123；
最终用户 wf-owner、wf-leader / User-password-123。
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi.testclient import TestClient
from sqlalchemy import text

from internal.infrastructure.config.settings import get_settings
from internal.infrastructure.model.database import dispose_engine, get_engine
from tests.helpers import (
    TENANT_ADMIN_PASSWORD,
    USER_PASSWORD,
    create_tenant,
    create_user,
    list_roles,
)
from tests.workflow_canvas import (
    build_start_end_canvas,
    build_start_human_end_canvas,
    build_start_llm_end_canvas,
)

PLATFORM_HOST = "platform.localhost"
TENANT_CODE = "wfco"

_APPS = (
    ("演示-直出工作流", build_start_end_canvas()),
    ("演示-LLM工作流", build_start_llm_end_canvas()),
    ("演示-人审工作流", build_start_human_end_canvas(assignee_role="leader", instructions="请核对发布内容后批准。")),
)


def _existing_app_id(name: str) -> str | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT id FROM application WHERE owner_type = 'platform' AND name = :n"),
            {"n": name},
        ).first()
    return str(row[0]) if row else None


def _platform_login(site: TestClient) -> dict[str, str]:
    settings = get_settings()
    resp = site.post(
        "/api/v1/admin/auth/login",
        json={
            "username": settings.admin_initial_username,
            "password": settings.admin_initial_password.get_secret_value(),
        },
    )
    assert resp.status_code == 200, f"平台管理员登录失败（检查 .env ADMIN_INITIAL_PASSWORD）：{resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed_platform_apps(admin_app) -> list[str]:
    app_ids: list[str] = []
    with TestClient(admin_app, base_url=f"http://{PLATFORM_HOST}") as site:
        headers = _platform_login(site)
        for name, canvas in _APPS:
            existing = _existing_app_id(name)
            if existing:
                print(f"[skip] 平台应用已存在：{name} ({existing})")
                app_ids.append(existing)
                continue
            resp = site.post(
                "/api/v1/admin/apps",
                json={"name": name, "description": "用户端 Workflow 演示应用", "flow_type": "workflow"},
                headers=headers,
            )
            assert resp.status_code == 201, resp.text
            app_id = resp.json()["application_id"]
            saved = site.put(
                f"/api/v1/admin/apps/{app_id}/graph",
                json={"graph": canvas, "changelog": "seed init"},
                headers=headers,
            )
            assert saved.status_code == 200, saved.text
            listed = site.post(f"/api/v1/admin/apps/{app_id}/listing", json={"listed": True}, headers=headers)
            assert listed.status_code == 200, listed.text
            with get_engine().begin() as conn:
                conn.execute(text("UPDATE application SET sale_mode = 2 WHERE id = :aid"), {"aid": app_id})
            print(f"[ok] 平台应用已上架：{name} ({app_id})")
            app_ids.append(app_id)

        tenant_exists = False
        with get_engine().connect() as conn:
            tenant_exists = conn.execute(
                text("SELECT 1 FROM tenants WHERE code = :c"), {"c": TENANT_CODE}
            ).first() is not None
        if not tenant_exists:
            create_tenant(site, headers, code=TENANT_CODE, name="Workflow 演示公司")
            print(f"[ok] 演示租户已创建：{TENANT_CODE}")
    return app_ids


def _seed_tenant_side(admin_app, app_ids: list[str]) -> None:
    def tenant_site(code: str) -> TestClient:
        return TestClient(admin_app, base_url=f"http://{code}.localhost")

    with tenant_site(TENANT_CODE) as site:
        site.__enter__()
        headers = _tenant_login(site)
        for app_id in app_ids:
            resp = site.post(
                "/api/v1/admin/marketplace/subscribe",
                json={"application_id": app_id},
                headers=headers,
            )
            assert resp.status_code in (200, 409), resp.text
            print(f"[{'ok' if resp.status_code == 200 else 'skip'}] 订阅应用 {app_id}")

        roles = list_roles(site, headers)
        if "leader" not in roles:
            created = site.post(
                "/api/v1/admin/roles",
                json={"code": "leader", "name": "审批人", "description": "演示人审角色"},
                headers=headers,
            )
            assert created.status_code == 201, created.text
            leader_role_id = created.json()["id"]
        else:
            leader_role_id = roles["leader"]["id"]
        viewer_role_id = roles["viewer"]["id"]

        existing_users = {u["username"] for u in _list_users(site, headers)}
        for username, role_id, display_name in (
            ("wf-owner", viewer_role_id, "工作流发起人"),
            ("wf-leader", leader_role_id, "工作流审批人"),
        ):
            if username in existing_users:
                print(f"[skip] 用户已存在：{username}")
                continue
            create_user(site, headers, username=username, role_id=role_id, display_name=display_name)
            print(f"[ok] 用户已创建：{username}")


def _tenant_login(site: TestClient) -> dict[str, str]:
    resp = site.post(
        "/api/v1/admin/auth/login",
        json={"username": f"{TENANT_CODE}-admin", "password": TENANT_ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, f"租户管理员登录失败：{resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _list_users(site: TestClient, headers: dict[str, str]) -> list[dict]:
    resp = site.get("/api/v1/admin/users", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["items"] if isinstance(body, dict) else body


def main() -> int:
    from web.app import create_app

    admin_app = create_app("admin")
    try:
        app_ids = _seed_platform_apps(admin_app)
        _seed_tenant_side(admin_app, app_ids)
        print(
            "\n演示账号（用户站点 http://wfco.localhost:5174）：\n"
            f"  发起：wf-owner / {USER_PASSWORD}\n"
            f"  审批：wf-leader / {USER_PASSWORD}\n"
            f"  管理：wfco-admin / {TENANT_ADMIN_PASSWORD}"
        )
        return 0
    finally:
        dispose_engine()


if __name__ == "__main__":
    raise SystemExit(main())
