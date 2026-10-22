"""智能体 ORM 模型与关联表。"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String, Table, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from internal.infrastructure.model.base import Base

agent_tools = Table(
    "agent_tools",
    Base.metadata,
    Column("agent_id", BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("tool_id", BigInteger, ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True),
)

agent_skills = Table(
    "agent_skills",
    Base.metadata,
    Column("agent_id", BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", BigInteger, ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
)


class AgentModel(Base):
    """agents 表。"""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
