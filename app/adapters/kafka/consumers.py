"""Kafka consumer factories.

Two builders, not one, because the two callers live in different worlds:

  build_sync_consumer  — kafka-python, for the pipeline's blocking poll loop
  build_async_consumer — aiokafka, for the alert consumers' asyncio loops

These cannot be collapsed into a single class. The pipeline runs a synchronous
for-loop over CPU-bound NLP work and has no event loop to await on; the alert
consumers are asyncio tasks and must not block one. Sharing the module keeps
the settings in one place without pretending the two are interchangeable.

Both are created with enable_auto_commit=False. Every caller commits manually
after processing so that a crash mid-message replays it instead of losing it.
"""

from __future__ import annotations

import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError
from kafka import KafkaConsumer

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _deserialize(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))


def build_sync_consumer(
    topic: str,
    group_id: str,
    *,
    bootstrap_servers: str | None = None,
    max_poll_records: int = 10,
    session_timeout_ms: int = 30000,
) -> KafkaConsumer:
    """Blocking consumer for the pipeline worker."""
    servers = bootstrap_servers or get_settings().kafka_bootstrap_servers
    return KafkaConsumer(
        topic,
        bootstrap_servers=servers,
        group_id=group_id,
        enable_auto_commit=False,
        value_deserializer=_deserialize,
        auto_offset_reset="earliest",  # on first run, read from the beginning
        max_poll_records=max_poll_records,
        session_timeout_ms=session_timeout_ms,
    )


def build_async_consumer(
    topic: str,
    group_id: str,
    *,
    bootstrap_servers: str | None = None,
) -> AIOKafkaConsumer:
    """asyncio consumer for the alert consumers. Call start_with_retry() next."""
    servers = bootstrap_servers or get_settings().kafka_bootstrap_servers
    return AIOKafkaConsumer(
        topic,
        bootstrap_servers=servers,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=_deserialize,
    )


async def start_with_retry(consumer: AIOKafkaConsumer, *, max_backoff: int = 30) -> None:
    """
    Start an async consumer, retrying while Kafka is still coming up.

    On a cold `docker compose up` Kafka takes longer to become ready than the
    processes that consume from it. Without this, one bootstrap failure kills
    the consumer task permanently and the container looks healthy while
    silently delivering nothing.
    """
    backoff = 2
    while True:
        try:
            await consumer.start()
            return
        except KafkaConnectionError as exc:
            logger.warning("Kafka not reachable yet (%s) — retrying in %ds...", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
