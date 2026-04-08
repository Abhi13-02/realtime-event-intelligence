"""
Celery Beat task: midnight UTC email digest.

Runs once per day at 00:00 UTC. Sweeps all pending email alerts from both
  - alerts (article-level alerts)
  - intelligence_alerts (sub-theme change events)
Groups them by user and sends one combined digest email per user.

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
    Fetch all pending email alerts (article + intelligence) grouped by user,
    send one combined digest email per user, then mark rows as 'sent'.

    Uses autocommit=False so each user's UPDATE commits independently —
    a failure for one user does not roll back other users' digests.
    """
    settings = get_settings()
    db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql")

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # ── Article alerts ────────────────────────────────────────────────
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
        article_rows = cur.fetchall()

        # ── Intelligence alerts ───────────────────────────────────────────
        cur.execute("""
            SELECT
                ia.user_id::text,
                u.email,
                u.name,
                array_agg(ia.id::text)           AS alert_ids,
                array_agg(ia.alert_type)         AS alert_types,
                array_agg(ia.payload::text)      AS payloads,
                array_agg(t.name)                AS topic_names
            FROM intelligence_alerts ia
            JOIN users  u ON ia.user_id  = u.id
            JOIN topics t ON ia.topic_id = t.id
            WHERE ia.channel = 'email'
              AND ia.status  = 'pending'
            GROUP BY ia.user_id, u.email, u.name
        """)
        intel_rows = cur.fetchall()

        # Build lookup: user_id → article rows
        article_by_user = {row[0]: row for row in article_rows}
        # Build lookup: user_id → intel rows
        intel_by_user   = {row[0]: row for row in intel_rows}

        all_user_ids = set(article_by_user) | set(intel_by_user)

        if not all_user_ids:
            logger.info("Email digest: no pending alerts.")
            return

        logger.info("Email digest: sending to %d user(s).", len(all_user_ids))

        for user_id in all_user_ids:
            a_row    = article_by_user.get(user_id)
            i_row    = intel_by_user.get(user_id)

            # Derive email + name from whichever row is available
            email    = (a_row or i_row)[1]
            name     = (a_row or i_row)[2]

            try:
                _send_combined_digest(
                    settings=settings,
                    to_email=email,
                    name=name,
                    article_row=a_row,
                    intel_row=i_row,
                )

                if a_row:
                    cur.execute(
                        "UPDATE alerts SET status='sent', sent_at=NOW() WHERE id = ANY(%s)",
                        (a_row[3],),
                    )
                if i_row:
                    cur.execute(
                        "UPDATE intelligence_alerts SET status='sent', sent_at=NOW() WHERE id = ANY(%s)",
                        (i_row[3],),
                    )
                conn.commit()
                logger.info("Digest sent to %s", email)

            except smtplib.SMTPException as exc:
                conn.rollback()
                logger.error("Digest failed for user %s (%s): %s", user_id, email, exc)

    finally:
        cur.close()
        conn.close()


def _send_combined_digest(
    settings,
    to_email: str,
    name: str,
    article_row,   # (user_id, email, name, alert_ids, headlines, summaries, urls, topic_names) | None
    intel_row,     # (user_id, email, name, alert_ids, alert_types, payloads, topic_names)   | None
) -> None:
    """Build and send one plain-text digest email combining article + intelligence alerts."""
    import json as _json

    body_lines = [f"Hello {name},", "", "Here is your daily digest:", ""]

    # ── Article alerts section ────────────────────────────────────────────
    if article_row:
        _, _, _, _, headlines, summaries, urls, topic_names = article_row
        body_lines.append("=== Article Alerts ===")
        body_lines.append("")
        for i, (headline, summary, url, topic) in enumerate(
            zip(headlines, summaries or [], urls, topic_names), start=1
        ):
            body_lines.append(f"{i}. [{topic}] {headline}")
            if summary:
                body_lines.append(f"   {summary}")
            body_lines.append(f"   {url}")
            body_lines.append("")

    # ── Intelligence alerts section ───────────────────────────────────────
    if intel_row:
        _, _, _, _, alert_types, payloads, topic_names = intel_row
        body_lines.append("=== Intelligence Alerts ===")
        body_lines.append("")
        for i, (alert_type, payload_str, topic) in enumerate(
            zip(alert_types, payloads, topic_names), start=1
        ):
            try:
                payload = _json.loads(payload_str) if isinstance(payload_str, str) else payload_str
            except Exception:
                payload = {}
            event_readable = alert_type.replace("sub_theme_", "").replace("_", " ").title()
            label = payload.get("sub_theme_label", "Unknown Sub-theme")
            description = payload.get("sub_theme_description", "")
            body_lines.append(f"{i}. [{topic}] {event_readable}: {label}")
            if description:
                body_lines.append(f"   {description}")
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
