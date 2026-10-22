"""FastAPI 统一异常处理器。"""

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from internal.application.errors import AppError
from internal.infrastructure.observability.context import get_request_id

logger = logging.getLogger("boxia.errors")


def _error_response(
    status_code: int,
    detail: str,
    code: str,
    headers: Mapping[str, str] | None = None,
    errors: list | None = None,
) -> JSONResponse:
    content: dict = {
        "detail": detail,
        "code": code,
        "request_id": get_request_id(),
    }
    if errors is not None:
        content["errors"] = errors
    response_headers = dict(headers or {})
    request_id = get_request_id()
    if request_id:
        response_headers.setdefault("X-Request-ID", request_id)
    return JSONResponse(status_code=status_code, content=content, headers=response_headers)


def install_exception_handlers(app: FastAPI) -> None:
    """注册业务、校验、HTTP、数据库与兜底异常处理器。"""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.message, exc.code, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            422,
            "请求参数校验失败",
            "VALIDATION_ERROR",
            errors=jsonable_encoder(exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
        code = "HTTP_ERROR" if exc.status_code != 401 else "UNAUTHORIZED"
        return _error_response(exc.status_code, detail, code, exc.headers)

    @app.exception_handler(IntegrityError)
    async def _handle_integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("database integrity error: %s", exc.orig)
        return _error_response(409, "数据冲突，请检查名称等唯一字段", "CONFLICT")

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception: %s", exc)
        return _error_response(500, "服务器内部错误，请稍后重试", "INTERNAL_ERROR")
