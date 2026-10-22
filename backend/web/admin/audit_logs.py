"""审计日志查询接口（仅 superadmin）。"""

from fastapi import APIRouter, Depends, Query

from web.admin.schemas import AuditLogOut, PageOut
from web.deps.auth import require_superadmin
from web.deps.services import AuditServiceDep

router = APIRouter(
    prefix="/audit-logs",
    tags=["admin-audit"],
    dependencies=[Depends(require_superadmin)],
)


@router.get("", response_model=PageOut[AuditLogOut])
def list_audit_logs(
    service: AuditServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = Query(None, max_length=64),
    actor_id: int | None = Query(None, ge=1),
) -> PageOut[AuditLogOut]:
    """分页查询审计日志。"""
    result = service.list(page, page_size, action, actor_id)
    return PageOut[AuditLogOut](
        items=[AuditLogOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
