"""用户端接口模块：按资源/职责拆分。"""

from web.user.routers.agent_run import router as agent_run_router
from web.user.routers.agents import router as agents_router
from web.user.routers.auth import router as auth_router
from web.user.routers.profile import router as profile_router
from web.user.routers.workflow_runs import router as workflow_runs_router

__all__ = [
    "agents_router",
    "agent_run_router",
    "auth_router",
    "profile_router",
    "workflow_runs_router",
]
