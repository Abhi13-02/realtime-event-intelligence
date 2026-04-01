from fastapi.testclient import TestClient

from app.main import app


def test_health_route_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_topics_routes_are_registered() -> None:
    route_paths = {route.path for route in app.routes}

    assert "/v1/topics" in route_paths
    assert "/v1/topics/{topic_id}" in route_paths
    assert "/v1/topics/{topic_id}/channels" in route_paths
