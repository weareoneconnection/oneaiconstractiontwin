# Build context is the REPOSITORY ROOT, not apps/api:
#   docker build -f apps/api/Dockerfile .
# A monorepo service on Railway builds from the repo root, and a Dockerfile whose
# COPY paths assume its own directory cannot be built there.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN useradd --create-home --uid 10001 oneai \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt apps/api/requirements-prod.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-prod.txt

COPY apps/api/app ./app
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/scripts ./scripts
COPY apps/api/entrypoint.sh ./entrypoint.sh

RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /data/uploads /data/generated-assets /data/object-store /data/asset-work /backups \
    && chown -R oneai:oneai /app /data /backups

USER oneai
EXPOSE 8000
ENV PORT=8000
ENTRYPOINT ["/app/entrypoint.sh"]
# Shell form so $PORT injected by the platform (Railway, Cloud Run, Heroku) is honoured.
# --forwarded-allow-ips is required behind a platform proxy, otherwise uvicorn reports
# the proxy as the client and ignores X-Forwarded-* entirely.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
