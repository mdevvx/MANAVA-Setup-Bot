# MANAVA Multiverse Discord bot — single service: Discord gateway client +
# aiohttp MANAVA webhook receiver in one process, listening on $PORT.
#
# The image does NOT run database migrations. The deploy pipeline must run
#   python -m scripts.run_migrations
# against the target database once per release, before starting the container
# (see docs/deployment.md).

FROM python:3.12-slim AS base

# - PYTHONDONTWRITEBYTECODE: no .pyc in the image
# - PYTHONUNBUFFERED: logs stream straight to stdout for the platform's collector
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Dependencies first, so a code-only change doesn't reinstall them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (src/ carries the SQL migrations under src/db/migrations/).
COPY src ./src
COPY scripts ./scripts
COPY Procfile ./

# Run as an unprivileged user.
RUN useradd --system --no-create-home --uid 10001 manava \
    && chown -R manava:manava /app
USER manava

EXPOSE 8080

# GET /healthz on the webhook port (no auth) — usable as the platform health check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8080') + '/healthz', timeout=3)"]

CMD ["python", "-m", "src.main"]
