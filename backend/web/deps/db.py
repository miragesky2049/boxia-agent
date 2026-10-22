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


UowDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_uow)]
