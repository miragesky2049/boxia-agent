"""Visibility 枚举与 visibility_filter 单元测试。"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from internal.domain.entity.access import AccessScope
from internal.domain.entity.visibility import Visibility
from internal.infrastructure.repository.visibility_filters import visibility_filter


class _Base(DeclarativeBase):
    pass


class FakeAppModel(_Base):
    __tablename__ = "fake_app"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tenant_group_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    creator_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    visibility: Mapped[str] = mapped_column(String(32), default="private")


def test_visibility_enum_values():
    assert Visibility.PRIVATE.value == "private"
    assert Visibility.TENANT.value == "tenant"
    assert Visibility.TENANT_GROUP.value == "tenant_group"
    assert Visibility.WHITELIST.value == "whitelist"
    assert Visibility.default() == Visibility.PRIVATE


def test_visibility_filter_builds_without_error():
    """表达式能正常生成 SQL 字符串即可，不实际查库。"""
    tenant_id = uuid4()
    user_id = uuid4()
    scope = AccessScope(
        tenant_id=tenant_id,
        role_ids=(uuid4(),),
        user_id=user_id,
        tenant_group_id=uuid4(),
    )

    expr = visibility_filter("app", FakeAppModel, scope)
    sql = str(expr)
    # 四种 visibility 分支都应出现在 SQL 中（值用绑定参数，按 visibility = 出现次数计）
    assert sql.count("fake_app.visibility =") == 4


def test_visibility_filter_fail_closed_without_tenant():
    """无租户上下文时，所有资源不可见。"""
    scope = AccessScope(tenant_id=None, role_ids=())
    expr = visibility_filter("app", FakeAppModel, scope)
    # 应返回 false()
    assert "false" in str(expr).lower()
