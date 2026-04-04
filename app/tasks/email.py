"""
Celery Beat task: midnight UTC email digest.

Runs once per day at 00:00 UTC. Sweeps all pending email alerts from PostgreSQL,
groups them by user, and sends one digest email per user containing all their
undelivered alerts since the last run.

On SMTP failure: alerts stay 'pending' and are picked up at the next midnight run.
No data loss — the next digest will include today's alerts plus any that failed tonight.

Why a digest and not per-alert emails?
  Sending one email per matched article would flood users' inboxes — a user with a
  broad topic could receive hundreds of emails per day. A daily digest batches all
  matches into one email, which is easier to read and less likely to be marked as spam.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import psycopg2

from app.celery_app import celery_app
from app.config import get_settings

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.email.send_email_digest")
def send_email_digest() -> None:
    """
    Fetch all pending email alerts grouped by user, send one digest email per user,
    then mark their alert rows as 'sent'.

    Uses autocommit=False so each user's UPDATE commits independently —
    a failure for one user does not roll back other users' digests.
    """
    settings = get_settings()
    db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql")

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT
                a.user_id::text,
                u.email,
                u.name,
                array_agg(a.id::text)     AS alert_ids,
                array_agg(ar.headline)    AS headlines,
                array_agg(ar.summary)     AS summaries,
                array_agg(ar.url)         AS urls,
                array_agg(t.name)         AS topic_names
            FROM alerts a
            JOIN users    u  ON a.user_id    = u.id
            JOIN articles ar ON a.article_id = ar.id
            JOIN topics   t  ON a.topic_id   = t.id
            WHERE a.channel = 'email'
              AND a.status  = 'pending'
            GROUP BY a.user_id, u.email, u.name
        """)
        rows = cur.fetchall()

        if not rows:
            logger.info("Email digest: no pending alerts.")
            return

        logger.info("Email digest: sending to %d user(s).", len(rows))

        for user_id, email, name, alert_ids, headlines, summaries, urls, topic_names in rows:
            try:
                _send_digest_email(
                    settings=settings,
                    to_email=email,
                    name=name,
                    headlines=headlines,
                    summaries=summaries,
                    urls=urls,
                    topic_names=topic_names,
                )

                # Mark all this user's email alerts as sent in one UPDATE
                cur.execute(
                    "UPDATE alerts SET status='sent', sent_at=NOW() WHERE id = ANY(%s)",
                    (alert_ids,),
                )
                conn.commit()
                logger.info("Digest sent to %s (%d alerts)", email, len(alert_ids))

            except smtplib.SMTPException as exc:
                conn.rollback()
                # Leave as pending — next midnight run will retry
                logger.error("Digest failed for user %s (%s): %s", user_id, email, exc)

    finally:
        cur.close()
        conn.close()


def _send_digest_email(settings, to_email, name, headlines, summaries, urls, topic_names):
    """Build and send one plain-text digest email to a single user."""
    body_lines = [
        f"Hello {name},",
        "",
        "Here are your topic alerts from today:",
        "",
    ]

    for i, (headline, summary, url, topic) in enumerate(
        zip(headlines, summaries or [], urls, topic_names), start=1
    ):
        body_lines.append(f"{i}. [{topic}] {headline}")
        if summary:
            body_lines.append(f"   {summary}")
        body_lines.append(f"   {url}")
        body_lines.append("")

    body = "\n".join(body_lines)

    msg = MIMEMultipart()
    msg["From"]    = settings.from_email
    msg["To"]      = to_email
    msg["Subject"] = "Your daily alert digest"
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.from_email, to_email, msg.as_string())
