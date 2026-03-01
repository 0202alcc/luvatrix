from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer
from luvatrix_plot import figure
from luvatrix_ui import (
    CoordinatePoint,
    DisplayableArea,
    SVGComponent,
    TableComponent,
    TextAppearance,
    TextComponent,
    TextSizeSpec,
)
from luvatrix_ui.component_schema import BoundingBox


def _render_plot_frame(*, panned: bool) -> np.ndarray:
    top_fig = figure(width=1920, height=760)
    left_ax, right_ax = top_fig.subplots(
        1,
        2,
        titles=("Dense Labels + Bars", "Viewport + Pan"),
        x_label_bottom="x",
        y_label_left="value",
    )
    left_ax.set_preferred_panel_aspect_ratio(1.25)

    x_left = np.arange(18, dtype=np.float64)
    y_left = np.asarray([4, -2, 5, 3, -3, 2, 4, -1, 3, -4, 5, 2, -2, 4, 1, -3, 2, 5], dtype=np.float64)
    labels = [f"rule-{idx:02d}-long-segment-name" for idx in range(x_left.size)]
    left_ax.set_major_tick_steps(x=1.0)
    left_ax.set_x_tick_labels(labels)
    left_ax.bar(x=x_left, y=y_left, width=0.75, color=(96, 182, 255))

    x_right = np.linspace(0.0, 120.0, 121, dtype=np.float64)
    y_right = 0.65 * np.sin(x_right * 0.16) + 0.22 * np.cos(x_right * 0.05)
    right_ax.plot(x=x_right, y=y_right, color=(255, 170, 70), width=1)
    right_ax.scatter(x=x_right, y=y_right, color=(90, 190, 255), size=2, alpha=0.9)
    right_ax.set_preferred_panel_aspect_ratio(1.6)
    right_ax.set_preferred_plot_aspect_ratio(4.0 / 3.0)
    right_ax.set_viewport(xmin=20.0, xmax=70.0)
    if panned:
        right_ax.pan_viewport(24.0)

    bottom_fig = figure(width=1800, height=500)
    bottom_ax = bottom_fig.axes(title="Horizontal Bars", x_label_bottom="value", y_label_left="bucket")
    y_pos = np.arange(8, dtype=np.float64)
    widths = np.asarray([2.2, -1.4, 3.1, -2.0, 4.2, -0.8, 1.7, 2.9], dtype=np.float64)
    bottom_ax.set_major_tick_steps(y=1.0)
    bottom_ax.barh(width=widths, y=y_pos, height=0.72, color=(104, 190, 255))

    top_rgba = top_fig.to_rgba()
    bottom_rgba = bottom_fig.to_rgba()
    gap = 12
    out_h = top_rgba.shape[0] + gap + bottom_rgba.shape[0]
    out_w = max(top_rgba.shape[1], bottom_rgba.shape[1])
    out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
    out[:, :, :] = np.asarray([12, 16, 23, 255], dtype=np.uint8)
    out[0 : top_rgba.shape[0], 0 : top_rgba.shape[1], :] = top_rgba
    y0 = top_rgba.shape[0] + gap
    out[y0 : y0 + bottom_rgba.shape[0], 0 : bottom_rgba.shape[1], :] = bottom_rgba
    return out


def _build_demo_table(out_dir: Path) -> TableComponent:
    csv_lines = [
        "symbol,qty,pnl",
        "AAPL,50,1240.5",
        "MSFT,20,-115.2",
        "NVDA,12,840.4",
        "AMD,35,210.0",
        "TSLA,9,-450.9",
        "META,15,330.7",
        "AMZN,18,145.1",
        "GOOGL,14,188.6",
        "NFLX,8,-52.2",
        "ORCL,27,94.0",
        "INTC,60,-18.0",
    ]
    csv_path = out_dir / "m008_demo_positions.csv"
    csv_path.write_text("\n".join(csv_lines) + "\n", encoding="utf-8")

    table = TableComponent.from_csv(
        csv_path,
        component_id="positions",
        bounds=BoundingBox(x=0.0, y=0.0, width=300.0, height=120.0, frame="screen_tl"),
        page_size=6,
        virtual_window=4,
    )
    table.sort_by("pnl", direction="desc")
    table.handle_key("ArrowRight")
    table.handle_key("ArrowRight")
    table.handle_key("Enter")
    table.handle_key("ArrowDown")
    table.handle_key("ArrowDown")
    table.handle_key("PageDown")
    return table


def _render_table_luvatrix_rgba(table: TableComponent) -> np.ndarray:
    display = DisplayableArea(content_width_px=1320.0, content_height_px=860.0)
    renderer = MatrixUIFrameRenderer()
    renderer.begin_frame(display, clear_color=(4, 10, 20, 255))
    columns = list(table.columns)
    rows = list(table.visible_rows())
    header_h = 72.0
    row_h = 64.0
    table_x = 70.0
    table_y = 120.0
    col_widths = [280.0, 180.0, 220.0]
    table_w = float(sum(col_widths))
    table_h = header_h + row_h * max(1, len(rows))
    table_svg = f"""
<svg width="{int(table_w)}" height="{int(table_h)}" viewBox="0 0 {int(table_w)} {int(table_h)}">
  <rect x="0" y="0" width="{int(table_w)}" height="{int(table_h)}" fill="#0c1728" stroke="#6f88ad" stroke-width="2"/>
  <rect x="0" y="0" width="{int(table_w)}" height="{int(header_h)}" fill="#16304d"/>
</svg>
""".strip()
    SVGComponent(
        component_id="table-bg",
        svg_markup=table_svg,
        position=CoordinatePoint(table_x, table_y, "screen_tl"),
        width=table_w,
        height=table_h,
    ).render(renderer)
    cursor_x = table_x
    for i, width in enumerate(col_widths):
        if i > 0:
            line_svg = '<svg width="2" height="2"><rect x="0" y="0" width="2" height="2" fill="#6f88ad"/></svg>'
            SVGComponent(
                component_id=f"table-col-line-{i}",
                svg_markup=line_svg,
                position=CoordinatePoint(cursor_x, table_y, "screen_tl"),
                width=2.0,
                height=table_h,
            ).render(renderer)
        cursor_x += width
    for i in range(1, max(1, len(rows)) + 1):
        y = table_y + header_h + (i - 1) * row_h
        line_svg = '<svg width="2" height="2"><rect x="0" y="0" width="2" height="2" fill="#2d4362"/></svg>'
        SVGComponent(
            component_id=f"table-row-line-{i}",
            svg_markup=line_svg,
            position=CoordinatePoint(table_x, y, "screen_tl"),
            width=table_w,
            height=2.0,
        ).render(renderer)

    TextComponent(
        component_id="table-title",
        text=f"Positions (page {table.page_index + 1}/{table.page_count()})",
        position=CoordinatePoint(table_x, 48.0, "screen_tl"),
        size=TextSizeSpec(unit="px", value=34.0),
        appearance=TextAppearance(color_hex="#d0dae8"),
    ).render(renderer, display)
    TextComponent(
        component_id="table-subtitle",
        text=f"sort={table.sort_column_id}:{table.sort_direction} window={table.virtual_offset + 1}-{table.virtual_offset + len(rows)}",
        position=CoordinatePoint(table_x, 84.0, "screen_tl"),
        size=TextSizeSpec(unit="px", value=24.0),
        appearance=TextAppearance(color_hex="#93abc9"),
    ).render(renderer, display)

    x_cursor = table_x + 20.0
    for idx, column in enumerate(columns):
        sort_marker = ""
        if table.sort_column_id == column.column_id:
            sort_marker = " ^" if table.sort_direction == "asc" else " v"
        TextComponent(
            component_id=f"table-header-{idx}",
            text=f"{column.label}{sort_marker}",
            position=CoordinatePoint(x_cursor, table_y + 18.0, "screen_tl"),
            size=TextSizeSpec(unit="px", value=30.0),
            appearance=TextAppearance(color_hex="#e5efff"),
        ).render(renderer, display)
        x_cursor += col_widths[idx]

    for row_idx, row in enumerate(rows):
        focus = table.focus_region == "body" and row_idx == table.focus_row
        y = table_y + header_h + row_idx * row_h + 16.0
        x_cursor = table_x + 20.0
        row_color = "#f2f7ff" if focus else "#afbdd1"
        if focus:
            TextComponent(
                component_id=f"table-focus-{row_idx}",
                text=">",
                position=CoordinatePoint(table_x + 6.0, y, "screen_tl"),
                size=TextSizeSpec(unit="px", value=30.0),
                appearance=TextAppearance(color_hex="#f2f7ff"),
            ).render(renderer, display)
        for col_idx, column in enumerate(columns):
            raw = row.get(column.key)
            if isinstance(raw, float):
                value_text = f"{raw:.1f}"
            else:
                value_text = str(raw)
            TextComponent(
                component_id=f"table-cell-{row_idx}-{col_idx}",
                text=value_text,
                position=CoordinatePoint(x_cursor, y, "screen_tl"),
                size=TextSizeSpec(unit="px", value=34.0 if col_idx == 0 else 32.0),
                appearance=TextAppearance(color_hex=row_color),
            ).render(renderer, display)
            x_cursor += col_widths[col_idx]
    frame = renderer.end_frame().cpu().numpy()
    return frame


def _save_rgba(path: Path, frame: np.ndarray) -> None:
    Image.fromarray(frame, mode="RGBA").save(path)


def main() -> None:
    file_path = Path(__file__).resolve()
    repo_root = None
    for parent in file_path.parents:
        if (parent / "discord").exists() and (parent / "examples").exists():
            repo_root = parent
            break
    if repo_root is None:
        raise RuntimeError("could not resolve repository root for demo output directory")
    out_dir = repo_root / "discord" / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)

    frame_default = _render_plot_frame(panned=False)
    frame_panned = _render_plot_frame(panned=True)
    table = _build_demo_table(out_dir)
    table_snapshot = table.render_ascii()
    table_frame = _render_table_luvatrix_rgba(table)

    plot_default_path = out_dir / "m008_demo_plot_default.png"
    plot_panned_path = out_dir / "m008_demo_plot_panned.png"
    table_path = out_dir / "m008_demo_table.txt"
    table_png_path = out_dir / "m008_demo_table.png"

    _save_rgba(plot_default_path, frame_default)
    _save_rgba(plot_panned_path, frame_panned)
    _save_rgba(table_png_path, table_frame)
    table_path.write_text(table_snapshot + "\n", encoding="utf-8")

    print(f"wrote {plot_default_path}")
    print(f"wrote {plot_panned_path}")
    print(f"wrote {table_path}")
    print(f"wrote {table_png_path}")


if __name__ == "__main__":
    main()
