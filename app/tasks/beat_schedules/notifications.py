from datetime import timedelta

NOTIFICATIONS_BEAT_SCHEDULE = {
    "send-email-digest-midnight": {
        "task": "app.tasks.email.send_email_digest",
        "schedule": timedelta(hours=24),
    },
}
