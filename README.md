# boxia-agent
Boxia Agent is an intelligent dialogue system based on large language models

## FastAPI 说明

本项目 Web 服务基于 [FastAPI](https://fastapi.tiangolo.com/) 构建，用 Uvicorn 作为 ASGI 服务器，应用入口为 `web/app.py`。

### 现有接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 返回欢迎信息 |

### 新增接口

在 `web/app.py` 中定义路由。FastAPI 依据类型提示自动生成参数校验、序列化与接口文档，无需手写文档或额外插件：

```python
from pydantic import BaseModel


class Item(BaseModel):
    name: str
    price: float


@app.post("/items")
def create_item(item: Item):
    return {"id": 1, **item.model_dump()}
```

### 特性

- 自动生成 OpenAPI 文档：`/docs`（Swagger UI）、`/redoc`、`/openapi.json`
- 基于 Pydantic 的请求/响应校验与序列化
- 原生 async 支持，接口可定义为 `async def`

## uv 使用说明

本项目使用 [uv](https://docs.astral.sh/uv/) 管理 Python 依赖：`pyproject.toml` 声明依赖，`uv.lock` 锁定精确版本。

### 安装 uv

- Windows：`winget install astral-sh.uv`
- macOS / Linux：`curl -LsSf https://astral.sh/uv/install.sh | sh`
- 或通过 pip：`pip install uv`

### 常用命令

```bash
# 安装/同步依赖到 .venv（首次运行项目必做）
uv sync

# 添加/移除依赖（自动更新 pyproject.toml 和 uv.lock）
uv add fastapi
uv remove flask

# 在虚拟环境中执行命令
uv run python --version

# 启动 Web 服务（开发模式，带热重载）
uv run uvicorn web.app:app --reload

# 直接运行入口脚本
uv run python web/app.py

# 重新生成 uv.lock / 升级所有依赖到最新兼容版本
uv lock
uv sync --upgrade
```

### 服务访问

启动后：

- 首页：<http://127.0.0.1:8000/>
- Swagger 文档：<http://127.0.0.1:8000/docs>
- OpenAPI JSON：<http://127.0.0.1:8000/openapi.json>
