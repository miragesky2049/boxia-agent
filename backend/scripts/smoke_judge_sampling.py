"""M4-d T-d8 真机冒烟：线上采样 judge 端到端链路（配置→对话→投递→worker 判定→落库）。

前置：admin 8000 / user 8001（scripts/serve_noreload.py）与 celery worker
（celery -A internal.infrastructure.celery_app worker -Q rag --pool=solo）在跑；
docker 容器 postgres（boxia_agent 库）用于判定行核验。
用法（凭据走环境变量，脚本不落盘口令）：
    SMOKE_ADMIN_USER=xxx SMOKE_ADMIN_PASSWORD='yyy' .venv/Scripts/python.exe scripts/smoke_judge_sampling.py
校验：
1. rate=1.0 配置四处同构（GET readout 携键 / PUT 回读 / 发布快照生效）；
2. 对话收尾后 worker 落 eval_result(source=runtime_sample)：status/score/judge_usage 齐、
   ledger 有 node_id=judge_sampling 行（租户计费可见）；
3. rate=0.0 恒不投：同链路对话后无采样行；
4. 收尾恢复关闭默认组并发布。
"""

import json
import os
import subprocess
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
# 口令不落默认值（review P3-4）：缺失时报错退出，避免真机凭据进版本库
CHAT_PASSWORD = os.environ.get("SMOKE_CHAT_PASSWORD", "")
if not CHAT_PASSWORD:
    raise SystemExit("缺少环境变量 SMOKE_CHAT_PASSWORD")


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
    """GET 现表单 → 携 judgeSampling PUT 回（四处同构验证点）→ 发布。"""
    form = admin.get(f"/apps/{APP}/agent-config").json()
    assert "judgeSampling" in form, f"GET readout 缺 judgeSampling 键：{list(form)}"
    form["judgeSampling"] = sampling
    r = admin.put(f"/apps/{APP}/agent-config", json=form)
    assert r.status_code == 200, f"PUT 失败 {r.status_code}: {r.text[:300]}"
    back = admin.get(f"/apps/{APP}/agent-config").json()["judgeSampling"]
    assert back["enabled"] == sampling["enabled"] and back["rate"] == sampling["rate"], back
    p = admin.post(f"/apps/{APP}/publish")
    assert p.status_code == 200, f"发布失败 {p.status_code}: {p.text[:200]}"


def _chat_once(chat: httpx.Client, message: str) -> str:
    """跑一轮 SSE 对话，返回 result 帧 run_id（收尾正常即通过）。"""
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


def _psq(sql: str) -> str:
    out = subprocess.run(
        ["docker", "exec", "postgres", "psql", "-U", "postgres", "-d", "boxia_agent", "-tAc", sql],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if out.returncode != 0:
        raise SystemExit(f"psql 失败：{out.stderr[:200]}")
    return out.stdout.strip()


def _wait_sample_row(run_id: str, seconds: int) -> str:
    """轮询采样判定行（worker 异步执行，含 judge 调用耗时）。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        row = _psq(
            "SELECT status || '|' || score::text || '|' || COALESCE(judge_usage->>'total_tokens','0') "
            f"FROM eval_result WHERE run_id = '{run_id}' AND source = 'runtime_sample'"
        )
        if row:
            return row
        time.sleep(3)
    return ""


def main() -> None:
    admin = _admin_client()
    chat = _chat_client()

    # 场景1：rate=1.0 恒投 → worker 判定落库 + ledger 计量
    _put_sampling(admin, {"enabled": True, "rate": 1.0, "judgeModel": "", "rubric": ""})
    run_id = _chat_once(chat, "用一句话介绍光的折射")
    row = _wait_sample_row(run_id, 120)
    assert row, f"rate=1.0 已对话但 120s 内无采样行 run_id={run_id}（worker 未跑/投递断？）"
    status, score, tokens = row.split("|")
    assert status in ("pass", "fail") and int(score) >= 0, f"判定行异常：{row}"
    assert int(tokens) > 0, f"judge_usage 缺 token：{row}"
    ledger = _psq(
        "SELECT COUNT(*) FROM tenant_usage_ledger "
        f"WHERE run_id = '{run_id}' AND node_id = 'judge_sampling'"
    )
    assert ledger == "1", f"ledger 采样计量行缺失：{ledger}"
    print(f"[采样链路] run={run_id} 判定={status}/{score} judge_tokens={tokens} ledger=1")

    # 场景2：幂等——同 run 重复投递不再新增行（has_runtime_sample 探测）
    from internal.infrastructure.tasks.judge_sampling_tasks import judge_sampling

    dup_before = _psq("SELECT COUNT(*) FROM eval_result WHERE source='runtime_sample'")
    judge_sampling.delay(run_id)  # 模拟任务重投：worker 应探测跳过、零新增
    time.sleep(25)
    dup_after = _psq("SELECT COUNT(*) FROM eval_result WHERE source='runtime_sample'")
    assert dup_before == dup_after, f"重复投递产生新采样行：{dup_before} -> {dup_after}"
    print(f"[幂等] 重投后 runtime_sample 行数不变：{dup_after}")

    # 场景3：rate=0.0 恒不投
    _put_sampling(admin, {"enabled": True, "rate": 0.0})
    run_id2 = _chat_once(chat, "用一句话介绍光的衍射")
    assert not _wait_sample_row(run_id2, 25), f"rate=0.0 不应采样却有行 run_id={run_id2}"

    # 收尾：恢复关闭默认组并发布（不留全量采样配置过夜计费）
    _put_sampling(admin, {"enabled": False, "rate": 0.1})
    back = admin.get(f"/apps/{APP}/agent-config").json()["judgeSampling"]
    assert back["enabled"] is False, back
    print("SMOKE PASS T-d8 采样链路：rate=1.0 落库+计量 幂等重投不增行 rate=0.0 恒不投 恢复关闭")


if __name__ == "__main__":
    main()
