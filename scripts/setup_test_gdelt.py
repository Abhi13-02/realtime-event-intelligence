import os
import json
import uuid
import psycopg2
from pathlib import Path

def get_db_url():
    url = os.environ.get("DATABASE_URL")
    if url:
        return url.replace("+asyncpg", "")
    return "postgresql://postgres:postgres@127.0.0.1:5432/realtimeintel"

DB_URL = get_db_url()
DEFAULT_USER_ID = "00000000-0000-4000-8000-000000000001"
TOPIC_ID = "11111111-1111-4111-8111-111111111111"

def setup_test_data():
    current_user_id = DEFAULT_USER_ID
    print(f"\n[1/3] Connecting to DB: {DB_URL}")
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        print("[2/3] Ensuring 'gdelt_theme_ids' column exists...")
        cur.execute("ALTER TABLE topics ADD COLUMN IF NOT EXISTS gdelt_theme_ids jsonb;")
        cur.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
        
        print("[3/3] Seeding dummy user and topic...")
        cur.execute("SELECT id FROM users WHERE email = 'test@example.com' LIMIT 1")
        res = cur.fetchone()
        if not res:
            cur.execute("""
                INSERT INTO users (id, name, email)
                VALUES (%s, 'Test User', 'test@example.com')
            """, (current_user_id,))
        else:
            current_user_id = str(res[0])
        
        themes = ["ECON_STOCKMARKET", "TAX_ETHNICITY_INDIAN", "WB_694_BROADCAST_AND_MEDIA"]
        
        cur.execute("""
            INSERT INTO topics (id, user_id, name, sensitivity, is_active, gdelt_theme_ids, embedding)
            VALUES (%s, %s, 'Indian Economy & Media', 'balanced', TRUE, %s, %s)
            ON CONFLICT (id) DO UPDATE 
            SET gdelt_theme_ids = EXCLUDED.gdelt_theme_ids,
                user_id = EXCLUDED.user_id,
                is_active = TRUE;
        """, (TOPIC_ID, current_user_id, json.dumps(themes), [0.0]*384))
        
        conn.commit()
        print("\n[SUCCESS] GDELT Test Data seeded.")
        print(f"  User ID  : {current_user_id}")
        print(f"  Topic ID : {TOPIC_ID}")
        print(f"  Themes   : {themes}")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"\n[ERROR] Setup failed: {e}")

if __name__ == "__main__":
    setup_test_data()
