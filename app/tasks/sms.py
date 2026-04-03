"""
Celery task: SMS alert delivery via Twilio.

Dispatched immediately by the alert consumer when a matched-articles message
contains a user with 'sms' configured. The consumer does not call Twilio —
it just enqueues this task and moves on. The Celery worker handles the actual
HTTP call to Twilio's API and retries if Twilio is down.

Retry schedule (slow backoff — Twilio outages last minutes, not seconds):
  Attempt 1 → immediate
  Attempt 2 → 60s (1 minute)
  Attempt 3 → 300s (5 minutes)
  Attempt 4 → 1800s (30 minutes) → all retries exhausted → mark failed
"""
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
    name="app.tasks.sms.dispatch_sms_task",
)
def dispatch_sms_task(self, alert_id: str, user_id: str) -> None:
    """
    Fetch user phone number + article content from DB, then send SMS via Twilio.
    Updates alert status to 'sent' on success, 'failed' after all retries exhausted.
    """
    settings = get_settings()
    db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql")

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    try:
        # Fetch user phone number — last line of defense null guard.
        # Primary validation is at PUT /topics/{id}/channels (API rejects SMS if no phone set).
        cur.execute("SELECT phone_number FROM users WHERE id = %s", (user_id,))
        user_row = cur.fetchone()
        if not user_row or not user_row[0]:
            cur.execute("UPDATE alerts SET status='failed' WHERE id = %s", (alert_id,))
            logger.error("SMS skipped — no phone number for user %s", user_id)
            return

        phone_number = user_row[0]

        # Fetch article headline + URL via the alert row
        cur.execute(
            """
            SELECT ar.headline, ar.url
            FROM alerts al
            JOIN articles ar ON al.article_id = ar.id
            WHERE al.id = %s
            """,
            (alert_id,),
        )
        row = cur.fetchone()
        if not row:
            logger.error("SMS skipped — alert %s not found in DB", alert_id)
            return

        headline, url = row

        # Send SMS via Twilio
        client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            to=phone_number,
            from_=settings.twilio_from_number,
            body=f"Alert: {headline}\n{url}",
        )

        cur.execute(
            "UPDATE alerts SET status='sent', sent_at=NOW() WHERE id = %s",
            (alert_id,),
        )
        logger.info("SMS sent for alert %s to user %s", alert_id, user_id)

    except TwilioRestException as exc:
        countdown = RETRY_BACKOFFS[min(self.request.retries, len(RETRY_BACKOFFS) - 1)]

        if self.request.retries >= self.max_retries:
            # All retries exhausted — mark permanently failed so it's visible in monitoring
            cur.execute("UPDATE alerts SET status='failed' WHERE id = %s", (alert_id,))
            logger.error(
                "SMS permanently failed for alert %s after %d retries: %s",
                alert_id, self.max_retries, exc,
            )

        raise self.retry(exc=exc, countdown=countdown)

    finally:
        cur.close()
        conn.close()
