from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .schema import AgileTaskCard, PlanningTimeline


@dataclass(frozen=True)
class PlanningInteractionState:
    week_start: int = 1
    week_span: int = 8
    status_filter: tuple[str, ...] = ("Backlog", "Ready", "In Progress", "Review", "Done", "Blocked")
    milestone_filter: tuple[str, ...] = ()
    owner_filter: tuple[str, ...] = ()
    text_query: str = ""

    def __post_init__(self) -> None:
        if self.week_start < 1:
            raise ValueError("week_start must be >= 1")
        if self.week_span < 1:
            raise ValueError("week_span must be >= 1")


def clamp_week_window(model: PlanningTimeline, *, start_week: int, week_span: int) -> tuple[int, int]:
    if week_span < 1:
        raise ValueError("week_span must be >= 1")
    max_week = model.max_week()
    span = min(week_span, max_week)
    start = max(1, min(start_week, max_week - span + 1))
    end = start + span - 1
    return (start, end)


def pan_week_window(
    model: PlanningTimeline, state: PlanningInteractionState, *, delta_weeks: int
) -> PlanningInteractionState:
    start, _ = clamp_week_window(model, start_week=state.week_start + delta_weeks, week_span=state.week_span)
    return dataclasses.replace(state, week_start=start)


def zoom_week_window(
    model: PlanningTimeline,
    state: PlanningInteractionState,
    *,
    delta_span: int,
    anchor_week: int | None = None,
) -> PlanningInteractionState:
    target_span = max(1, state.week_span + delta_span)
    max_week = model.max_week()
    target_span = min(target_span, max_week)
    anchor = state.week_start if anchor_week is None else anchor_week
    next_start = anchor - (target_span // 2)
    start, _ = clamp_week_window(model, start_week=next_start, week_span=target_span)
    return dataclasses.replace(state, week_start=start, week_span=target_span)


def apply_week_viewport(model: PlanningTimeline, state: PlanningInteractionState) -> PlanningTimeline:
    start_week, end_week = clamp_week_window(model, start_week=state.week_start, week_span=state.week_span)

    visible_milestones = []
    for milestone in model.milestones:
        if milestone.end_week < start_week or milestone.start_week > end_week:
            continue
        visible_milestones.append(
            dataclasses.replace(
                milestone,
                start_week=max(milestone.start_week, start_week),
                end_week=min(milestone.end_week, end_week),
            )
        )

    visible_milestone_ids = {m.milestone_id for m in visible_milestones}
    visible_tasks = tuple(task for task in model.tasks if task.milestone_id in visible_milestone_ids)
    return dataclasses.replace(
        model,
        milestones=tuple(visible_milestones),
        tasks=visible_tasks,
    )


def apply_task_filters(model: PlanningTimeline, state: PlanningInteractionState) -> tuple[AgileTaskCard, ...]:
    query = state.text_query.strip().lower()
    out: list[AgileTaskCard] = []
    for task in model.tasks:
        if state.status_filter and task.status not in state.status_filter:
            continue
        if state.milestone_filter and task.milestone_id not in state.milestone_filter:
            continue
        if state.owner_filter:
            owner_set = set(task.owners)
            if not owner_set.intersection(state.owner_filter):
                continue
        if query:
            haystack = " ".join((task.task_id, task.title, task.milestone_id, ",".join(task.owners))).lower()
            if query not in haystack:
                continue
        out.append(task)
    return tuple(sorted(out, key=lambda t: t.task_id))


def milestone_clickthrough_map(model: PlanningTimeline) -> dict[str, tuple[AgileTaskCard, ...]]:
    mapping: dict[str, list[AgileTaskCard]] = {}
    for task in model.tasks:
        mapping.setdefault(task.milestone_id, []).append(task)
    return {
        milestone_id: tuple(sorted(tasks, key=lambda t: t.task_id))
        for milestone_id, tasks in mapping.items()
    }
