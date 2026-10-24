"""用户端路由聚合：统一前缀与鉴权，业务接口放在 routers/ 下。"""

from fastapi import APIRouter, Depends

from web.deps.auth import require_user
from web.user.routers import profile_router

router = APIRouter(
    prefix="/user",
    tags=["user"],
    dependencies=[Depends(require_user)],
)
router.include_router(profile_router)
