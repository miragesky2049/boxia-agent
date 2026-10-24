"""管理端应用入口：独立打包部署，仅装配 admin 站点路由。"""

from web.app import create_app

app = create_app("admin")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app_admin:app", host="127.0.0.1", port=8000, reload=True)
