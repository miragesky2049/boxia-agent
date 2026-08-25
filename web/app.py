import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from internal.infrastructure.middleware.trace_middleware import install_trace
from internal.infrastructure.trace.dependencies import TraceDep
from internal.infrastructure.trace.logging_filter import LoggingConfig, setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(LoggingConfig.from_env())
    yield


app = FastAPI(
    title="Boxia Agent",
    description="Boxia Agent API",
    version="0.1.0",
    lifespan=lifespan,
)
install_trace(app, service_name="boxia-agent")


@app.get("/")
def hello_world(trace: TraceDep) -> dict:
    """返回欢迎信息"""
    logger.info("handle hello world")
    return {
        "message": "Hello, World!",
        "trace_id": trace.trace_id,
        "span_id": trace.span_id,
        "parent_span_id": trace.parent_span_id,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=True)
