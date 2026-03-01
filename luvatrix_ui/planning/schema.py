from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

MILESTONE_STATUSES: tuple[str, ...] = ("Planned", "In Progress", "At Risk", "Blocked", "Complete")
TASK_STATUSES: tuple[str, ...] = ("Backlog", "Ready", "In Progress", "Review", "Done", "Blocked")

STATUS_COLORS: dict[str, str] = {
    "Planned": "#94A3B8",
    "In Progress": "#2563EB",
    "At Risk": "#F59E0B",
    "Blocked": "#DC2626",
    "Complete": "#16A34A",
    "Backlog": "#9CA3AF",
    "Ready": "#0EA5E9",
    "Review": "#8B5CF6",
    "Done": "#16A34A",
}


@dataclass(frozen=True)
class TimelineMilestone:
    milestone_id: str
    name: str
    start_week: int
    end_week: int
    status: str = "Planned"
    emoji: str = ""
    completed_on: str | None = None
    dependencies: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.milestone_id.strip():
            raise ValueError("TimelineMilestone.milestone_id must be non-empty")
        if not self.name.strip():
            raise ValueError("TimelineMilestone.name must be non-empty")
        if self.start_week < 1:
            raise ValueError("TimelineMilestone.start_week must be >= 1")
        if self.end_week < self.start_week:
            raise ValueError("TimelineMilestone.end_week must be >= start_week")
        if self.status not in MILESTONE_STATUSES:
            raise ValueError(f"Unsupported milestone status: {self.status}")


@dataclass(frozen=True)
class AgileTaskCard:
    task_id: str
    milestone_id: str
    title: str
    status: str = "Backlog"
    epic_id: str | None = None
    dependencies: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("AgileTaskCard.task_id must be non-empty")
        if not self.milestone_id.strip():
            raise ValueError("AgileTaskCard.milestone_id must be non-empty")
        if not self.title.strip():
            raise ValueError("AgileTaskCard.title must be non-empty")
        if self.status not in TASK_STATUSES:
            raise ValueError(f"Unsupported task status: {self.status}")


@dataclass(frozen=True)
class PlanningTimeline:
    title: str
    baseline_start_date: dt.date
    milestones: tuple[TimelineMilestone, ...] = ()
    tasks: tuple[AgileTaskCard, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("PlanningTimeline.title must be non-empty")
        if not self.milestones:
            raise ValueError("PlanningTimeline.milestones must not be empty")
        milestone_ids = {m.milestone_id for m in self.milestones}
        for task in self.tasks:
            if task.milestone_id not in milestone_ids:
                raise ValueError(
                    f"Task `{task.task_id}` references missing milestone `{task.milestone_id}`"
                )

    def max_week(self) -> int:
        return max(m.end_week for m in self.milestones)

    def week_start_date(self, week: int) -> dt.date:
        if week < 1:
            raise ValueError("week must be >= 1")
        return self.baseline_start_date + dt.timedelta(days=(week - 1) * 7)

    def milestone_lookup(self) -> dict[str, TimelineMilestone]:
        return {m.milestone_id: m for m in self.milestones}


PLANNING_TIMELINE_JSON_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://luvatrix.dev/schemas/planning_timeline.schema.json",
    "title": "Luvatrix Planning Timeline",
    "type": "object",
    "required": ["title", "baseline_start_date", "milestones"],
    "properties": {
        "title": {"type": "string"},
        "baseline_start_date": {"type": "string", "format": "date"},
        "milestones": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "start_week", "end_week", "status"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "emoji": {"type": "string"},
                    "start_week": {"type": "integer", "minimum": 1},
                    "end_week": {"type": "integer", "minimum": 1},
                    "status": {"type": "string", "enum": list(MILESTONE_STATUSES)},
                    "completed_on": {"type": "string"},
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                    "owners": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "milestone_id", "title", "status"],
                "properties": {
                    "id": {"type": "string"},
                    "epic_id": {"type": "string"},
                    "milestone_id": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": list(TASK_STATUSES)},
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                    "owners": {"type": "array", "items": {"type": "string"}},
                    "blockers": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def planning_timeline_schema() -> dict[str, object]:
    return json.loads(json.dumps(PLANNING_TIMELINE_JSON_SCHEMA))


def timeline_from_dict(
    payload: Mapping[str, object],
    *,
    tasks: Iterable[AgileTaskCard] | None = None,
) -> PlanningTimeline:
    title = str(payload.get("title", "Luvatrix Planning Timeline"))
    baseline_start_date = dt.date.fromisoformat(str(payload["baseline_start_date"]))

    raw_milestones = payload.get("milestones")
    if not isinstance(raw_milestones, list):
        raise TypeError("`milestones` must be a list")

    milestones: list[TimelineMilestone] = []
    for raw in raw_milestones:
        if not isinstance(raw, Mapping):
            raise TypeError("Each milestone must be a mapping")
        milestones.append(
            TimelineMilestone(
                milestone_id=str(raw["id"]),
                name=str(raw["name"]),
                emoji=str(raw.get("emoji", "")),
                start_week=int(raw["start_week"]),
                end_week=int(raw["end_week"]),
                status=str(raw.get("status", "Planned")),
                completed_on=_coerce_optional_str(raw.get("completed_on")),
                dependencies=_coerce_string_tuple(raw.get("dependencies") or raw.get("deps")),
                owners=_coerce_string_tuple(raw.get("owners") or raw.get("owner")),
            )
        )

    task_cards: tuple[AgileTaskCard, ...]
    if tasks is not None:
        task_cards = tuple(tasks)
    else:
        raw_tasks = payload.get("tasks", [])
        if not isinstance(raw_tasks, list):
            raise TypeError("`tasks` must be a list when provided")
        task_cards = tuple(
            AgileTaskCard(
                task_id=str(item["id"]),
                milestone_id=str(item["milestone_id"]),
                title=str(item["title"]),
                status=str(item.get("status", "Backlog")),
                epic_id=_coerce_optional_str(item.get("epic_id")),
                dependencies=_coerce_string_tuple(item.get("dependencies") or item.get("deps")),
                owners=_coerce_string_tuple(item.get("owners") or item.get("owner")),
                blockers=_coerce_string_tuple(item.get("blockers") or item.get("blocked_by")),
            )
            for item in raw_tasks
            if isinstance(item, Mapping)
        )

    return PlanningTimeline(
        title=title,
        baseline_start_date=baseline_start_date,
        milestones=tuple(milestones),
        tasks=task_cards,
    )


def load_timeline_model(
    schedule_path: str | Path,
    *,
    tasks: Iterable[AgileTaskCard] | None = None,
) -> PlanningTimeline:
    schedule = Path(schedule_path)
    payload = json.loads(schedule.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("Schedule payload must be a JSON object")
    return timeline_from_dict(payload, tasks=tasks)


def build_m011_task_cards() -> tuple[AgileTaskCard, ...]:
    return (
        AgileTaskCard(
            task_id="T-1101",
            milestone_id="M-011",
            epic_id="E-1101",
            title="Define canonical timeline/task schema for Gantt + Agile cards.",
            status="In Progress",
            owners=("AI-Architect", "AI-Implementer"),
        ),
        AgileTaskCard(
            task_id="T-1102",
            milestone_id="M-011",
            epic_id="E-1101",
            title="Build native Luvatrix Gantt renderer.",
            status="In Progress",
            dependencies=("T-1101",),
            owners=("AI-Rendering", "AI-Implementer"),
        ),
        AgileTaskCard(
            task_id="T-1103",
            milestone_id="M-011",
            epic_id="E-1101",
            title="Build native Luvatrix Agile board renderer.",
            status="In Progress",
            dependencies=("T-1102",),
        ),
        AgileTaskCard(
            task_id="T-1104",
            milestone_id="M-011",
            epic_id="E-1101",
            title="Add interaction layer (filtering, zoom/scroll, click-through).",
            status="In Progress",
            dependencies=("T-1103",),
        ),
        AgileTaskCard(
            task_id="T-1105",
            milestone_id="M-011",
            epic_id="E-1101",
            title="Add export adapters (ASCII/Markdown/PNG) and Discord payload compatibility.",
            status="In Progress",
            dependencies=("T-1104",),
        ),
        AgileTaskCard(
            task_id="T-1106",
            milestone_id="M-011",
            epic_id="E-1101",
            title="Add validation suite for render correctness and dependency integrity.",
            status="In Progress",
            dependencies=("T-1105",),
        ),
    )


def _coerce_optional_str(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text if text else None


def _coerce_string_tuple(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        text = raw.strip()
        return (text,) if text else ()
    if isinstance(raw, Iterable):
        out: list[str] = []
        for item in raw:
            value = str(item).strip()
            if value:
                out.append(value)
        return tuple(out)
    raise TypeError("Expected string or iterable of strings")
