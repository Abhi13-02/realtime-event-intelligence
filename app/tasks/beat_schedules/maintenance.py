from datetime import timedelta

MAINTENANCE_BEAT_SCHEDULE = {
    # Postgres has no TTL, so dropped articles are aged out on a schedule.
    # Hourly with a 10k-row cap per run keeps each delete short rather than
    # letting a single nightly job hold a long lock on the articles table.
    "purge-dropped-articles": {
        "task": "app.tasks.retention.purge_dropped_articles",
        "schedule": timedelta(hours=1),
    },
    # sub_theme_memberships is append-only per discovery run, so it grows
    # without bound. Daily is ample: discovery runs every few hours, so the
    # table can only drift a handful of runs past the cap between purges.
    "purge-old-memberships": {
        "task": "app.tasks.retention.purge_old_memberships",
        "schedule": timedelta(days=1),
    },
    # queue_messages is the transport that replaced Kafka, and Kafka expired
    # its own messages via retention.ms. This is that setting. Hourly with the
    # same 10k cap, for the same reason as the dropped-article purge.
    "purge-queue-messages": {
        "task": "app.tasks.retention.purge_queue_messages",
        "schedule": timedelta(hours=1),
    },
}
