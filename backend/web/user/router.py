"""用户端接口：面向最终用户的对话与智能体使用能力。"""

from fastapi import APIRouter, Depends

from web.deps.auth import UserAuthDep, require_user

router = APIRouter(
    prefix="/user",
    tags=["user"],
    dependencies=[Depends(require_user)],
)


@router.get("/me")
def get_user_profile(principal: UserAuthDep) -> dict:
    """返回当前用户身份，用于验证用户端鉴权链路。"""
    return {"scope": "user", "subject": principal.subject}
