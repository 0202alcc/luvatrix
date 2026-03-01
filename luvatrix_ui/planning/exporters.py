from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .agile_renderer import AgileRenderConfig, render_agile_board_ascii, render_agile_board_markdown
from .gantt_renderer import GanttRenderConfig, render_gantt_ascii
from .schema import PlanningTimeline


@dataclass(frozen=True)
class PlanningExportBundle:
    ascii_gantt_expanded: Path
    ascii_gantt_collapsed: Path
    ascii_agile: Path
    markdown_overview: Path
    markdown_agile: Path
    png_overview: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "ascii_gantt_expanded": str(self.ascii_gantt_expanded),
            "ascii_gantt_collapsed": str(self.ascii_gantt_collapsed),
            "ascii_agile": str(self.ascii_agile),
            "markdown_overview": str(self.markdown_overview),
            "markdown_agile": str(self.markdown_agile),
            "png_overview": str(self.png_overview),
        }


def export_planning_bundle(
    model: PlanningTimeline,
    *,
    out_dir: str | Path,
    prefix: str = "m011_native",
) -> PlanningExportBundle:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    gantt_expanded = render_gantt_ascii(model, GanttRenderConfig(collapsed_lanes=False))
    gantt_collapsed = render_gantt_ascii(model, GanttRenderConfig(collapsed_lanes=True))
    agile_ascii = render_agile_board_ascii(model, AgileRenderConfig(lane_mode="milestone"))
    agile_markdown = render_agile_board_markdown(model, AgileRenderConfig(lane_mode="milestone"))
    overview_markdown = _build_markdown_overview(gantt_expanded=gantt_expanded, agile_markdown=agile_markdown)

    path_gantt_expanded = root / f"{prefix}_gantt_expanded.txt"
    path_gantt_collapsed = root / f"{prefix}_gantt_collapsed.txt"
    path_agile_ascii = root / f"{prefix}_agile_board.txt"
    path_overview_md = root / f"{prefix}_overview.md"
    path_agile_md = root / f"{prefix}_agile_board.md"
    path_overview_png = root / f"{prefix}_overview.png"

    path_gantt_expanded.write_text(gantt_expanded, encoding="utf-8")
    path_gantt_collapsed.write_text(gantt_collapsed, encoding="utf-8")
    path_agile_ascii.write_text(agile_ascii, encoding="utf-8")
    path_overview_md.write_text(overview_markdown, encoding="utf-8")
    path_agile_md.write_text(agile_markdown, encoding="utf-8")

    _render_text_png(
        text=gantt_expanded + "\n" + ("=" * 88) + "\n" + agile_ascii,
        out_path=path_overview_png,
    )

    return PlanningExportBundle(
        ascii_gantt_expanded=path_gantt_expanded,
        ascii_gantt_collapsed=path_gantt_collapsed,
        ascii_agile=path_agile_ascii,
        markdown_overview=path_overview_md,
        markdown_agile=path_agile_md,
        png_overview=path_overview_png,
    )


def build_discord_payload(
    *,
    title: str,
    summary: str,
    bundle: PlanningExportBundle,
) -> dict[str, Any]:
    files = [
        bundle.markdown_overview,
        bundle.markdown_agile,
        bundle.ascii_gantt_expanded,
        bundle.ascii_gantt_collapsed,
        bundle.ascii_agile,
        bundle.png_overview,
    ]
    return {
        "content": f"**{title}**\n{summary}",
        "allowed_mentions": {"parse": []},
        "attachments": [
            {"id": index, "filename": path.name}
            for index, path in enumerate(files)
        ],
        "files": [str(path) for path in files],
    }


def _build_markdown_overview(*, gantt_expanded: str, agile_markdown: str) -> str:
    return (
        "# Native Planning Export\n\n"
        "## Gantt (Expanded)\n\n"
        "```text\n"
        f"{gantt_expanded.rstrip()}\n"
        "```\n\n"
        "## Agile Board\n\n"
        f"{agile_markdown.rstrip()}\n"
    )


def _render_text_png(
    *,
    text: str,
    out_path: Path,
    padding: int = 16,
    line_spacing: int = 4,
    bg: tuple[int, int, int] = (17, 24, 39),
    fg: tuple[int, int, int] = (226, 232, 240),
) -> None:
    lines = text.rstrip("\n").split("\n")
    if not lines:
        lines = [""]

    font = ImageFont.load_default()
    probe = Image.new("RGB", (8, 8), color=bg)
    draw = ImageDraw.Draw(probe)
    max_width = 0
    line_height = 0
    for line in lines:
        x0, y0, x1, y1 = draw.textbbox((0, 0), line, font=font)
        max_width = max(max_width, x1 - x0)
        line_height = max(line_height, y1 - y0)
    line_height = max(12, line_height)

    width = max(320, max_width + (padding * 2))
    height = max(120, len(lines) * (line_height + line_spacing) + (padding * 2))
    image = Image.new("RGB", (width, height), color=bg)
    draw = ImageDraw.Draw(image)

    y = padding
    for line in lines:
        draw.text((padding, y), line, fill=fg, font=font)
        y += line_height + line_spacing

    image.save(out_path)
