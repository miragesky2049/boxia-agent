"""用户端应用入口：独立打包部署，仅装配 user 站点路由。"""

from web.app import create_app

app = create_app("user")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app_user:app", host="127.0.0.1", port=8001, reload=True)
