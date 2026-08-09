from datetime import timedelta

MAINTENANCE_BEAT_SCHEDULE = {
    # Postgres has no TTL, so dropped articles are aged out on a schedule.
    # Hourly with a 10k-row cap per run keeps each delete short rather than
    # letting a single nightly job hold a long lock on the articles table.
    "purge-dropped-articles": {
        "task": "app.tasks.retention.purge_dropped_articles",
        "schedule": timedelta(hours=1),
    },
}
