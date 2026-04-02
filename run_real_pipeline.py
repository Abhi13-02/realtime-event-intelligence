"""
Full End-to-End Integration Test for the ChoogleNews Processing Pipeline.

Prerequisites:
    1. Docker container running:
       docker run -d --name pgvector_db \
         -e POSTGRES_HOST_AUTH_METHOD=trust \
         -e POSTGRES_USER=postgres \
         -e POSTGRES_DB=postgres \
         -p 5433:5432 pgvector/pgvector:pg15

    2. Schema loaded:
       docker cp docs/low-level-design/schema.sql pgvector_db:/schema.sql
       docker exec pgvector_db psql -U postgres -f /schema.sql

Run with:
    .venv\\Scripts\\python.exe run_real_pipeline.py

What this tests:
    SCENARIO 1: AI article                -> should PASS, match AI topics based on sensitivity
    SCENARIO 2: Space article             -> should PASS, match Space topic
    SCENARIO 3: Finance article           -> should PASS, match Finance topic
    SCENARIO 4: Exact URL duplicate       -> should DROP at Stage 1
    SCENARIO 5: Near-duplicate via vector -> should DROP at Stage 1
    SCENARIO 6: Off-topic sports          -> should DROP at Stage 2
"""

import sys
import uuid
import logging
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone

# Register UUID support in psycopg2
psycopg2.extras.register_uuid()

# Configure clear logging with DEBUG enabled for the pipeline
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s | %(message)s",
    stream=sys.stdout
)
# Enable debug logs strictly for the pipeline module so we can see matching scores
logging.getLogger("app.pipeline").setLevel(logging.DEBUG)

from app.pipeline.models import RawArticle, Topic
from app.pipeline.adapters.embedding_adapter import SentenceBertAdapter
from app.pipeline.adapters.db_adapter import PostgresAdapter
from app.pipeline.adapters.bus_adapter import MockKafkaAdapter
from app.pipeline.orchestrator import ArticlePipeline
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# LLM selection: Use Langchain + Cohere
# ─────────────────────────────────────────────────────────────
def get_llm():
    """Use Langchain Cohere for summarization. Sentence-BERT runs locally for embeddings."""
    from app.pipeline.adapters.langchain_adapter import LangchainCohereAdapter
    logging.info("LLM      | Using Cohere Command R via Langchain for summarization.")
    return LangchainCohereAdapter(model_name="command-r-08-2024"), 3


# ─────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────
DB_DSN = "host=127.0.0.1 port=5433 dbname=postgres user=postgres"


def reset_db(conn):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE alerts, article_topic_matches, articles, topics, topic_channels, sources, users RESTART IDENTITY CASCADE")
    conn.commit()
    logging.info("DB       | Tables truncated — clean state.")


def seed_data(conn, embedder: SentenceBertAdapter):
    """
    Insert 4 users, a source, and 4 specific topics.
    Returns the seeded IDs and topic variables.
    """
    logging.info("DB       | Seeding diverse users, sources, and topics...")

    desc_ai = (
        "artificial intelligence machine learning deep learning neural networks "
        "large language models LLMs GPT-4 GPT-5 ChatGPT OpenAI Anthropic Google Gemini "
        "transformer attention BERT NLP natural language processing computer vision "
        "reinforcement learning AI safety alignment"
    )
    desc_space = (
        "space exploration astronomy astrophysics cosmology NASA SpaceX Mars rocket launch "
        "satellite universe galaxy black hole telescope ISS astronaut"
    )
    desc_finance = (
        "stock market finance investing economy economy inflation interest rates "
        "Federal Reserve Wall Street trading dividend yield index fund emerging markets"
    )

    vec_ai = embedder.encode_text(desc_ai)
    vec_space = embedder.encode_text(desc_space)
    vec_finance = embedder.encode_text(desc_finance)

    u1, u2, u3, u4 = [str(uuid.uuid4()) for _ in range(4)]
    source_id = str(uuid.uuid4())
    t1, t2, t3, t4 = [str(uuid.uuid4()) for _ in range(4)]

    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (id, name, email) VALUES (%s, 'AI Broad User', 'user1@local')", (u1,))
        cur.execute("INSERT INTO users (id, name, email) VALUES (%s, 'AI High User', 'user2@local')", (u2,))
        cur.execute("INSERT INTO users (id, name, email) VALUES (%s, 'Space User', 'user3@local')", (u3,))
        cur.execute("INSERT INTO users (id, name, email) VALUES (%s, 'Finance User', 'user4@local')", (u4,))

        cur.execute("INSERT INTO sources (id, name, url, type, credibility_score) VALUES (%s, 'TechCrunch', 'https://techcrunch.com', 'rss', 0.88)", (source_id,))

        cur.execute("""
            INSERT INTO topics (id, user_id, name, description, expanded_description, embedding, sensitivity)
            VALUES (%s, %s, 'Artificial Intelligence (Broad)', 'AI/ML news', %s, %s::vector, 'broad')
        """, (t1, u1, desc_ai, f"[{','.join(str(v) for v in vec_ai)}]"))

        cur.execute("""
            INSERT INTO topics (id, user_id, name, description, expanded_description, embedding, sensitivity)
            VALUES (%s, %s, 'Artificial Intelligence (High)', 'Strict AI news', %s, %s::vector, 'high')
        """, (t2, u2, desc_ai, f"[{','.join(str(v) for v in vec_ai)}]"))

        cur.execute("""
            INSERT INTO topics (id, user_id, name, description, expanded_description, embedding, sensitivity)
            VALUES (%s, %s, 'Space Exploration (Balanced)', 'Space news', %s, %s::vector, 'balanced')
        """, (t3, u3, desc_space, f"[{','.join(str(v) for v in vec_space)}]"))

        cur.execute("""
            INSERT INTO topics (id, user_id, name, description, expanded_description, embedding, sensitivity)
            VALUES (%s, %s, 'Finance (Balanced)', 'Financial news', %s, %s::vector, 'balanced')
        """, (t4, u4, desc_finance, f"[{','.join(str(v) for v in vec_finance)}]"))

    conn.commit()
    logging.info(f"DB       | Successfully seeded 4 users and 4 topics.")
    
    topics_list = [
        Topic(id=uuid.UUID(t1), user_id=uuid.UUID(u1), name="Artificial Intelligence (Broad)", sensitivity="broad", embedding=vec_ai),
        Topic(id=uuid.UUID(t2), user_id=uuid.UUID(u2), name="Artificial Intelligence (High)", sensitivity="high", embedding=vec_ai),
        Topic(id=uuid.UUID(t3), user_id=uuid.UUID(u3), name="Space Exploration (Balanced)", sensitivity="balanced", embedding=vec_space),
        Topic(id=uuid.UUID(t4), user_id=uuid.UUID(u4), name="Finance (Balanced)", sensitivity="balanced", embedding=vec_finance),
    ]

    return uuid.UUID(source_id), topics_list


def show_db_results(conn):
    """Print everything written to the DB by the pipeline."""
    print("\n" + "="*80)
    print("  FINAL DATABASE STATE")
    print("="*80)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.headline, a.pipeline_status, a.summary,
                   atm.relevance_score, t.name as topic_name, u.name as user_name
            FROM articles a
            LEFT JOIN article_topic_matches atm ON atm.article_id = a.id
            LEFT JOIN topics t ON t.id = atm.topic_id
            LEFT JOIN users u ON u.id = t.user_id
        """)
        rows = cur.fetchall()
        if rows:
            for r in rows:
                print(f"\n  Article : {r[0]}")
                print(f"  Status  : {r[1]}")
                print(f"  Summary : {r[2]}")
                if r[3] is not None:
                    print(f"  Topic   : {r[4]} (User: {r[5]}) |  Relevance: {r[3]:.4f}")
                else:
                    print("  Topic   : (No match)")
        else:
            print("  No articles in DB.")
    print("="*80)


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def run():
    print("\n" + "="*60)
    print("  ChoogleNews — Pipeline End-to-End Integration Test")
    print("="*60)

    # 1. Connect to real PostgreSQL
    logging.info("DB       | Connecting to PostgreSQL on port 5433...")
    try:
        conn = psycopg2.connect(DB_DSN)
        logging.info("DB       | Connected successfully.")
    except Exception as e:
        logging.error(f"DB       | Connection FAILED: {e}")
        sys.exit(1)

    # 2. Reset and seed
    reset_db(conn)
    logging.info("SBERT    | Loading all-MiniLM-L6-v2 model (Sentence-BERT)...")
    embedder = SentenceBertAdapter()
    logging.info("SBERT    | Model loaded.")
    source_id, topics_list = seed_data(conn, embedder)

    # 3. Build the pipeline with real adapters
    llm, max_retries = get_llm()
    db    = PostgresAdapter(DB_DSN)
    bus   = MockKafkaAdapter()

    pipeline = ArticlePipeline(db=db, embedder=embedder, llm=llm, bus=bus, max_retries=max_retries)
    pipeline.refresh_topic_cache(topics_list)
    logging.info(f"PIPELINE | Initialized. Topic cache loaded with {len(topics_list)} topics.")

    # ─────────────────────────────────────────────────────────
    print(f"\n{'-'*60}")
    print("  SCENARIO 1: AI Article (Matches AI Broad, possibly High based on score)")
    print(f"{'-'*60}")
    a1 = RawArticle(
        url="https://techcrunch.com/2026/03/28/openai-gpt5",
        headline="OpenAI releases GPT-5 with breakthrough reasoning capabilities",
        content=(
            "artificial intelligence machine learning deep learning neural networks "
            "large language models LLMs GPT-4 GPT-5 ChatGPT OpenAI Anthropic Google Gemini "
            "transformer attention BERT NLP natural language processing computer vision "
            "reinforcement learning AI safety alignment"
        ),
        source_id=source_id,
        published_at=datetime.now(timezone.utc),
    )
    pipeline.process_article(a1)

    print(f"\n{'-'*60}")
    print("  SCENARIO 2: Space Article (Matches Space Exploration topic)")
    print(f"{'-'*60}")
    a2 = RawArticle(
        url="https://techcrunch.com/2026/03/29/spacex-mars",
        headline="SpaceX successfully lands Starship on Mars",
        content=(
            "space exploration astronomy astrophysics cosmology NASA SpaceX Mars rocket launch "
            "satellite universe galaxy black hole telescope ISS astronaut touching down on the "
            "red planet successfully."
        ),
        source_id=source_id,
    )
    pipeline.process_article(a2)

    print(f"\n{'-'*60}")
    print("  SCENARIO 3: Finance Article (Matches Finance topic)")
    print(f"{'-'*60}")
    a3 = RawArticle(
        url="https://finance.yahoo.com/2026/03/30/fed-cuts-rates",
        headline="Federal Reserve cuts interest rates amid strong stock market rally",
        content=(
            "The Federal Reserve announced a surprising 50 basis point cut to interest rates today, "
            "sending the stock market to new all-time highs. Wall Street analysts applauded the move, "
            "noting that inflation has finally reached the 2 percent target. Investors poured money into "
            "index funds and tech stocks in response to the dovish policy shift."
        ),
        source_id=source_id,
    )
    pipeline.process_article(a3)

    print(f"\n{'-'*60}")
    print("  SCENARIO 4: Exact URL duplicate of AI Article (DROP)")
    print(f"{'-'*60}")
    a4 = RawArticle(
        url="https://techcrunch.com/2026/03/28/openai-gpt5",  # SAME URL
        headline="Repost: OpenAI releases GPT-5",
        content="Exactly the same article reposted by the feed.",
        source_id=source_id,
    )
    pipeline.process_article(a4)

    print(f"\n{'-'*60}")
    print("  SCENARIO 5: Near-duplicate of Space Article (DROP via Vector Search)")
    print(f"{'-'*60}")
    a5 = RawArticle(
        url="https://bbc.com/news/spacex-mars-landing",  # Different URL
        headline="SpaceX Starship makes historic landing on Mars",
        content=(
            "Space exploration reached a new milestone today as SpaceX landed its Starship "
            "on Mars. The uncrewed mission successfully touched down after a long journey from "
            "Earth. NASA has congratulated the company, noting this will help future astronauts."
        ),
        source_id=source_id,
    )
    pipeline.process_article(a5)

    print(f"\n{'-'*60}")
    print("  SCENARIO 6: Off-topic sports article (DROP at Stage 2)")
    print(f"{'-'*60}")
    a6 = RawArticle(
        url="https://espn.com/2026/03/28/lakers-championship",
        headline="Los Angeles Lakers win the NBA Championship in overtime",
        content=(
            "The Los Angeles Lakers defeated the Boston Celtics 112–108 in overtime "
            "to win the 2026 NBA Championship. LeBron James scored 38 points and grabbed "
            "15 rebounds in a historic performance. Head coach JJ Redick praised the team's "
            "effort throughout the season."
        ),
        source_id=source_id,
    )
    pipeline.process_article(a6)

    # ─────────────────────────────────────────────────────────
    show_db_results(conn)
    conn.close()
    db.close()
    print("\n[SUCCESS] Details execution test complete.\n")


if __name__ == "__main__":
    run()
