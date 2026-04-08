"""seed all ingestion sources (BBC, NYT, Al Jazeera, NewsAPI, NewsData, Reddit)

Revision ID: 004
Revises: 003
Create Date: 2026-04-06

Migration 002 only seeded Hacker News. This migration adds every other source
so that the Celery beat schedule has valid FK targets when it passes source_id
to crawl_rss_feed / crawl_newsapi / crawl_newsdata / crawl_reddit.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO sources (id, name, url, type, credibility_score, poll_interval, is_active)
        VALUES
            ('a1b2c3d4-0001-0001-0001-000000000001', 'BBC News',    'https://feeds.bbci.co.uk/news/rss.xml',                  'rss',    0.95, 600,  TRUE),
            ('a1b2c3d4-0002-0002-0002-000000000002', 'NYT',         'https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml', 'rss',  0.95, 600,  TRUE),
            ('a1b2c3d4-0003-0003-0003-000000000003', 'Al Jazeera',  'https://www.aljazeera.com/xml/rss/all.xml',               'rss',    0.90, 600,  TRUE),
            ('a1b2c3d4-0004-0004-0004-000000000004', 'NewsAPI',     'https://newsapi.org',                                     'api',    0.85, 1800, TRUE),
            ('a1b2c3d4-0005-0005-0005-000000000005', 'Hacker News', 'https://news.ycombinator.com',                            'api',    0.80, 600,  TRUE),
            ('a1b2c3d4-0006-0006-0006-000000000006', 'Reddit',      'https://reddit.com',                                      'reddit', 0.70, 600,  TRUE),
            ('a1b2c3d4-0007-0007-0007-000000000007', 'NewsData',    'https://newsdata.io',                                     'api',    0.80, 1800, TRUE)
        ON CONFLICT (id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM sources WHERE id IN (
            'a1b2c3d4-0001-0001-0001-000000000001',
            'a1b2c3d4-0002-0002-0002-000000000002',
            'a1b2c3d4-0003-0003-0003-000000000003',
            'a1b2c3d4-0004-0004-0004-000000000004',
            'a1b2c3d4-0006-0006-0006-000000000006',
            'a1b2c3d4-0007-0007-0007-000000000007'
        )
    """)
