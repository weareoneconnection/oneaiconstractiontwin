# Known Limitations

v0.7.1 is a controlled Enterprise Pilot Edition. The following are explicit boundaries.

## Reasoning and prediction

1. **No reasoning model is bundled.** With `ONEAI_CORE_URL` unset, Ask Twin answers are
   composed by a local deterministic reasoner that summarises retrieved records. Every
   response reports this in `reasoning.model_backed = false` and `reasoning.mode =
   "demonstrative-local"`, and the answer text states it. Configure the gateway for
   model-backed reasoning.
2. **Evidence retrieval is lexical (BM25 plus a small construction synonym list),** not
   semantic. It will miss records that answer a question in entirely different words.
   A vector index is the intended upgrade path; the calling contract will not change.
3. **The risk model is an uncalibrated heuristic** over measured activity slippage. Every
   response carries `calibrated: false`, the sample size and a data-quality grade.
4. **The forecast is a bootstrap over the project's own activity variance,** not a full
   CPM schedule simulation: it does not traverse the dependency network, and it treats
   critical activities as the driving set. With fewer than three measured activities it
   falls back to the recorded baseline delay and returns a warning instead of a
   confident-looking distribution. It must be calibrated on real project history before
   any contractual use.
5. **Scenario simulation runs on stated assumptions,** returned in full with every
   response (`assumptions`). They are planning defaults, not estimates for a specific
   project.
6. Agent recommendations are grounded in the current schedule but are template-composed.
   Every action is created as `pending_approval` and requires a human with
   `action:approve`. Automated equipment or robot control is not included.

## Data and integration

7. The IFC fallback parser extracts limited semantics; full accuracy requires
   IfcOpenShell and customer-model validation. Without IfcOpenShell geometry support,
   the viewer shows proxy boxes, labelled `"mode": "proxy-box"` in the API and in the UI.
8. P6 and MS Project are supported through exported data/CSV paths, not every
   proprietary native integration.
9. The relational Twin Graph is suitable for pilot scale; a dedicated graph database may
   be required for large cross-project reasoning.
10. Geometry/LOD generation is not yet benchmarked on multi-gigabyte railway/airport
    models. Partition planning streams entities rather than loading the model into
    memory, but throughput at that scale is unmeasured.

## Platform and operations

11. OIDC-ready; no identity provider is bundled or operated.
12. Audit records are hash-chained and verifiable, which makes tampering detectable. It
    does not make them immutable: WORM storage or an external notary is required for
    that.
13. The Kubernetes manifests are deployment references, not a managed production service.
14. The pilot SLO figures in `/api/v1/pilot/checklist` are operating targets. No load or
    availability testing is included in this package, and they are not a contractual SLA.
15. Regulatory, privacy, data-residency and construction-contract requirements remain
    customer- and jurisdiction-specific.
16. Production readiness requires customer-specific security review, load testing,
    recovery rehearsal and operating ownership.
