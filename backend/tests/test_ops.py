"""运维端点、请求 ID 与安全响应头测试。"""

from fastapi.testclient import TestClient


def test_health_live(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200, response.text
    assert response.json()["components"]["database"] == "ok"


def test_metrics_endpoint(client: TestClient) -> None:
    client.get("/health/live")
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "boxia_db_pool_size" in response.text


def test_request_id_echoed(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"


def test_request_id_generated(client: TestClient) -> None:
    response = client.get("/health/live")

    assert len(response.headers["X-Request-ID"]) >= 8


def test_security_headers(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_login_response_no_store(client: TestClient) -> None:
    response = client.post(
        "/api/v1/admin/auth/login", json={"username": "nobody", "password": "wrong-password"}
    )

    assert response.headers["Cache-Control"] == "no-store"


def test_error_body_contains_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/admin/resources")

    assert response.status_code == 401
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
