"""知识库文档管理接口：CRUD + 异步触发 ingest。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from internal.infrastructure.tasks.ingest_tasks import ingest_document_task
from web.admin.schemas.common import PageOut
from web.admin.schemas.document import DocumentIngestResponse, DocumentOut, DocumentPayload
from web.deps.auth import require_permission
from web.deps.services import DocumentServiceDep

router = APIRouter(prefix="/documents", tags=["admin-documents"])


@router.get(
    "",
    response_model=PageOut[DocumentOut],
    dependencies=[Depends(require_permission("document:read"))],
)
def list_documents(
    service: DocumentServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    agent_id: UUID | None = Query(None),
    ingest_status: str | None = Query(None, max_length=16),
) -> PageOut[DocumentOut]:
    """分页查询知识库文档。"""
    result = service.list(page, page_size, keyword, agent_id, ingest_status)
    return PageOut[DocumentOut](
        items=[DocumentOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("document:create"))],
)
def create_document(
    payload: DocumentPayload,
    service: DocumentServiceDep,
) -> DocumentOut:
    """创建文档元数据；原文内联传入，状态为 pending。"""
    document = service.create(
        title=payload.title,
        source_type=payload.source_type,
        content=payload.content,
        agent_id=payload.agent_id,
        metadata=payload.metadata,
    )
    return DocumentOut.model_validate(document)


@router.get(
    "/{document_id}",
    response_model=DocumentOut,
    dependencies=[Depends(require_permission("document:read"))],
)
def get_document(document_id: UUID, service: DocumentServiceDep) -> DocumentOut:
    """查询文档详情。"""
    return DocumentOut.model_validate(service.get(document_id))


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("document:delete"))],
)
def delete_document(document_id: UUID, service: DocumentServiceDep) -> None:
    """删除文档及其分块。"""
    service.delete(document_id)


@router.post(
    "/{document_id}/ingest",
    response_model=DocumentIngestResponse,
    dependencies=[Depends(require_permission("document:update"))],
)
def trigger_ingest(
    document_id: UUID,
    service: DocumentServiceDep,
) -> DocumentIngestResponse:
    """异步触发 ingest：文档状态置为 queued，Celery worker 消费任务后切分→embedding→写 chunks。

    前端轮询 GET /documents/{id} 或 GET /documents/{id}/ingest 查询状态。
    """
    document = service.get(document_id)
    # 状态机：pending → queued；重复触发 queued/processing 中的任务时拒绝
    if document.ingest_status in {"queued", "processing"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"文档正在 ingest 中（status={document.ingest_status}）",
        )

    service.update(document_id, {"ingest_status": "queued", "ingest_error": ""})
    tenant_id_str = str(document.tenant_id) if document.tenant_id else None
    ingest_document_task.delay(str(document_id), tenant_id_str)

    return DocumentIngestResponse(
        document_id=document_id,
        ingest_status="queued",
        chunk_count=0,
    )


@router.get(
    "/{document_id}/ingest",
    response_model=DocumentIngestResponse,
    dependencies=[Depends(require_permission("document:read"))],
)
def get_ingest_status(
    document_id: UUID,
    service: DocumentServiceDep,
) -> DocumentIngestResponse:
    """查询 ingest 任务状态（前端轮询用）。"""
    document = service.get(document_id)
    return DocumentIngestResponse(
        document_id=document_id,
        ingest_status=document.ingest_status,
        chunk_count=document.chunk_count,
    )
