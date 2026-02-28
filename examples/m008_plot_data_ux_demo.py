from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer
from luvatrix_plot import figure
from luvatrix_ui import CoordinatePoint, DisplayableArea, TableComponent, TextAppearance, TextComponent, TextSizeSpec
from luvatrix_ui.component_schema import BoundingBox


def _render_plot_frame(*, panned: bool) -> np.ndarray:
    fig = figure(width=1800, height=1080)
    left_ax, right_ax = fig.subplots(
        1,
        2,
        titles=("Dense Labels + Bars", "Viewport + Pan"),
        x_label_bottom="x",
        y_label_left="value",
    )
    left_ax.set_preferred_panel_aspect_ratio(1.05)
    right_ax.set_preferred_panel_aspect_ratio(1.25)

    x_left = np.arange(18, dtype=np.float64)
    y_left = np.asarray([4, -2, 5, 3, -3, 2, 4, -1, 3, -4, 5, 2, -2, 4, 1, -3, 2, 5], dtype=np.float64)
    labels = [f"rule-{idx:02d}-long-segment-name" for idx in range(x_left.size)]
    left_ax.set_major_tick_steps(x=1.0)
    left_ax.set_x_tick_labels(labels)
    left_ax.bar(x=x_left, y=y_left, width=0.75, color=(96, 182, 255))
    left_ax.plot(x=x_left, y=np.cumsum(y_left) * 0.08, color=(255, 184, 70), width=1)

    x_right = np.linspace(0.0, 120.0, 121, dtype=np.float64)
    y_right = 0.65 * np.sin(x_right * 0.16) + 0.22 * np.cos(x_right * 0.05)
    right_ax.plot(x=x_right, y=y_right, color=(255, 170, 70), width=1)
    right_ax.scatter(x=x_right, y=y_right, color=(90, 190, 255), size=2, alpha=0.9)
    right_ax.set_viewport(xmin=20.0, xmax=70.0)
    if panned:
        right_ax.pan_viewport(24.0)

    return fig.to_rgba()


def _render_table_snapshot(out_dir: Path) -> str:
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
    return table.render_ascii()


def _render_table_luvatrix_rgba(table_ascii: str) -> np.ndarray:
    display = DisplayableArea(content_width_px=1200.0, content_height_px=820.0)
    renderer = MatrixUIFrameRenderer()
    renderer.begin_frame(display, clear_color=(4, 10, 20, 255))
    lines = table_ascii.splitlines()
    for idx, line in enumerate(lines):
        component = TextComponent(
            component_id=f"table-line-{idx}",
            text=line,
            position=CoordinatePoint(28.0, 24.0 + idx * 34.0, "screen_tl"),
            size=TextSizeSpec(unit="px", value=30.0),
            appearance=TextAppearance(color_hex="#d0dae8"),
        )
        component.render(renderer, display)
    frame = renderer.end_frame().cpu().numpy()
    return frame


def _save_rgba(path: Path, frame: np.ndarray) -> None:
    Image.fromarray(frame, mode="RGBA").save(path)


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "discord" / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)

    frame_default = _render_plot_frame(panned=False)
    frame_panned = _render_plot_frame(panned=True)
    table_snapshot = _render_table_snapshot(out_dir)
    table_frame = _render_table_luvatrix_rgba(table_snapshot)

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
