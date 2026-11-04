"""参数化资源仓储：按 type 隔离作用域，非法类型拒绝，tools 等价 resource_repo('tool')。"""

import pytest

from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork

_CONFIG = {"url": "https://example.com/api", "method": "GET", "description": "类型隔离用例"}


def _uow() -> SqlAlchemyUnitOfWork:
    """超级管理员视角：关闭角色过滤，否则平台资源无授权不可见。"""
    uow = SqlAlchemyUnitOfWork()
    uow.apply_scope((), apply_role_filter=False)
    return uow


def test_platform_scoped_types_are_isolated():
    """平台作用域分别创建 skill/prompt/knowledge，各类型 list_page 互不可见。"""
    uow = _uow()
    try:
        for resource_type in ("skill", "prompt", "knowledge"):
            uow.resource_repo(resource_type).create(
                {"name": f"平台{resource_type}", "config": _CONFIG}
            )
        uow.commit()
        for resource_type in ("skill", "prompt", "knowledge"):
            items, total = uow.resource_repo(resource_type).list_page(
                page=1, page_size=10, keyword=None, is_enabled=None
            )
            assert total == 1, f"{resource_type} 应只看到自己的 1 条"
            assert {item.type for item in items} == {resource_type}
    finally:
        uow.rollback()
        uow.close()


def test_cross_type_lookup_misses():
    """创建 skill 后用 tool 作用域仓储查询不可见。"""
    uow = _uow()
    try:
        created = uow.resource_repo("skill").create({"name": "仅技能可见", "config": _CONFIG})
        uow.commit()
        assert uow.resource_repo("tool").get(created.id) is None
        assert uow.resource_repo("tool").ids_exist([created.id]) == set()
        assert uow.resource_repo("skill").get(created.id) is not None
    finally:
        uow.rollback()
        uow.close()


def test_resource_repo_rejects_app_type():
    """app 不落 resource 表，resource_repo('app') 必须拒绝。"""
    uow = _uow()
    try:
        with pytest.raises(ValueError):
            uow.resource_repo("app")
    finally:
        uow.close()


def test_tools_equivalent_to_resource_repo_tool():
    """uow.tools 与 resource_repo('tool') 结果集一致。"""
    uow = _uow()
    try:
        uow.tools.create({"name": "旧入口工具", "config": _CONFIG})
        uow.commit()
        tools_ids = {item.id for item in uow.tools.list_page(1, 10, None, None)[0]}
        repo_ids = {item.id for item in uow.resource_repo("tool").list_page(1, 10, None, None)[0]}
        assert tools_ids == repo_ids and tools_ids
    finally:
        uow.rollback()
        uow.close()


def test_update_rejects_invalid_type():
    """update 不允许把类型改成 resource 表之外的值。"""
    uow = _uow()
    try:
        created = uow.tools.create({"name": "类型校验工具", "config": _CONFIG})
        uow.commit()
        with pytest.raises(ValueError):
            uow.tools.update(created.id, {"type": "app"})
        uow.rollback()
        assert uow.tools.get(created.id) is not None
    finally:
        uow.close()
