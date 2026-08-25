"""OneAI ecosystem adapters.

The construction twin does not embed a reasoning model. It either calls the
configured OneAI Core gateway, or it runs a local, deterministic reasoner that
composes an answer from the project's own retrieved records.

The local reasoner is explicitly labelled `demonstrative-local` in every response
so that no caller, dashboard or report can mistake a template for a domain model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings


@dataclass
class OneAIResult:
    text: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_model_backed(self) -> bool:
        return bool(self.metadata.get("model_backed"))


def _local_reasoning(prompt: str, context: dict[str, Any]) -> OneAIResult:
    """Deterministic summary of the retrieved context. No inference, no invention."""
    project = context.get("project") or "the project"
    planned = float(context.get("planned") or 0.0)
    actual = float(context.get("actual") or 0.0)
    variance = round(actual - planned, 1)
    excerpts: list[str] = [str(item) for item in (context.get("evidence_excerpts") or [])]

    if variance < 0:
        headline = f"{project} is {abs(variance)} percentage points behind the baseline ({actual}% actual against {planned}% planned)."
    elif variance > 0:
        headline = f"{project} is {variance} percentage points ahead of the baseline ({actual}% actual against {planned}% planned)."
    else:
        headline = f"{project} is tracking the baseline at {actual}%."

    if excerpts:
        body = " The retrieved records that mention the terms in this question are: " + " | ".join(excerpts[:3])
        confidence = 0.62
    else:
        body = " No project record matched the terms in this question."
        confidence = 0.3

    disclosure = (
        " This answer was composed by the local deterministic reasoner from retrieved "
        "project records; it is not the output of a domain-trained model."
    )
    return OneAIResult(
        text=headline + body + disclosure,
        confidence=confidence,
        metadata={
            "provider": "local",
            "model": "deterministic-record-summary",
            "mode": "demonstrative-local",
            "model_backed": False,
        },
    )


class OneAICoreAdapter:
    """Calls the OneAI Core gateway when configured; otherwise reasons locally."""

    async def reason(self, prompt: str, context: dict[str, Any]) -> OneAIResult:
        if not settings.oneai_core_url:
            return _local_reasoning(prompt, context)
        headers = {"Content-Type": "application/json"}
        if settings.oneai_core_api_key:
            headers["Authorization"] = f"Bearer {settings.oneai_core_api_key}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    settings.oneai_core_url.rstrip("/") + "/v1/reason",
                    headers=headers,
                    json={"prompt": prompt, "context": context},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # network, timeout, non-2xx or malformed payload
            result = _local_reasoning(prompt, context)
            result.metadata.update({"mode": "degraded-local-fallback", "provider_error": str(exc)})
            return result

        text = str(payload.get("text") or payload.get("answer") or "").strip()
        if not text:
            result = _local_reasoning(prompt, context)
            result.metadata.update({"mode": "degraded-local-fallback", "provider_error": "empty response"})
            return result
        return OneAIResult(
            text=text,
            confidence=float(payload.get("confidence", 0.7)),
            metadata={
                "provider": "oneai-core",
                "model": str(payload.get("model") or "unspecified"),
                "mode": "gateway",
                "model_backed": True,
            },
        )


class OneFieldAdapter:
    """Long-term project memory. Not wired into the pilot; calls are no-ops."""

    configured = False

    async def remember(self, project_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return {"stored": False, "reason": "OneField is not configured in this deployment", "project_id": project_id}


class OneForgeAdapter:
    """Capability evaluation. Not wired into the pilot; calls are no-ops."""

    configured = False

    async def evaluate(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"evaluated": False, "reason": "OneForge is not configured in this deployment", "capability": capability}


class OneClawAdapter:
    """Actuation boundary. Deliberately inert: the pilot never executes physical actions."""

    configured = False

    async def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        return {"executed": False, "reason": "Automated execution is out of scope for the pilot release", "action": action}
