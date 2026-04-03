import asyncio

from fastapi.testclient import TestClient

from app.main import app


def test_health_route_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "alert_consumer": "running"}


def test_health_route_returns_503_if_alert_consumer_stops() -> None:
    finished_task = asyncio.new_event_loop().create_future()
    finished_task.set_result(None)

    app.state.alert_consumer_task = finished_task
    try:
        client = TestClient(app)
        response = client.get("/")
    finally:
        app.state.alert_consumer_task = None

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "alert_consumer": "stopped"}


def test_topics_routes_are_registered() -> None:
    route_paths = {route.path for route in app.routes}

    assert "/v1/topics" in route_paths
    assert "/v1/topics/{topic_id}" in route_paths
    assert "/v1/topics/{topic_id}/channels" in route_paths
