# Deploying to Railway

Target topology: four Railway services in one project.

```
 web (Next.js, Dockerfile)  ──HTTPS──▶  api (FastAPI, Dockerfile)
                                          │
                          asset-worker ───┤   same image, different start command
                                          │
                            Postgres ◀────┤
                               Redis ◀────┘
                                          ▼
                      Cloudflare R2 / S3 (generated assets)
```

`asset-worker` is not optional. It is the process that converts IFC models into
3D Tiles; without it, asset jobs stay queued forever and `/health/ready` reports
`asset_worker: false`.

---

## 1. Object storage first

Railway container filesystems are ephemeral - a redeploy discards everything written
to disk. Create an S3-compatible bucket before deploying (Cloudflare R2 is the cheapest
fit; Backblaze B2 and AWS S3 work identically) and keep its endpoint, bucket, access key
and secret at hand.

With `ASSET_STORAGE_BACKEND=s3` the distributed pipeline writes every tile and manifest
to that bucket and serves them through the authenticated `/api/v1/asset-objects/{key}`
endpoint. Nothing durable is left on local disk.

## 2. Create the project and data stores

```bash
railway login
railway init            # run from the repository root
```

In the Railway dashboard add:

- **Postgres** (`+ New` → Database → PostgreSQL)
- **Redis** (`+ New` → Database → Redis)

Redis is genuinely needed here rather than optional: it carries the worker wake-up
signal and the shared rate-limit window. With more than one API replica, the in-memory
fallback would give each replica its own quota.

## 3. Service: `api`

The API image is the repository's root `Dockerfile`, so Railway detects it
automatically. **No build configuration is needed at all** - no root directory, no
config-as-code path, no `RAILWAY_DOCKERFILE_PATH`.

| Setting | Value |
|---|---|
| Source | this repository |
| Root directory | leave as `/` |
| Build configuration | none - the root `Dockerfile` is detected automatically |
| Public domain | generate one, e.g. `twin-api.up.railway.app` |

Optional, under Settings → Deploy:

| Field | Value |
|---|---|
| Healthcheck path | `/health` |
| Restart policy | On failure, 10 retries |

Use `/health` (liveness) rather than `/health/ready` for the platform healthcheck.
Readiness includes the asset worker, so pointing the healthcheck at it would restart or
roll back the API whenever the worker is down - coupling two services that should fail
independently. Keep `/health/ready` for your own monitoring; with
`REQUIRE_ASSET_WORKER=true` it returns 503 until the worker is up, which is correct
behaviour rather than a deployment failure.

Variables: copy `.env.railway.example`, and set `AUTO_MIGRATE=true`.

If the build log still shows `railpack prepare`, the service is not seeing the root
`Dockerfile`: check that the service's root directory is `/` and that the deployment is
building the commit that contains it.

## 4. Service: `asset-worker`

| Setting | Value |
|---|---|
| Source | this repository |
| Root directory | leave as `/` |
| Build configuration | none - same root `Dockerfile` as the API |
| Custom start command | `python -m app.workers.asset_worker` |
| Public domain | none - this service must not be exposed |

Same variables as `api`, with two changes:

```bash
AUTO_MIGRATE=false            # only the api service migrates
REQUIRE_MIGRATION_HEAD=true   # refuse to start against an out-of-date schema
```

Running migrations from both services races on startup and can leave a half-applied
schema. Deploy `api` first, then the worker.

Scale conversion throughput by raising this service's replica count. The job queue lives
in Postgres with per-partition leases, so multiple workers cooperate safely and a worker
killed mid-partition has its lease recovered by the next one.

## 5. Service: `web`

| Setting | Value |
|---|---|
| Root directory | leave as `/` |
| Variable `RAILWAY_DOCKERFILE_PATH` | `apps/web/Dockerfile` (this service must override the root Dockerfile) |
| Public domain | generate one |

The web service is the only one that needs a build variable, because the root
`Dockerfile` builds the API. Set it under **Variables**, then trigger a redeploy -
the value is read at build time, so an already-running build will not pick it up.

**Set `NEXT_PUBLIC_*` as build arguments, not only as runtime variables.** Next inlines
them into the client bundle at build time; a value that exists only at runtime produces
a bundle still pointing at `http://127.0.0.1:8000`.

```
NEXT_PUBLIC_API_URL=https://twin-api.up.railway.app
NEXT_PUBLIC_TENANT_ID=demo-tenant
NEXT_PUBLIC_ORGANIZATION_ID=demo-org
NEXT_PUBLIC_USER_ID=demo-user
NEXT_PUBLIC_ROLE=platform_admin
```

After the web domain exists, set on `api`:

```
CORS_ORIGINS=https://twin-web.up.railway.app
TRUSTED_HOSTS=twin-api.up.railway.app
```

`TRUSTED_HOSTS` is enforced by middleware: if the deployed hostname is missing, every
request returns 400 before reaching a route.

## 6. Verify the deployment

```bash
curl https://<api-domain>/health
curl https://<api-domain>/health/ready        # all six checks must be ok
curl https://<api-domain>/version

python scripts/e2e_pilot.py --api https://<api-domain>
```

`e2e_pilot.py` runs the full pilot chain against the deployment and gates on the
security guarantees: no unauthenticated asset mount, cross-tenant asset access denied,
audit chain verifying, unmatched questions downgraded to provisional.

---

## What survives a redeploy

| Data | Survives | Why |
|---|---|---|
| Projects, twin entities, schedule, evidence, audit chain | ✅ | Managed Postgres |
| Uploaded IFC models | ✅ | Copied to the object store as `sources/{tenant}/...`; the database records the key, so asset rebuilds do not depend on local disk |
| Generated tiles and manifests (v0.6 job pipeline) | ✅ | Written to the object store, served via `/api/v1/asset-objects/{key}` |
| Generated assets from the **v0.5** `assets/build` endpoint | ❌ | That older pipeline writes to `GENERATED_ASSET_ROOT` on local disk. In a deployed environment use the v0.6 asset-job API (`POST /projects/{id}/bim/models/{doc}/asset-jobs`), which is what the dashboard already calls. |
| Local backup artefacts under `BACKUP_ROOT` | ❌ | Ephemeral. Push backups off-box. |

## Staging versus production mode

`APP_ENV=production` is enforced at startup by a configuration validator. The process
refuses to boot unless **all** of the following hold:

| Requirement | Variable |
|---|---|
| No development header auth | `ALLOW_DEV_HEADER_AUTH=false` |
| Real JWT secret (≥32 chars, not the default) | `JWT_SECRET` |
| OIDC configured (in `oidc`/`hybrid` mode) | `OIDC_ISSUER`, `OIDC_AUDIENCE` |
| HTTPS enforced | `FORCE_HTTPS=true` |
| Demo endpoints disabled | `DEMO_ENDPOINTS_ENABLED=false` |
| No wildcard CORS | `CORS_ORIGINS` |
| Real object-store credentials | `S3_ACCESS_KEY`, `S3_SECRET_KEY` |

**The web application has no login flow yet.** With `ALLOW_DEV_HEADER_AUTH=false` the
browser client cannot authenticate, because it currently sends identity headers rather
than obtaining a token. So the realistic sequence is:

1. Deploy with `APP_ENV=staging`, and restrict access at the edge (Railway private
   networking, an access proxy, or IP allowlisting). Do not put customer project data
   into a staging deployment reachable by URL alone.
2. Connect an identity provider (Keycloak, Microsoft Entra ID, Auth0) and implement the
   browser login flow.
3. Switch to `APP_ENV=production` with `ALLOW_DEV_HEADER_AUTH=false`.

Until step 3, treat the deployment as a controlled demonstration environment, not as a
system holding customer data.

## Backups

Railway's managed Postgres has its own backup schedule; enable it. The application's own
verified backup (database plus object store, with a checksum manifest) runs with:

```bash
# inside the running container
railway ssh --service api
python scripts/backup.py --label scheduled

# or from your machine, using the service's variables against the remote database
railway run --service api python apps/api/scripts/backup.py --label scheduled
```

Note that a local `railway run` writes the backup artefacts to your machine, while
`railway ssh` writes them inside an ephemeral container - so for anything you intend to
keep, run it locally or push the artefacts to the object store.

Restore is deliberately manual and requires an explicit confirmation token - see
`docs/BACKUP_RESTORE.md`.

## Cost expectation

For a pilot-sized deployment: api + asset-worker + Postgres + Redis lands roughly in the
**$20-40/month** range on Railway's usage-based pricing. IFC conversion is CPU-bound, so
the worker dominates cost while models are being processed and is nearly free when idle.
Object storage on R2 at pilot volumes is negligible.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Every request returns 400 | Deployed hostname missing from `TRUSTED_HOSTS` |
| Browser calls blocked by CORS | Web domain missing from `CORS_ORIGINS` |
| Asset jobs stay `queued` | `asset-worker` service not running |
| `/health/ready` 503 on `asset_worker` | Worker crashed, or `REQUIRE_ASSET_WORKER=true` with no worker |
| Tiles 404 after a redeploy | `ASSET_STORAGE_BACKEND` still `local` - the filesystem was discarded |
| Frontend calls `127.0.0.1:8000` | `NEXT_PUBLIC_API_URL` set as a runtime variable only, not as a build argument |
| Redirect loop | `FORCE_HTTPS=true` without `--proxy-headers` (already handled in the shipped Dockerfile) |
| Startup error about production configuration | Expected: see the production-mode table above |
| Container crashes with `No module named 'psycopg2'` | Fixed in v0.7.1: the app rewrites `postgresql://` to `postgresql+psycopg://`. If you see it, the deployment predates that fix |
| Container starts then every request 400s | `TRUSTED_HOSTS` empty or missing the generated domain - it is only populated after a public domain exists |
| Build log shows `railpack prepare` | The service is not using a Dockerfile: the API/worker need root directory `/`; the web service needs `RAILWAY_DOCKERFILE_PATH` |
| `COPY failed: ... not found` during build | A root directory was set on the service; the Dockerfiles expect the repository root as build context |
