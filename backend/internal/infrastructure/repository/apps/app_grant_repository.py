"""应用授权仓储：把 application 表适配成资源授权统一接口（app 不落 resource 表）。"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.access import AppGrantRow


class AppGrantRepository:
    """应用授权候选与汇总查询；授权写入仍由 resource_grants 仓储负责。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _select_rows(
        self, where: str, params: dict[str, Any], limit: int, offset: int
    ) -> list[AppGrantRow]:
        rows = self._session.execute(
            text(
                f"SELECT id, name, description, is_enabled, updated_at "
                f"FROM application WHERE {where} "
                f"ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        ).all()
        return [self._to_row(r) for r in rows]

    @staticmethod
    def _to_row(row: Any) -> AppGrantRow:
        mapping = row._mapping
        return AppGrantRow(
            id=mapping["id"],
            name=mapping["name"],
            description=mapping["description"] or "",
            tenant_id=PLATFORM_TENANT_ID,
            is_enabled=mapping["is_enabled"],
            updated_at=mapping["updated_at"],
        )

    @staticmethod
    def _grant_exists_condition(grant_state: str, grant_tenant_id: UUID | None) -> str:
        """授权状态过滤：granted 要求存在授权，ungranted 要求不存在。"""
        tenant_clause = ""
        if grant_tenant_id is not None:
            tenant_clause = " AND g.tenant_id = :grant_tenant_id"
        exists = (
            "EXISTS (SELECT 1 FROM resource_grants g "
            f"WHERE g.resource_type = 'app' AND g.resource_id = application.id{tenant_clause})"
        )
        return exists if grant_state == "granted" else f"NOT {exists}"

    def _base_conditions(
        self,
        keyword: str | None,
        is_enabled: bool | None,
        grant_state: str | None,
        grant_tenant_id: UUID | None,
    ) -> tuple[list[str], dict[str, Any]]:
        conditions = ["owner_type = 'platform'"]
        params: dict[str, Any] = {}
        if keyword:
            conditions.append("(name ILIKE :kw OR description ILIKE :kw)")
            params["kw"] = f"%{keyword}%"
        if is_enabled is not None:
            conditions.append("is_enabled = :is_enabled")
            params["is_enabled"] = is_enabled
        if grant_state is not None:
            conditions.append(self._grant_exists_condition(grant_state, grant_tenant_id))
            if grant_tenant_id is not None:
                params["grant_tenant_id"] = str(grant_tenant_id)
        return conditions, params

    def list_page(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        manageable_only: bool = False,
        grant_state: str | None = None,
        grant_tenant_id: UUID | None = None,
    ) -> tuple[list[AppGrantRow], int]:
        """分页查询可授权的应用；manageable_only 对应用无额外含义（应用均为产品级）。"""
        conditions, params = self._base_conditions(
            keyword, is_enabled, grant_state, grant_tenant_id
        )
        where = " AND ".join(conditions)
        total = (
            self._session.execute(
                text(f"SELECT COUNT(*) FROM application WHERE {where}"), params
            ).scalar()
            or 0
        )
        items = self._select_rows(where, params, page_size, (page - 1) * page_size)
        return items, int(total)

    def get(self, resource_id: UUID) -> AppGrantRow | None:
        """按主键查询产品级应用。"""
        row = self._session.execute(
            text(
                "SELECT id, name, description, is_enabled, updated_at FROM application "
                "WHERE owner_type = 'platform' AND id = :id"
            ),
            {"id": str(resource_id)},
        ).first()
        return self._to_row(row) if row else None

    def ids_exist(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中真实存在的产品级应用集合。"""
        if not ids:
            return set()
        rows = self._session.execute(
            text("SELECT id FROM application WHERE owner_type = 'platform' AND id = ANY(:ids)"),
            {"ids": [str(i) for i in ids]},
        ).all()
        return {r._mapping["id"] for r in rows}

    def ids_owned(self, ids: list[UUID]) -> set[UUID]:
        """应用由平台维护，可管理集合与 ids_exist 一致。"""
        return self.ids_exist(ids)

    def list_grantable(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        ids: list[UUID] | None = None,
    ) -> tuple[list[AppGrantRow], int]:
        """分页查询可授权给角色的应用。"""
        conditions, params = self._base_conditions(keyword, None, None, None)
        if ids is not None:
            if not ids:
                return [], 0
            conditions.append("id = ANY(:ids)")
            params["ids"] = [str(i) for i in ids]
        where = " AND ".join(conditions)
        total = (
            self._session.execute(
                text(f"SELECT COUNT(*) FROM application WHERE {where}"), params
            ).scalar()
            or 0
        )
        items = self._select_rows(where, params, page_size, (page - 1) * page_size)
        return items, int(total)

    def ids_grantable(self, ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中可授权给角色的应用集合。"""
        return self.ids_exist(ids)
