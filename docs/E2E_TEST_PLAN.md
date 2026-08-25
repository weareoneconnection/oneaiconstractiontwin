# End-to-End Test Plan

## Automated gate

```bash
PYTHONPATH=apps/api python -m pytest -q
```

The inherited v0.1-v0.6 tests must remain green, followed by v0.7 enterprise tests for authentication, migration readiness, tenant isolation, audit and recovery.

## Live-service gate
With API and worker running:

```bash
python scripts/e2e_pilot.py
```

The script covers project seed, IFC ingestion, schedule import, mapping, distributed conversion, manifest, 4D, Ask Twin, risk, forecast, simulation, agent recommendation, human approval, audit and pilot status.

## Manual release gate
- OIDC login and logout
- Least-privilege role tests
- Cross-tenant negative tests
- Upload over-limit rejection
- Invalid file rejection
- Worker termination and lease recovery
- Cache hit after repeat build
- Backup and clean-environment restore
- Browser load of Cesium Workers/Assets
- Large-model memory and initial-load measurement
- Evidence drill-down from Ask Twin
