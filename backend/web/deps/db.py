"""数据库工作单元依赖。"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends

from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork


def get_uow() -> Iterator[SqlAlchemyUnitOfWork]:
    """每个请求一个工作单元，异常回滚，结束关闭。"""
    uow = SqlAlchemyUnitOfWork()
    try:
        yield uow
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()


UowDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_uow)]
