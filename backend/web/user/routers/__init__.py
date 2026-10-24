"""用户端接口模块：按资源/职责拆分。"""

from web.user.routers.profile import router as profile_router

__all__ = ["profile_router"]
