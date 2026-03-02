# UI IR v2 Demo and Verification Plan (T-824)

Status: Draft plan (2026-03-01)
Milestone: M-008
Task: T-824

## 1) Purpose

Define the demonstration and verification workflow that proves `planes-v2` behavior end-to-end before rollout gating.

## 2) Demo Objectives

1. Prove full-page camera scrolling over content outside initial view bounds.
2. Prove deterministic global scrollbars (bottom/right) reflect camera position/extent.
3. Prove overlay components remain camera-fixed over scrolled world content.
4. Prove section-cut and nested scroll targeting behavior in controlled fixtures.
5. Prove `absolute_rgba` and `delta_rgba` compositing correctness with clamping.

## 3) Demo Artifacts

Primary demo app:
1. `examples/app_protocol/planes_v2_poc`

Expected artifact classes:
1. Runtime smoke logs (`headless` run).
2. Deterministic frame snapshot hashes for selected ticks.
3. Optional exported PNG references for human review.

## 4) Verification Commands

Baseline runtime checks:
```bash
PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py
```

Headless demo smoke:
```bash
PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 16 --fps 60
```

Optional compatibility batch:
```bash
PYTHONPATH=. uv run pytest tests/test_planes_protocol.py tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py
```

## 5) Scenario Checklist

Scenario D01. Main-plane camera scroll
1. Start at origin.
2. Scroll right/down.
3. Confirm out-of-bounds components appear deterministically.

Scenario D02. Global scrollbars
1. Verify bottom/right bars exist only when overflow present.
2. Verify thumb size scales with viewport/content ratio.
3. Verify thumb position tracks camera offset.

Scenario D03. Overlay persistence
1. Scroll world content.
2. Confirm camera-fixed controls stay pinned to screen.

Scenario D04. Clamp and blend correctness
1. Render `absolute_rgba` + `delta_rgba` fixtures.
2. Confirm channel values are clamped to `[0,255]`.

Scenario D05. Determinism rerun
1. Re-run same fixture twice.
2. Assert identical hash outputs and ordering diagnostics.

## 6) Acceptance Criteria

1. All required pytest suites pass.
2. Headless smoke run succeeds without runtime exceptions.
3. D01-D05 checklist passes with no visual correctness regressions.
4. Deterministic snapshot/hash parity holds across repeated runs.

## 7) Failure Triage Playbook

1. If scroll behavior mismatches:
- inspect camera offset/clamp logs.

2. If scrollbar mismatch:
- inspect content extent math and thumb geometry formula inputs.

3. If compositing mismatch:
- inspect `blend_mode` field propagation and clamp counters.

4. If nondeterministic diffs:
- inspect stable-order key generation and warning sort order.

## 8) Deliverable Packaging

For release candidate review bundle:
1. command log snippets,
2. deterministic hash outputs,
3. selected visual captures,
4. checklist pass/fail table with notes.

## 9) Dependencies

1. T-820 validation matrix
2. T-821 compiler design
3. T-822 runtime pipeline design
4. T-823 performance execution plan

## 10) Evidence

1. `examples/app_protocol/planes_v2_poc`
2. `tests/test_planes_runtime.py`
3. `tests/test_planes_v2_poc_example.py`
4. `ops/planning/agile/m008_execution_board.md`
