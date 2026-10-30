"""管理端受保护路由聚合。"""

from fastapi import APIRouter, Depends

from web.admin.routers.admin_users import router as admin_users_router
from web.admin.routers.applies import router as applies_router
from web.admin.routers.apps_admin import router as apps_admin_router
from web.admin.routers.audit_logs import router as audit_logs_router
from web.admin.routers.context import router as context_router
from web.admin.routers.departments import router as departments_router
from web.admin.routers.documents import router as documents_router
from web.admin.routers.employments import router as employments_router
from web.admin.routers.grants import router as grants_router
from web.admin.routers.hr_dictionaries import router as hr_dictionaries_router
from web.admin.routers.marketplace import router as marketplace_router
from web.admin.routers.models import router as models_router
from web.admin.routers.mgmt_units import router as mgmt_units_router
from web.admin.routers.permissions import router as permissions_router
from web.admin.routers.prompt_optimize import router as prompt_optimize_router
from web.admin.routers.resources import admin_router as resource_admin_router
from web.admin.routers.resources import tenant_router as resource_tenant_router
from web.admin.routers.roles import router as roles_router
from web.admin.routers.tenants import router as tenants_router
from web.admin.routers.tools import router as tools_router
from web.admin.routers.users import router as users_router
from web.deps.auth import require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
router.include_router(context_router)
router.include_router(tenants_router)
router.include_router(tools_router)
router.include_router(users_router)
router.include_router(departments_router)
router.include_router(documents_router)
router.include_router(employments_router)
router.include_router(hr_dictionaries_router)
router.include_router(mgmt_units_router)
router.include_router(admin_users_router)
router.include_router(roles_router)
router.include_router(permissions_router)
router.include_router(grants_router)
router.include_router(audit_logs_router)
router.include_router(marketplace_router)
router.include_router(applies_router)
router.include_router(apps_admin_router)
router.include_router(models_router)
router.include_router(prompt_optimize_router)
router.include_router(resource_admin_router)
router.include_router(resource_tenant_router)
