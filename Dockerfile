FROM python:3.12-slim-bookworm

# Forces Python to flush stdout/stderr immediately instead of buffering.
# Without this, log output may not appear until the buffer fills up.
# Critical for debugging — you want to see logs in real time in Docker.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

# HEALTHCHECK tells Docker how to verify the app is actually healthy (not just started).
# Docker Compose uses this to know when 'backend' is ready before starting dependents.
# start-period=30s gives extra time on first run when migrations are applying.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"

CMD ["./docker-entrypoint.sh"]
