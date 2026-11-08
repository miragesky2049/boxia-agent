"""M4-d T-d7 真机冒烟：运行时质量门（重生链路 + 验收 7 fail-open）。

前置：admin uvicorn 8000 与 user uvicorn 8001 在跑；应用 A「接管冒烟主助手」
（e2etenant，画布 agent_loop 通道，T-d4 评测冒烟同应用）。
用法（凭据走环境变量，脚本不落盘口令）：
    SMOKE_ADMIN_USER=xxx SMOKE_ADMIN_PASSWORD='yyy' .venv/Scripts/python.exe scripts/smoke_quality_gate.py
校验：
1. admin GET/PUT agent-config 携 qualityGate（四处同构：passScore=10 必不过 → 观察重生）；
2. 用户端 SSE：judge 帧逐判定透出、result 帧与门关态差异仅 additive judge 键；
3. judgeModel 指向不存在模型 → judge 调用异常 fail-open（score=None/error=true）且对话正常收尾；
4. 收尾恢复门关闭默认组。
"""

import json
import os
import time

import httpx

ADMIN = "http://127.0.0.1:8000/api/v1/admin"
# 用户端强制租户子域名（Host 决定租户解析）；命令行 Python 不解析 *.localhost，
# 连接走 127.0.0.1、显式 Host 头给中间件做子域名租户判定
USER = "http://127.0.0.1:8001/api/v1/user"
USER_HOST = "e2etenant.localhost"
APP = "01a1b601-f0a9-73a5-8582-5f420732e565"
ADMIN_USER = os.environ.get("SMOKE_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "")
# e2etenant 用户端对话账号（M4-a 冒烟沿用）
CHAT_USER = os.environ.get("SMOKE_CHAT_USER", "m4-chat")
CHAT_PASSWORD = os.environ.get("SMOKE_CHAT_PASSWORD", "M4chat-2026!")


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


def _put_gate(admin: httpx.Client, gate: dict) -> None:
    """GET 现表单 → 携 qualityGate PUT 回 → 发布（应用 A 已有发布版，不发布用户端跑旧版）。"""
    form = admin.get(f"/apps/{APP}/agent-config").json()
    assert "qualityGate" in form, f"GET readout 缺 qualityGate 键：{list(form)}"
    form["qualityGate"] = gate
    r = admin.put(f"/apps/{APP}/agent-config", json=form)
    assert r.status_code == 200, f"PUT 失败 {r.status_code}: {r.text[:300]}"
    back = admin.get(f"/apps/{APP}/agent-config").json()["qualityGate"]
    assert back["enabled"] == gate["enabled"] and back["passScore"] == gate.get("passScore", 7), back
    p = admin.post(f"/apps/{APP}/publish")
    assert p.status_code == 200, f"发布失败 {p.status_code}: {p.text[:200]}"


def _stream_chat_once(chat: httpx.Client, message: str) -> dict[str, list[dict]]:
    """跑一轮 SSE 对话，按帧名归组收集 payload（新会话，避免历史干扰 judge 评分）。"""
    frames: dict[str, list[dict]] = {}
    with chat.stream(
        "POST", f"/agents/{APP}/chatflow/run/stream", json={"message": message}
    ) as resp:
        resp.raise_for_status()
        current_event = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and current_event:
                frames.setdefault(current_event, []).append(json.loads(line.split(":", 1)[1]))
    return frames


def _assert_gate_open_stream(frames: dict[str, list[dict]], label: str) -> dict:
    assert "error" not in frames, f"{label}：对话出现 error 帧 {frames.get('error')}"
    judge_frames = frames.get("judge", [])
    result = frames["result"][-1]
    assert judge_frames, f"{label}：门开启但无 judge 帧"
    assert "judge" in result, f"{label}：result 帧缺 judge 键 {list(result)}"
    verdict = result["judge"]
    assert verdict["attempts"] == len(judge_frames), (
        f"{label}：judge 帧数 {len(judge_frames)} 与终判 attempts {verdict['attempts']} 不一致"
    )
    print(f"[{label}] judge帧={judge_frames} result.judge={verdict}")
    return verdict


def main() -> None:
    admin = _admin_client()
    chat = _chat_client()

    # 场景1：passScore=10 必不过 → critique 追加重生成型（maxRegen=1 → 终判 attempts=2）
    # rubric 苛刻到单句回答必不满足（表格+出处），稳定压低 judge 分触发重生
    _put_gate(
        admin,
        {
            "enabled": True,
            "passScore": 10,
            "maxRegen": 1,
            "rubric": "满分要求：回答必须包含 markdown 表格与至少两条带 URL 的文献出处；缺任一项必须扣到 9 分以下",
        },
    )
    frames = _stream_chat_once(chat, "用一句话介绍光合作用")
    verdict = _assert_gate_open_stream(frames, "重生链路")
    assert verdict["attempts"] == 2, f"未观察到重生（attempts={verdict['attempts']}，judge 两轮都给了满分？）"
    assert frames["result"][-1]["content"], "重生后答案为空"

    # 场景2（验收 7）：judgeModel 不存在 → judge 调用异常 fail-open，带 error 标记且对话正常
    _put_gate(
        admin,
        {"enabled": True, "passScore": 7, "maxRegen": 1, "judgeModel": "no-such-model-xyz"},
    )
    frames2 = _stream_chat_once(chat, "用一句话介绍蒸腾作用")
    verdict2 = _assert_gate_open_stream(frames2, "fail-open")
    assert verdict2.get("error") is True and verdict2["score"] is None, f"fail-open 标记缺失：{verdict2}"
    assert verdict2["attempts"] == 1, f"judge 异常不应触发重生：{verdict2}"
    assert frames2["result"][-1]["content"], "fail-open 后原答案未放行"

    # 场景3：恢复关闭态 → 帧序列回到基线（无 judge 帧与 judge 键）
    _put_gate(admin, {"enabled": False})
    frames3 = _stream_chat_once(chat, "用一句话介绍呼吸作用")
    assert "judge" not in frames3, "门已关闭仍出现 judge 帧"
    assert "judge" not in frames3["result"][-1], "门已关闭 result 帧仍带 judge 键"

    print("SMOKE PASS T-d7 质量门：重生=2次判定 fail-open=标记透出 门关态=基线一致")


if __name__ == "__main__":
    main()
