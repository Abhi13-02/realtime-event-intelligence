from datetime import timedelta
from app.config import get_settings

settings = get_settings()

DISCOVERY_BEAT_SCHEDULE = {
    "run-subtheme-discovery": {
        "task": "app.tasks.subtheme_discovery.run_subtheme_discovery",
        "schedule": timedelta(minutes=10), # Check every 10 mins, task handles the actual interval logic
    },
}
