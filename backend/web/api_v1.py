"""API v1 路由聚合。"""

from fastapi import APIRouter

from web.admin import router as admin_router
from web.admin.auth import login_router
from web.user import router as user_router


def build_api_router() -> APIRouter:
    """构建完整的 API 路由树（admin 登录、受保护 admin、user）。"""
    router = APIRouter()
    router.include_router(login_router)
    router.include_router(admin_router)
    router.include_router(user_router)
    return router
