"""权限资源目录查询接口（只读，随版本迁移预置）。"""

from fastapi import APIRouter, Depends

from web.admin.schemas.role_permission import PermissionResourceOut
from web.deps.auth import require_permission
from web.deps.services import RolePermissionServiceDep

router = APIRouter(prefix="/permissions", tags=["admin-permissions"])


@router.get(
    "",
    response_model=list[PermissionResourceOut],
    dependencies=[Depends(require_permission("page:roles"))],
)
def list_permissions(service: RolePermissionServiceDep) -> list[PermissionResourceOut]:
    """查询当前作用域可授权的功能权限目录。"""
    return [PermissionResourceOut.model_validate(item) for item in service.catalog()]
