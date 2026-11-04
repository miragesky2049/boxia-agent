"""管理端应用入口：独立打包部署，仅装配 admin 站点路由。"""

import sys

# Windows 上 psycopg async 不兼容 ProactorEventLoop，必须切到 SelectorEventLoop
# Linux/macOS 上无此问题，policy 设置无副作用
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from web.app import create_app

app = create_app("admin")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app_admin:app", host="127.0.0.1", port=8000, reload=True)
