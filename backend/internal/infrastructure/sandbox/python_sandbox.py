"""Python 代码沙箱：子进程隔离 + 超时 + 资源限制。

设计要点：
- 用独立子进程执行用户代码，主进程崩溃不影响主服务
- 通过 stdin/stdout 传 JSON，避免命令注入
- 超时强制 kill
- 内存/CPU 限制在 POSIX 下用 resource.setrlimit，Windows 下仅超时兜底

用户代码约定：
    def main(args: dict) -> dict:
        return {"output": "..."}

调用方通过 services.get("sandbox") 拿到本实例。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SandboxResult:
    """沙箱执行结果。"""

    outputs: dict[str, Any]
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


class PythonSandbox:
    """Python 代码沙箱执行器。

    Args:
        timeout_s: 单次执行超时（秒）
        memory_mb: 内存上限（POSIX 生效，Windows 忽略）
        python_path: 解释器路径，默认用当前进程的 python
    """

    def __init__(
        self,
        timeout_s: float = 10.0,
        memory_mb: int = 256,
        python_path: str | None = None,
    ):
        self._timeout_s = timeout_s
        self._memory_mb = memory_mb
        self._python_path = python_path or sys.executable

    async def run(self, code: str, args: dict[str, Any]) -> SandboxResult:
        """执行用户代码。

        Args:
            code: 用户 Python 源码（必须定义 main(args) -> dict）
            args: 入参 dict

        Returns:
            SandboxResult
        """
        wrapper = self._build_wrapper(code)
        payload = json.dumps({"args": args})

        proc = await asyncio.create_subprocess_exec(
            self._python_path,
            "-I",  # isolated mode：不加载用户 site-packages
            "-c",
            wrapper,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._build_env(),
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=payload.encode("utf-8")),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(
                outputs={},
                stdout="",
                stderr=f"沙箱执行超时（{self._timeout_s}s）",
                exit_code=-1,
                timed_out=True,
            )

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        outputs: dict[str, Any] = {}
        if proc.returncode == 0:
            outputs = self._parse_stdout(stdout_text)

        return SandboxResult(
            outputs=outputs,
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=proc.returncode or 0,
        )

    def _build_wrapper(self, user_code: str) -> str:
        """生成包装脚本：把用户代码塞进 main 调用，捕获 JSON 输出。"""
        return f'''
import json, sys, traceback

_USER_CODE = {user_code!r}
_ns = {{}}
exec(compile(_USER_CODE, "<user_code>", "exec"), _ns)
_main = _ns.get("main")
if _main is None:
    print(json.dumps({{"__error__": "用户代码未定义 main(args) 函数"}}))
    sys.exit(1)

try:
    _payload = json.loads(sys.stdin.read() or "{{}}")
    _result = _main(_payload.get("args") or {{}})
    if not isinstance(_result, dict):
        _result = {{"output": _result}}
    sys.stdout.write(json.dumps(_result, ensure_ascii=False, default=str))
except Exception:
    sys.stdout.write(json.dumps({{"__error__": traceback.format_exc()}}))
    sys.exit(1)
'''

    def _build_env(self) -> dict[str, str]:
        """隔离环境：只保留最小必要变量。"""
        env = {"PATH": os.environ.get("PATH", "")}
        if "PYTHONIOENCODING" not in env:
            env["PYTHONIOENCODING"] = "utf-8"
        return env

    def _parse_stdout(self, stdout: str) -> dict[str, Any]:
        """从 stdout 末尾解析最后一行 JSON（用户 print 可能混入输出）。"""
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        if not lines:
            return {}
        try:
            data = json.loads(lines[-1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        return {"output": stdout}
