from datetime import timedelta

INGESTION_BEAT_SCHEDULE = {
    # ── RSS Dispatchers (shared source_id from sources table) ────────────────
    "dispatch-bbc": {
        "task": "app.tasks.ingestion.dispatch_source",
        "schedule": timedelta(minutes=2),
        "args": ("a1b2c3d4-0001-0001-0001-000000000001",),
    },
    "dispatch-nyt": {
        "task": "app.tasks.ingestion.dispatch_source",
        "schedule": timedelta(minutes=2),
        "args": ("a1b2c3d4-0002-0002-0002-000000000002",),
    },
    "dispatch-guardian": {
        "task": "app.tasks.ingestion.dispatch_source",
        "schedule": timedelta(minutes=2),
        "args": ("a1b2c3d4-0008-0008-0008-000000000008",),
    },
    "dispatch-ndtv": {
        "task": "app.tasks.ingestion.dispatch_source",
        "schedule": timedelta(minutes=2),
        "args": ("a1b2c3d4-0010-0010-0010-000000000010",),
    },
    "dispatch-indiatv": {
        "task": "app.tasks.ingestion.dispatch_source",
        "schedule": timedelta(minutes=2),
        "args": ("a1b2c3d4-0011-0011-0011-000000000011",),
    },
    "dispatch-hindu": {
        "task": "app.tasks.ingestion.dispatch_source",
        "schedule": timedelta(minutes=2),
        "args": ("a1b2c3d4-0009-0009-0009-000000000009",),
    },

    # ── Social Dispatcher ───────────────────────────────────────────────────
    "dispatch-reddit": {
        "task": "app.tasks.ingestion.dispatch_reddit",
        "schedule": timedelta(minutes=2),
    },

    # ── API Dispatchers ─────────────────────────────────────────────────────
    "dispatch-newsapi": {
        "task": "app.tasks.ingestion.dispatch_api",
        "schedule": timedelta(minutes=2),
        "args": ("a1b2c3d4-0004-0004-0004-000000000004",),
    },
    "dispatch-newsdata": {
        "task": "app.tasks.ingestion.dispatch_api",
        "schedule": timedelta(minutes=2),
        "args": ("a1b2c3d4-0007-0007-0007-000000000007",),
    },
}
