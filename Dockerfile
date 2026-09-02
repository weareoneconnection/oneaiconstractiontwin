# API image for OneAI Construction Twin (also runs the asset worker, with a different
# start command). It lives at the repository root on purpose: platforms that build a
# monorepo service auto-detect a root Dockerfile with no extra configuration, and the
# build context is the repository root, which is what the COPY paths below assume.
#
#   docker build -t construction-twin-api .
#   docker run -p 8000:8000 construction-twin-api
#   docker run construction-twin-api python -m app.workers.asset_worker
#
# The web application has its own image at apps/web/Dockerfile.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN useradd --create-home --uid 10001 oneai \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt apps/api/requirements-prod.txt apps/api/requirements-ifc.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-prod.txt

# Exact IFC geometry. Without it the viewer falls back to labelled proxy boxes, which is
# honest but not usable for a real model review. IfcOpenShell is a large wheel, so it is
# opt-in per environment: the image builds either way, and the API reports which mode it
# is in through `geometry_mode`.
ARG INSTALL_IFC=false
RUN if [ "$INSTALL_IFC" = "true" ]; then python -m pip install -r requirements-ifc.txt; fi

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
