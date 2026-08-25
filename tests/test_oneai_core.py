"""OneAI Core gateway integration.

These tests run against a local stub that speaks the gateway's OpenAI-compatible
contract, so the HTTP path, the prompt construction, the degraded fallback and the
citation check are all exercised without a network or an API key.

What they pin down is the part that matters for an evidence-first product: the model
must be given only the retrieved records, and anything it claims beyond them must be
detectable.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "apps", "api")))

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

RECEIVED: list[dict] = []
REPLY: dict = {}


class StubGateway(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        RECEIVED.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        status = REPLY.get("status", 200)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(REPLY.get("payload", {})).encode())

    def log_message(self, *_args):  # keep the test output clean
        return


@pytest.fixture(scope="module")
def gateway():
    server = HTTPServer(("127.0.0.1", 0), StubGateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(autouse=True)
def configured(gateway, monkeypatch):
    RECEIVED.clear()
    REPLY.clear()
    REPLY.update(
        {
            "status": 200,
            "payload": {
                "id": "chatcmpl_stub",
                "model": "gpt-4o-mini-2024-07-18",
                "provider": "openai",
                "choices": [{"message": {"role": "assistant", "content": "Crane C02 was unavailable [DR-241]."}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "estimated_cost_usd": 0.00003},
                "oneai": {"trace": {"mode": "cheap", "fallbackUsed": False, "latencyMs": 900}},
            },
        }
    )
    monkeypatch.setattr(settings, "oneai_core_url", gateway)
    monkeypatch.setattr(settings, "oneai_core_api_key", "test-key")
    monkeypatch.setattr(settings, "oneai_core_model", "openai:gpt-4o-mini")
    yield


def headers(tenant: str, organization: str) -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Organization-ID": organization, "X-User-ID": "tester", "X-Role": "platform_admin"}


def seed(client: TestClient, tenant: str, organization: str) -> str:
    return client.post("/api/v1/demo/seed", headers=headers(tenant, organization)).json()["project_id"]


def test_the_model_receives_only_retrieved_records_and_the_evidence_policy():
    with TestClient(app) as client:
        head = headers("core-tenant", "core-org")
        project_id = seed(client, "core-tenant", "core-org")
        answer = client.post(
            f"/api/v1/projects/{project_id}/ask", headers=head, json={"question": "Why was the crane unavailable?"}
        ).json()

        assert RECEIVED, "the gateway was not called"
        call = RECEIVED[-1]
        assert call["path"] == "/v1/chat/completions"
        assert call["auth"] == "Bearer test-key"
        assert call["body"]["model"] == "openai:gpt-4o-mini"

        system, user = call["body"]["messages"]
        assert system["role"] == "system"
        # The policy is instructed, not merely enforced afterwards.
        assert "ONLY from the project records" in system["content"]
        assert "Never fill a gap" in system["content"]
        assert "Cite the record identifiers" in system["content"]

        # The retrieved record is present; unrelated project data is not smuggled in.
        assert "DR-241" in user["content"]
        assert "Crane C02" in user["content"]
        assert "QUESTION" in user["content"]

        assert answer["reasoning"]["model_backed"] is True
        assert answer["reasoning"]["provider"] == "openai"
        assert answer["reasoning"]["usage"]["total_tokens"] == 120
        assert answer["reasoning"]["usage"]["estimated_cost_usd"] == 0.00003


def test_a_fabricated_citation_is_detected_and_lowers_confidence():
    """The worst failure mode for this product is a confident, invented source."""
    REPLY["payload"]["choices"] = [
        {"message": {"content": "The delay was caused by a permit issue [RFI-999] and crane downtime [DR-241]."}}
    ]
    with TestClient(app) as client:
        head = headers("citation-tenant", "citation-org")
        project_id = seed(client, "citation-tenant", "citation-org")
        answer = client.post(
            f"/api/v1/projects/{project_id}/ask", headers=head, json={"question": "Why was the crane unavailable?"}
        ).json()

        citations = answer["reasoning"]["citations"]
        assert "DR-241" in citations["verified"]
        assert "RFI-999" in citations["unverified"]
        # The reader is told, in the answer itself, which reference could not be checked.
        assert "RFI-999" in answer["answer"]
        assert "unverified" in answer["answer"].lower()
        assert answer["confidence"] <= 0.45


def test_a_failing_gateway_degrades_to_the_local_reasoner():
    REPLY["status"] = 503
    REPLY["payload"] = {"error": "upstream unavailable"}
    with TestClient(app) as client:
        head = headers("degrade-tenant", "degrade-org")
        project_id = seed(client, "degrade-tenant", "degrade-org")
        answer = client.post(
            f"/api/v1/projects/{project_id}/ask", headers=head, json={"question": "Why was the crane unavailable?"}
        ).json()

        # An outage must not become an outage of the product.
        assert answer["reasoning"]["mode"] == "degraded-local-fallback"
        assert answer["reasoning"]["model_backed"] is False
        assert answer["reasoning"]["provider_error"]
        assert "not the output of a domain-trained model" in answer["answer"]


def test_an_empty_completion_is_treated_as_a_failure_not_an_answer():
    REPLY["payload"]["choices"] = [{"message": {"content": "   "}}]
    with TestClient(app) as client:
        head = headers("empty-tenant", "empty-org")
        project_id = seed(client, "empty-tenant", "empty-org")
        answer = client.post(
            f"/api/v1/projects/{project_id}/ask", headers=head, json={"question": "Why was the crane unavailable?"}
        ).json()
        assert answer["reasoning"]["mode"] == "degraded-local-fallback"
        assert answer["answer"].strip()


def test_an_unmatched_question_stays_provisional_even_with_a_model_behind_it():
    REPLY["payload"]["choices"] = [{"message": {"content": "Foundations normally require C30/37 concrete."}}]
    with TestClient(app) as client:
        head = headers("provisional-core-tenant", "provisional-core-org")
        project_id = seed(client, "provisional-core-tenant", "provisional-core-org")
        answer = client.post(
            f"/api/v1/projects/{project_id}/ask",
            headers=head,
            json={"question": "What concrete grade does the helipad slab require?"},
        ).json()

        # The model answered from general knowledge; retrieval found nothing, so the
        # response is still marked provisional and capped.
        assert answer["evidence"] == []
        assert answer["provisional"] is True
        assert answer["confidence"] <= 0.4
        assert "provisional" in answer["answer"].lower()


def test_the_api_key_never_appears_in_an_error_returned_to_the_caller(monkeypatch):
    monkeypatch.setattr(settings, "oneai_core_url", "http://127.0.0.1:9/unreachable")
    monkeypatch.setattr(settings, "oneai_core_api_key", "oak_supersecret_value")
    with TestClient(app) as client:
        head = headers("secret-tenant", "secret-org")
        project_id = seed(client, "secret-tenant", "secret-org")
        answer = client.post(
            f"/api/v1/projects/{project_id}/ask", headers=head, json={"question": "Why was the crane unavailable?"}
        ).json()
        assert "oak_supersecret_value" not in json.dumps(answer)
