import os
import psycopg2
from uuid import UUID

def register_gdelt():
    try:
        url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/realtimeintel")
        sync_url = url.replace("+asyncpg", "")
        
        conn = psycopg2.connect(sync_url)
        cur = conn.cursor()
        
        source_id = "d1e2f3a4-0005-0005-0005-000000000005"
        cur.execute("""
            INSERT INTO sources (id, name, url, type, credibility_score)
            VALUES (%s, 'GDELT Global News', 'https://www.gdeltproject.org', 'gdelt', 0.8)
            ON CONFLICT (id) DO NOTHING;
        """, (source_id,))
        
        conn.commit()
        print("[SUCCESS] GDELT registered as an official source.")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Registration failed: {e}")

if __name__ == "__main__":
    register_gdelt()
