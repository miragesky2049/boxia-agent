"""数据库工作单元依赖。"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends

from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from web.deps.tenant import RequestContextDep


def get_uow(context: RequestContextDep) -> Iterator[SqlAlchemyUnitOfWork]:
    """每个请求一个工作单元，并按当前作用域构造仓储；异常回滚，结束关闭。"""
    uow = SqlAlchemyUnitOfWork(tenant_id=context.tenant_id)
    try:
        yield uow
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()


# DDD 五期决策：UowDep 在 web 边界保持具体 SqlAlchemyUnitOfWork 类型（而非 UnitOfWork Protocol）。
# 理由：8 个 router 与 apps_services 组合根工厂需要 `.session` 做 session-per-repo 装配，
# Protocol 不暴露 session；组合根本就允许点名具体类，此处不视为依赖违规。
UowDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_uow)]
