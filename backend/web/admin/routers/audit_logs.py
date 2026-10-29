"""审计日志查询接口（仅 superadmin）。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from web.admin.schemas.audit import AuditLogOut
from web.admin.schemas.common import PageOut
from web.deps.auth import require_permission
from web.deps.services import AuditServiceDep

router = APIRouter(
    prefix="/audit-logs",
    tags=["admin-audit"],
    dependencies=[Depends(require_permission("page:audit"))],
)


@router.get("", response_model=PageOut[AuditLogOut])
def list_audit_logs(
    service: AuditServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = Query(None, max_length=64),
    actor_id: UUID | None = Query(None),
) -> PageOut[AuditLogOut]:
    """分页查询审计日志。"""
    result = service.list(page, page_size, action, actor_id)
    return PageOut[AuditLogOut](
        items=[AuditLogOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.delete("")
def clear_audit_logs(
    service: AuditServiceDep,
    _permission: None = Depends(require_permission("button:audit:clear")),
) -> dict:
    """清空审计日志：产品级清全部，租户级只清本租户。"""
    count = service.clear()
    return {"deleted": count}
