from datetime import timedelta
from app.config import get_settings

settings = get_settings()

DISCOVERY_BEAT_SCHEDULE = {
    "run-subtheme-discovery": {
        "task": "app.tasks.subtheme_discovery.run_subtheme_discovery",
        "schedule": timedelta(hours=settings.subtheme_discovery_interval_hours),
    },
}
