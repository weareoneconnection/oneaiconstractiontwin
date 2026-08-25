from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.version import APP_NAME, APP_VERSION


API_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = (API_ROOT.parent.parent if API_ROOT.name == "api" and API_ROOT.parent.name == "apps" else API_ROOT)


class Settings(BaseSettings):
    # Application
    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    app_env: Literal["development", "test", "staging", "production", "docker"] = "development"
    log_level: str = "INFO"
    public_base_url: str = "http://127.0.0.1:8000"
    web_base_url: str = "http://localhost:3000"

    # Persistence / migrations
    database_url: str = "sqlite:///./construction_twin.db"
    auto_migrate: bool = True
    require_migration_head: bool = True
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Cache / coordination
    redis_url: str = "redis://localhost:6379/0"
    redis_required: bool = False

    # HTTP / browser security
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    force_https: bool = False
    security_headers_enabled: bool = True
    max_upload_mb: int = 512
    allowed_upload_extensions: str = ".ifc,.glb,.gltf,.json,.csv,.pdf,.docx,.xlsx,.jpg,.jpeg,.png"

    # Authentication: headers is local-development compatibility only.
    auth_mode: Literal["headers", "jwt", "oidc", "hybrid"] = "hybrid"
    allow_dev_header_auth: bool = True
    jwt_secret: str = "development-only-change-me-32-chars!!"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "oneai-construction-twin"
    jwt_audience: str = "construction-twin-api"
    jwt_exp_minutes: int = 60
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_algorithms: str = "RS256"
    # Public client id used by the browser for Authorization Code + PKCE. A single-page
    # application holds no client secret, so this value is not confidential.
    oidc_client_id: str = ""
    oidc_scopes: str = "openid profile email"
    # Which claims carry the tenant scope. Identity providers name these differently,
    # and Keycloak emits nothing of the sort until a mapper is configured, so both the
    # claim name and a fallback are configurable.
    oidc_tenant_claim: str = "tenant_id"
    oidc_organization_claim: str = "organization_id"
    oidc_default_tenant: str = ""
    oidc_default_organization: str = ""
    api_key_records_json: str = "{}"

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 240
    rate_limit_window_seconds: int = 60
    rate_limit_fail_open: bool = True
    # X-Forwarded-For is only honoured when the API actually runs behind a trusted
    # proxy. Otherwise any client could rotate the header to reset its own quota.
    trust_forwarded_for: bool = False

    # S3 / MinIO
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "oneai"
    s3_secret_key: str = "oneai-secret"
    s3_bucket: str = "construction-twin"
    s3_region: str = "us-east-1"

    # Runtime data roots
    upload_root: str = str(PROJECT_ROOT / "data" / "uploads")
    generated_asset_root: str = str(PROJECT_ROOT / "data" / "generated-assets")

    # Distributed asset pipeline inherited from v0.6
    asset_storage_backend: Literal["local", "s3"] = "local"
    asset_local_root: str = ""
    # Set this only when the API and the workers genuinely share one filesystem
    # (a compose volume, or a Kubernetes ReadWriteMany claim). On a platform where
    # each service gets its own disk, local storage cannot work across containers.
    asset_local_shared: bool = False
    asset_object_prefix: str = "v07"
    asset_work_root: str = ""
    asset_worker_poll_seconds: float = 1.0
    asset_worker_lease_seconds: int = 180
    asset_job_max_attempts: int = 3
    asset_partition_max_entities: int = 64
    asset_partition_max_triangles: int = 1_000_000
    asset_max_triangles_per_entity: int = 120_000
    asset_compression: str = "none"
    gltf_transform_bin: str = "gltf-transform"

    # Readiness / worker state
    require_asset_worker: bool = False
    worker_heartbeat_seconds: int = 15
    worker_stale_after_seconds: int = 90
    provider_health_required: bool = False

    # OneAI ecosystem integrations. An empty URL means "not configured", and the
    # corresponding adapter reports that rather than pretending to work.
    oneai_core_url: str = ""
    oneai_core_api_key: str = ""
    #: OneAI Core is an OpenAI-compatible gateway, so the model is a routing string it
    #: resolves ("openai:gpt-4o-mini", "anthropic:claude-...", and so on). Changing
    #: providers is a configuration change here, not a code change.
    oneai_core_model: str = "openai:gpt-4o-mini"
    oneai_core_max_tokens: int = 700
    oneai_core_temperature: float = 0.2
    onefield_url: str = ""
    onefield_api_key: str = ""
    oneforge_url: str = ""
    oneforge_api_key: str = ""
    oneclaw_url: str = ""
    oneclaw_api_key: str = ""
    integration_timeout_seconds: float = 20.0
    #: OneClaw actuates in the physical world. A URL alone must never be enough to let
    #: this system act on a site; execution additionally requires this explicit opt-in,
    #: and only ever for an action a human has already approved.
    oneclaw_execution_enabled: bool = False

    # Observability
    otel_enabled: bool = False
    otel_service_name: str = "oneai-construction-twin-api"
    otel_exporter_otlp_endpoint: str = ""
    sentry_dsn: str = ""

    # Backup / recovery
    backup_root: str = str(PROJECT_ROOT / "data" / "backups")
    backup_retention_days: int = 14

    # Pilot controls
    demo_endpoints_enabled: bool = True
    pilot_name: str = "Steel Structure Schedule Intelligence"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def backup_path(self) -> Path:
        return Path(self.backup_root).expanduser().resolve()

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_root).expanduser().resolve()

    @property
    def generated_asset_path(self) -> Path:
        return Path(self.generated_asset_root).expanduser().resolve()

    @property
    def asset_work_path(self) -> Path:
        """Scratch space for materialised source models.

        Deriving this from `__file__`'s ancestors broke inside the container image,
        where the package sits at /app/app rather than apps/api/app: the index simply
        ran off the end of the path and raised IndexError.
        """
        root = Path(self.asset_work_root).expanduser() if self.asset_work_root else PROJECT_ROOT / "data" / "asset-work"
        return root.resolve()

    @property
    def database_target(self) -> str:
        """Human-readable database target with the password removed.

        Startup failures like "migration is not at head" are ambiguous without it: the
        usual cause is a service pointing at a different database than it should (an
        unset DATABASE_URL silently falls back to local SQLite). Credentials are
        stripped so this is safe to print in logs.
        """
        url = self.database_url
        if "://" not in url:
            return url
        scheme, _, remainder = url.partition("://")
        if "@" in remainder:
            credentials, _, host = remainder.rpartition("@")
            user = credentials.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}"
        return f"{scheme}://{remainder}"

    @property
    def libpq_database_url(self) -> str:
        """The database URL in the form libpq tools accept.

        `pg_dump` and `pg_restore` do not understand SQLAlchemy's `+driver` suffix, so
        the backup path must strip it.
        """
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [value.strip() for value in self.trusted_hosts.split(",") if value.strip()]

    @property
    def oidc_algorithm_list(self) -> list[str]:
        return [value.strip() for value in self.oidc_algorithms.split(",") if value.strip()]

    @property
    def allowed_extension_set(self) -> set[str]:
        return {
            value.strip().lower() if value.strip().startswith(".") else f".{value.strip().lower()}"
            for value in self.allowed_upload_extensions.split(",")
            if value.strip()
        }

    @model_validator(mode="after")
    def normalize_database_url(self) -> "Settings":
        """Validate and normalise the database URL before anything tries to connect.

        Two failure modes are handled here because both produce unreadable errors
        otherwise:

        * An empty value. A platform variable that references a service which does not
          resolve (a misspelled `${{Postgres.DATABASE_URL}}`) arrives as an empty
          string, which overrides the default and reaches SQLAlchemy as ''. The
          resulting `Could not parse SQLAlchemy URL from string ''` says nothing about
          the cause, and it repeats on every restart.
        * A driver-less PostgreSQL URL. Managed platforms hand out `postgresql://` or
          the legacy `postgres://`; SQLAlchemy maps both to psycopg2, which this project
          does not ship, so the process dies with `No module named 'psycopg2'`.
        """
        url = (self.database_url or "").strip()
        if not url:
            raise ValueError(
                "DATABASE_URL is set but empty. On a managed platform this usually means "
                "a variable reference did not resolve - on Railway use the reference "
                "${{Postgres.DATABASE_URL}} (the service name must match exactly). "
                "Remove the variable entirely to fall back to local SQLite."
            )
        self.database_url = url
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                self.database_url = "postgresql+psycopg://" + url[len(prefix):]
                break
        # Redis is a cache and wake-up channel rather than a system of record, so an
        # empty value falls back to the default instead of stopping the service.
        if not (self.redis_url or "").strip():
            self.redis_url = type(self).model_fields["redis_url"].default
        return self

    @model_validator(mode="after")
    def validate_enterprise_configuration(self) -> "Settings":
        if self.is_production:
            if self.auth_mode == "headers" or self.allow_dev_header_auth:
                raise ValueError("Production requires JWT/OIDC authentication and must disable development header auth")
            if self.auth_mode in {"jwt", "hybrid"} and (
                not self.jwt_secret or self.jwt_secret.startswith("development-only") or len(self.jwt_secret) < 32
            ):
                raise ValueError("Production JWT_SECRET must be a unique value of at least 32 characters")
            if self.auth_mode in {"oidc", "hybrid"} and not (self.oidc_issuer and self.oidc_audience):
                raise ValueError("Production OIDC requires OIDC_ISSUER and OIDC_AUDIENCE")
            if self.auth_mode in {"oidc", "hybrid"} and not self.oidc_client_id:
                # Without it the browser cannot start a sign-in, so the deployment would
                # be locked out the moment header auth is disabled.
                raise ValueError("Production OIDC requires OIDC_CLIENT_ID for the browser sign-in flow")
            if self.asset_storage_backend == "s3" and (
                not self.s3_access_key
                or not self.s3_secret_key
                or self.s3_secret_key == "oneai-secret"
            ):
                raise ValueError("Production S3/MinIO credentials must be configured")
            if "*" in self.cors_origin_list:
                raise ValueError("Wildcard CORS is prohibited in production")
            if not self.force_https:
                raise ValueError("Production requires FORCE_HTTPS=true")
            if self.demo_endpoints_enabled:
                raise ValueError("Production requires DEMO_ENDPOINTS_ENABLED=false")
        return self


settings = Settings()
