from fastapi import FastAPI

app = FastAPI(
    title="Boxia Agent",
    description="Boxia Agent API",
    version="0.1.0",
)


@app.get("/")
def hello_world():
    """返回欢迎信息"""
    return {"message": "Hello, World!"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=True)
