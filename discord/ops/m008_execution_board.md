# M-008 Execution Board

Milestone: `M-008` Plot + data UX foundations
Epic: `E-801`
Task chain: `T-801 -> T-802 -> T-803 -> T-804 -> T-805`
Last updated: `2026-02-28`

## Backlog
1. None.

## Ready
1. `T-805` Table UI component system (sortable columns, pagination/virtualization, keyboard access).

## In Progress
1. None.

## Review
1. `T-801` Sideways/compact x-axis labels for dense long labels.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py` (pass).
2. `T-802` Bar renderer support (`Axes.bar(...)`) with deterministic behavior.
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py` (pass).
3. `T-803` Multi-plot support (minimum 2-panel subplot layout in one figure/frame).
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py` (pass).
4. `T-804` Scrolling/viewport controls for dense x-domains (pan/viewport APIs; optional zoom).
- Evidence: `PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py` (pass).

## Done
1. None.

## Evidence Log
1. `2026-02-28`: Board initialized for `M-008`; `T-801` started.
2. `2026-02-28`: `T-801` moved to `Review` after deterministic x-label layout updates and plot test pass.
3. `2026-02-28`: `T-802` started after `T-801` review handoff.
4. `2026-02-28`: `T-802` moved to `Review` after deterministic bar-render tests passed.
5. `2026-02-28`: `T-803` started after `T-802` review handoff.
6. `2026-02-28`: `T-803` moved to `Review` after subplot compatibility tests passed.
7. `2026-02-28`: `T-804` started after `T-803` review handoff.
8. `2026-02-28`: `T-804` moved to `Review` after viewport clamp/alignment tests passed.
