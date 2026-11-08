"""M4-b T-b6：Prometheus MCP 观测适配器（F17.6 指标落名与装配）。"""

from __future__ import annotations

from prometheus_client import generate_latest

from internal.domain.agent.mcp_observer import McpCallRecord, mcp_observer
from internal.infrastructure.observability import metrics


def test_metrics_import_registers_prometheus_mcp_observer() -> None:
    """导入 metrics 模块（= web 进程装配 Prometheus）时自动注册 MCP 观测实现。"""
    assert isinstance(mcp_observer(), metrics.PrometheusMcpObserver)


def test_prometheus_mcp_observer_records_series() -> None:
    """握手/复用/调用直方图/池水位四类指标均落 Prometheus 注册表。"""
    observer = metrics.PrometheusMcpObserver()
    server = "http://mcp-local.test/mcp"
    observer.on_handshake(server)
    observer.on_reuse(server)
    observer.set_pool_size(3)
    observer.observe_call(
        McpCallRecord(
            tenant="t0000000",
            server=server,
            tool="echo",
            status="ok",
            duration_seconds=0.42,
        )
    )

    payload = generate_latest().decode("utf-8")
    assert 'boxia_mcp_handshake_total{server="http://mcp-local.test/mcp"}' in payload
    assert 'boxia_mcp_session_reuse_total{server="http://mcp-local.test/mcp"}' in payload
    assert (
        'boxia_mcp_call_duration_seconds_count{server="http://mcp-local.test/mcp",'
        'status="ok",tenant="t0000000",tool="echo"}'
    ) in payload
    assert "boxia_mcp_pool_size 3.0" in payload
