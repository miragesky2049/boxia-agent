# boxia-agent
Boxia Agent is an intelligent dialogue system based on large language models

## 项目结构

```
boxia-agent/
├── web/                        # Web 层：FastAPI 应用与路由
│   └── app.py                  # 应用入口（uvicorn web.app:app）
├── internal/                   # 内部实现（DDD 分层）
│   ├── application/            # 应用层（预留骨架）
│   │   ├── appservice/         # 应用服务实现
│   │   └── iappservice/        # 应用服务接口
│   ├── domain/                 # 领域层（预留骨架）
│   │   ├── entity/             # 领域实体
│   │   ├── irepository/        # 仓储接口
│   │   ├── iservice/           # 领域服务接口
│   │   └── service/            # 领域服务实现
│   └── infrastructure/         # 基础设施层
│       ├── middleware/         # HTTP 中间件
│       │   └── trace_middleware.py
│       └── trace/              # 链路追踪（OpenTelemetry）
│           ├── context.py
│           ├── dependencies.py
│           ├── exporter.py
│           ├── headers.py
│           └── logging_filter.py
├── pyproject.toml              # 项目配置与依赖声明
└── uv.lock                     # 依赖锁定文件
```

> `internal/application`、`internal/domain` 为预留的 DDD 分层骨架，可随业务扩展填充。

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

## 链路追踪（Trace）使用说明

本项目基于 **W3C Trace Context + OpenTelemetry** 实现分布式链路追踪，无需修改业务代码即可获得请求链路信息。

### 工作原理

- **入口建 span**：请求到达时由 `FastAPIInstrumentor` 自动创建 server span，从请求头 `traceparent` 提取上游链路并延续；无该请求头则生成新的根 span
- **进程内传播**：trace_id/span_id 通过 OTel context 传播，随 `async/await` 自动流动
- **日志关联**：`LoggingInstrumentor` 为每条日志自动注入 `otelTraceID`/`otelSpanID` 字段
- **响应回传**：响应头写回 `traceparent`，供调用方继续传递链路

### 接入方式

应用启动时在 `web/app.py` 中启用 OTel 自动插桩与日志关联：

```python
from internal.infrastructure.middleware.trace_middleware import install_trace
from internal.infrastructure.trace.logging_filter import setup_logging

# lifespan 中配置日志关联（覆盖 uvicorn 对 root logger 的默认配置）
async def lifespan(_):
    setup_logging()
    yield

# 模块级安装 OTel 自动插桩（入口建 span + W3C 传播 + 响应头回传）
install_trace(app, service_name="boxia-agent")
```

### 快速开始（本地验证）

默认使用 `ConsoleSpanExporter`，span 直接打印到控制台，无需额外配置：

```bash
uv run uvicorn web.app:app --reload
```

发起请求后可在控制台看到 span 输出：

```bash
curl http://127.0.0.1:8000/
```

携带上游 `traceparent` 可延续已有链路（trace_id 不变，parent_span_id 指向上游）：

```bash
curl -H "traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" http://127.0.0.1:8000/
```

### 生产配置（OTLP 上报）

设置 `OTEL_EXPORTER_OTLP_ENDPOINT` 环境变量即切换为 OTLP 上报，兼容 Jaeger / OTel Collector：

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger-collector:4318
export OTEL_SERVICE_NAME=boxia-agent
uv run uvicorn web.app:app
```

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 无（输出到控制台） | OTLP Collector/Jaeger 上报地址，SDK 自动拼接信号路径（如 `/v1/traces`） |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | 无 | Trace 专用上报地址，优先于 `OTEL_EXPORTER_OTLP_ENDPOINT` |
| `OTEL_SERVICE_NAME` | `boxia-agent` | 服务名，上报时标记在 span 的 `service.name` 上 |

### 接口中获取 trace 上下文

接口参数上用 `TraceDep` 注入，自动拿到当前请求的 trace 信息：

```python
from internal.infrastructure.trace.dependencies import TraceDep


@app.get("/")
def hello_world(trace: TraceDep) -> dict:
    return {
        "trace_id": trace.trace_id,
        "span_id": trace.span_id,
        "parent_span_id": trace.parent_span_id,
    }
```

### 调用下游服务时透传

调用下游服务时，用 `trace_headers()` 生成需要透传的 header，保持跨服务链路一致：

```python
from internal.infrastructure.trace.headers import trace_headers

async with httpx.AsyncClient() as client:
    resp = await client.get("https://downstream/api", headers=trace_headers())
```

### 日志关联示例

启用日志关联后，每条日志自动携带 trace_id/span_id，便于按链路检索：

```text
2026-08-25 10:31:05,996 INFO web.app [trace_id=0d813adddd28afbaeef481b13d126c08 span_id=544f45910ded3db1] handle hello world
```

日志配置通过 `LoggingConfig.from_env()` 依赖注入，可用环境变量覆盖：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | 日志级别（DEBUG/INFO/WARNING/ERROR） |
| `LOG_FORMAT` | 见上方格式 | 日志格式模板，须含 `%(otelTraceID)s`/`%(otelSpanID)s` 才能输出 trace 字段 |
| `LOG_TRACE_CORRELATION` | `true` | 设为 `false` 可关闭 trace 字段注入 |

### 相关代码位置

| 组件 | 位置 |
| --- | --- |
| 中间件安装入口 | `internal/infrastructure/middleware/trace_middleware.py` → `install_trace()` |
| TracerProvider 配置 | `internal/infrastructure/trace/exporter.py` → `get_tracer_provider()` |
| Depends 注入 | `internal/infrastructure/trace/dependencies.py` → `TraceDep` |
| 下游透传 | `internal/infrastructure/trace/headers.py` → `trace_headers()` |
| 日志关联 | `internal/infrastructure/trace/logging_filter.py` → `setup_logging()` |

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
