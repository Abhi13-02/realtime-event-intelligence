FROM python:3.13-slim-bookworm

# Forces Python to flush stdout/stderr immediately instead of buffering.
# Without this, log output may not appear until the buffer fills up.
# Critical for debugging — you want to see logs in real time in Docker.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# HEALTHCHECK tells Docker how to verify the app is actually healthy (not just started).
# Docker Compose uses this to know when 'backend' is ready before starting dependents.
# --start-period=10s gives the app 10 seconds to boot before checks begin.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
