# Build Progress — RealTime Event Intelligence

> Personal progress tracker. Not committed to GitHub.

---

## Overall Build Order

| Step | What | Status |
|------|------|--------|
| 1 | Alembic migrations + model cleanup | ✅ Done |
| 2 | Topics API | 🔄 In progress |
| 3 | User Profile API | ⬜ Not started |
| 4 | Celery ingestion tasks (RSS / Reddit / HN) | ⬜ Not started |
| 5 | Kafka consumer + pipeline wire-up | ⬜ Not started |
| 6 | Alert service (WebSocket + email digest + SMS) | ⬜ Not started |
| 7 | Auth — NextAuth + Google OAuth (frontend + FastAPI) | ⬜ Not started — deferred to last |

---

## Step 1 — Alembic + Model Cleanup ✅

| File | What |
|------|------|
| `app/db/models.py` | Removed `RefreshToken`, removed `password_hash`, added `google_sub` on `User` |
| `alembic.ini` | Alembic config |
| `alembic/env.py` | Connects Alembic to models + DB (converts asyncpg URL → psycopg2) |
| `alembic/script.py.mako` | Template for future migration files |
| `alembic/versions/20260330_001_initial_schema.py` | Creates all 7 tables + pgvector extensions + updated_at trigger |
| `docker-entrypoint.sh` | Runs `alembic upgrade head` then starts uvicorn |
| `Dockerfile` | Updated to copy alembic files and use entrypoint |

---

## Step 2 — Topics API 🔄

### Done
| File | What |
|------|------|
| `app/core/dependencies.py` | Mock `get_current_user` — returns hardcoded dev user, creates it in DB on first call |
| `app/schemas/topics.py` | `TopicCreateRequest`, `TopicPatchRequest`, `TopicResponse`, `TopicListResponse`, `TopicChannelItem`, etc. |
| `app/services/topics.py` | `create_topic`, `list_topics`, `get_topic`, `update_topic`, `delete_topic`, `replace_topic_channels` |
| `app/api/topics.py` | All 6 routes: POST, GET, GET/{id}, PATCH/{id}, DELETE/{id}, PUT/{id}/channels |
| `app/main.py` | Router wired up, global error handlers for `TopicServiceError` and `RequestValidationError` |
| `app/config.py` | Renamed `SECRET_KEY` → `AUTH_SECRET` |
| `.env.example` | Updated to reflect `AUTH_SECRET` |

### Still needed (app crashes without these)
| File | What |
|------|------|
| `app/core/gemini.py` | Gemini client — `expand_topic(name, description)` for generating `expanded_description` |
| `app/core/embeddings.py` | Sentence-BERT wrapper — `encode_text(text)` for generating 384-dim topic embeddings |

---

## Step 3 — User Profile API ⬜

Files to create:
- `app/schemas/users.py`
- `app/api/users.py`
- Wire router into `app/main.py`

No service file needed — simple enough to do DB calls directly in the route or a small service.

---

## Step 4 — Celery Ingestion Tasks ⬜

Files to create:
- `app/tasks/rss.py` — RSS feed crawler
- `app/tasks/reddit.py` — Reddit crawler (via PRAW)
- `app/tasks/hackernews.py` — HN crawler (Algolia API)
- Update `app/celery_app.py` — add beat_schedule entries

Also: replace the mock Kafka bus in the pipeline with a real producer.
Note: `app/pipeline/` is owned by teammate — do NOT touch it.

---

## Step 5 — Kafka Consumer + Pipeline Wire-up ⬜

Files to create:
- `app/consumers/pipeline_consumer.py` — reads `raw-articles`, calls pipeline, publishes to `matched-articles`

Note: The pipeline (`app/pipeline/`) is built by teammate. We just wire the consumer around it.

---

## Step 6 — Alert Service ⬜

Files to create:
- `app/alert/consumer.py` — Kafka consumer on `matched-articles`
- `app/alert/websocket.py` — `ConnectionManager` class + `POST /ws/ticket` + `WS /ws`
- `app/alert/email.py` — 24-hour digest Celery task (SMTP)
- `app/alert/sms.py` — Twilio SMS delivery

---

## Step 7 — Auth ⬜ (last)

**Frontend (Next.js):**
- Set up NextAuth with Google provider
- `AUTH_SECRET` shared with FastAPI

**Backend (FastAPI):**
- Replace mock body in `app/core/dependencies.py` with real NextAuth JWT verification
- Add `PyJWT` to `requirements.txt`
- Remove `python-jose` and `passlib[bcrypt]` from `requirements.txt`

No new endpoints needed — auth is entirely frontend-driven.

---

## Key Constraints

- `app/pipeline/` — teammate's code, never touch
- All other code including `app/celery_app.py` and Celery tasks — our responsibility
- Auth deferred to last — use mock `get_current_user` until Step 7
