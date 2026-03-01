from __future__ import annotations

from dataclasses import dataclass

from .schema import AgileTaskCard, PlanningTimeline, STATUS_COLORS, TASK_STATUSES

AGILE_COLUMNS: tuple[str, ...] = ("Backlog", "Ready", "In Progress", "Review", "Done")


@dataclass(frozen=True)
class AgileRenderConfig:
    lane_mode: str = "milestone"
    include_blocked_column: bool = False
    max_title_chars: int = 58

    def __post_init__(self) -> None:
        if self.lane_mode not in {"milestone", "owner", "epic"}:
            raise ValueError("lane_mode must be one of: milestone, owner, epic")
        if self.max_title_chars < 12:
            raise ValueError("max_title_chars must be >= 12")

    @property
    def columns(self) -> tuple[str, ...]:
        if self.include_blocked_column:
            return AGILE_COLUMNS + ("Blocked",)
        return AGILE_COLUMNS


def render_agile_board_ascii(model: PlanningTimeline, config: AgileRenderConfig | None = None) -> str:
    cfg = config or AgileRenderConfig()
    grouped = _group_tasks_by_lane(model.tasks, lane_mode=cfg.lane_mode)

    lines: list[str] = []
    lines.append(f"{model.title} - Agile Board")
    lines.append(f"Columns: {' | '.join(cfg.columns)}")
    lines.append(
        "Status colors: " + ", ".join(f"{status}={STATUS_COLORS[status]}" for status in cfg.columns if status in STATUS_COLORS)
    )

    for lane_key in sorted(grouped.keys()):
        lines.append("")
        lines.append(f"[swimlane:{lane_key}]")
        lane_cards = grouped[lane_key]
        by_status = _cards_by_status(lane_cards)
        for column in cfg.columns:
            cards = by_status.get(column, ())
            if not cards:
                lines.append(f"{column}: -")
                continue
            lines.append(f"{column}:")
            for card in cards:
                lines.append(f"  - {_format_card(card, max_title_chars=cfg.max_title_chars)}")
        blocked_cards = tuple(
            card
            for card in lane_cards
            if card.blockers or card.status == "Blocked"
        )
        if blocked_cards and "Blocked" not in cfg.columns:
            lines.append("Blockers:")
            for card in blocked_cards:
                lines.append(f"  - {card.task_id}: {', '.join(card.blockers) if card.blockers else 'status=Blocked'}")

    if not model.tasks:
        lines.append("")
        lines.append("(no task cards)")

    return "\n".join(lines) + "\n"


def render_agile_board_markdown(model: PlanningTimeline, config: AgileRenderConfig | None = None) -> str:
    cfg = config or AgileRenderConfig()
    grouped = _group_tasks_by_lane(model.tasks, lane_mode=cfg.lane_mode)

    lines: list[str] = []
    lines.append(f"# {model.title} Agile Board")
    lines.append("")
    lines.append(f"Lane mode: `{cfg.lane_mode}`")
    lines.append("")

    for lane_key in sorted(grouped.keys()):
        lines.append(f"## Swimlane `{lane_key}`")
        headers = cfg.columns
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        lane_cards = grouped[lane_key]
        by_status = _cards_by_status(lane_cards)
        row: list[str] = []
        for column in headers:
            cards = by_status.get(column, ())
            if not cards:
                row.append("-")
                continue
            values = "<br>".join(_format_card(card, max_title_chars=cfg.max_title_chars) for card in cards)
            row.append(values)
        lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    if not model.tasks:
        lines.append("_No task cards._")
        lines.append("")

    return "\n".join(lines)


def _group_tasks_by_lane(
    cards: tuple[AgileTaskCard, ...], *, lane_mode: str
) -> dict[str, tuple[AgileTaskCard, ...]]:
    lanes: dict[str, list[AgileTaskCard]] = {}
    for card in cards:
        lane_keys = _lane_keys(card, lane_mode=lane_mode)
        for lane_key in lane_keys:
            lanes.setdefault(lane_key, []).append(card)
    return {
        lane_key: tuple(sorted(lane_cards, key=lambda c: c.task_id))
        for lane_key, lane_cards in lanes.items()
    }


def _lane_keys(card: AgileTaskCard, *, lane_mode: str) -> tuple[str, ...]:
    if lane_mode == "milestone":
        return (card.milestone_id,)
    if lane_mode == "epic":
        return (card.epic_id or "no-epic",)
    if card.owners:
        return tuple(card.owners)
    return ("unassigned",)


def _cards_by_status(cards: tuple[AgileTaskCard, ...]) -> dict[str, tuple[AgileTaskCard, ...]]:
    out: dict[str, list[AgileTaskCard]] = {status: [] for status in TASK_STATUSES}
    for card in cards:
        out.setdefault(card.status, []).append(card)
    return {
        status: tuple(sorted(entries, key=lambda c: c.task_id))
        for status, entries in out.items()
        if entries
    }


def _format_card(card: AgileTaskCard, *, max_title_chars: int) -> str:
    title = card.title.strip()
    if len(title) > max_title_chars:
        title = title[: max_title_chars - 1].rstrip() + "…"
    suffix: list[str] = []
    if card.dependencies:
        suffix.append(f"deps={','.join(card.dependencies)}")
    if card.blockers:
        suffix.append(f"blocked_by={','.join(card.blockers)}")
    if suffix:
        return f"{card.task_id} {title} ({'; '.join(suffix)})"
    return f"{card.task_id} {title}"
