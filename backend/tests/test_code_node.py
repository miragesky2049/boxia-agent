"""Code 节点沙箱测试。"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.code import CodeNodeHandler
from internal.infrastructure.sandbox.python_sandbox import PythonSandbox


def _make_env() -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="code-test",
        application_id=uuid4(),
    )


def _run_sandbox(code: str, args: dict | None = None, timeout_s: float = 5.0):
    """直接跑沙箱，返回 SandboxResult。"""
    sandbox = PythonSandbox(timeout_s=timeout_s)
    return asyncio.run(sandbox.run(code, args or {}))


def test_code_node_stub():
    """未注入 sandbox 时走 stub。"""
    handler = CodeNodeHandler()
    ctx = NodeContext(
        node_id="code_1",
        node_type="5",
        inputs={"input": "hi"},
        config={"code": "def main(args): return args"},
        env=_make_env(),
        services=ServiceRegistry(),
    )
    result = asyncio.run(handler.run(ctx))
    assert "stub" in result.outputs


def test_code_node_executes_user_function():
    """注入真实沙箱后，用户 main 函数被执行。"""
    sandbox = PythonSandbox(timeout_s=5.0)
    services = ServiceRegistry({"sandbox": sandbox})

    user_code = """
def main(args):
    text = args.get("input", "")
    return {"output": f"echo: {text}", "len": len(text)}
"""
    handler = CodeNodeHandler()
    ctx = NodeContext(
        node_id="code_1",
        node_type="5",
        inputs={"input": "boxia"},
        config={"code": user_code, "timeoutMs": 5000},
        env=_make_env(),
        services=services,
    )
    result = asyncio.run(handler.run(ctx))
    assert result.outputs["output"] == "echo: boxia"
    assert result.outputs["len"] == 5


def test_code_node_timeout_raises():
    """死循环代码应超时并抛异常。"""
    sandbox = PythonSandbox(timeout_s=1.0)
    services = ServiceRegistry({"sandbox": sandbox})

    user_code = """
def main(args):
    while True:
        pass
    return {}
"""
    handler = CodeNodeHandler()
    ctx = NodeContext(
        node_id="code_1",
        node_type="5",
        inputs={},
        config={"code": user_code, "timeoutMs": 1000},
        env=_make_env(),
        services=services,
    )
    try:
        asyncio.run(handler.run(ctx))
        assert False, "应该抛出 RuntimeError"
    except RuntimeError as exc:
        assert "超时" in str(exc)


def test_sandbox_allows_whitelisted_modules():
    """白名单内的模块（re/json/math）应能正常 import。"""
    code = """
import re
import json
import math

def main(args):
    text = args.get("text", "")
    digits = re.findall(r"\\d+", text)
    return {
        "digits": digits,
        "pi_rounded": round(math.pi, 2),
        "json_ok": json.dumps({"a": 1}),
    }
"""
    result = _run_sandbox(code, {"text": "order 123 total 456"})
    assert result.exit_code == 0
    assert result.outputs["digits"] == ["123", "456"]
    assert result.outputs["pi_rounded"] == 3.14
    assert result.outputs["json_ok"] == '{"a": 1}'


def test_sandbox_blocks_disallowed_os_import():
    """import os 应被拒绝，__error__ 包含白名单提示。"""
    code = """
import os

def main(args):
    return {"cwd": os.getcwd()}
"""
    result = _run_sandbox(code)
    assert result.exit_code != 0
    assert "__error__" in result.outputs
    assert "os" in result.outputs["__error__"]
    assert "白名单" in result.outputs["__error__"]


def test_sandbox_blocks_subprocess_import():
    """import subprocess 应被拒绝。"""
    code = """
import subprocess

def main(args):
    return {"out": subprocess.check_output(["echo", "hi"])}
"""
    result = _run_sandbox(code)
    assert result.exit_code != 0
    assert "__error__" in result.outputs


def test_sandbox_blocks_dynamic_importlib():
    """importlib 动态加载也应被白名单拦截。"""
    code = """
import importlib

def main(args):
    os = importlib.import_module("os")
    return {"cwd": os.getcwd()}
"""
    result = _run_sandbox(code)
    assert result.exit_code != 0
    assert "__error__" in result.outputs


def test_sandbox_custom_allowed_modules():
    """构造时传入 allowed_modules 可扩展白名单。"""
    from internal.infrastructure.sandbox.python_sandbox import PythonSandbox as SB

    custom = SB(timeout_s=5.0, allowed_modules=frozenset({"json", "os"}))
    code = """
import os

def main(args):
    return {"cwd_len": len(os.getcwd())}
"""
    result = asyncio.run(custom.run(code, {}))
    # os.getcwd() 返回路径长度 > 0
    assert result.exit_code == 0
    assert result.outputs["cwd_len"] > 0
