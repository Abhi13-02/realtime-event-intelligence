"""
Seed script — deletes all existing topics and recreates the 5 benchmark
topics using the real service layer (Gemini expansion + SentenceBERT embedding).

Run inside the backend container:
    docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/seed_topics.py"
"""

import asyncio
import logging

from sqlalchemy import text

from app.db.session import AsyncSessionLocal, engine
from app.db.models import User
from app.schemas.topics import SensitivityLevel, TopicCreateRequest
from app.services.topics import create_topic

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
logger = logging.getLogger(__name__)

USER_ID = "00000000-0000-0000-0000-000000000001"

TOPICS = [
    "Artificial Intelligence",
    "Climate Change",
    "Global Economy",
    "Space Exploration",
    "Public Health",
]


async def main() -> None:
    # ── Step 1: delete all existing topics ───────────────────────────────────
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM topics"))
        await session.commit()
    logger.info("Deleted all existing topics.")

    # ── Step 2: fetch the user row ────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, name, email, google_sub FROM users WHERE id = :uid"),
            {"uid": USER_ID},
        )
        row = result.fetchone()

    if row is None:
        logger.error("User %s not found in DB. Aborting.", USER_ID)
        return

    user = User(id=row[0], name=row[1], email=row[2], google_sub=row[3])

    # ── Step 3: create each topic through the real service layer ─────────────
    for name in TOPICS:
        logger.info("Creating topic: %s ...", name)
        try:
            async with AsyncSessionLocal() as session:
                topic = await create_topic(
                    session,
                    user=user,
                    payload=TopicCreateRequest(
                        name=name,
                        sensitivity=SensitivityLevel.balanced,
                    ),
                )
            logger.info(
                "  Created '%s' — id=%s, subtopics stored.",
                topic.name,
                topic.id,
            )
        except Exception as exc:
            logger.error("  Failed to create '%s': %s", name, exc)

    logger.info("Done. Run the benchmark:")
    logger.info(
        "  docker compose exec backend bash -c "
        '"cd /app && PYTHONPATH=/app pytest tests/test_pipeline_accuracy_db.py -v -s"'
    )


if __name__ == "__main__":
    asyncio.run(engine.dispose())
    asyncio.run(main())
