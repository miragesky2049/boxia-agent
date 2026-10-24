"""用户个人身份接口。"""

from fastapi import APIRouter

from internal.domain.entity.access import SYSTEM_ROLE_PERMISSIONS
from web.deps.auth import UserAuthDep
from web.user.schemas.auth import UserProfileOut

router = APIRouter(tags=["user"])


@router.get("/me", response_model=UserProfileOut)
def get_user_profile(principal: UserAuthDep) -> UserProfileOut:
    """返回当前最终用户身份、角色与基础权限。"""
    return UserProfileOut(
        id=principal.user_id,
        username=principal.username,
        display_name=principal.display_name,
        tenant_id=principal.tenant_id,
        role_id=principal.role_id,
        role_code=principal.role_code,
        role_name=principal.role_name,
        permissions=sorted(
            SYSTEM_ROLE_PERMISSIONS.get(principal.role_code, ("read",))
        ),
    )
