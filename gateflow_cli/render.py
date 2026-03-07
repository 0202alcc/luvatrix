from __future__ import annotations

from pathlib import Path

from gateflow_cli.config import get_config_value
from gateflow_cli.workspace import GateflowWorkspace


def render_gantt(workspace: GateflowWorkspace, *, out_path: Path | None, fmt: str | None) -> str:
    resolved = _resolve_format(workspace.root, fmt)
    if resolved not in {"ascii", "md"}:
        raise ValueError("render format must be 'md' or 'ascii'")

    rows = sorted(workspace.list_items("milestones"), key=lambda row: str(row.get("id", "")))
    text = _render_gantt_markdown(rows) if resolved == "md" else _render_gantt_ascii(rows)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    return text


def _resolve_format(root: Path, fmt: str | None) -> str:
    if fmt:
        return fmt
    configured = get_config_value(root, "render.format")
    if not isinstance(configured, str):
        raise ValueError("config render.format must be a string")
    return configured


def _render_gantt_ascii(rows: list[dict]) -> str:
    headers = ("ID", "Name", "Status", "Start", "End", "Tasks")
    table: list[tuple[str, str, str, str, str, str]] = []
    for row in rows:
        task_ids = row.get("task_ids", [])
        task_count = len(task_ids) if isinstance(task_ids, list) else 0
        table.append(
            (
                str(row.get("id", "-")),
                str(row.get("name", "-")),
                str(row.get("status", "Planned")),
                str(row.get("start_week", "-")),
                str(row.get("end_week", "-")),
                str(task_count),
            )
        )

    widths = [len(h) for h in headers]
    for record in table:
        for idx, value in enumerate(record):
            widths[idx] = max(widths[idx], len(value))

    def _line(values: tuple[str, str, str, str, str, str]) -> str:
        return " | ".join(values[idx].ljust(widths[idx]) for idx in range(len(values)))

    sep = "-+-".join("-" * width for width in widths)
    lines = [_line(headers), sep]
    lines.extend(_line(record) for record in table)
    return "\n".join(lines) + "\n"


def _render_gantt_markdown(rows: list[dict]) -> str:
    lines = [
        "| ID | Name | Status | Start Week | End Week | Task Count |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        task_ids = row.get("task_ids", [])
        task_count = len(task_ids) if isinstance(task_ids, list) else 0
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("id", "-")),
                    str(row.get("name", "-")),
                    str(row.get("status", "Planned")),
                    str(row.get("start_week", "-")),
                    str(row.get("end_week", "-")),
                    str(task_count),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"
