"""add articles.image_url and refresh sources (add Guardian/Hindu/NDTV/IndiaTV, remove AlJazeera+HN)

Revision ID: 007_img_sources
Revises: 640968141458
Create Date: 2026-04-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007_img_sources"
down_revision: Union[str, None] = "640968141458"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Source IDs (fixed UUIDs so celery beat args line up deterministically)
ALJAZEERA_ID = "a1b2c3d4-0003-0003-0003-000000000003"
HN_ID        = "a1b2c3d4-0005-0005-0005-000000000005"
GUARDIAN_ID  = "a1b2c3d4-0008-0008-0008-000000000008"
HINDU_ID     = "a1b2c3d4-0009-0009-0009-000000000009"
NDTV_ID      = "a1b2c3d4-0010-0010-0010-000000000010"
INDIATV_ID   = "a1b2c3d4-0011-0011-0011-000000000011"


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column("image_url", sa.Text(), nullable=True),
    )

    # Drop article_topic_matches first? No — FK is articles → sources, not
    # matches → sources. Articles referencing AlJazeera/HN stay; we null
    # their source_id via SET NULL? FK in schema is nullable=False. Safer:
    # leave historical articles, just deactivate sources so no new ingestion.
    # We physically delete only if no articles reference them.
    op.execute(f"""
        DELETE FROM sources
        WHERE id IN ('{ALJAZEERA_ID}', '{HN_ID}')
          AND NOT EXISTS (
              SELECT 1 FROM articles WHERE articles.source_id = sources.id
          )
    """)
    op.execute(f"""
        UPDATE sources SET is_active = FALSE
        WHERE id IN ('{ALJAZEERA_ID}', '{HN_ID}')
    """)

    op.execute(f"""
        INSERT INTO sources (id, name, url, type, credibility_score, poll_interval, is_active)
        VALUES
            ('{GUARDIAN_ID}', 'The Guardian', 'https://www.theguardian.com',   'rss', 0.92, 600,  TRUE),
            ('{HINDU_ID}',    'The Hindu',    'https://www.thehindu.com',      'rss', 0.85, 1200, TRUE),
            ('{NDTV_ID}',     'NDTV',         'https://www.ndtv.com',          'rss', 0.80, 600,  TRUE),
            ('{INDIATV_ID}',  'India TV',     'https://www.indiatvnews.com',   'rss', 0.70, 600,  TRUE)
        ON CONFLICT (id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM sources
        WHERE id IN ('{GUARDIAN_ID}', '{HINDU_ID}', '{NDTV_ID}', '{INDIATV_ID}')
          AND NOT EXISTS (
              SELECT 1 FROM articles WHERE articles.source_id = sources.id
          )
    """)
    op.execute(f"""
        UPDATE sources SET is_active = TRUE
        WHERE id IN ('{ALJAZEERA_ID}', '{HN_ID}')
    """)
    op.drop_column("articles", "image_url")
