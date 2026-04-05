FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HTTP_PORT=8000

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY app /app/app
COPY scripts /app/scripts

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -e .

RUN mkdir -p /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"HTTP_PORT\", \"8000\")}/api/v1/health/livez', timeout=5)"

CMD ["sh", "-c", "python scripts/run_migrations_or_bootstrap.py && uvicorn app.main:app --host 0.0.0.0 --port ${HTTP_PORT:-8000}"]
