"""MCP 客户端：McpSession 会话生命周期对象 + 兼容门面（M4-b F17.1/F17.3）。"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from internal.domain.agent.mcp_observer import mcp_observer

logger = logging.getLogger(__name__)

# 条目级调用超时默认值（PRD F17.3②：默认 30s，配置面取值范围 1~300 由表单校验）
DEFAULT_TIMEOUT_SECONDS = 30.0

# 连接失败最大尝试次数：1 次原始 + 1 次重试（F17.3③；工具调用不自动重试——非幂等）
_MAX_CONNECT_ATTEMPTS = 2

# close 的兜底预算：调用超时被 wait_for 取消后连接状态不可信，close 需快速收尾
_CLOSE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class McpToolSpec:
    """从 MCP server 拉到的工具描述。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


class McpClientError(Exception):
    """MCP 调用失败。"""


def _make_client(server_url: str, headers: dict[str, str] | None) -> Any:
    """构造 fastmcp Client；带自定义请求头时走 StreamableHttpTransport。

    0074 PRD F6：MCP server 多需 API Key 等请求头，fastmcp 的裸 URL 形态不支持，
    显式构造 transport 传入 headers。依赖缺失在此统一抛 McpClientError。
    """
    try:
        from fastmcp import Client
    except ImportError as exc:  # pragma: no cover
        raise McpClientError(
            "未安装 fastmcp 依赖，无法调用 MCP server；请在 backend 安装 fastmcp"
        ) from exc
    if not headers:
        return Client(server_url)
    from fastmcp.client.transports import StreamableHttpTransport

    return Client(StreamableHttpTransport(url=server_url, headers=dict(headers)))


def _extract_result_text(result: Any) -> str:
    """把 fastmcp CallToolResult 归一化为给模型的文本（F17.3④⑤）。

    - structuredContent 存在时优先 JSON 序列化（结构化输出比 text 拼接更完整）；
    - is_error=True 时加 "[error] " 前缀：工具执行错误不再伪装成正常结果；
    - 非文本 content 项以计数占位（P1 再做完整多模态还原）。
    """
    texts: list[str] = []
    non_text_count = 0
    for content in getattr(result, "content", None) or []:
        text = getattr(content, "text", None)
        if text:
            texts.append(text)
        else:
            non_text_count += 1
    structured = getattr(result, "structured_content", None)
    joined = "\n".join(texts)
    # fastmcp 对返回标量的工具自动包成 {"result": x}，与 text 内容重复；
    # 这种包装不比 text 更丰富时回落原文，避免 "echo:hi" 变成 '{"result": "echo:hi"}'
    if (
        structured is not None
        and joined
        and isinstance(structured, dict)
        and set(structured) == {"result"}
        and str(structured["result"]) == joined
    ):
        structured = None
    body = json.dumps(structured, ensure_ascii=False) if structured is not None else joined
    if getattr(result, "is_error", False):
        return f"[error] {body or '工具执行失败（无错误详情）'}"
    if non_text_count:
        body += f"\n[{non_text_count} 个非文本内容项，当前不支持展示]"
    return body


class McpSession:
    """单个 MCP server 的连接会话：显式 connect/close，多次调用复用握手（F17.1）。

    T-b0 spike（docs/agent-m4-execution-plan.md 附录）结论：fastmcp 4.1.4 经私有
    `Client._connect()` + 公开 `Client.close()` 可实现跨多次 call_tool 的握手复用
    （N 次调用 1 次握手）；协议为 modern per-POST 无状态（无 Mcp-Session-Id），
    "会话"的收益即握手 + httpx 连接复用。close 幂等、工具异常不破坏连接。
    私有 API 只在本类一处使用，升级 fastmcp 时仅需在此适配。
    """

    def __init__(
        self,
        server_url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not server_url:
            raise ValueError("server_url 不能为空")
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds 必须为正数，收到 {timeout_seconds}")
        self._server_url = server_url
        self._headers = dict(headers) if headers else None
        self._timeout_seconds = float(timeout_seconds)
        self._client: Any = None

    @property
    def server_url(self) -> str:
        return self._server_url

    @property
    def headers(self) -> dict[str, str] | None:
        return dict(self._headers) if self._headers is not None else None

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        """建立连接（协议握手一次）；失败重试 1 次后抛 McpClientError。"""
        if self._client is not None:
            return
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_CONNECT_ATTEMPTS + 1):
            client = _make_client(self._server_url, self._headers)
            try:
                await asyncio.wait_for(client._connect(), self._timeout_seconds)
            except TimeoutError as exc:
                await McpSession._close_quietly(client)
                last_exc = exc
                logger.warning(
                    "mcp connect timeout server=%s attempt=%d/%d",
                    self._server_url,
                    attempt,
                    _MAX_CONNECT_ATTEMPTS,
                )
                continue
            except Exception as exc:  # noqa: BLE001 - 连接期错误统一包装后重试
                await McpSession._close_quietly(client)
                last_exc = exc
                logger.warning(
                    "mcp connect failed server=%s attempt=%d/%d err=%s",
                    self._server_url,
                    attempt,
                    _MAX_CONNECT_ATTEMPTS,
                    exc,
                )
                continue
            self._client = client
            mcp_observer().on_handshake(self._server_url)
            logger.info("mcp connected server=%s", self._server_url)
            return
        raise McpClientError(
            f"无法连接 MCP server {self._server_url}（已重试 1 次）: {last_exc}"
        ) from last_exc

    async def close(self) -> None:
        """关闭连接并释放 client；幂等，重复调用与未连接时直接返回。"""
        client, self._client = self._client, None
        if client is None:
            return
        await McpSession._close_quietly(client)

    @staticmethod
    async def _close_quietly(client: Any) -> None:
        """best-effort 关闭：关闭失败只记日志（spike 实测 close 幂等，正常不抛）。"""
        try:
            await asyncio.wait_for(client.close(), _CLOSE_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001
            logger.warning("failed to close mcp client", exc_info=True)

    async def __aenter__(self) -> McpSession:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def list_tools(self) -> list[McpToolSpec]:
        """在既有连接上拉取工具列表；未连接时自动建连。"""
        await self._ensure_connected()
        try:
            tools = await asyncio.wait_for(self._client.list_tools(), self._timeout_seconds)
        except TimeoutError as exc:
            raise McpClientError(
                f"无法连接 MCP server {self._server_url}: list_tools 超时 {self._timeout_seconds}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise McpClientError(f"无法连接 MCP server {self._server_url}: {exc}") from exc
        return [
            McpToolSpec(
                name=tool.name,
                description=tool.description or "",
                input_schema=dict(tool.input_schema or {}),
            )
            for tool in tools
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """在既有连接上调用工具，返回归一化文本；未连接时自动建连。

        错误语义：连接/超时/协议错误抛 McpClientError；工具自身执行失败
        （isError）返回 "[error] ..." 文本，交由模型处理，不中断 run。
        """
        await self._ensure_connected()
        try:
            result = await asyncio.wait_for(
                # raise_on_error=False：让 isError 走结果对象，由 _extract_result_text
                # 统一加 "[error]" 前缀（fastmcp 默认会把 isError 抛成 ToolError）
                self._client.call_tool(tool_name, arguments, raise_on_error=False),
                self._timeout_seconds,
            )
        except TimeoutError as exc:
            # wait_for 取消会让 fastmcp 的 per-task 记账失去收尾，连接状态不可信：
            # 关闭旧连接，下次调用自动重新握手（连接不自动重试见 F17.3③）
            await self.close()
            logger.warning("mcp call_tool timeout server=%s tool=%s", self._server_url, tool_name)
            raise McpClientError(
                f"调用 MCP 工具 {tool_name} 超时（{self._timeout_seconds}s）"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise McpClientError(f"调用 MCP 工具 {tool_name} 失败: {exc}") from exc
        return _extract_result_text(result)

    async def _ensure_connected(self) -> None:
        if self._client is None:
            await self.connect()


async def list_tools(server_url: str, headers: dict[str, str] | None = None) -> list[McpToolSpec]:
    """兼容门面：一次性建连拉取工具列表（discovery 服务沿用，行为与 M4-b 前一致）。"""
    logger.info("mcp list_tools server=%s", server_url)
    session = McpSession(server_url, headers)
    try:
        async with session:
            return await session.list_tools()
    except McpClientError as exc:
        logger.warning("mcp list_tools failed server=%s err=%s", server_url, exc)
        raise


async def call_tool(
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> str:
    """兼容门面：短连接调用一次工具（T-b2 接线 agent_loop 后由 McpSession 取代）。"""
    logger.info(
        "mcp call_tool server=%s tool=%s args_keys=%s",
        server_url,
        tool_name,
        list(arguments.keys()),
    )
    session = McpSession(server_url, headers)
    try:
        async with session:
            return await session.call_tool(tool_name, arguments)
    except McpClientError as exc:
        logger.warning("mcp call_tool failed server=%s tool=%s err=%s", server_url, tool_name, exc)
        raise
