"""用户端接口模块：按资源/职责拆分。"""

from web.user.routers.agents import router as agents_router
from web.user.routers.auth import router as auth_router
from web.user.routers.chat import router as chat_router
from web.user.routers.profile import router as profile_router
from web.user.routers.workflow import router as workflow_router

__all__ = [
    "agents_router",
    "auth_router",
    "chat_router",
    "profile_router",
    "workflow_router",
]
