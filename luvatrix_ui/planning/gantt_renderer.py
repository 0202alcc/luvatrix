from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .schema import STATUS_COLORS, PlanningTimeline, TimelineMilestone

STATUS_FILL: dict[str, str] = {
    "Planned": "~",
    "In Progress": "#",
    "At Risk": "!",
    "Blocked": "x",
    "Complete": "=",
}

_STATUS_PRIORITY: dict[str, int] = {
    "Blocked": 5,
    "At Risk": 4,
    "In Progress": 3,
    "Planned": 2,
    "Complete": 1,
}


@dataclass(frozen=True)
class GanttRenderConfig:
    collapsed_lanes: bool = False
    show_dependency_lines: bool = True
    week_column_width: int = 2

    def __post_init__(self) -> None:
        if self.week_column_width < 1:
            raise ValueError("week_column_width must be >= 1")


def render_gantt_ascii(model: PlanningTimeline, config: GanttRenderConfig | None = None) -> str:
    cfg = config or GanttRenderConfig()
    max_week = model.max_week()

    lines: list[str] = []
    lines.append(model.title)
    lines.append(f"Baseline start: {model.baseline_start_date.isoformat()} | mode={'collapsed' if cfg.collapsed_lanes else 'expanded'}")
    lines.append("Status colors: " + ", ".join(f"{k}={v}" for k, v in STATUS_COLORS.items() if k in STATUS_FILL))
    lines.append(_build_week_header(max_week, cfg.week_column_width))
    lines.append(_build_date_header(model, max_week, cfg.week_column_width))

    if cfg.collapsed_lanes:
        lane_rows = _render_collapsed_lanes(model, max_week, cfg.week_column_width)
    else:
        lane_rows = _render_expanded_lanes(model, max_week, cfg.week_column_width)
    lines.extend(lane_rows)

    if cfg.show_dependency_lines:
        lines.append("")
        lines.append("Dependency lines:")
        dep_lines = _render_dependency_lines(model, max_week, cfg.week_column_width)
        if dep_lines:
            lines.extend(dep_lines)
        else:
            lines.append("  (none)")

    return "\n".join(lines) + "\n"


def attach_dependency_defaults(model: PlanningTimeline) -> PlanningTimeline:
    defaults: dict[str, tuple[str, ...]] = {
        "M-001": ("H-008",),
        "M-002": ("M-001",),
        "M-003": ("M-002", "M-007"),
        "M-004": ("M-002",),
        "M-005": ("M-004",),
        "M-006": ("M-003", "M-004", "M-005"),
        "M-007": ("H-006", "H-009"),
        "M-008": ("M-007",),
        "M-009": ("M-008",),
        "M-010": ("M-008", "M-009"),
        "M-011": ("M-008",),
    }
    updated = []
    for milestone in model.milestones:
        if milestone.dependencies:
            updated.append(milestone)
            continue
        deps = defaults.get(milestone.milestone_id, ())
        updated.append(dataclasses.replace(milestone, dependencies=deps))
    return dataclasses.replace(model, milestones=tuple(updated))


def _render_expanded_lanes(
    model: PlanningTimeline, max_week: int, week_column_width: int
) -> list[str]:
    ordered = sorted(model.milestones, key=lambda m: (m.start_week, m.end_week, m.milestone_id))
    label_width = max(len(f"{m.milestone_id} {m.name}") for m in ordered)
    lines: list[str] = []
    for milestone in ordered:
        bar = _render_bar_for_milestone(milestone, max_week, week_column_width)
        label = f"{milestone.milestone_id} {milestone.name}".ljust(label_width)
        suffix = f"{milestone.status} ({STATUS_COLORS[milestone.status]})"
        if milestone.dependencies:
            suffix = f"{suffix} deps={','.join(milestone.dependencies)}"
        lines.append(f"{label} |{bar}| {suffix}")
    return lines


def _render_collapsed_lanes(
    model: PlanningTimeline, max_week: int, week_column_width: int
) -> list[str]:
    lanes: dict[str, list[TimelineMilestone]] = {}
    for milestone in model.milestones:
        lane = _lane_key(milestone)
        lanes.setdefault(lane, []).append(milestone)

    lines: list[str] = []
    for lane in sorted(lanes.keys()):
        milestones = lanes[lane]
        label = f"lane:{lane}"
        bar = _render_aggregate_lane_bar(milestones, max_week, week_column_width)
        member_ids = ",".join(m.milestone_id for m in sorted(milestones, key=lambda m: m.milestone_id))
        lines.append(f"{label:<14} |{bar}| members={member_ids}")
    return lines


def _render_aggregate_lane_bar(
    milestones: list[TimelineMilestone], max_week: int, week_column_width: int
) -> str:
    week_status: list[str | None] = [None] * max_week
    for milestone in milestones:
        for week in range(milestone.start_week, milestone.end_week + 1):
            idx = week - 1
            current = week_status[idx]
            if current is None:
                week_status[idx] = milestone.status
                continue
            if _STATUS_PRIORITY[milestone.status] > _STATUS_PRIORITY[current]:
                week_status[idx] = milestone.status

    week_cells: list[str] = []
    for status in week_status:
        if status is None:
            week_cells.append(" " * week_column_width)
            continue
        week_cells.append(STATUS_FILL[status] * week_column_width)
    return "".join(week_cells)


def _render_bar_for_milestone(milestone: TimelineMilestone, max_week: int, week_column_width: int) -> str:
    cells = [" " * week_column_width for _ in range(max_week)]
    fill = STATUS_FILL[milestone.status]
    for week in range(milestone.start_week, milestone.end_week + 1):
        cells[week - 1] = fill * week_column_width
    return "".join(cells)


def _render_dependency_lines(model: PlanningTimeline, max_week: int, week_column_width: int) -> list[str]:
    lookup = model.milestone_lookup()
    lines: list[str] = []
    for target in sorted(model.milestones, key=lambda m: m.milestone_id):
        for dep_id in target.dependencies:
            source = lookup.get(dep_id)
            if source is None:
                continue
            cells = [" " * week_column_width for _ in range(max_week)]
            start_week = min(source.end_week, target.start_week)
            end_week = max(source.end_week, target.start_week)
            for week in range(start_week, end_week + 1):
                cells[week - 1] = "-" * week_column_width
            cells[target.start_week - 1] = ">" + "-" * (week_column_width - 1)
            marker = "overlap" if target.start_week <= source.end_week else "ok"
            lines.append(
                f"  {dep_id:>6} -> {target.milestone_id:<6} |{''.join(cells)}| {marker}"
            )
    return lines


def _build_week_header(max_week: int, week_column_width: int) -> str:
    parts = [f"W{week:02d}".center(week_column_width) for week in range(1, max_week + 1)]
    return "Weeks:  " + "".join(parts)


def _build_date_header(model: PlanningTimeline, max_week: int, week_column_width: int) -> str:
    parts = [model.week_start_date(week).strftime("%m/%d").center(week_column_width) for week in range(1, max_week + 1)]
    return "Dates:  " + "".join(parts)


def _lane_key(milestone: TimelineMilestone) -> str:
    head, _, _ = milestone.milestone_id.partition("-")
    return head or "DEFAULT"
