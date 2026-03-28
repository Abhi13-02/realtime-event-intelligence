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

    3. (Optional) For real LLM summaries - install Ollama:
       https://ollama.com/download
       Run: ollama pull llama3 && ollama serve

Run with:
    .venv\\Scripts\\python.exe run_real_pipeline.py

What this tests:
    SCENARIO 1: Relevant AI article       -> should PASS all 6 stages, stored + summarized
    SCENARIO 2: Exact URL duplicate       -> should DROP at Stage 1 (URL check)
    SCENARIO 3: Near-duplicate via vector -> should DROP at Stage 1 (pgvector ANN)
    SCENARIO 4: Off-topic sports article  -> should DROP at Stage 2 (no topic match)
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

# Configure clear logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s | %(message)s",
    stream=sys.stdout
)

from app.pipeline.models import RawArticle, Topic
from app.pipeline.adapters.embedding_adapter import SentenceBertAdapter
from app.pipeline.adapters.db_adapter import PostgresAdapter
from app.pipeline.adapters.bus_adapter import MockKafkaAdapter
from app.pipeline.orchestrator import ArticlePipeline

GEMINI_API_KEY = "AIzaSyA20zL2KttXruMynE_AjstyM2l0DKWKzzM"

# ─────────────────────────────────────────────────────────────
# LLM selection: Use Gemini API
# ─────────────────────────────────────────────────────────────
def get_llm():
    """Use Gemini API for summarization. Sentence-BERT runs locally for embeddings."""
    from app.pipeline.adapters.llm_adapter import GeminiAdapter
    logging.info("LLM      | Using Gemini 1.5 Flash for summarization.")
    return GeminiAdapter(api_key=GEMINI_API_KEY), 3


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
    Insert a user, a source, and an AI-focused topic into the DB.
    Returns the seeded IDs and the topic embedding vector (for the cache).
    """
    logging.info("DB       | Seeding user, source, and AI topic...")

    # Rich expanded topic description (mimicking what Gemini would generate for topic creation).
    # Using a long, keyword-dense description maximises Sentence-BERT similarity with AI articles.
    expanded_desc = (
        "artificial intelligence machine learning deep learning neural networks "
        "large language models LLMs GPT-4 GPT-5 ChatGPT OpenAI Anthropic Google Gemini "
        "transformer attention BERT NLP natural language processing computer vision "
        "reinforcement learning AI safety alignment AI regulation AI chips GPU Nvidia "
        "generative AI diffusion models image generation text generation code generation "
        "AI research papers arxiv foundation models autonomous agents AI assistants "
        "machine intelligence algorithm data science python pytorch tensorflow"
    )
    topic_vec = embedder.encode_text(expanded_desc)
    vec_str = f"[{','.join(str(v) for v in topic_vec)}]"

    user_id   = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    topic_id  = str(uuid.uuid4())

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users (id, name, email, password_hash)
            VALUES (%s, 'Test User', 'test@chooglenews.com', 'hashed')
        """, (user_id,))

        cur.execute("""
            INSERT INTO sources (id, name, url, type, credibility_score)
            VALUES (%s, 'TechCrunch', 'https://techcrunch.com', 'rss', 0.88)
        """, (source_id,))

        cur.execute("""
            INSERT INTO topics (id, user_id, name, description, expanded_description, embedding, threshold)
            VALUES (%s, %s, 'Artificial Intelligence', 'AI/ML news', %s, %s::vector, 0.50)
        """, (topic_id, user_id, expanded_desc, vec_str))

    conn.commit()
    logging.info(f"DB       | User   ID: {user_id}")
    logging.info(f"DB       | Source ID: {source_id}")
    logging.info(f"DB       | Topic  ID: {topic_id} | threshold=0.50")

    return uuid.UUID(user_id), uuid.UUID(source_id), uuid.UUID(topic_id), topic_vec


def show_db_results(conn):
    """Print everything written to the DB by the pipeline."""
    print("\n" + "="*60)
    print("  FINAL DATABASE STATE")
    print("="*60)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.headline, a.pipeline_status, a.summary,
                   atm.relevance_score, t.name as topic_name
            FROM articles a
            LEFT JOIN article_topic_matches atm ON atm.article_id = a.id
            LEFT JOIN topics t ON t.id = atm.topic_id
        """)
        rows = cur.fetchall()
        if rows:
            for r in rows:
                print(f"\n  Article : {r[0]}")
                print(f"  Status  : {r[1]}")
                print(f"  Summary : {r[2]}")
                print(f"  Topic   : {r[4]}  |  Relevance: {r[3]:.4f}" if r[3] else "  (No match)")
        else:
            print("  No articles in DB.")
    print("="*60)


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
    user_id, source_id, topic_id, topic_vec = seed_data(conn, embedder)

    # 3. Build the pipeline with real adapters
    llm, max_retries = get_llm()
    db    = PostgresAdapter(DB_DSN)
    bus   = MockKafkaAdapter()

    pipeline = ArticlePipeline(db=db, embedder=embedder, llm=llm, bus=bus, max_retries=max_retries)
    pipeline.refresh_topic_cache([
        Topic(
            id=topic_id,
            name="Artificial Intelligence",
            threshold=0.50,
            embedding=topic_vec
        )
    ])
    logging.info("PIPELINE | Initialized. Topic cache loaded with 1 topic.")

    # ─────────────────────────────────────────────────────────
    # SCENARIO 1: Fresh AI Article — SHOULD PASS all 6 stages
    # ─────────────────────────────────────────────────────────
    print(f"\n{'-'*60}")
    print("  SCENARIO 1: Fresh AI article (expected: PASS all stages)")
    print(f"{'-'*60}")
    a1 = RawArticle(
        url="https://techcrunch.com/2026/03/28/openai-gpt5",
        headline="OpenAI releases GPT-5 with breakthrough reasoning capabilities",
        content=(
            "OpenAI has officially launched GPT-5, the most advanced large language model "
            "ever created. The new neural network model significantly outperforms GPT-4 on "
            "mathematical reasoning, code generation, and complex multi-step problem solving. "
            "OpenAI's CEO Sam Altman described GPT-5 as a major step toward artificial general "
            "intelligence. The AI model is now available to API users and will be integrated "
            "into ChatGPT. Machine learning researchers have noted improvements in transformer "
            "architecture and training methodology."
        ),
        source_id=source_id,
        published_at=datetime.now(timezone.utc),
    )
    pipeline.process_article(a1)

    # ─────────────────────────────────────────────────────────
    # SCENARIO 2: Exact URL duplicate — Stage 1 URL check should DROP
    # ─────────────────────────────────────────────────────────
    print(f"\n{'-'*60}")
    print("  SCENARIO 2: Exact URL duplicate (expected: DROP at Stage 1)")
    print(f"{'-'*60}")
    a2 = RawArticle(
        url="https://techcrunch.com/2026/03/28/openai-gpt5",  # SAME URL
        headline="Repost: OpenAI releases GPT-5",
        content="Exactly the same article reposted by the feed.",
        source_id=source_id,
    )
    pipeline.process_article(a2)

    # ─────────────────────────────────────────────────────────
    # SCENARIO 3: Near-duplicate — pgvector ANN should DROP
    # ─────────────────────────────────────────────────────────
    print(f"\n{'-'*60}")
    print("  SCENARIO 3: Near-duplicate via pgvector (expected: DROP at Stage 1)")
    print(f"{'-'*60}")
    a3 = RawArticle(
        url="https://bbc.com/news/openai-gpt5-launch",  # Different URL
        headline="OpenAI unveils GPT-5, its most powerful AI language model yet",
        content=(
            "OpenAI has launched GPT-5, the newest iteration of its large language model series. "
            "The release marks a significant advancement in artificial intelligence and neural "
            "network performance. GPT-5 improves upon GPT-4 in reasoning, code generation, "
            "and problem-solving. CEO Sam Altman stated the model brings us closer to AGI. "
            "The transformer-based model is available immediately through the OpenAI API."
        ),
        source_id=source_id,
    )
    pipeline.process_article(a3)

    # ─────────────────────────────────────────────────────────
    # SCENARIO 4: Off-topic — Stage 2 topic match should DROP
    # ─────────────────────────────────────────────────────────
    print(f"\n{'-'*60}")
    print("  SCENARIO 4: Off-topic sports article (expected: DROP at Stage 2)")
    print(f"{'-'*60}")
    a4 = RawArticle(
        url="https://espn.com/2026/03/28/lakers-championship",
        headline="Los Angeles Lakers win the NBA Championship in overtime",
        content=(
            "The Los Angeles Lakers defeated the Boston Celtics 112–108 in overtime "
            "to win the 2026 NBA Championship. LeBron James scored 38 points and grabbed "
            "15 rebounds in a historic performance. Head coach JJ Redick praised the team's "
            "effort throughout the season. The crowd at the Crypto.com Arena celebrated the victory."
        ),
        source_id=source_id,
    )
    pipeline.process_article(a4)

    # ─────────────────────────────────────────────────────────
    # Show final DB state
    # ─────────────────────────────────────────────────────────
    show_db_results(conn)
    conn.close()
    db.close()
    print("\n✅ Integration test complete.\n")


if __name__ == "__main__":
    run()
