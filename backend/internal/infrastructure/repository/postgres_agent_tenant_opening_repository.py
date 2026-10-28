"""平台智能体对租户开通关系的 PostgreSQL 仓储实现。"""

from typing import cast
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.entity.access import AgentTenantOpening
from internal.domain.entity.resource import Agent
from internal.domain.entity.tenant import Tenant
from internal.infrastructure.model.agent import AgentModel, AgentTenantOpeningModel
from internal.infrastructure.model.tenant import TenantModel


class PostgresAgentTenantOpeningRepository:
    """基于 SQLAlchemy 的开通关系仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def get(self, agent_id: UUID, tenant_id: UUID) -> AgentTenantOpening | None:
        """查询单条开通关系。"""
        row = self._session.scalar(
            select(AgentTenantOpeningModel).where(
                AgentTenantOpeningModel.agent_id == agent_id,
                AgentTenantOpeningModel.tenant_id == tenant_id,
            )
        )
        return self._to_entity(row) if row else None

    def open(self, agent_id: UUID, tenant_id: UUID, opened_by: UUID | None) -> AgentTenantOpening:
        """开通智能体；重复开通保持原开通时间并返回现有记录。"""
        self._session.execute(
            pg_insert(AgentTenantOpeningModel)
            .values(
                agent_id=agent_id,
                tenant_id=tenant_id,
                opened_by=opened_by,
            )
            .on_conflict_do_nothing(constraint="ux_agent_tenant_openings")
        )
        self._session.flush()
        opening = self.get(agent_id, tenant_id)
        if opening is None:
            # 唯一约束冲突后记录必然存在，此处仅用于满足类型收窄
            raise RuntimeError("开通关系写入失败")
        return opening

    def close(self, agent_id: UUID, tenant_id: UUID) -> bool:
        """关闭开通；返回是否存在并删除成功。"""
        result = self._session.execute(
            delete(AgentTenantOpeningModel).where(
                AgentTenantOpeningModel.agent_id == agent_id,
                AgentTenantOpeningModel.tenant_id == tenant_id,
            )
        )
        self._session.flush()
        return bool(cast(CursorResult, result).rowcount)

    def list_platform_agent_ids(self, agent_ids: list[UUID]) -> set[UUID]:
        """返回给定 id 中属于平台级智能体的部分。"""
        if not agent_ids:
            return set()
        rows = self._session.scalars(
            select(AgentModel.id).where(
                AgentModel.id.in_(agent_ids),
                AgentModel.tenant_id == PLATFORM_TENANT_ID,
            )
        ).all()
        return set(rows)

    def open_many(self, agent_ids: list[UUID], tenant_id: UUID, opened_by: UUID | None) -> None:
        """批量开通；已开通的保持原开通时间。"""
        if not agent_ids:
            return
        self._session.execute(
            pg_insert(AgentTenantOpeningModel)
            .values(
                [
                    {
                        "agent_id": agent_id,
                        "tenant_id": tenant_id,
                        "opened_by": opened_by,
                    }
                    for agent_id in agent_ids
                ]
            )
            .on_conflict_do_nothing(constraint="ux_agent_tenant_openings")
        )
        self._session.flush()

    def close_many(self, agent_ids: list[UUID], tenant_id: UUID) -> int:
        """批量关闭；返回实际删除的数量。"""
        if not agent_ids:
            return 0
        result = self._session.execute(
            delete(AgentTenantOpeningModel).where(
                AgentTenantOpeningModel.agent_id.in_(agent_ids),
                AgentTenantOpeningModel.tenant_id == tenant_id,
            )
        )
        self._session.flush()
        return int(cast(CursorResult, result).rowcount or 0)

    def sync_for_resource(
        self, agent_id: UUID, tenant_ids: set[UUID], opened_by: UUID | None
    ) -> None:
        """按给定租户集合同步开通关系，用于兼容旧的整资源授权接口。"""
        if tenant_ids:
            self._session.execute(
                delete(AgentTenantOpeningModel).where(
                    AgentTenantOpeningModel.agent_id == agent_id,
                    AgentTenantOpeningModel.tenant_id.not_in(tenant_ids),
                )
            )
        else:
            self._session.execute(
                delete(AgentTenantOpeningModel).where(AgentTenantOpeningModel.agent_id == agent_id)
            )
        if tenant_ids:
            self._session.execute(
                pg_insert(AgentTenantOpeningModel)
                .values(
                    [
                        {
                            "agent_id": agent_id,
                            "tenant_id": tenant_id,
                            "opened_by": opened_by,
                        }
                        for tenant_id in sorted(tenant_ids)
                    ]
                )
                .on_conflict_do_nothing(constraint="ux_agent_tenant_openings")
            )
        self._session.flush()

    def list_for_tenant(
        self,
        tenant_id: UUID,
        page: int,
        page_size: int,
        keyword: str | None,
        is_enabled: bool | None,
        opened_only: bool,
    ) -> tuple[list[tuple[Agent, AgentTenantOpening | None]], int]:
        """分页查询平台智能体及该租户的开通状态。"""
        stmt = (
            select(AgentModel, AgentTenantOpeningModel)
            .outerjoin(
                AgentTenantOpeningModel,
                and_(
                    AgentTenantOpeningModel.agent_id == AgentModel.id,
                    AgentTenantOpeningModel.tenant_id == tenant_id,
                ),
            )
            .where(AgentModel.tenant_id == PLATFORM_TENANT_ID)
        )
        if opened_only:
            stmt = stmt.where(AgentTenantOpeningModel.id.is_not(None))
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(AgentModel.name.ilike(pattern), AgentModel.description.ilike(pattern))
            )
        if is_enabled is not None:
            stmt = stmt.where(AgentModel.is_enabled.is_(is_enabled))

        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.execute(
            stmt.order_by(AgentModel.updated_at.desc(), AgentModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        items = [
            (
                self._to_agent(agent_row),
                self._to_entity(opening_row) if opening_row is not None else None,
            )
            for agent_row, opening_row in rows
        ]
        return items, int(total)

    def list_opened_tenants(
        self, agent_id: UUID, page: int, page_size: int, keyword: str | None
    ) -> tuple[list[tuple[Tenant, AgentTenantOpening]], int]:
        """分页查询已开通该智能体的租户。"""
        stmt = select(TenantModel, AgentTenantOpeningModel).join(
            AgentTenantOpeningModel,
            and_(
                AgentTenantOpeningModel.tenant_id == TenantModel.id,
                AgentTenantOpeningModel.agent_id == agent_id,
            ),
        )
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(TenantModel.name.ilike(pattern), TenantModel.code.ilike(pattern)))

        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.execute(
            stmt.order_by(AgentTenantOpeningModel.opened_at.desc(), TenantModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [
            (self._to_tenant(tenant_row), self._to_entity(opening_row))
            for tenant_row, opening_row in rows
        ], int(total)

    def get_platform_agent(self, agent_id: UUID) -> Agent | None:
        """查询平台级智能体，忽略平台角色的数据授权过滤。"""
        row = self._session.scalar(
            select(AgentModel).where(
                AgentModel.id == agent_id,
                AgentModel.tenant_id == PLATFORM_TENANT_ID,
            )
        )
        return self._to_agent(row) if row else None

    @staticmethod
    def _to_entity(row: AgentTenantOpeningModel) -> AgentTenantOpening:
        return AgentTenantOpening(
            id=row.id,
            agent_id=row.agent_id,
            tenant_id=row.tenant_id,
            opened_by=row.opened_by,
            opened_at=row.opened_at,
        )

    @staticmethod
    def _to_agent(row: AgentModel) -> Agent:
        return Agent(
            id=row.id,
            name=row.name,
            avatar_url=row.avatar_url,
            description=row.description,
            config=row.config,
            is_enabled=row.is_enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tenant_id=row.tenant_id,
        )

    @staticmethod
    def _to_tenant(row: TenantModel) -> Tenant:
        return Tenant(
            id=row.id,
            code=row.code,
            name=row.name,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
