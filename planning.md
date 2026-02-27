# Luvatrix Phase 1 Plan and Status

## TL;DR
Luvatrix now has a working app protocol runtime, matrix protocol, HDI/sensor threads, macOS visualizer path (fallback + experimental Vulkan), audit pipeline, and protocol governance. The next major work is production-hardening and platform expansion.

## 1. Current Implemented Scope

### 1.1 Core Runtime
1. `WindowMatrix` protocol is implemented (`H x W x 4`, `torch.uint8`) with atomic write batches.
2. `call_blit` event flow is implemented end-to-end through `DisplayRuntime`.
3. `UnifiedRuntime` runs app lifecycle + display + HDI + sensors in one loop.
4. App lifecycle contract is implemented: `init(ctx)`, `loop(ctx, dt)`, `stop(ctx)`.

### 1.2 App Protocol
1. `app.toml` + Python entrypoint loader is implemented.
2. Capability gating is enforced for matrix writes, HDI events, and sensors.
3. Protocol version governance is enforced with compatibility checks.
4. Security controls are implemented:
- denied capability access returns structured `DENIED` responses.
- sensor read rate limiting.
- sensor data sanitization/quantization unless high-precision capability is granted.

### 1.3 Platform Targeting in App Manifests
1. Apps can declare optional `platform_support` (OS allowlist).
2. Apps can declare `[[variants]]` with `id`, `os`, optional `arch`, optional `module_root`, optional `entrypoint`.
3. Runtime resolves and loads only the host-compatible variant.
4. Variant resolution is deterministic and path-confined (`module_root` cannot escape app dir).

### 1.4 HDI
1. HDI thread is implemented.
2. macOS native HDI source exists as a first-class module.
3. Keyboard/mouse/trackpad events are window-gated.
4. Pointer coordinates are normalized to window-relative values.
5. Out-of-window/inactive cases are represented via `NOT_DETECTED`.

### 1.5 Sensors
1. Sensor manager thread is implemented with polling and status model.
2. Default safety sensors are enabled by default:
- `thermal.temperature`
- `power.voltage_current`
3. macOS providers exist for:
- thermal
- power/voltage/current
- motion
4. Sensor state model is implemented: `OK`, `DISABLED`, `UNAVAILABLE`, `DENIED`.

### 1.6 Energy Safety
1. Runtime energy safety controller is implemented.
2. It consumes thermal/power telemetry, computes `OK/WARN/CRITICAL`, and throttles frame pacing.
3. `enforce` mode gracefully stops runtime on sustained critical telemetry.
4. Policy thresholds are configurable via CLI.

### 1.7 Rendering (macOS)
1. macOS presenter + target are implemented.
2. Fallback layer-blit path works for stretch and preserve-aspect examples.
3. Experimental Vulkan path renders and handles resize flow better than earlier revisions.
4. Vulkan path remains marked experimental while long-tail stability hardening continues.

### 1.8 Audit Pipeline
1. JSONL and SQLite sinks are implemented.
2. Capability, sensor, and energy-safety events can be persisted.
3. Report/prune CLI commands exist.

### 1.9 Testing and CI
1. Deterministic unit/integration suite is implemented and passing.
2. Coverage includes app runtime, protocol governance, sensor manager, HDI behavior, renderer integration with recording backend, and energy safety.
3. Guarded macOS GUI smoke workflow exists (flag-gated in CI).

## 2. Supported Developer Contract (Phase 1)

### 2.1 Required App Layout
```text
my_app/
├── app.toml
└── app_main.py
```

### 2.2 Required Manifest Fields
1. `app_id`
2. `protocol_version`
3. `entrypoint`
4. `required_capabilities`
5. `optional_capabilities`

### 2.3 Optional Manifest Fields
1. `min_runtime_protocol_version`
2. `max_runtime_protocol_version`
3. `platform_support`
4. `[[variants]]`

### 2.4 Core AppContext APIs
1. `submit_write_batch(batch)`
2. `poll_hdi_events(max_events)`
3. `read_sensor(sensor_type)`
4. `read_matrix_snapshot()`

## 3. What Is Still Open

1. Promote macOS Vulkan path from experimental to production-ready default.
2. Add robust retention/rotation/reporting tooling for audit stores.
3. Add richer consent UX and policy lifecycle for capabilities.
4. Add guarded OS-level end-to-end smoke strategy for more macOS environments.
5. Prepare shared Vulkan compatibility layer for non-macOS future backends.
6. Implement additional OS backends by reusing common runtime/protocol and shared Vulkan utilities.

## 4. Non-Goals for Current Phase

1. Full web renderer implementation (stub remains acceptable for now).
2. iOS/Android backend rollout in this phase.
3. Replacing protocol model with out-of-process app sandboxing in this phase.

## 5. Immediate Next Milestones

1. Vulkan stabilization pass (surface/swapchain/fence resilience and fallback parity).
2. Finalize app protocol docs with packaging/variant examples and compatibility policy.
3. Expand CI matrix with gated macOS GUI smoke and artifacted logs.

## 6. Engineering Operating Protocols (Technical)

### 6.1 Why These Protocols Exist
1. Preserve release quality as team count and AI contribution volume grow.
2. Keep versioning and branching deterministic for humans and automation.
3. Enforce test rigor before merge so regressions are caught early.
4. Separate domain ownership from shared quality governance.

### 6.2 QA Organization Model
1. **Embedded quality ownership per engineering team**:
- each team designs and maintains tests for their domain features.
2. **Central quality governance function**:
- owns org-wide quality standards, release gates, flake policy, and cross-team/system tests.
3. **Operational split**:
- teams own local correctness;
- central quality owns consistency and system-level confidence.

### 6.3 Mandatory Feature Test Lifecycle
Every feature/change must follow this order:
1. Define success criteria.
2. Define safety tests.
3. Define implementation tests.
4. Define edge-case tests.
5. Build prototype/implementation.
6. Define and execute performance budget checks.
7. Define and execute regression checks.
8. Attach test evidence to PR before merge.

### 6.4 Done Criteria (Technical)
A PR is merge-eligible only if:
1. Test lifecycle steps are completed and documented.
2. Deterministic CI suite passes.
3. Required review approvals pass.
4. Security/risk gates pass when applicable.
5. Linked milestone ID and decision reference exist for major changes.

### 6.5 Versioning Protocol
Use SemVer-compatible `MAJOR.MINOR.PATCH` with optional prerelease tags.
1. `MAJOR`: breaking protocol/runtime changes or major stable generation.
2. `MINOR`: backward-compatible feature additions/improvements.
3. `PATCH`: backward-compatible fixes.
4. Prerelease format for beta builds: `vX.Y.Z-beta.N`.
5. Stable release tags: `vX.Y.Z`.

### 6.6 Branching Protocol
1. `main` must stay releasable.
2. Feature branches start from `main`:
- `feat/<team>/<ticket>-<slug>`
3. AI implementation attempts use isolated branches:
- `ai/<agent>/<ticket>/<attempt-n>`
4. Hotfix branches are cut from latest stable tag:
- `hotfix/<version>/<slug>`
5. Optional release stabilization branches:
- `release/vX.Y.0`
6. No direct pushes to `main`; changes land through PRs only.
7. Prefer squash merges for clean history.

### 6.7 Branch Protection and Merge Gates
1. Required status checks must pass before merge.
2. Required reviewer approvals must be present.
3. Stale reviews are dismissed on new commits.
4. Major changes require linked RFC/ADR references.
5. PR template requires:
- milestone ID (`M-###`)
- test evidence links
- risk notes (if applicable)

### 6.8 Release Flow
1. Merge to `main` only after merge gates pass.
2. Build candidate from `main`.
3. Run deterministic validation gates.
4. Tag prerelease or stable version.
5. Publish release notes with:
- included features/fixes
- known issues
- rollback notes

### 6.9 CI and Quality Gates
1. Deterministic tests remain the hard gate.
2. Guarded GUI smoke stays optional/flag-gated but monitored.
3. Flaky tests are tracked with explicit governance; repeated flakes must be fixed or quarantined by policy.
4. Security, safety, and performance checks are required for affected change classes.

### 6.10 Milestone and Agile Linkage
1. High-level milestones are planned in Gantt by CEO + leads.
2. Teams execute via Agile boards linked to milestone IDs.
3. Every epic/task maps to one milestone.
4. Weekly leadership review updates milestone confidence from board + CI evidence.
