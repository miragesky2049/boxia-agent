"""API v1 路由聚合：admin 与 user 站点各自独立，互不包含对方路由。"""

from fastapi import APIRouter

from web.admin import router as admin_router
from web.admin.routers.auth import login_router
from web.admin.routers.public import router as public_router
from web.user import router as user_router


def build_admin_api_router() -> APIRouter:
    """管理站点：匿名作用域 + 管理员登录 + 受保护管理接口。"""
    router = APIRouter()
    router.include_router(public_router)
    router.include_router(login_router)
    router.include_router(admin_router)
    return router


def build_user_api_router() -> APIRouter:
    """用户站点：仅装配面向最终用户的接口，不包含 admin / public 路由。"""
    router = APIRouter()
    router.include_router(user_router)
    return router
