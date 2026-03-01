from __future__ import annotations

from dataclasses import dataclass

from .agile_renderer import render_agile_board_ascii
from .gantt_renderer import GanttRenderConfig, render_gantt_ascii
from .schema import PlanningTimeline


@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_dependency_integrity(model: PlanningTimeline) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    milestone_ids = {m.milestone_id for m in model.milestones}
    milestone_edges: dict[str, tuple[str, ...]] = {}
    for milestone in model.milestones:
        missing = tuple(dep for dep in milestone.dependencies if dep not in milestone_ids)
        if missing:
            warnings.append(
                f"Milestone `{milestone.milestone_id}` has unresolved dependencies: {', '.join(missing)}"
            )
        milestone_edges[milestone.milestone_id] = tuple(dep for dep in milestone.dependencies if dep in milestone_ids)

    task_ids = {task.task_id for task in model.tasks}
    task_edges: dict[str, tuple[str, ...]] = {}
    for task in model.tasks:
        missing = tuple(dep for dep in task.dependencies if dep not in task_ids)
        if missing:
            errors.append(
                f"Task `{task.task_id}` has unresolved dependencies: {', '.join(missing)}"
            )
        task_edges[task.task_id] = tuple(dep for dep in task.dependencies if dep in task_ids)

    milestone_cycle = _detect_cycle(milestone_edges)
    if milestone_cycle:
        errors.append(f"Milestone dependency cycle detected: {' -> '.join(milestone_cycle)}")

    task_cycle = _detect_cycle(task_edges)
    if task_cycle:
        errors.append(f"Task dependency cycle detected: {' -> '.join(task_cycle)}")

    return ValidationReport(errors=tuple(errors), warnings=tuple(warnings))


def validate_render_consistency(model: PlanningTimeline) -> ValidationReport:
    errors: list[str] = []

    gantt_once = render_gantt_ascii(model, GanttRenderConfig(collapsed_lanes=False))
    gantt_twice = render_gantt_ascii(model, GanttRenderConfig(collapsed_lanes=False))
    if gantt_once != gantt_twice:
        errors.append("Gantt renderer output is not deterministic across repeated calls")
    if "Weeks:" not in gantt_once or "Dates:" not in gantt_once:
        errors.append("Gantt renderer output missing required axis markers")

    agile_once = render_agile_board_ascii(model)
    agile_twice = render_agile_board_ascii(model)
    if agile_once != agile_twice:
        errors.append("Agile renderer output is not deterministic across repeated calls")
    if "Columns:" not in agile_once:
        errors.append("Agile renderer output missing required column markers")

    return ValidationReport(errors=tuple(errors))


def validate_planning_suite(model: PlanningTimeline) -> ValidationReport:
    dep = validate_dependency_integrity(model)
    render = validate_render_consistency(model)
    return ValidationReport(
        errors=tuple(list(dep.errors) + list(render.errors)),
        warnings=tuple(list(dep.warnings) + list(render.warnings)),
    )


def require_valid_planning_suite(model: PlanningTimeline) -> None:
    report = validate_planning_suite(model)
    if report.errors:
        joined = "; ".join(report.errors)
        raise ValueError(f"Planning validation failed: {joined}")


def _detect_cycle(edges: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    visited: set[str] = set()
    active: set[str] = set()
    trail: list[str] = []

    def dfs(node: str) -> tuple[str, ...] | None:
        visited.add(node)
        active.add(node)
        trail.append(node)
        for dep in edges.get(node, ()):
            if dep not in visited:
                cycle = dfs(dep)
                if cycle:
                    return cycle
            elif dep in active:
                idx = trail.index(dep)
                return tuple(trail[idx:] + [dep])
        active.remove(node)
        trail.pop()
        return None

    for node in sorted(edges.keys()):
        if node in visited:
            continue
        cycle = dfs(node)
        if cycle:
            return cycle
    return None
