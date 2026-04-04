import asyncio
import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.alert.consumer import _process_message
from app.alert.websocket import connection_manager
from app.core.dependencies import get_current_user
from app.db.models import User
from app.db.session import AsyncSessionLocal, engine
from app.main import app


class FakeRedis:
    """Small in-memory stand-in for Redis used by the WS ticket flow test."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class FakeWebSocket:
    """Captures pushed websocket payloads without opening a real socket."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.messages.append(payload)


class FakeConsumer:
    """Tracks whether the alert consumer committed its offset."""

    def __init__(self) -> None:
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1


@dataclass
class FakeMessage:
    value: dict


@pytest.fixture
def disable_alert_background_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    TestClient starts FastAPI lifespan, which would otherwise start the real Kafka
    alert consumer. Stub it so this test file stays focused and deterministic.
    """

    async def _noop_alert_consumer(_connection_manager) -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr("app.main.run_alert_consumer", _noop_alert_consumer)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr("app.alert.websocket._redis", None)
    monkeypatch.setattr("app.alert.websocket._get_redis", lambda: redis)
    return redis


@pytest.fixture
def override_current_user() -> None:
    async def _fake_current_user() -> User:
        return User(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            name="Dev User",
            email="dev@localhost",
            google_sub="mock-google-sub-dev",
        )

    app.dependency_overrides[get_current_user] = _fake_current_user
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_websocket_ticket_is_single_use(
    disable_alert_background_consumer: None,
    fake_redis: FakeRedis,
    override_current_user: None,
) -> None:
    """
    Verifies the websocket auth handshake:
    1. Issue a ticket over HTTP
    2. Connect once successfully
    3. Reuse the same ticket and confirm it is rejected
    """

    with TestClient(app) as client:
        ticket_response = client.post("/v1/ws/ticket")
        assert ticket_response.status_code == 200

        ticket = ticket_response.json()["ticket"]
        assert fake_redis._store[f"ws_ticket:{ticket}"] == "00000000-0000-0000-0000-000000000001"

        with client.websocket_connect(f"/v1/ws?ticket={ticket}") as websocket:
            websocket.close()

        assert fake_redis._store.get(f"ws_ticket:{ticket}") is None

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/v1/ws?ticket={ticket}"):
                pass

        assert exc.value.code == 4001


def test_alert_consumer_pushes_websocket_alert_and_cleans_up() -> None:
    """
    Inserts a temporary source/topic/article directly into Postgres, runs one
    matched-articles message through the alert consumer, verifies a websocket
    payload was pushed and the alert row is marked as sent, then cleans up.

    Run this inside the backend container so DATABASE_URL resolves correctly:
      docker compose exec backend pytest tests/test_alert_service.py -q
    """

    async def _run() -> None:
        source_id = uuid.uuid4()
        topic_id = uuid.uuid4()
        article_id = uuid.uuid4()
        user_id = "00000000-0000-0000-0000-000000000001"

        fake_ws = FakeWebSocket()
        fake_consumer = FakeConsumer()
        fake_message = FakeMessage(
            value={
                "article_id": str(article_id),
                "topic_id": str(topic_id),
                "relevance_score": 0.91,
                "user_id": user_id,
            }
        )

        connection_manager.connect(user_id, fake_ws)

        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO sources (id, name, url, type, credibility_score, poll_interval, is_active)
                    VALUES (:id, :name, :url, :type, :credibility_score, :poll_interval, :is_active)
                    """
                ),
                {
                    "id": str(source_id),
                    "name": "Alert Service Test Source",
                    "url": f"https://example.com/source/{source_id}",
                    "type": "rss",
                    "credibility_score": 0.8,
                    "poll_interval": 600,
                    "is_active": True,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO topics (id, user_id, name, description, sensitivity, is_active)
                    VALUES (:id, :user_id, :name, :description, :sensitivity, :is_active)
                    """
                ),
                {
                    "id": str(topic_id),
                    "user_id": user_id,
                    "name": "Alert Service Test Topic",
                    "description": "temporary topic used by pytest",
                    "sensitivity": "balanced",
                    "is_active": True,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO topic_channels (topic_id, channel)
                    VALUES (:topic_id, :channel)
                    """
                ),
                {"topic_id": str(topic_id), "channel": "websocket"},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO articles (id, source_id, url, headline, content, summary, pipeline_status)
                    VALUES (:id, :source_id, :url, :headline, :content, :summary, :pipeline_status)
                    """
                ),
                {
                    "id": str(article_id),
                    "source_id": str(source_id),
                    "url": f"https://example.com/article/{article_id}",
                    "headline": "Alert service integration test headline",
                    "content": "Temporary content for the alert service test.",
                    "summary": "Temporary summary for the alert service test.",
                    "pipeline_status": "processed",
                },
            )
            await session.commit()

        try:
            await _process_message(fake_consumer, fake_message, connection_manager)

            assert fake_consumer.commit_calls == 1
            assert len(fake_ws.messages) == 1
            assert '"event": "new_alert"' in fake_ws.messages[0]
            assert "Alert service integration test headline" in fake_ws.messages[0]

            async with AsyncSessionLocal() as session:
                alert_row = await session.execute(
                    text(
                        """
                        SELECT status, channel
                        FROM alerts
                        WHERE user_id = :user_id
                          AND article_id = :article_id
                          AND topic_id = :topic_id
                        """
                    ),
                    {
                        "user_id": user_id,
                        "article_id": str(article_id),
                        "topic_id": str(topic_id),
                    },
                )
                row = alert_row.fetchone()

            assert row is not None
            assert row.status == "sent"
            assert row.channel == "websocket"

        finally:
            connection_manager.disconnect(user_id)

            async with AsyncSessionLocal() as session:
                await session.execute(
                    text("DELETE FROM alerts WHERE article_id = :article_id"),
                    {"article_id": str(article_id)},
                )
                await session.execute(
                    text("DELETE FROM topic_channels WHERE topic_id = :topic_id"),
                    {"topic_id": str(topic_id)},
                )
                await session.execute(
                    text("DELETE FROM topics WHERE id = :topic_id"),
                    {"topic_id": str(topic_id)},
                )
                await session.execute(
                    text("DELETE FROM articles WHERE id = :article_id"),
                    {"article_id": str(article_id)},
                )
                await session.execute(
                    text("DELETE FROM sources WHERE id = :source_id"),
                    {"source_id": str(source_id)},
                )
                await session.commit()

    asyncio.run(engine.dispose())
    asyncio.run(_run())


def test_alert_consumer_marks_sms_failed_when_enqueue_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    If Celery/Redis is unavailable and SMS cannot even be enqueued, the alert row
    should be marked failed rather than left pending indefinitely.
    """

    async def _run() -> None:
        source_id = uuid.uuid4()
        topic_id = uuid.uuid4()
        article_id = uuid.uuid4()
        user_id = "00000000-0000-0000-0000-000000000001"

        fake_consumer = FakeConsumer()
        fake_message = FakeMessage(
            value={
                "article_id": str(article_id),
                "topic_id": str(topic_id),
                "relevance_score": 0.91,
                "user_id": user_id,
            }
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("redis unavailable")

        monkeypatch.setattr("app.alert.consumer.dispatch_sms_task.delay", _boom)

        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO sources (id, name, url, type, credibility_score, poll_interval, is_active)
                    VALUES (:id, :name, :url, :type, :credibility_score, :poll_interval, :is_active)
                    """
                ),
                {
                    "id": str(source_id),
                    "name": "Alert Service SMS Failure Test Source",
                    "url": f"https://example.com/source/{source_id}",
                    "type": "rss",
                    "credibility_score": 0.8,
                    "poll_interval": 600,
                    "is_active": True,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO topics (id, user_id, name, description, sensitivity, is_active)
                    VALUES (:id, :user_id, :name, :description, :sensitivity, :is_active)
                    """
                ),
                {
                    "id": str(topic_id),
                    "user_id": user_id,
                    "name": "Alert Service SMS Failure Test Topic",
                    "description": "temporary sms failure topic used by pytest",
                    "sensitivity": "balanced",
                    "is_active": True,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO topic_channels (topic_id, channel)
                    VALUES (:topic_id, :channel)
                    """
                ),
                {"topic_id": str(topic_id), "channel": "sms"},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO articles (id, source_id, url, headline, content, summary, pipeline_status)
                    VALUES (:id, :source_id, :url, :headline, :content, :summary, :pipeline_status)
                    """
                ),
                {
                    "id": str(article_id),
                    "source_id": str(source_id),
                    "url": f"https://example.com/article/{article_id}",
                    "headline": "Alert service sms enqueue failure test headline",
                    "content": "Temporary content for the sms failure test.",
                    "summary": "Temporary summary for the sms failure test.",
                    "pipeline_status": "processed",
                },
            )
            await session.commit()

        try:
            await _process_message(fake_consumer, fake_message, connection_manager)

            assert fake_consumer.commit_calls == 1

            async with AsyncSessionLocal() as session:
                alert_row = await session.execute(
                    text(
                        """
                        SELECT status, channel
                        FROM alerts
                        WHERE user_id = :user_id
                          AND article_id = :article_id
                          AND topic_id = :topic_id
                        """
                    ),
                    {
                        "user_id": user_id,
                        "article_id": str(article_id),
                        "topic_id": str(topic_id),
                    },
                )
                row = alert_row.fetchone()

            assert row is not None
            assert row.status == "failed"
            assert row.channel == "sms"

        finally:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text("DELETE FROM alerts WHERE article_id = :article_id"),
                    {"article_id": str(article_id)},
                )
                await session.execute(
                    text("DELETE FROM topic_channels WHERE topic_id = :topic_id"),
                    {"topic_id": str(topic_id)},
                )
                await session.execute(
                    text("DELETE FROM topics WHERE id = :topic_id"),
                    {"topic_id": str(topic_id)},
                )
                await session.execute(
                    text("DELETE FROM articles WHERE id = :article_id"),
                    {"article_id": str(article_id)},
                )
                await session.execute(
                    text("DELETE FROM sources WHERE id = :source_id"),
                    {"source_id": str(source_id)},
                )
                await session.commit()

    asyncio.run(engine.dispose())
    asyncio.run(_run())
