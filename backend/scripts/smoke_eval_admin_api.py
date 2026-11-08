"""M4-d T-d4/T-d5 真机冒烟：走 HTTP 端点跑通评测批全链路。

前置：先启动 worker（另开进程，命令同 smoke_eval_batch.py），admin uvicorn 8000 在跑。
用法（SMOKE_ADMIN_USER/PASSWORD 为本地管理员凭据）：
    SMOKE_ADMIN_USER=xxx SMOKE_ADMIN_PASSWORD='yyy' .venv/Scripts/python.exe scripts/smoke_eval_admin_api.py
校验：登录→CRUD→发起批（clamp 6→4）→worker 跑完→报告/diff/quality-summary→捕获用例。
"""

import os
import time

import httpx

BASE = "http://127.0.0.1:8000/api/v1/admin"
# 接管冒烟主助手（e2etenant，图版本 4 已发布，T-d3 真机链路验证过）
APP = "01a1b601-f0a9-73a5-8582-5f420732e565"
GRAPH_VERSION = 4
# 凭据走环境变量注入，脚本不落盘口令；本地默认对应 .env 的开发账号
USERNAME = os.environ.get("SMOKE_ADMIN_USER", "admin")
PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "")


def _wait_done(client: httpx.Client, run_id: str, limit: int = 300) -> dict:
    deadline = time.time() + limit
    while time.time() < deadline:
        detail = client.get(f"/eval/eval-runs/{run_id}")
        detail.raise_for_status()
        if detail.json()["run"]["status"] in ("completed", "error"):
            return detail.json()
        time.sleep(10)
    raise SystemExit(f"评测批 {run_id} 超时未终态")


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=30)
    login = client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
    if login.status_code != 200:
        raise SystemExit(f"登录失败 {login.status_code}: {login.text[:200]}")
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    ds = client.post(
        "/eval/datasets",
        json={"application_id": APP, "name": f"T-d4真机集-{int(time.time())}", "description": "smoke"},
    )
    assert ds.status_code == 201, ds.text
    ds_id = ds.json()["id"]
    for msg in ("杭州明天天气怎么样？", "北京今天天气如何？"):
        r = client.post(f"/eval/datasets/{ds_id}/cases", json={"input": {"message": msg}})
        assert r.status_code == 201, r.text
    ev = client.post("/eval/evaluators", json={"name": "恒过", "type": "rule", "config": {}})
    assert ev.status_code == 201, ev.text
    ev_id = ev.json()["id"]

    started = client.post(
        "/eval/eval-runs",
        json={
            "dataset_id": ds_id, "graph_version": GRAPH_VERSION,
            "evaluator_ids": [ev_id], "concurrency": 6,
        },
    )
    assert started.status_code == 201, started.text
    run_a = started.json()["eval_run_id"]
    started2 = client.post(
        "/eval/eval-runs",
        json={"dataset_id": ds_id, "graph_version": GRAPH_VERSION, "evaluator_ids": [ev_id]},
    )
    assert started2.status_code == 201, started2.text
    run_b = started2.json()["eval_run_id"]

    report_a = _wait_done(client, run_a)
    assert report_a["run"]["status"] == "completed", report_a["run"]["error_message"]
    assert report_a["summary"]["passed"] == report_a["summary"]["total"], report_a["summary"]
    # start_batch 初始 progress 会被心跳覆盖，改校验批内实际执行了 2 case
    assert report_a["run"]["progress"]["done"] == 2, report_a["run"]["progress"]
    _wait_done(client, run_b)

    diff = client.get("/eval/eval-runs/diff", params={"run_a": run_a, "run_b": run_b})
    assert diff.status_code == 200 and len(diff.json()["items"]) == 2, diff.text

    quality = client.get(f"/apps/{APP}/quality/summary")
    assert quality.status_code == 200, quality.text
    qb = quality.json()
    assert qb["eval_batches"]["count"] >= 1 and qb["eval_batches"]["latest_pass_rate"] == 1.0, qb

    captured_run = report_a["results"][0]["run_id"]
    assert captured_run, "结果行缺 run_id，无法验证捕获链路"
    cap = client.post(f"/eval/datasets/{ds_id}/cases/from-run", json={"run_id": captured_run})
    assert cap.status_code == 201, cap.text
    assert cap.json()["input"]["message"], cap.json()

    listed = client.get("/eval/datasets", params={"application_id": APP})
    assert any(d["id"] == ds_id for d in listed.json()["items"])
    print(
        f"SMOKE PASS run_a={run_a} run_b={run_b} ds={ds_id} "
        f"捕获case={cap.json()['id']} 质量摘要={qb}"
    )


if __name__ == "__main__":
    main()
