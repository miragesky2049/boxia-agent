"""WorkflowState：langgraph state schema + reducer。

核心设计：
- node_outputs: {block_id: {field: value}}，所有节点输出按节点 id 隔离
- globals: 全局变量，VariableAssign / SetVariable 写入
- 并行分支汇合、batch 聚合靠 reducer 自动合并，不丢数据
"""

from __future__ import annotations

from typing import Any, TypedDict


def _merge_dict(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """字典合并 reducer：right 覆盖 left，用于 node_outputs / globals。"""
    result = dict(left or {})
    result.update(right or {})
    return result


class WorkflowState(TypedDict, total=False):
    """langgraph state schema。

    字段说明：
    - input: 工作流入参（START 节点定义的 inputParameters）
    - node_outputs: 每个节点的输出 {block_id: {field: value}}
    - globals: 全局变量（VariableAssign 写入）
    - variables: 应用变量作用域（运行期写入仍合并进 globals，见 EvalContext）
    - system: 只读系统变量（USER_INPUT / USER_ID / RUN_ID 等）
    - env: 运行时环境（tenant_id / user_id / run_id / thread_id）
    - output: 最终输出（END 节点写入）
    - errors: 节点错误收集（settingOnError 时写入）
    """

    input: dict[str, Any]
    node_outputs: dict[str, dict[str, Any]]
    globals: dict[str, Any]
    variables: dict[str, Any]
    system: dict[str, Any]
    env: dict[str, Any]
    output: dict[str, Any]
    errors: dict[str, str]


# 导出 reducer，供 Compiler 挂载到 StateGraph
merge_dict = _merge_dict
