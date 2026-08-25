# M12 Enterprise Pilot Architecture

## Core invariants

1. Everything operationally meaningful is a Twin Entity or is linked to one.
2. Every important state transition emits a domain event.
3. Every AI claim is expected to link to evidence.
4. Every agent action is policy-gated and auditable.
5. Every real-world outcome can be persisted into OneField memory.
6. Model/provider implementations are replaceable behind OneAI Core and OneForge adapters.

## Bounded contexts

- Identity & Tenant
- Project
- Twin / BIM / Spatial
- Schedule
- Documents / RFI / NCR / Quality
- Evidence
- Graph
- Risk
- Forecast / Simulation
- Agent / Action
- Audit / Events

## Evolution strategy

M1-M7 can run as a modular monolith. Maintain API and event contracts as if each bounded context were separately deployable. Split high-load capabilities first: BIM conversion, CV, document ingestion, forecasting/simulation, and agent workers.

## Enterprise readiness gates

- SSO / OIDC / MFA
- Tenant isolation tests
- Backup and restore drill
- P95 API SLOs
- Evidence coverage KPI
- Model/agent action audit coverage
- HA data services
- load test on target project size
- security review / pentest
- customer-specific data residency and retention policy
