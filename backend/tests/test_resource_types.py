"""资源类型常量单一来源校验：domain 定义、ORM CHECK 一致、无历史遗留类型。"""

import re

from internal.domain.entity.access import (
    APP_RESOURCE_TYPE,
    RESOURCE_TABLE_TYPES,
    RESOURCE_TYPES,
)
from internal.infrastructure.model.access import ResourceGrantModel


def _orm_check_types() -> set[str]:
    """取 ORM 中 ck_resource_grants_type 的字面量类型集合。"""
    constraints = [
        constraint.sqltext.text
        for constraint in ResourceGrantModel.__table__.constraints
        if constraint.name == "ck_resource_grants_type"
    ]
    assert len(constraints) == 1, "ck_resource_grants_type 必须且只能声明一次"
    return set(re.findall(r"'([^']+)'", constraints[0]))


def test_domain_types_cover_expected_set():
    """domain 为唯一来源：五类资源，应用类型不落在 resource 表。"""
    assert set(RESOURCE_TYPES) == {"tool", "skill", "prompt", "knowledge", "app"}
    assert RESOURCE_TYPES == (*RESOURCE_TABLE_TYPES, APP_RESOURCE_TYPE)
    assert APP_RESOURCE_TYPE not in RESOURCE_TABLE_TYPES


def test_orm_check_matches_domain():
    """ORM CHECK 文案必须与 domain 类型清单完全对应，避免与迁移 DDL 漂移。"""
    assert _orm_check_types() == set(RESOURCE_TYPES)


def test_no_legacy_types():
    """0037 已 DROP agents/components，历史类型不得再出现在授权类型清单中。"""
    assert "agent" not in RESOURCE_TYPES
    assert "component" not in RESOURCE_TYPES
    assert "agent" not in _orm_check_types()
    assert "component" not in _orm_check_types()
