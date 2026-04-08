"""
Celery task: SMS delivery for intelligence alerts via Twilio.

Dispatched immediately by the intelligence alert consumer when a sub-theme-events
message has a user with 'sms' configured. The consumer enqueues this task and
moves on — the Celery worker handles the actual Twilio API call and retries.

Retry schedule (slow backoff — same as tasks/sms.py):
  Attempt 1 → immediate
  Attempt 2 → 60s  (1 minute)
  Attempt 3 → 300s (5 minutes)
  Attempt 4 → 1800s (30 minutes) → all retries exhausted → mark failed
"""
import json
import logging

import psycopg2
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

from app.celery_app import celery_app
from app.config import get_settings

logger = logging.getLogger(__name__)

RETRY_BACKOFFS = [0, 60, 300, 1800]  # seconds between retry attempts


@celery_app.task(
    bind=True,
    max_retries=3,
    name="app.tasks.intelligence_sms.dispatch_intelligence_sms_task",
)
def dispatch_intelligence_sms_task(self, alert_id: str, user_id: str) -> None:
    """
    Fetch user phone number + intelligence alert payload from DB, then send SMS.
    Updates intelligence_alerts.status to 'sent' on success, 'failed' on exhaustion.
    """
    settings = get_settings()
    db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql")

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    try:
        # Fetch user phone number — same null guard as tasks/sms.py
        cur.execute("SELECT phone_number FROM users WHERE id = %s", (user_id,))
        user_row = cur.fetchone()
        if not user_row or not user_row[0]:
            cur.execute(
                "UPDATE intelligence_alerts SET status='failed' WHERE id = %s",
                (alert_id,),
            )
            logger.error("Intelligence SMS skipped — no phone number for user %s", user_id)
            return

        phone_number = user_row[0]

        # Fetch intelligence alert payload
        cur.execute(
            "SELECT payload, alert_type FROM intelligence_alerts WHERE id = %s",
            (alert_id,),
        )
        row = cur.fetchone()
        if not row:
            logger.error("Intelligence SMS skipped — alert %s not found in DB", alert_id)
            return

        payload, alert_type = row
        # payload may be a dict (psycopg2 auto-parses JSONB) or a string
        if isinstance(payload, str):
            payload = json.loads(payload)

        sub_theme_label = payload.get("sub_theme_label") or "Unknown Sub-theme"
        event_readable = alert_type.replace("sub_theme_", "").replace("_", " ").title()

        sms_body = f"Intelligence Alert [{event_readable}]: {sub_theme_label}"

        # Send via Twilio
        client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            to=phone_number,
            from_=settings.twilio_from_number,
            body=sms_body,
        )

        cur.execute(
            "UPDATE intelligence_alerts SET status='sent', sent_at=NOW() WHERE id = %s",
            (alert_id,),
        )
        logger.info("Intelligence SMS sent for alert %s to user %s", alert_id, user_id)

    except TwilioRestException as exc:
        countdown = RETRY_BACKOFFS[min(self.request.retries, len(RETRY_BACKOFFS) - 1)]

        if self.request.retries >= self.max_retries:
            cur.execute(
                "UPDATE intelligence_alerts SET status='failed' WHERE id = %s",
                (alert_id,),
            )
            logger.error(
                "Intelligence SMS permanently failed for alert %s after %d retries: %s",
                alert_id, self.max_retries, exc,
            )

        raise self.retry(exc=exc, countdown=countdown)

    finally:
        cur.close()
        conn.close()
