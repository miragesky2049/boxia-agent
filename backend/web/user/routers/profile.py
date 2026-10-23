"""用户个人身份接口。"""

from fastapi import APIRouter

from web.deps.auth import UserAuthDep

router = APIRouter(tags=["user"])


@router.get("/me")
def get_user_profile(principal: UserAuthDep) -> dict:
    """返回当前用户身份，用于验证用户端鉴权链路。"""
    return {"scope": "user", "subject": principal.subject}
