"""OneAI ecosystem adapters.

Each adapter is configured by a URL. An empty URL means the capability is absent, and
every call then returns a result that says so — no adapter fabricates success, because a
fabricated integration result is indistinguishable from a working one until it matters.

Failures degrade in the way each capability deserves:

* **OneAI Core** (reasoning) falls back to the local deterministic reasoner and labels
  the answer `degraded-local-fallback`.
* **OneField** (memory) and **OneForge** (evaluation) fail soft: they are enrichment, and
  the request they accompany must still succeed.
* **OneClaw** (actuation) fails closed, and is additionally gated behind an explicit
  opt-in. Acting on a construction site is not something a URL should be able to enable
  by itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


@dataclass
class OneAIResult:
    text: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_model_backed(self) -> bool:
        return bool(self.metadata.get("model_backed"))


class _Service:
    """Shared HTTP behaviour: auth header, timeout, and a uniform probe.

    Configuration is read on every access rather than captured in __init__. Adapters are
    module-level singletons, so capturing at construction time froze whatever the
    environment happened to be at import — which made the integration impossible to
    reconfigure or to test.
    """

    name = "service"
    url_field = ""
    key_field = ""

    @property
    def _url(self) -> str:
        return str(getattr(settings, self.url_field, "") or "").rstrip("/")

    @property
    def _api_key(self) -> str:
        return str(getattr(settings, self.key_field, "") or "")

    @property
    def configured(self) -> bool:
        return bool(self._url)

    @property
    def base_url(self) -> str:
        return self._url

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "User-Agent": f"construction-twin/{settings.app_version}"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _redact(self, text: str) -> str:
        """Never let a key reach a log line or an API response."""
        key = self._api_key
        return text.replace(key, "***") if key and key in text else text

    async def _post(self, path: str, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout or settings.integration_timeout_seconds) as client:
            response = await client.post(f"{self._url}{path}", headers=self._headers(), json=payload)
            response.raise_for_status()
            return dict(response.json())

    async def probe(self) -> dict[str, Any]:
        """Liveness of the remote service, used by readiness and the admin view."""
        if not self.configured:
            return {"service": self.name, "configured": False, "reachable": False, "detail": "No URL configured"}
        import time

        started = time.perf_counter()
        for path in ("/health", "/healthz", "/"):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{self._url}{path}", headers=self._headers())
                if response.status_code < 500:
                    return {
                        "service": self.name,
                        "configured": True,
                        "reachable": True,
                        "status_code": response.status_code,
                        "probe_path": path,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "url": self._url,
                    }
            except Exception as exc:  # try the next candidate path
                last_error = str(exc)
                continue
        else:
            last_error = locals().get("last_error", "no health endpoint responded")
        return {
            "service": self.name,
            "configured": True,
            "reachable": False,
            "detail": last_error,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "url": self._url,
        }


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


SYSTEM_PROMPT = """You are the reasoning engine of a construction digital twin.

Answer ONLY from the project records supplied in the user message. These records are the
complete evidence available to you.

Rules, in order of precedence:
1. If the records do not support an answer, say exactly that and stop. Never fill a gap
   with general construction knowledge, an assumption, or a plausible guess.
2. Cite the record identifiers you used, in square brackets, e.g. [DR-241].
3. Do not invent dates, quantities, activity identifiers or causes that are not in the
   records. Quantities and dates must be copied, not estimated.
4. State a cause only if a record states it. If records show correlation but not cause,
   say what the records show and that the cause is not established.
5. Be concise: a site team reads this on a phone. Three or four sentences.

You are answering for a contractual, safety-relevant context. An answer that is honest
about what is unknown is more valuable than one that sounds complete."""


def _build_messages(question: str, context: dict[str, Any]) -> list[dict[str, str]]:
    """Compose an evidence-grounded prompt.

    The model receives the retrieved records and the measured schedule position, and
    nothing else. Everything it is allowed to assert therefore has a source the caller
    can open.
    """
    lines: list[str] = ["PROJECT RECORDS", ""]
    records = context.get("evidence_records") or []
    if records:
        for record in records:
            lines.append(f"[{record.get('source_id')}] ({record.get('source_type')}) {record.get('content')}")
    else:
        lines.append("(No project record matched this question.)")

    lines += ["", "MEASURED POSITION", ""]
    lines.append(f"Project: {context.get('project')}")
    lines.append(f"Planned progress: {context.get('planned')}% · actual progress: {context.get('actual')}%")
    if context.get("forecast_delay_days") is not None:
        lines.append(f"Recorded baseline delay: {context.get('forecast_delay_days')} days")
    late = context.get("late_activities") or []
    if late:
        lines.append("Activities behind plan (measured from the schedule):")
        for item in late:
            lines.append(f"  - {item.get('external_id')} {item.get('name')}: slipped {item.get('slip_days')} days")
    else:
        lines.append("No activity is recorded as behind plan.")

    lines += ["", "QUESTION", "", question]
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(lines)}]


class OneAICoreAdapter(_Service):
    """Reasoning gateway (OpenAI-compatible). Falls back to the local reasoner, never to silence."""

    name = "oneai_core"
    url_field = "oneai_core_url"
    key_field = "oneai_core_api_key"

    async def reason(self, prompt: str, context: dict[str, Any]) -> OneAIResult:
        if not self.configured:
            return _local_reasoning(prompt, context)

        body = {
            "model": settings.oneai_core_model,
            "messages": _build_messages(prompt, context),
            "max_completion_tokens": settings.oneai_core_max_tokens,
            "temperature": settings.oneai_core_temperature,
        }
        try:
            payload = await self._post("/v1/chat/completions", body)
        except Exception as exc:
            result = _local_reasoning(prompt, context)
            result.metadata.update({"mode": "degraded-local-fallback", "provider_error": self._redact(str(exc))})
            log.warning("OneAI Core unavailable, answered locally: %s", self._redact(str(exc)))
            return result

        choices = payload.get("choices") or []
        text = ""
        if choices:
            text = str((choices[0].get("message") or {}).get("content") or "").strip()
        if not text:
            result = _local_reasoning(prompt, context)
            result.metadata.update({"mode": "degraded-local-fallback", "provider_error": "empty completion"})
            return result

        trace = payload.get("oneai", {}).get("trace", {}) if isinstance(payload.get("oneai"), dict) else {}
        usage = payload.get("usage") or {}
        return OneAIResult(
            text=text,
            # The gateway returns no calibrated confidence, and inventing one would be
            # exactly the false precision this product removes elsewhere. The caller
            # scales this by measured evidence coverage.
            confidence=0.75,
            metadata={
                "provider": str(payload.get("provider") or "oneai-core"),
                "model": str(payload.get("model") or settings.oneai_core_model),
                "mode": "gateway",
                "model_backed": True,
                "request_id": payload.get("id"),
                "routed_mode": trace.get("mode"),
                "fallback_used": trace.get("fallbackUsed"),
                "latency_ms": trace.get("latencyMs"),
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "estimated_cost_usd": usage.get("estimated_cost_usd"),
                },
            },
        )


class OneFieldAdapter(_Service):
    """Long-term project memory. Enrichment: it must never fail the request it rides on."""

    name = "onefield"
    url_field = "onefield_url"
    key_field = "onefield_api_key"

    async def remember(self, project_id: str, event: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            return {"stored": False, "reason": "OneField is not configured in this deployment", "project_id": project_id}
        try:
            payload = await self._post("/v1/memories", {"project_id": project_id, "event": event})
            return {"stored": True, "project_id": project_id, **payload}
        except Exception as exc:
            log.warning("OneField write failed (non-fatal): %s", exc)
            return {"stored": False, "reason": f"OneField unavailable: {exc}", "project_id": project_id}

    async def recall(self, project_id: str, query: str, limit: int = 5) -> dict[str, Any]:
        if not self.configured:
            return {"available": False, "memories": [], "reason": "OneField is not configured in this deployment"}
        try:
            payload = await self._post("/v1/memories/search", {"project_id": project_id, "query": query, "limit": limit})
            return {"available": True, "memories": payload.get("memories", []), **{k: v for k, v in payload.items() if k != "memories"}}
        except Exception as exc:
            return {"available": False, "memories": [], "reason": f"OneField unavailable: {exc}"}


class OneForgeAdapter(_Service):
    """Capability evaluation, used to gate releases. Enrichment: fails soft."""

    name = "oneforge"
    url_field = "oneforge_url"
    key_field = "oneforge_api_key"

    async def evaluate(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            return {"evaluated": False, "reason": "OneForge is not configured in this deployment", "capability": capability}
        try:
            result = await self._post("/v1/evaluations", {"capability": capability, "payload": payload})
            return {"evaluated": True, "capability": capability, **result}
        except Exception as exc:
            return {"evaluated": False, "capability": capability, "reason": f"OneForge unavailable: {exc}"}


class OneClawExecutionDenied(Exception):
    """Raised when execution is requested but the safety conditions are not met."""


class OneClawAdapter(_Service):
    """Actuation boundary.

    Three conditions must all hold before anything is dispatched: the service is
    configured, execution is explicitly enabled, and the action carries a human
    approval. Any one of them missing means the call is refused - loudly, and with the
    reason, because a silently skipped actuation is the worst possible outcome here.
    """

    name = "oneclaw"
    url_field = "oneclaw_url"
    key_field = "oneclaw_api_key"

    @property
    def execution_enabled(self) -> bool:
        return bool(self.configured and settings.oneclaw_execution_enabled)

    def refusal_reason(self, approved_by: str | None) -> str | None:
        if not self.configured:
            return "OneClaw is not configured in this deployment"
        if not settings.oneclaw_execution_enabled:
            return "Automated execution is disabled (set ONECLAW_EXECUTION_ENABLED=true to allow it)"
        if not approved_by:
            return "The action has not been approved by a human"
        return None

    async def _post_task(
        self,
        payload: dict[str, Any],
        idempotency_key: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """POST a task graph, keyed so a repeated dispatch cannot act twice.

        OneClaw stores the idempotency key and returns the original task for a
        repeat, which is what makes it safe to retry a dispatch that failed
        somewhere between here and there without a second notification reaching
        the site team.
        """
        headers = self._headers()
        headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=timeout or settings.oneclaw_dispatch_timeout_seconds) as client:
            response = await client.post(f"{self._url}/v1/tasks/run", headers=headers, json=payload)
            response.raise_for_status()
            return dict(response.json())

    def _post_task_sync(
        self,
        payload: dict[str, Any],
        idempotency_key: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Synchronous twin of _post_task.

        dispatch runs inside a FastAPI sync endpoint, which Starlette executes in
        an anyio worker thread. Driving httpx.AsyncClient there via asyncio.run
        creates a fresh event loop in a thread that has none of the main thread's
        loop machinery, and the connection fails with an exception whose str is
        empty — surfacing as the maddening "OneClaw unavailable:" with no reason.
        A plain synchronous client has no event loop to misplace, so the request
        behaves the same on every thread.
        """
        headers = self._headers()
        headers["Idempotency-Key"] = idempotency_key
        with httpx.Client(timeout=timeout or settings.oneclaw_dispatch_timeout_seconds) as client:
            response = client.post(f"{self._url}/v1/tasks/run", headers=headers, json=payload)
            response.raise_for_status()
            return dict(response.json())

    async def execute(self, action: dict[str, Any], approved_by: str | None = None) -> dict[str, Any]:
        """Run a single capability. Kept for callers that need one step only."""
        refusal = self.refusal_reason(approved_by)
        if refusal:
            return {"executed": False, "reason": refusal, "action_id": action.get("id")}

        action_id = str(action.get("id") or "")
        body = {
            # OneClaw's contract: `action` is a capability name and `input` is its
            # payload. Sending the whole action object here is what silently broke
            # this integration before - it 404'd against a path that never existed.
            "action": str(action.get("action") or action.get("capability") or ""),
            "input": dict(action.get("input") or {}),
            "approvalMode": "auto",
        }
        if not body["action"]:
            return {"executed": False, "action_id": action_id, "reason": "The action carries no capability name"}

        headers = self._headers()
        if action_id:
            headers["Idempotency-Key"] = action_id
        try:
            async with httpx.AsyncClient(timeout=settings.oneclaw_dispatch_timeout_seconds) as client:
                response = await client.post(f"{self._url}/v1/actions/execute", headers=headers, json=body)
                response.raise_for_status()
                result = dict(response.json())
        except Exception as exc:
            # Fail closed and say so: the caller must not assume the site acted.
            log.error("OneClaw execution failed for action %s: %s", action_id, exc)
            return {"executed": False, "action_id": action_id, "reason": f"OneClaw unavailable: {self._redact(str(exc))}"}
        return {"executed": True, "action_id": action_id, **result}

    async def dispatch_notification(
        self,
        *,
        action_id: str,
        project_id: str,
        approved_by: str,
        subject: str,
        body: str,
        recipients: list[dict[str, Any]],
        summary: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send an approved action out for delivery, then have it reported back.

        Two steps, not one. The report is a separate step so that a delivery that
        succeeded and a write-back that failed are distinguishable in OneClaw's
        task graph, and so the write-back can be retried on its own. A single
        fire-and-forget step would leave this twin unable to tell "delivered" from
        "never happened".
        """
        refusal = self.refusal_reason(approved_by)
        if refusal:
            return {"dispatched": False, "reason": refusal, "action_id": action_id}

        payload = self._dispatch_payload(
            action_id=action_id,
            project_id=project_id,
            approved_by=approved_by,
            subject=subject,
            body=body,
            recipients=recipients,
            summary=summary,
            attachments=attachments,
        )

        try:
            result = await self._post_task(payload, idempotency_key=action_id)
        except Exception as exc:
            log.error("OneClaw dispatch failed for action %s: %s", action_id, exc)
            return {"dispatched": False, "action_id": action_id, "reason": f"OneClaw unavailable: {self._redact(str(exc))}"}

        return self._dispatch_result(action_id, result)

    def _dispatch_payload(
        self,
        *,
        action_id: str,
        project_id: str,
        approved_by: str,
        subject: str,
        body: str,
        recipients: list[dict[str, Any]],
        summary: str,
        attachments: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """The two-step task graph: deliver, then report the outcome back.

        The report is a separate step so a delivery that succeeded and a
        write-back that failed stay distinguishable, and so the write-back can be
        retried on its own.
        """
        return {
            "taskName": f"twin-action-{action_id}",
            "approvalMode": "auto",
            "metadata": {
                "source": "construction-twin",
                "actionId": action_id,
                "projectId": project_id,
                "idempotencyKey": action_id,
            },
            "steps": [
                {
                    "id": "notify",
                    "action": "twin.notify.stakeholders",
                    "input": {
                        "actionId": action_id,
                        "projectId": project_id,
                        "approvedBy": approved_by,
                        "subject": subject,
                        "body": body,
                        "recipients": recipients,
                        "attachments": attachments or [],
                    },
                },
                {
                    "id": "report",
                    "action": "twin.action.report",
                    "dependsOn": ["notify"],
                    "input": {
                        "actionId": action_id,
                        "outcome": "executed",
                        "summary": summary,
                        # Resolved by OneClaw from the notify step. Its worker refuses to report
                        # an unresolved template rather than filing blank receipts as proof.
                        "receipts": "{{notify.output.deliveries}}",
                    },
                },
            ],
        }

    def dispatch_notification_sync(
        self,
        *,
        action_id: str,
        project_id: str,
        approved_by: str,
        subject: str,
        body: str,
        recipients: list[dict[str, Any]],
        summary: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Synchronous dispatch, for callers that are already on a worker thread.

        The approval endpoint is one of them. See _post_task_sync for why the
        async path fails there — briefly, asyncio.run in an anyio worker thread
        builds a loop with no working networking and dies with an empty error.
        """
        refusal = self.refusal_reason(approved_by)
        if refusal:
            return {"dispatched": False, "reason": refusal, "action_id": action_id}

        payload = self._dispatch_payload(
            action_id=action_id,
            project_id=project_id,
            approved_by=approved_by,
            subject=subject,
            body=body,
            recipients=recipients,
            summary=summary,
            attachments=attachments,
        )

        try:
            result = self._post_task_sync(payload, idempotency_key=action_id)
        except Exception as exc:
            log.error("OneClaw dispatch failed for action %s: %s", action_id, exc)
            return {"dispatched": False, "action_id": action_id, "reason": f"OneClaw unavailable: {self._redact(str(exc))}"}

        return self._dispatch_result(action_id, result)

    def _dispatch_result(self, action_id: str, result: dict[str, Any]) -> dict[str, Any]:
        task = result.get("task") if isinstance(result.get("task"), dict) else result
        return {
            "dispatched": True,
            "action_id": action_id,
            "task_id": str((task or {}).get("id") or ""),
            "task_status": str((task or {}).get("status") or ""),
            "idempotent": bool(result.get("idempotent")),
        }


def all_adapters() -> list[_Service]:
    return [OneAICoreAdapter(), OneFieldAdapter(), OneForgeAdapter(), OneClawAdapter()]
