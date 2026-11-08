"""冒烟/联调用无 reload 启动器：selector loop（psycopg async 要求）+ 指定站点端口。

用法：.venv/Scripts/python.exe scripts/serve_noreload.py admin|user

两个已知坑：
1. uvicorn --reload / 模块 __main__ 入口的 watchfiles 会监视 .pyc，pytest 落盘缓存
   会触发起动实例自重启循环，冒烟窗口禁用 reload；
2. uvicorn ≥0.36 的 loop="auto" 在 Windows 单进程下硬编码 ProactorEventLoop（无视
   set_event_loop_policy，见 uvicorn.loops.asyncio.asyncio_loop_factory），psycopg
   async 在其上无法建连。这里用 Config(loop="none") 不自建循环 + 外部 selector loop
   跑 server.serve()，绕开工厂。
"""

import asyncio
import sys
from pathlib import Path

import uvicorn

# 脚本目录默认是 sys.path[0]，'web' 包在 backend 根下，需显式补路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PORTS = {"admin": ("web.app_admin:app", 8000), "user": ("web.app_user:app", 8001)}

site = sys.argv[1] if len(sys.argv) > 1 else "admin"
app, port = PORTS[site]
config = uvicorn.Config(app, host="127.0.0.1", port=port, loop="none")
server = uvicorn.Server(config)
asyncio.run(server.serve())
