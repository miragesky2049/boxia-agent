"""管理端评测 schemas（M4-d F18.2/F18.4/F18.5）：数据集/用例/评估器/批任务入参契约。"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DatasetPayload(BaseModel):
    """创建评测数据集。"""

    application_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class DatasetUpdatePayload(BaseModel):
    """更新数据集基本信息（整行覆盖）。"""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class CasePayload(BaseModel):
    """新增/更新用例：input 为 {message, images?, inputs?}（直调侧仅消费这三个键）。"""

    input: dict[str, Any]
    expected: str | None = None
    expected_tool_calls: dict[str, Any] | None = None


class CaptureCasePayload(BaseModel):
    """从既有 run 捕获用例（F18.2 冷启动主通道）。"""

    run_id: UUID


class EvaluatorPayload(BaseModel):
    """创建评估器：rule 纯代码断言 / llm_judge 走唯一内核（F19.1）。"""

    name: str = Field(min_length=1, max_length=200)
    type: Literal["rule", "llm_judge"]
    config: dict[str, Any] = Field(default_factory=dict)


class EvaluatorUpdatePayload(BaseModel):
    """更新评估器（type 可改：库内条目语义修正，历史 eval_run 不受影响）。"""

    name: str = Field(min_length=1, max_length=200)
    type: Literal["rule", "llm_judge"]
    config: dict[str, Any] = Field(default_factory=dict)


class StartEvalRunPayload(BaseModel):
    """发起评测批：锁 dataset 归属应用的某个发布图版本。"""

    dataset_id: UUID
    graph_version: int = Field(gt=0)
    evaluator_ids: list[UUID] = Field(min_length=1)
    # 下限与服务侧 MIN_CONCURRENCY 一致：避免"传 1 得 2"的静默向上 clamp（批末 review#8）
    concurrency: int = Field(default=2, ge=2, le=8)
