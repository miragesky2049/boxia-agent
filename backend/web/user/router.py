"""用户端路由聚合：登录公开，其余接口统一要求最终用户身份。"""

from fastapi import APIRouter, Depends

from web.deps.auth import require_user
from web.user.routers import agent_run_router, agents_router, auth_router, profile_router

router = APIRouter(prefix="/user", tags=["user"])
router.include_router(auth_router)

protected_router = APIRouter(dependencies=[Depends(require_user)])
protected_router.include_router(profile_router)
protected_router.include_router(agents_router)
protected_router.include_router(agent_run_router)
router.include_router(protected_router)
