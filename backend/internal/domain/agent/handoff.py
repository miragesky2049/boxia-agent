"""会话接管链语义（M4 PRD F14.9 / R15）：深度与去环判定纯函数，无 IO。

handoff_chain 存 conversation 行 JSONB 列，按接管顺序记录应用 id，归属应用为首元素
（如 ["M","B"] 表示 M→B 接管中）；归位（hand_back 伪工具 / 请求 handback）不属于
链追加，由应用层清空（active=NULL、链=[]）。

深度预算与委派链（application/apps/call_chain）对齐：顶层应答方（归属应用）不计入，
最多 3 次接管（owner+3 个应答应用），第 4 次切换拒绝。
"""

from __future__ import annotations

from typing import Any

MAX_HANDOFF_CHAIN_DEPTH = 3


def parse_handoff_chain(raw: Any) -> list[str]:
    """把 JSONB 列值统一解析为应用 id 字符串列表。

    容忍历史脏数据：非列表形态返回空链，列表内空项丢弃。
    """
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item]


def handoff_chain_error(chain: list[str], owner_id: str, target_id: str) -> str | None:
    """追加一次接管前的链校验；合法返回 None，非法返回通告文案（[error] 语义由上层拼接）。

    去环：目标已在链中（含归属应用）即乒乓移交，归位必须走 hand_back/handback 通道；
    深度：归属应用不计入预算，见模块 docstring。
    """
    normalized = chain or [owner_id]
    if target_id in normalized:
        return f"检测到接管循环：应用 {target_id} 已在接管链 {normalized} 中"
    if len(normalized) - 1 >= MAX_HANDOFF_CHAIN_DEPTH:
        return f"接管链深度超过上限 {MAX_HANDOFF_CHAIN_DEPTH}，请归位主助手后再切换"
    return None


def append_handoff_chain(chain: list[str], owner_id: str, target_id: str) -> list[str]:
    """返回追加目标后的新链（空链以归属应用为种子）；须先经 handoff_chain_error 放行。"""
    normalized = chain or [owner_id]
    return [*normalized, target_id]
