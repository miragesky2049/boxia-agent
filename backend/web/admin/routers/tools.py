"""工具管理接口。"""

import shlex
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from internal.application.errors import NotFoundError, ValidationError
from internal.domain.constants import PLATFORM_TENANT_ID
from internal.domain.agent.run_context import AgentRunContext
from internal.domain.agent.mcp_client import McpClientError, list_tools as mcp_list_tools
from internal.domain.agent.tools import ToolExecutionError, build_tools
from internal.infrastructure.security.ssrf_guard import validate_outbound_url
from web.admin.schemas.common import PageOut
from web.admin.schemas.resource import ToolOut, ToolPayload
from web.deps.auth import AdminAuthDep, require_permission
from web.deps.db import UowDep
from web.deps.services import ToolServiceDep

router = APIRouter(prefix="/tools", tags=["admin-tools"])


@router.get(
    "",
    response_model=PageOut[ToolOut],
    dependencies=[Depends(require_permission("tool:read"))],
)
def list_tools(
    service: ToolServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=100),
    is_enabled: bool | None = Query(None),
) -> PageOut[ToolOut]:
    """分页查询工具。"""
    result = service.list(page, page_size, keyword, is_enabled)
    return PageOut[ToolOut](
        items=[ToolOut.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "",
    response_model=ToolOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("tool:create"))],
)
def create_tool(
    payload: ToolPayload,
    principal: AdminAuthDep,
    service: ToolServiceDep,
) -> ToolOut:
    """创建工具，并授权给创建者角色。"""
    return ToolOut.model_validate(service.create(payload.model_dump(), principal.role_ids))


# ---------- MCP 自动同步：输入 server_url → 拉取工具列表 / 批量入库 ----------


class McpPullRequest(BaseModel):
    """MCP 拉取请求：只给 server_url，由后端连过去 list_tools。"""

    server_url: str = Field(..., min_length=1, max_length=500)


class McpPulledTool(BaseModel):
    """从 MCP server 拉到的单个工具描述。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class McpPullResponse(BaseModel):
    """MCP 拉取响应：返回候选工具列表，由前端勾选后再调 import 接口。"""

    server_url: str
    tools: list[McpPulledTool]


@router.post(
    "/pull-mcp-tools",
    response_model=McpPullResponse,
    dependencies=[Depends(require_permission("tool:read"))],
)
async def pull_mcp_tools(payload: McpPullRequest) -> McpPullResponse:
    """连接 MCP server 并 list_tools，返回工具描述；不落库。"""
    server_url = validate_outbound_url(payload.server_url)
    try:
        specs = await mcp_list_tools(server_url)
    except McpClientError as exc:
        raise ValidationError(exc.message) from exc
    return McpPullResponse(
        server_url=payload.server_url,
        tools=[
            McpPulledTool(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
            )
            for spec in specs
        ],
    )


class McpImportItem(BaseModel):
    """批量入库时单个工具的配置。"""

    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    tool_name_remote: str = Field(..., min_length=1)
    input_schema: dict[str, Any] = Field(default_factory=dict)


class McpImportRequest(BaseModel):
    """批量入库请求：server_url + 勾选后的工具列表。"""

    server_url: str = Field(..., min_length=1, max_length=500)
    tools: list[McpImportItem] = Field(..., min_length=1)


class McpImportResponse(BaseModel):
    """批量入库响应：返回创建成功的工具实体。"""

    created: list[ToolOut]


@router.post(
    "/import-mcp-tools",
    response_model=McpImportResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("tool:create"))],
)
def import_mcp_tools(
    payload: McpImportRequest,
    principal: AdminAuthDep,
    service: ToolServiceDep,
) -> McpImportResponse:
    """把勾选后的 MCP 工具批量落库为 type=mcp 的 Tool 实体。"""
    created: list[ToolOut] = []
    for item in payload.tools:
        config: dict[str, Any] = {
            "server_url": payload.server_url,
            "tool_name": item.tool_name_remote,
            "input_schema": item.input_schema or {"type": "object", "properties": {}},
        }
        entity = service.create(
            {
                "name": item.name,
                "description": item.description,
                "type": "mcp",
                "config": config,
                "is_enabled": True,
            },
            principal.role_ids,
        )
        created.append(ToolOut.model_validate(entity))
    return McpImportResponse(created=created)


# ---------- curl 解析：粘贴 curl → 回填 HTTP 工具配置 ----------


class ParseCurlRequest(BaseModel):
    """curl 解析请求。"""

    curl_command: str = Field(..., min_length=1)


class ParseCurlResponse(BaseModel):
    """curl 解析响应：直接可作为 HTTP 工具 config 入库。"""

    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)


@router.post(
    "/parse-curl",
    response_model=ParseCurlResponse,
    dependencies=[Depends(require_permission("tool:read"))],
)
def parse_curl(payload: ParseCurlRequest) -> ParseCurlResponse:
    """把用户粘贴的 curl 命令解析为 method/url/headers/body，前端回填到表单。"""
    notes: list[str] = []
    try:
        # shlex 能正确处理引号包裹的 URL 与 header
        tokens = shlex.split(payload.curl_command.strip())
    except ValueError as exc:
        raise ValidationError(f"curl 解析失败：{exc}") from exc

    if not tokens or tokens[0] not in ("curl", "curl.exe"):
        raise ValidationError("请粘贴以 curl 开头的命令")

    method = "GET"
    url = ""
    headers: dict[str, str] = {}
    body: dict[str, Any] | None = None

    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token in ("-X", "--request"):
            i += 1
            method = tokens[i].upper()
        elif token in ("-H", "--header"):
            i += 1
            header_raw = tokens[i]
            if ":" in header_raw:
                key, _, value = header_raw.partition(":")
                headers[key.strip()] = value.strip()
        elif token in ("-d", "--data", "--data-raw", "--data-binary"):
            i += 1
            if method == "GET":
                method = "POST"
            raw_body = tokens[i]
            try:
                import json

                body = json.loads(raw_body)
            except (ValueError, json.JSONDecodeError):
                notes.append("body 不是合法 JSON，已保留原始字符串")
                body = {"__raw__": raw_body}
        elif token in ("-u", "--user"):
            i += 1
            headers["Authorization"] = f"Basic {tokens[i]}"
        elif token.startswith("http://") or token.startswith("https://"):
            url = token
        elif token.startswith("") and not token.startswith("-"):
            url = token
        i += 1

    if not url:
        raise ValidationError("未能从 curl 中解析出 URL")

    return ParseCurlResponse(method=method, url=url, headers=headers, body=body, notes=notes)


@router.get(
    "/{tool_id}",
    response_model=ToolOut,
    dependencies=[Depends(require_permission("tool:read"))],
)
def get_tool(tool_id: UUID, service: ToolServiceDep) -> ToolOut:
    """查询工具详情。"""
    return ToolOut.model_validate(service.get(tool_id))


@router.put(
    "/{tool_id}",
    response_model=ToolOut,
    dependencies=[Depends(require_permission("tool:update"))],
)
def update_tool(tool_id: UUID, payload: ToolPayload, service: ToolServiceDep) -> ToolOut:
    """更新工具。"""
    return ToolOut.model_validate(service.update(tool_id, payload.model_dump()))


@router.delete(
    "/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("tool:delete"))],
)
def delete_tool(tool_id: UUID, service: ToolServiceDep) -> None:
    """删除工具。"""
    service.delete(tool_id)


class ToolTestInvokeRequest(BaseModel):
    """工具试调入参。"""

    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolTestInvokeResponse(BaseModel):
    """工具试调出参。"""

    success: bool
    duration_ms: int
    output: str = ""
    error: str = ""


@router.post(
    "/{tool_id}/test-invoke",
    response_model=ToolTestInvokeResponse,
    dependencies=[Depends(require_permission("tool:read"))],
)
async def test_invoke_tool(
    tool_id: UUID,
    payload: ToolTestInvokeRequest,
    uow: UowDep,
) -> ToolTestInvokeResponse:
    """在 admin 端试调工具，返回耗时 / 输出 / 错误；不落库。"""
    entity = uow.tools.get(tool_id)
    if entity is None:
        raise NotFoundError("工具不存在")
    if not entity.is_enabled:
        raise ValidationError("工具已停用，无法试调")

    runtime_tools = build_tools([entity])
    if not runtime_tools:
        raise ValidationError("工具类型不支持试调")
    tool = runtime_tools[0]

    ctx = AgentRunContext(
        agent_id=tool_id,
        tenant_id=entity.tenant_id or PLATFORM_TENANT_ID,
        user_id=None,
        conversation_id="tool-test-invoke",
    )

    started = time.perf_counter()
    try:
        output = await tool.invoke(payload.arguments or {}, ctx)
        return ToolTestInvokeResponse(
            success=True,
            duration_ms=int((time.perf_counter() - started) * 1000),
            output=output,
        )
    except ToolExecutionError as exc:
        return ToolTestInvokeResponse(
            success=False,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=exc.message,
        )
    except Exception as exc:  # noqa: BLE001 - 试调兜底返回错误文本
        return ToolTestInvokeResponse(
            success=False,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error=f"试调异常：{exc}",
        )
