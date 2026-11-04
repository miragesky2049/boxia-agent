"""权限目录一致性：0058 迁移种子 vs domain 目录、作用域分区、内置角色默认集合与库内种子。"""

import importlib.util
from pathlib import Path

from sqlalchemy import text

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.permission import (
    PERMISSION_BY_CODE,
    PERMISSION_CODES,
    PLATFORM_ADMIN_CODES,
    PLATFORM_ONLY_CODES,
    PLATFORM_SUPERADMIN_CODES,
    PLATFORM_VIEWER_CODES,
    TENANT_ADMIN_CODES,
    TENANT_ONLY_CODES,
    TENANT_SUPERADMIN_CODES,
    TENANT_VIEWER_CODES,
)
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork

_PLATFORM_CODES = (
    "menu:entitlements",
    "page:entitlements",
    "button:entitlement:manage",
    "button:resource:review",
)
_TENANT_CODES = (
    "menu:role-access",
    "page:role-access",
    "button:role-access:manage",
    "button:resource:create",
)


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0058_entitlement_permissions.py"
    )
    spec = importlib.util.spec_from_file_location("m0058", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_codes_in_catalog():
    assert set(_PLATFORM_CODES + _TENANT_CODES) <= set(PERMISSION_CODES)


def test_migration_permissions_match_catalog():
    """迁移 _PERMISSIONS 与 domain 目录逐字段一致，防止两侧漂移。"""
    module = _load_migration_module()
    rows = module._PERMISSIONS
    assert {row[0] for row in rows} == set(_PLATFORM_CODES + _TENANT_CODES)
    for code, name, category, action, sort_order, _desc in rows:
        item = PERMISSION_BY_CODE[code]
        assert (item.name, item.category, item.action, item.sort_order) == (
            name,
            category,
            action,
            sort_order,
        )


def test_scope_partition():
    for code in _PLATFORM_CODES:
        assert code in PLATFORM_ONLY_CODES
        assert code not in TENANT_ONLY_CODES
    for code in _TENANT_CODES:
        assert code in TENANT_ONLY_CODES
        assert code not in PLATFORM_ONLY_CODES


def test_platform_role_sets():
    for code in _PLATFORM_CODES:
        assert code in PLATFORM_SUPERADMIN_CODES
        assert code in PLATFORM_ADMIN_CODES
        assert code not in PLATFORM_VIEWER_CODES
    assert not PLATFORM_ADMIN_CODES & TENANT_ONLY_CODES
    assert not PLATFORM_SUPERADMIN_CODES & TENANT_ONLY_CODES


def test_tenant_role_sets():
    for code in _TENANT_CODES:
        assert code in TENANT_SUPERADMIN_CODES
        assert code in TENANT_ADMIN_CODES
        assert code not in TENANT_VIEWER_CODES
    assert not TENANT_ADMIN_CODES & PLATFORM_ONLY_CODES
    assert not TENANT_SUPERADMIN_CODES & PLATFORM_ONLY_CODES


def test_db_seeded_permissions_and_grants():
    """conftest 重播后：8 码在目录表内，且平台 admin 角色持有 menu:entitlements。"""
    uow = SqlAlchemyUnitOfWork()
    try:
        session = uow.session
        for code in _PLATFORM_CODES + _TENANT_CODES:
            row = session.execute(
                text("SELECT id FROM permission_resources WHERE code = :code"),
                {"code": code},
            ).first()
            assert row is not None, f"权限码未入库：{code}"
        granted = session.execute(
            text(
                "SELECT 1 FROM role_permissions rp "
                "JOIN roles r ON r.id = rp.role_id "
                "JOIN permission_resources p ON p.id = rp.permission_id "
                "WHERE r.tenant_id = :platform AND r.code = 'admin' "
                "AND p.code = 'menu:entitlements'"
            ),
            {"platform": str(PLATFORM_TENANT_ID)},
        ).first()
        assert granted is not None
    finally:
        uow.close()
