"""工具即调用的祖先链防护（0074 PRD F7.2 / M4-c PRD F14.2，20261107）。

workflow 即工具与 agent 即工具共用同一祖先链（workflow_chain）与预算：链内出现重复
应用 ID 即成环、链长达到 MAX_CALL_CHAIN_DEPTH 即拒绝。此前校验内联在
WorkflowToolService，M4-c T-c1 抽出共享，语义从"工作流链"泛化为"调用链"。
"""

from __future__ import annotations

# 调用链最大深度（PRD F7.2 / F14.2）：超限拒绝，防成本/递归失控
MAX_CALL_CHAIN_DEPTH = 3


def ensure_chain_allowed(
    chain: list[str],
    application_id: str,
    *,
    target_name: str,
    kind: str = "工作流",
) -> None:
    """校验把 application_id 追加到 chain 后不成环、不超深，否则抛 RuntimeError。

    Args:
        chain: 祖先应用 ID 列表（字符串形态）。
        application_id: 本次拟调用的目标应用 ID。
        target_name: 目标应用名，用于组装可读的拒绝信息。
        kind: 工具类型文案（"工作流" / "智能体"），决定异常措辞。

    Raises:
        RuntimeError: 目标已在链中（成环）或链长已达深度上限。
    """
    normalized = str(application_id)
    if normalized in chain:
        raise RuntimeError(f"检测到{kind}工具循环调用：「{target_name}」已在调用链 {chain} 中")
    if len(chain) >= MAX_CALL_CHAIN_DEPTH:
        raise RuntimeError(
            f"{kind}工具嵌套深度超过上限 {MAX_CALL_CHAIN_DEPTH}，请拆平流程或减少挂载"
        )
