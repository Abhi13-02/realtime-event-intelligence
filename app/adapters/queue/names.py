"""Queue names.

These are the three Kafka topics this system used to run, kept under the same
names so log lines, dashboards and the LLD docs still line up with what the
code does. They are now values in queue_messages.queue, not brokers' topics.
"""

RAW_ARTICLES = "raw-articles"
MATCHED_ARTICLES = "matched-articles"
SUB_THEME_EVENTS = "sub-theme-events"

ALL_QUEUES = (RAW_ARTICLES, MATCHED_ARTICLES, SUB_THEME_EVENTS)
