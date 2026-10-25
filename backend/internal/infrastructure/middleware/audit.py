"""管理端写操作审计中间件。"""

import logging
import re

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork
from internal.infrastructure.observability.context import get_request_id
from internal.infrastructure.observability.metrics import AUDIT_WRITE_FAILURE

logger = logging.getLogger("boxia.audit")
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# 主键为 UUID：只把形如 8-4-4-4-12 的路径段识别为资源 ID，避免误记子路径
_UUID_SEGMENT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class AuditMiddleware(BaseHTTPMiddleware):
    """记录管理端成功的写请求；审计失败不回滚业务，但必须告警。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        principal = getattr(request.state, "admin_user", None)
        if principal is None or request.method not in _WRITE_METHODS or response.status_code >= 400:
            return response

        resource_type, resource_id = _parse_resource(request.url.path)
        if resource_type is None:
            return response

        payload = {
            "actor_id": principal.user_id,
            "actor_username": principal.username,
            "action": f"{request.method.lower()}.{resource_type}",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "request_id": get_request_id(),
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent", "")[:255] or None,
            "detail": {"path": request.url.path, "status": response.status_code},
        }
        await run_in_threadpool(_write_audit, payload)
        return response


def _parse_resource(path: str) -> tuple[str | None, str]:
    """从管理端路径解析资源类型与 id，忽略认证类接口。"""
    for prefix in ("/api/v1/admin/", "/api/admin/"):
        if path.startswith(prefix):
            parts = path[len(prefix) :].split("/")
            # auth/users 由应用服务自行写审计，中间件不重复记录
            if not parts or not parts[0] or parts[0] in {"auth", "users"}:
                return None, ""
            resource_type = parts[0]
            resource_id = (
                parts[1] if len(parts) > 1 and _UUID_SEGMENT.fullmatch(parts[1]) else ""
            )
            return resource_type, resource_id
    return None, ""


def _write_audit(payload: dict) -> None:
    """独立事务写入审计记录。"""
    uow = SqlAlchemyUnitOfWork()
    try:
        uow.audit_logs.record(payload)
        uow.commit()
    except Exception:
        # 审计写入失败不阻断业务，但必须记录并计数以便告警
        AUDIT_WRITE_FAILURE.inc()
        logger.exception("failed to persist audit log")
    finally:
        uow.close()
