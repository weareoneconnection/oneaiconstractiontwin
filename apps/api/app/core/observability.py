from __future__ import annotations

import logging
import sys

try:
    import structlog
except ImportError:
    structlog = None
from prometheus_client import Counter, Gauge, Histogram

from app.core.config import settings


HTTP_REQUESTS = Counter(
    "construction_twin_http_requests_total",
    "HTTP requests processed by the Construction Twin API",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "construction_twin_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
READINESS = Gauge(
    "construction_twin_readiness",
    "Readiness of required dependencies",
    ["component"],
)
AI_REQUESTS = Counter(
    "construction_twin_ai_requests_total",
    "AI operations",
    ["operation", "status"],
)
EVIDENCE_COVERAGE = Gauge(
    "construction_twin_ai_evidence_coverage_ratio",
    "Share of returned AI claims backed by evidence",
    ["project_id"],
)
SECURITY_EVENTS = Counter(
    "construction_twin_security_events_total",
    "Security-relevant events",
    ["event_type"],
)


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    if structlog:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(level),
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )


def configure_telemetry(app, engine) -> None:
    if settings.sentry_dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                environment=settings.app_env,
                release=f"oneai-construction-twin@{settings.app_version}",
                traces_sample_rate=0.1,
                send_default_pii=False,
            )
        except Exception as exc:
            logging.getLogger(__name__).warning("sentry_configuration_failed: %s", exc)
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({
            "service.name": settings.otel_service_name,
            "service.version": settings.app_version,
            "deployment.environment": settings.app_env,
        })
        provider = TracerProvider(resource=resource)
        if settings.otel_exporter_otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=provider)
    except Exception as exc:  # telemetry must never prevent startup
        if structlog:
            structlog.get_logger(__name__).warning("otel_configuration_failed", error=str(exc))
        else:
            logging.getLogger(__name__).warning("otel_configuration_failed: %s", exc)
