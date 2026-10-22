"""管理端受保护路由聚合。"""

from fastapi import APIRouter, Depends

from web.admin.agents import router as agents_router
from web.admin.audit_logs import router as audit_logs_router
from web.admin.components import router as components_router
from web.admin.prompts import router as prompts_router
from web.admin.skills import router as skills_router
from web.admin.tools import router as tools_router
from web.admin.users import router as users_router
from web.deps.auth import require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
router.include_router(agents_router)
router.include_router(skills_router)
router.include_router(tools_router)
router.include_router(components_router)
router.include_router(prompts_router)
router.include_router(users_router)
router.include_router(audit_logs_router)
