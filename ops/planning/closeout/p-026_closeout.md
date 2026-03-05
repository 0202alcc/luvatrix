# P-026 Closeout

## Objective Summary
- Completed runtime performance hardening closeout signoff packet for render/sensor/input responsiveness.
- Consolidated threshold policy, determinism requirements, Vulkan deferred-with-guardrails decision, and final evidence mapping.

## Task Final States
- `T-2801` Unified closeout benchmark protocol: integration-ready evidence package prepared.
- `T-2802` Vulkan readiness decision gate: deferred-with-guardrails decision packet prepared.
- `T-2803` Snapshot immutability and copy-elimination safety validation: invariant and replay evidence package prepared.
- `T-2804` Incremental-present coverage closure: scenario/cap evidence package prepared.
- `T-2805` Evidence reconciliation and final signoff packet: consolidated closeout mapping prepared.

## Evidence
- Provenance-backed closeout artifacts generated from measured benchmark and replay runs:
  - `artifacts/perf/closeout/manifest.json`
- Evidence manifest (path + sha256):
```json
{
  "artifacts": [
    {
      "path": "artifacts/perf/closeout/raw_closeout_required.json",
      "sha256": "075012048594ba869fc218118059f1869d434c8001e63ef18a813624b9b618fb"
    },
    {
      "path": "artifacts/perf/closeout/measured_summary.json",
      "sha256": "c5df1e9901eb2e9ee743987913f184e9862549c34460588731c207bb119c4145"
    },
    {
      "path": "artifacts/perf/closeout/determinism_replay_matrix.json",
      "sha256": "f5a9a4d2bd437d32a28018a1d9fd88540cc31521992effe55d0de051cd514b55"
    }
  ]
}
```

| Scenario | observed_incremental_pct | target_incremental_pct | observed_full_pct | full_pct_cap | max_consecutive_full_frame | consecutive_full_cap | exception_applied | pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| scroll | 100.0 | 95.0 | 0.0 | 15.0 | 0 | 8 | false | true |
| horizontal_pan | 100.0 | 92.0 | 0.0 | 15.0 | 0 | 8 | false | true |
| drag_heavy | 100.0 | 85.0 | 0.0 | 15.0 | 0 | 8 | false | true |
| mixed_burst | 100.0 | 88.0 | 0.0 | 15.0 | 0 | 8 | false | true |
| sensor_overlay | 100.0 | 90.0 | 0.0 | 15.0 | 0 | 8 | false | true |
| resize_overlap_incremental_required | 100.0 | 75.0 | 0.0 | 15.0 | 0 | 8 | false | true |
| input_burst | 100.0 | 85.0 | 0.0 | 15.0 | 0 | 8 | false | true |

- Top-level `policy_verdict.pass=true` computed across all required scenarios and caps.
- Verification commands:
  - `uv run python ops/planning/api/validate_closeout_packet.py --milestone-id P-026`
  - `uv run python ops/planning/agile/validate_milestone_task_links.py`
  - `uv run python ops/planning/api/validate_closeout_evidence.py --milestone-id P-026`

## Determinism
- Determinism policy target remains: 8 seeds x 10 runs with zero digest/invariant mismatches.
- Strict closeout bundle includes full `8x10` determinism replay matrix with zero digest/invariant mismatches.

## Protocol Compatibility
- App protocol and `AppContext` semantics preserved under Vulkan fallback guardrails.
- No backend-internal coupling introduced into app-layer logic; compatibility constraints retained.

## Modularity
- `RenderTarget` boundary preserved.
- `SensorProvider` contract preserved.
- `HDIThread` / `SensorManagerThread` separation preserved.

## Residual Risks
- Residual risk: latent driver-specific Vulkan instability on unvalidated hardware.
- Mitigation: deferred-with-guardrails policy plus mandatory fallback parity and instability fallback behavior.
- Follow-up: continue expanding hardware/driver validation matrix in future milestones.
- Strict closeout evidence gates are currently satisfied for this packet revision.

## Validation Outputs
- `2026-03-04` `uv run python ops/planning/api/validate_closeout_packet.py --milestone-id P-026` -> `validation: PASS (ops/planning/closeout/p-026_closeout.md)`
- `2026-03-04` `uv run python ops/planning/agile/validate_milestone_task_links.py` -> `validation: PASS (checked 27 milestones against 113 active + 18 archived tasks)`
- `2026-03-04` `uv run python ops/planning/api/validate_closeout_evidence.py --milestone-id P-026` -> `validation: PASS (evidence)`
