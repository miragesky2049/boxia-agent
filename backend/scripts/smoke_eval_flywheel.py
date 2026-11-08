"""M4-d T-d9 真机冒烟：采样飞轮端到端（低分线上样本 → 看板 → 一键转评测集 → 评测批消费）。

前置：admin 8000 / user 8001（scripts/serve_noreload.py admin|user）与 celery worker
（celery -A internal.infrastructure.celery_app worker -Q rag --pool=solo）在跑。
用法（凭据走环境变量，脚本不落盘口令）：
    SMOKE_ADMIN_USER=xxx SMOKE_ADMIN_PASSWORD='yyy' SMOKE_CHAT_PASSWORD='zzz' \
        .venv/Scripts/python.exe scripts/smoke_eval_flywheel.py
校验：
1. judgeSampling（rate=1.0 + 必低分 rubric）四处同构回读并发布；
2. 对话后采样行进入 quality/summary 的 trend 与 low_score_items（含问句预览，
   同时证明 T-d9 跨租户可见性修复：采样行落对话租户仍可按应用归因透出）；
3. 低分清单 run_id 直接 from-run 转评测集（问句/终答回填）；
4. 以该数据集发起评测批，worker 真跑终态 completed 且报告消费了捕获用例；
5. 清理数据集/评估器（FK CASCADE 连带评测行），恢复采样关闭默认组并发布。
"""

import json
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ADMIN = "http://127.0.0.1:8000/api/v1/admin"
USER = "http://127.0.0.1:8001/api/v1/user"
USER_HOST = "e2etenant.localhost"
APP = "01a1b601-f0a9-73a5-8582-5f420732e565"
ADMIN_USER = os.environ.get("SMOKE_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "")
CHAT_USER = os.environ.get("SMOKE_CHAT_USER", "m4-chat")
CHAT_PASSWORD = os.environ.get("SMOKE_CHAT_PASSWORD", "")
if not ADMIN_PASSWORD or not CHAT_PASSWORD:
    raise SystemExit("缺少环境变量 SMOKE_ADMIN_PASSWORD / SMOKE_CHAT_PASSWORD")

# 判分口径由 rubric 强制：正常物理问句的回答不可能逐字含该串 → 采样必为低分
LOW_RUBRIC = "回答必须逐字包含字符串「紫云朵」，未包含则必须给 0 分；包含则给 10 分。"
QUESTION = "用一句话解释潮汐现象"


def _admin_client() -> httpx.Client:
    client = httpx.Client(base_url=ADMIN, timeout=30)
    r = client.post("/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        raise SystemExit(f"admin 登录失败 {r.status_code}: {r.text[:200]}")
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return client


def _chat_client() -> httpx.Client:
    client = httpx.Client(base_url=USER, timeout=180, headers={"Host": USER_HOST})
    r = client.post("/auth/login", json={"username": CHAT_USER, "password": CHAT_PASSWORD})
    if r.status_code != 200:
        raise SystemExit(f"user 登录失败 {r.status_code}: {r.text[:200]}")
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return client


def _put_sampling(admin: httpx.Client, sampling: dict) -> None:
    form = admin.get(f"/apps/{APP}/agent-config").json()
    form["judgeSampling"] = sampling
    r = admin.put(f"/apps/{APP}/agent-config", json=form)
    assert r.status_code == 200, f"PUT 失败 {r.status_code}: {r.text[:300]}"
    p = admin.post(f"/apps/{APP}/publish")
    assert p.status_code == 200, f"发布失败 {p.status_code}: {p.text[:200]}"


def _chat_once(chat: httpx.Client, message: str) -> str:
    frames: dict[str, list[dict]] = {}
    with chat.stream(
        "POST", f"/agents/{APP}/chatflow/run/stream", json={"message": message}
    ) as resp:
        resp.raise_for_status()
        current = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                current = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and current:
                frames.setdefault(current, []).append(json.loads(line.split(":", 1)[1]))
    assert "error" not in frames, f"对话出现 error 帧：{frames.get('error')}"
    assert frames["result"][-1]["content"], "对话答案为空"
    return frames["result"][-1]["run_id"]


def _wait_low_item(admin: httpx.Client, run_id: str, seconds: int) -> dict:
    """轮询质量看板，直到本次 run 的采样行出现在低分清单（worker 异步判定含 judge 耗时）。"""
    deadline = time.time() + seconds
    body: dict = {}
    while time.time() < deadline:
        r = admin.get(f"/apps/{APP}/quality/summary", params={"days": 7})
        assert r.status_code == 200, r.text
        body = r.json()
        hit = next((i for i in body["low_score_items"] if i["run_id"] == run_id), None)
        if hit:
            return hit
        time.sleep(3)
    raise SystemExit(f"{seconds}s 内低分清单未出现 run={run_id}，看板：{json.dumps(body, ensure_ascii=False)[:400]}")


def main() -> None:
    admin = _admin_client()
    chat = _chat_client()

    ds_id: str | None = None
    ev_id: str | None = None
    try:
        # 1. 采样必投必低分：rate=1.0 + 强制 rubric，回读校验四处同构
        #    （批末 review F2：开门动作必须在 try 内——半途失败也要走 finally 恢复关闭组，
        #    否则残留 rate=1.0 必低分配置，每次对话都调 judge 持续计费）
        _put_sampling(admin, {"enabled": True, "rate": 1.0, "judgeModel": "", "rubric": LOW_RUBRIC})
        back = admin.get(f"/apps/{APP}/agent-config").json()["judgeSampling"]
        assert back["enabled"] and back["rate"] == 1.0 and back["rubric"] == LOW_RUBRIC, back
        # 2. 看板出现低分行 + 趋势；采样行落对话租户，按应用归因可见（T-d9 修复点）
        run_id = _chat_once(chat, QUESTION)
        low = _wait_low_item(admin, run_id, 150)
        assert low["question"] == QUESTION, f"低分清单问句不符：{low}"
        assert low["score"] <= 5, f"强制低分 rubric 未生效：{low}"
        summary = admin.get(f"/apps/{APP}/quality/summary", params={"days": 7}).json()
        assert summary["window_days"] == 7 and len(summary["trend"]) == 7, summary["window_days"]
        assert sum(p["count"] for p in summary["trend"]) >= 1, summary["trend"]
        assert summary["runtime_samples"]["count"] >= 1, summary["runtime_samples"]
        print(f"[看板] run={run_id} 低分={low['score']} 窗口采样数={summary['runtime_samples']['count']}")

        # 3. 飞轮：低分清单 run_id 一键 from-run 转评测集
        ts = time.strftime("%m%d%H%M%S")
        ds = admin.post(
            "/eval/datasets",
            json={"application_id": APP, "name": f"飞轮冒烟-{ts}", "description": "T-d9 smoke"},
        )
        assert ds.status_code == 201, ds.text
        ds_id = ds.json()["id"]
        case = admin.post(f"/eval/datasets/{ds_id}/cases/from-run", json={"run_id": run_id})
        assert case.status_code == 201, case.text
        body = case.json()
        assert body["input"]["message"] == QUESTION, body
        assert body["expected"], f"from-run 未回填线上终答：{body}"
        print(f"[转评测集] case={body['id']} 问句回填OK expected={body['expected'][:20]}…")

        # 4. 评测批消费该用例（恒过规则评估器；worker 真跑图，终态 completed）
        ev = admin.post("/eval/evaluators", json={"name": f"飞轮冒烟恒过-{ts}", "type": "rule", "config": {}})
        assert ev.status_code == 201, ev.text
        ev_id = ev.json()["id"]
        versions = admin.get(f"/apps/{APP}/graph-versions").json()
        latest = max(v["version"] for v in versions)
        started = admin.post(
            "/eval/eval-runs",
            json={"dataset_id": ds_id, "graph_version": latest, "evaluator_ids": [ev_id], "concurrency": 2},
        )
        assert started.status_code == 201, started.text
        eval_run_id = started.json()["eval_run_id"]
        deadline = time.time() + 300
        detail: dict = {}
        while time.time() < deadline:
            d = admin.get(f"/eval/eval-runs/{eval_run_id}")
            assert d.status_code == 200, d.text
            detail = d.json()
            if detail["run"]["status"] != "running":
                break
            time.sleep(8)
        assert detail["run"]["status"] == "completed", f"评测批未终态/失败：{detail['run']}"
        assert detail["summary"]["total"] == 1, detail["summary"]
        assert detail["results"][0]["case_id"] == body["id"], detail["results"]
        print(f"[评测批] eval_run={eval_run_id} completed 消费用例={detail['summary']['total']} 通过={detail['summary']['passed']}")
    finally:
        # 5. 恢复采样关闭默认组优先（防半途失败残留持续计费配置），
        #    再清理冒烟数据（CASCADE 连带评测行）——删除失败显式报错不静默
        _put_sampling(admin, {"enabled": False, "rate": 0.1, "judgeModel": "", "rubric": ""})
        done = admin.get(f"/apps/{APP}/agent-config").json()["judgeSampling"]
        assert done["enabled"] is False and done["rubric"] == "", done
        if ds_id:
            assert admin.delete(f"/eval/datasets/{ds_id}").status_code == 204, f"数据集残留 {ds_id}"
        if ev_id:
            assert admin.delete(f"/eval/evaluators/{ev_id}").status_code == 204, f"评估器残留 {ev_id}"
    print("SMOKE PASS T-d9 飞轮：低分入看板→一键转评测集→评测批消费→清理恢复")


if __name__ == "__main__":
    main()
