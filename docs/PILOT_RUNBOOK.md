# Enterprise Pilot Runbook

## Pilot scenario
**Steel Structure Schedule Intelligence**

## Required inputs
- IFC model
- Baseline schedule exported from P6/MS Project/CSV
- Daily reports
- Progress photos
- RFI/NCR
- Inspection records

## Acceptance workflow
1. Create organization and project.
2. Import IFC and inspect generated Twin Entities.
3. Import schedule.
4. Review BIM-to-schedule mapping confidence.
5. Build distributed GLB/3D Tiles assets.
6. Load Cesium/Three.js viewer.
7. Play 4D timeline.
8. Link project evidence.
9. Ask a delay-cause question.
10. Confirm every formal claim has evidence.
11. Generate risk and forecast.
12. Run a what-if scenario.
13. Run Project Director Agent.
14. Approve action with an authorized human role.
15. Review audit records.
16. Create, verify and restore a backup.

## Target business output
- Planned vs actual status
- Delay cause and cited source records
- Downstream impact
- P10/P50/P90 delay forecast
- At least three mitigation scenarios
- Human-approved action
- Exportable audit/evidence trail

## Pilot SLO targets
- Normal API P95 under 500 ms in agreed test environment
- Ask Twin first response under 5 seconds, excluding provider outage
- Project page under 3 seconds after cache warm-up
- Medium BIM first view under 10 seconds on agreed network/device
- 99.5% availability target during the controlled pilot
- 100% critical-action audit coverage
- 100% formal AI-claim evidence coverage or an explicit provisional label
