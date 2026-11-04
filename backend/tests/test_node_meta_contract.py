"""节点元数据契约测试（E5）：防止后端元数据、枚举、handler、前端控件之间漂移。

新增节点类型时的预期行为：
1. 在 ``node_meta.py`` 登记元数据；
2. 在 ``NodeType`` 增加枚举值；
3. 在 ``domain/graph/nodes/`` 注册 handler；
4. 若引入新的 ``field_type``，同步前端 ``FieldControl`` 的 switch 分支。

任何一步漏做都会让本文件的断言失败。
"""

from __future__ import annotations

import re

from internal.domain.canvas.node_meta import list_node_metas
from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.nodes import get_node_handler, list_registered_types

# 仅存在于 NodeType 枚举、当前不对前端暴露的历史类型。
# 新增枚举时必须显式决定：补元数据，或追加到本白名单并说明原因。
LEGACY_ENUM_WITHOUT_META: frozenset[str] = frozenset(
    {
        "11",  # VARIABLE 旧版变量节点
        "37",  # QUERY_MESSAGE_LIST
        "40",  # VARIABLE_ASSIGN，保留 handler 兼容历史画布但不在节点库展示
    }
)

# 已注册 handler 但不需要在节点库展示的类型。
LEGACY_HANDLER_WITHOUT_META: frozenset[str] = frozenset()

ALLOWED_CATEGORIES: frozenset[str] = frozenset(
    {
        "basic", "ai", "plugin", "workflow", "logic", "io", "control",
        "knowledge", "component", "conversation", "history", "message", "misc",
        "database", "memory", "image", "media",
    }
)

# 与 AppEditPage FieldControl 的 switch 分支保持一致。
ALLOWED_FIELD_TYPES: frozenset[str] = frozenset(
    {
        "text",
        "textarea",
        "number",
        "boolean",
        "select",
        "code_editor",
        "parameter_list",
        "tool_list",
        "case_list",
        "model_picker",
        "key_value_list",
        "intent_list",
    }
)


def _metas():
    return list_node_metas()


def test_meta_type_code_is_declared_in_enum() -> None:
    enum_values = {item.value for item in NodeType}
    unknown = sorted({m.type_code for m in _metas()} - enum_values)
    assert not unknown, f"元数据引用了 NodeType 中不存在的 type_code: {unknown}"


def test_meta_type_code_and_type_key_unique() -> None:
    metas = _metas()
    codes = [m.type_code for m in metas]
    keys = [m.type_key for m in metas]
    assert len(codes) == len(set(codes)), "type_code 重复"
    assert len(keys) == len(set(keys)), "type_key 重复"


def test_every_enum_type_is_exposed_or_whitelisted() -> None:
    exposed = {m.type_code for m in _metas()}
    missing = sorted({item.value for item in NodeType} - exposed - LEGACY_ENUM_WITHOUT_META)
    assert not missing, f"新增枚举未登记元数据，也未加入 LEGACY_ENUM_WITHOUT_META: {missing}"


def test_every_available_type_has_handler() -> None:
    handlers = set(list_registered_types())
    missing = sorted({m.type_code for m in _metas() if m.available} - handlers)
    assert not missing, f"可用节点未注册 handler，试运行将抛 KeyError: {missing}"


def test_unavailable_nodes_explain_reason() -> None:
    for meta in _metas():
        if not meta.available:
            assert meta.unavailable_reason, (
                f"{meta.type_key} 标记为不可用但未填写 unavailable_reason"
            )


def test_every_handler_is_exposed_or_whitelisted() -> None:
    exposed = {m.type_code for m in _metas()}
    undocumented = sorted(set(list_registered_types()) - exposed - LEGACY_HANDLER_WITHOUT_META)
    assert not undocumented, f"新增 handler 未登记元数据，前端节点库看不到: {undocumented}"


def test_display_fields_are_complete() -> None:
    for meta in _metas():
        assert meta.title, f"{meta.type_key} 缺少 title"
        assert meta.icon, f"{meta.type_key} 缺少 icon"
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", meta.color), (
            f"{meta.type_key} color 不是 6 位十六进制: {meta.color}"
        )
        assert meta.category in ALLOWED_CATEGORIES, (
            f"{meta.type_key} category 不在约定集合内: {meta.category}"
        )


def test_next_recommendations_reference_existing_type_keys() -> None:
    known = {m.type_key for m in _metas()}
    for meta in _metas():
        dangling = sorted(set(meta.next_recommendations) - known)
        assert not dangling, f"{meta.type_key} 推荐了下游不存在的 type_key: {dangling}"


def test_config_field_types_supported_by_frontend() -> None:
    for meta in _metas():
        for config_field in meta.config_fields:
            assert config_field.field_type in ALLOWED_FIELD_TYPES, (
                f"{meta.type_key}.{config_field.name} 使用了前端未实现的 field_type: "
                f"{config_field.field_type}"
            )


def test_config_field_names_unique_within_node() -> None:
    for meta in _metas():
        names = [config_field.name for config_field in meta.config_fields]
        duplicated = sorted({name for name in names if names.count(name) > 1})
        assert not duplicated, f"{meta.type_key} 配置字段重名: {duplicated}"


def test_capability_semantics() -> None:
    by_key = {m.type_key: m for m in _metas()}
    assert by_key["start"].capabilities.deletable is False, "开始节点不允许删除"
    for key in ("comment", "note"):
        caps = by_key[key].capabilities
        assert caps.runnable is False, f"{key} 便签节点不应参与执行"
        assert caps.has_outputs is False, f"{key} 便签节点不应有输出"
    subgraph_keys = {k for k, m in by_key.items() if m.capabilities.has_subgraph}
    assert subgraph_keys == {"loop", "batch", "subworkflow"}, (
        f"子图节点集合发生变化: {sorted(subgraph_keys)}"
    )


def test_note_node_has_noop_handler() -> None:
    assert NodeType.NOTE.value == "7"
    handler = get_node_handler(NodeType.NOTE.value)
    assert handler.type_name == NodeType.NOTE.value


def test_api_payload_shape_matches_frontend_types() -> None:
    from dataclasses import asdict

    for meta in _metas():
        payload = asdict(meta)
        assert {"type_code", "type_key", "icon", "subtitle_hint", "next_recommendations"} <= payload.keys()
        assert set(payload["capabilities"]) == {
            "runnable",
            "copyable",
            "deletable",
            "has_subgraph",
            "has_outputs",
        }
        for config_field in payload["config_fields"]:
            assert "group" in config_field
