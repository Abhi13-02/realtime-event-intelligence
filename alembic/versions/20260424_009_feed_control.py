"""modular celery and dynamic feed control

Revision ID: 009_feed_control
Revises: 008_snapshot_history
Create Date: 2026-04-24

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "009_feed_control"
down_revision: Union[str, None] = "008_snapshot_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create rss_feed_configs table
    op.create_table(
        "rss_feed_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feed_url", sa.Text(), nullable=False, unique=True),
        sa.Column("feed_label", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("TRUE"), nullable=False),
        sa.Column("articles_per_crawl", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("idx_rss_feed_configs_source_id", "rss_feed_configs", ["source_id"])

    # 2. Create reddit_subreddits table
    op.create_table(
        "reddit_subreddits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("limit_per_crawl", sa.Integer(), server_default=sa.text("10"), nullable=False),
        sa.Column("sort", sa.Text(), server_default=sa.text("'new'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("TRUE"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # 3. Add articles_per_crawl to sources
    op.add_column("sources", sa.Column("articles_per_crawl", sa.Integer(), nullable=True))

    # 4. Seed RSS feeds
    rss_feeds = [
        # BBC
        ("https://feeds.bbci.co.uk/news/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001", "BBC News - Top Stories"),
        ("https://feeds.bbci.co.uk/news/world/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001", "BBC News - World"),
        ("https://feeds.bbci.co.uk/news/business/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001", "BBC News - Business"),
        ("https://feeds.bbci.co.uk/news/technology/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001", "BBC News - Technology"),
        ("https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001", "BBC News - Science"),
        
        # NYT
        ("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "a1b2c3d4-0002-0002-0002-000000000002", "NYT - Home Page"),
        ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "a1b2c3d4-0002-0002-0002-000000000002", "NYT - World"),
        ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "a1b2c3d4-0002-0002-0002-000000000002", "NYT - Business"),
        ("https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", "a1b2c3d4-0002-0002-0002-000000000002", "NYT - Technology"),
        ("https://rss.nytimes.com/services/xml/rss/nyt/Science.xml", "a1b2c3d4-0002-0002-0002-000000000002", "NYT - Science"),
        
        # Guardian
        ("https://www.theguardian.com/world/rss", "a1b2c3d4-0008-0008-0008-000000000008", "The Guardian - World"),
        ("https://www.theguardian.com/technology/rss", "a1b2c3d4-0008-0008-0008-000000000008", "The Guardian - Technology"),
        ("https://www.theguardian.com/business/rss", "a1b2c3d4-0008-0008-0008-000000000008", "The Guardian - Business"),
        ("https://www.theguardian.com/science/rss", "a1b2c3d4-0008-0008-0008-000000000008", "The Guardian - Science"),
        ("https://www.theguardian.com/environment/rss", "a1b2c3d4-0008-0008-0008-000000000008", "The Guardian - Environment"),
        ("https://www.theguardian.com/sport/rss", "a1b2c3d4-0008-0008-0008-000000000008", "The Guardian - Sport"),

        # NDTV
        ("https://feeds.feedburner.com/ndtvnews-top-stories", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - Top Stories"),
        ("https://feeds.feedburner.com/ndtvnews-latest", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - Latest"),
        ("https://feeds.feedburner.com/ndtvnews-trending-news", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - Trending"),
        ("https://feeds.feedburner.com/ndtvnews-india-news", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - India"),
        ("https://feeds.feedburner.com/ndtvnews-world-news", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - World"),
        ("https://feeds.feedburner.com/ndtvprofit-latest", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - Business"),
        ("https://feeds.feedburner.com/ndtvsports-latest", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - Sports"),
        ("https://feeds.feedburner.com/ndtvsports-cricket", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - Cricket"),
        ("https://feeds.feedburner.com/gadgets360-latest", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - Tech"),
        ("https://feeds.feedburner.com/ndtvmovies-latest", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - Movies"),
        ("https://feeds.feedburner.com/ndtvnews-south", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - South"),
        ("https://feeds.feedburner.com/ndtvnews-indians-abroad", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - Indians Abroad"),
        ("https://feeds.feedburner.com/ndtvcooks-latest", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - Health"),
        ("https://feeds.feedburner.com/ndtvnews-people", "a1b2c3d4-0010-0010-0010-000000000010", "NDTV - People"),

        # India TV
        ("https://www.indiatvnews.com/rssnews/topstory.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - Top Stories"),
        ("https://www.indiatvnews.com/rssnews/topstory-india.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - India"),
        ("https://www.indiatvnews.com/rssnews/topstory-world.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - World"),
        ("https://www.indiatvnews.com/rssnews/topstory-business.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - Business"),
        ("https://www.indiatvnews.com/rssnews/topstory-sports.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - Sports"),
        ("https://www.indiatvnews.com/rssnews/topstory-entertainment.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - Entertainment"),
        ("https://www.indiatvnews.com/rssnews/topstory-lifestyle.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - Lifestyle"),
        ("https://www.indiatvnews.com/rssnews/topstory-politics.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - Politics"),
        ("https://www.indiatvnews.com/rssnews/topstory-health.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - Health"),
        ("https://www.indiatvnews.com/rssnews/topstory-auto.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - Auto"),
        ("https://www.indiatvnews.com/rssnews/topstory-education.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - Education"),
        ("https://www.indiatvnews.com/rssnews/topstory-trending.xml", "a1b2c3d4-0011-0011-0011-000000000011", "India TV - Trending"),

        # The Hindu
        ("https://www.thehindu.com/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Home"),
        ("https://www.thehindu.com/news/national/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - India"),
        ("https://www.thehindu.com/news/international/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - World"),
        ("https://www.thehindu.com/opinion/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Opinion"),
        ("https://www.thehindu.com/sport/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Sports"),
        ("https://www.thehindu.com/business/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Business"),
        ("https://www.thehindu.com/entertainment/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Entertainment"),
        ("https://www.thehindu.com/life-and-style/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Lifestyle"),
        ("https://www.thehindu.com/society/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Society"),
        ("https://www.thehindu.com/sci-tech/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Sci-Tech"),
        ("https://www.thehindu.com/entertainment/movies/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Movies"),
        ("https://www.thehindu.com/sci-tech/technology/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Technology"),
        ("https://www.thehindu.com/life-and-style/food/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Food"),
        ("https://www.thehindu.com/books/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Books"),
        ("https://www.thehindu.com/data/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Data"),
        ("https://www.thehindu.com/children/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Children"),
        ("https://www.thehindu.com/news/cities/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Cities"),
        ("https://www.thehindu.com/sci-tech/health/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Health"),
        ("https://www.thehindu.com/education/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Education"),
        ("https://www.thehindu.com/sci-tech/agriculture/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Agriculture"),
        ("https://www.thehindu.com/business/Industry/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Industry"),
        ("https://www.thehindu.com/business/markets/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Markets"),
        ("https://www.thehindu.com/business/Economy/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Economy"),
        ("https://www.thehindu.com/real-estate/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Real Estate"),
        ("https://www.thehindu.com/sci-tech/science/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Science"),
        ("https://www.thehindu.com/sci-tech/technology/gadgets/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Gadgets"),
        ("https://www.thehindu.com/life-and-style/fashion/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Fashion"),
        ("https://www.thehindu.com/life-and-style/fitness/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Fitness"),
        ("https://www.thehindu.com/sci-tech/energy-and-environment/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Environment"),
        ("https://www.thehindu.com/entertainment/music/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Music"),
        ("https://www.thehindu.com/entertainment/art/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Art"),
        ("https://www.thehindu.com/life-and-style/travel/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Travel"),
        ("https://www.thehindu.com/life-and-style/luxury/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Luxury"),
        ("https://www.thehindu.com/sport/cricket/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Cricket"),
        ("https://www.thehindu.com/sport/football/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Football"),
        ("https://www.thehindu.com/sport/hockey/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009", "The Hindu - Hockey"),
    ]
    
    op.bulk_insert(
        sa.table(
            "rss_feed_configs",
            sa.column("source_id", postgresql.UUID(as_uuid=True)),
            sa.column("feed_url", sa.Text()),
            sa.column("feed_label", sa.Text()),
        ),
        [
            {"source_id": s_id, "feed_url": url, "feed_label": label}
            for url, s_id, label in rss_feeds
        ]
    )

    # 5. Seed Subreddits
    subreddits = [
        {"name": "MachineLearning", "limit_per_crawl": 3, "sort": "new"},
        {"name": "technology", "limit_per_crawl": 3, "sort": "new"},
        {"name": "worldnews", "limit_per_crawl": 3, "sort": "new"},
        {"name": "science", "limit_per_crawl": 3, "sort": "new"},
        {"name": "news", "limit_per_crawl": 3, "sort": "new"},
        {"name": "geopolitics", "limit_per_crawl": 3, "sort": "new"},
        {"name": "Futurology", "limit_per_crawl": 3, "sort": "new"},
        {"name": "inthenews", "limit_per_crawl": 3, "sort": "new"},
        {"name": "TrueReddit", "limit_per_crawl": 3, "sort": "new"},
        {"name": "IndiaCricket", "limit_per_crawl": 3, "sort": "new"}
    ]
    
    op.bulk_insert(
        sa.table(
            "reddit_subreddits",
            sa.column("name", sa.Text()),
            sa.column("limit_per_crawl", sa.Integer()),
            sa.column("sort", sa.Text()),
        ),
        subreddits
    )


def downgrade() -> None:
    op.drop_column("sources", "articles_per_crawl")
    op.drop_table("reddit_subreddits")
    op.drop_table("rss_feed_configs")
