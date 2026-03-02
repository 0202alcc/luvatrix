# UI IR v2 Validation Plan and Snapshot Matrix (T-820)

Status: Draft plan (2026-03-01)
Milestone: M-008
Task: T-820

## 1) Purpose

Define deterministic validation and snapshot strategy required to safely introduce `planes-v2` IR alongside existing `planes-v0` behavior.

This plan is the pre-implementation test contract for:
1. schema/IR correctness,
2. ordering and compositing determinism,
3. compatibility migration safety,
4. runtime parity during rollout.

## 2) Validation Scope

Validation must cover four layers:

1. Schema validation
- `planes-v0` and vNext source payload checks.

2. Compiler validation
- JSON schema -> UI IR (`planes-v0` and `planes-v2`) field correctness.

3. Ordering/compositing determinism
- stable draw/hit ordering, `absolute_rgba` vs `delta_rgba`, section-cut routing effects.

4. Runtime parity and regression
- expected rendered output and event-routing behavior remain stable across runs/platforms.

## 3) Required Test Suites (Planned)

1. `tests/test_planes_protocol.py`
- add vNext schema acceptance/rejection cases.

2. `tests/test_ui_ir.py` (or equivalent)
- add `planes-v2` serialization/deserialization/validation tests.

3. `tests/test_planes_runtime.py`
- add deterministic ordering, section-cut pass-through, blend-mode behavior checks.

4. Snapshot tests (new)
- `tests/snapshots/planes_v2/*.json` for IR snapshots,
- `tests/snapshots/planes_v2/*.png` (or tensor hash fixtures) for render snapshots where appropriate.

## 4) Snapshot Matrix

Each scenario must execute in both strict and permissive compile modes unless explicitly noted.

| Case ID | Input Schema | Mode | Expected IR | Expected Outcome |
| --- | --- | --- | --- | --- |
| S01 | v0 minimal valid | strict | `planes-v0` | pass |
| S02 | v0 minimal valid | permissive | `planes-v0` | pass |
| S03 | vNext minimal valid (`planes[]`) | strict | `planes-v2` | pass |
| S04 | vNext minimal valid (`planes[]`) | permissive | `planes-v2` | pass |
| S05 | vNext missing `attachment_kind` | strict | n/a | fail |
| S06 | vNext missing `attachment_kind` | permissive | `planes-v2` defaulted | pass + warning |
| S07 | invalid `blend_mode` | strict | n/a | fail |
| S08 | invalid `blend_mode` | permissive | fallback `absolute_rgba` | pass + warning |
| S09 | unresolved `attach_to` plane | strict | n/a | fail |
| S10 | unresolved `attach_to` plane | permissive | drop/default policy | pass + warning |
| S11 | section-cut valid | strict | `planes-v2` + cut refs | pass |
| S12 | section-cut unresolved target | strict | n/a | fail |
| S13 | equal plane z with lexical tie-break | strict | deterministic keys | stable pass |
| S14 | equal local z with mount-order tie-break | strict | deterministic keys | stable pass |
| S15 | delta blend clamp upper bound | strict | `blend_mode=delta_rgba` | stable pass |
| S16 | delta blend clamp lower bound | strict | `blend_mode=delta_rgba` | stable pass |
| S17 | v0 -> v2 compatibility mapper | strict | deterministic `planes-v2` | stable pass |
| S18 | route activation plane subset | strict | active plane filtering | stable pass |

## 5) Determinism Rules for Snapshots

1. Normalize all ordering keys before snapshot write.
2. Use fixed seed for any non-deterministic helper generation.
3. Ensure lexical ordering of serialized dictionaries where supported.
4. Compare render snapshots by deterministic tensor hash plus optional image artifact.

## 6) Golden Artifact Policy

1. IR golden files are reviewed text artifacts (`.json`).
2. Render golden files are reviewed as:
- image plus hash, or
- hash-only where images are unstable/expensive.
3. Golden updates require explicit review note in commit message and board evidence.

## 7) Compatibility Gate Criteria

`planes-v2` gate is considered pass-ready when:

1. All matrix cases `S01..S18` pass in CI.
2. No nondeterministic snapshot diffs across two consecutive CI runs.
3. v0 baseline tests remain green with no behavior regressions.
4. Runtime smoke command succeeds for `planes_v2_poc`.

## 8) CI Execution Plan

Recommended command bundle (to be finalized in implementation tasks):

```bash
PYTHONPATH=. uv run pytest \
  tests/test_planes_protocol.py \
  tests/test_planes_runtime.py \
  tests/test_planes_v2_poc_example.py \
  tests/test_ui_ir.py
```

During migration, add dual-path compare job:
1. compile same fixtures through `planes-v0` compatibility and `planes-v2` path
2. assert deterministic equivalence where expected

## 9) Risk Controls

1. Snapshot churn risk
- Mitigation: strict tie-break contract and approved golden update workflow.

2. Cross-platform render drift
- Mitigation: prefer IR/hash assertions for deterministic core checks; keep image snapshots targeted.

3. Backward-compat break risk
- Mitigation: maintain explicit `v0 -> v2` mapping tests (`S17`) and keep v0 suite mandatory.

## 10) Follow-on Task Dependencies

1. T-821 must implement compiler design aligned to this matrix.
2. T-822 must implement runtime behavior validated by matrix expectations.
3. T-825 rollout gate must require these matrix checks in CI before default switch.

## 11) Evidence

1. `docs/ui_ir_v2_field_contract.md`
2. `docs/ui_ir_v2_gap_assessment.md`
3. `docs/planes_protocol_vnext.md`
4. `ops/planning/agile/m008_execution_board.md`
