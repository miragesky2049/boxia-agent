"""用户端路由聚合：登录公开，其余接口统一要求最终用户身份。"""

from fastapi import APIRouter, Depends

from web.deps.auth import require_user
from web.user.routers import (
    agents_router,
    auth_router,
    chat_router,
    profile_router,
    workflow_router,
)

router = APIRouter(prefix="/user", tags=["user"])
router.include_router(auth_router)

protected_router = APIRouter(dependencies=[Depends(require_user)])
protected_router.include_router(profile_router)
protected_router.include_router(agents_router)
protected_router.include_router(chat_router)
protected_router.include_router(workflow_router)
router.include_router(protected_router)
