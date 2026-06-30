from __future__ import annotations

import csv
from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol, Sequence

from luvatrix_ui.component_schema import BoundingBox, ComponentBase


SortDirection = Literal["asc", "desc"]
FocusRegion = Literal["header", "body"]


class TableFrame(Protocol):
    def rect(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        color: tuple[int, int, int, int] | str,
        z_index: int = 0,
    ) -> None:
        ...

    def text(
        self,
        text: str,
        *,
        x: float,
        y: float,
        font_size_px: float = 14.0,
        color: tuple[int, int, int, int] | str = (255, 255, 255, 255),
        z_index: int = 0,
        cache_key: str | None = None,
    ) -> None:
        ...


@dataclass(frozen=True)
class TableColumn:
    column_id: str
    label: str
    key: str
    sortable: bool = True

    def __post_init__(self) -> None:
        if not self.column_id.strip():
            raise ValueError("column_id must be non-empty")
        if not self.label.strip():
            raise ValueError("column label must be non-empty")
        if not self.key.strip():
            raise ValueError("column key must be non-empty")


@dataclass(frozen=True)
class TableState:
    sort_column_id: str | None
    sort_direction: SortDirection
    page_index: int
    page_size: int
    virtual_offset: int
    virtual_window: int
    focus_region: FocusRegion
    focus_col: int
    focus_row: int


@dataclass(frozen=True)
class TableRenderStyle:
    background_color: str = "#0b1220ff"
    header_background_color: str = "#111827ff"
    odd_row_background_color: str = "#0f172aff"
    grid_color: str = "#1f2937ff"
    header_text_color: str = "#93c5fdff"
    body_text_color: str = "#e5e7ebff"
    padding_x: float = 12.0
    padding_y: float = 10.0
    header_height: float = 34.0
    row_height: float = 42.0
    header_font_size_px: float = 12.0
    body_font_size_px: float = 12.0
    min_text_chars: int = 4
    approx_char_width_px: float = 7.0
    line_height_multiplier: float = 1.25
    fit_content_width: bool = True
    fit_content_height: bool = True


CellColorResolver = Callable[[TableColumn, Mapping[str, object], str], str | None]


@dataclass
class TableComponent(ComponentBase):
    columns: tuple[TableColumn, ...] = ()
    rows: tuple[Mapping[str, object], ...] = ()
    bounds: BoundingBox = field(default_factory=lambda: BoundingBox(x=0.0, y=0.0, width=1.0, height=1.0, frame="screen_tl"))
    page_size: int = 10
    virtual_window: int = 8
    sort_column_id: str | None = None
    sort_direction: SortDirection = "asc"
    page_index: int = 0
    virtual_offset: int = 0
    focus_region: FocusRegion = "header"
    focus_col: int = 0
    focus_row: int = 0

    def __post_init__(self) -> None:
        if not self.columns:
            raise ValueError("table requires at least one column")
        if self.page_size <= 0:
            raise ValueError("page_size must be > 0")
        if self.virtual_window <= 0:
            raise ValueError("virtual_window must be > 0")
        self.columns = tuple(self.columns)
        self.rows = tuple(dict(row) for row in self.rows)
        if self.sort_column_id is None:
            sortable = [column.column_id for column in self.columns if column.sortable]
            self.sort_column_id = sortable[0] if sortable else None
        self._clamp_state()

    @classmethod
    def from_csv(
        cls,
        csv_path: str | Path,
        *,
        component_id: str,
        bounds: BoundingBox,
        page_size: int = 50,
        virtual_window: int = 20,
        delimiter: str = ",",
    ) -> "TableComponent":
        path = Path(csv_path)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            fieldnames = list(reader.fieldnames or [])
            if not fieldnames:
                raise ValueError("csv has no header columns")
            rows = [dict(row) for row in reader]
        columns = tuple(TableColumn(column_id=name, label=name, key=name) for name in fieldnames)
        return cls(
            component_id=component_id,
            columns=columns,
            rows=tuple(rows),
            bounds=bounds,
            page_size=page_size,
            virtual_window=virtual_window,
        )

    @classmethod
    def from_dataframe(
        cls,
        dataframe: object,
        *,
        component_id: str,
        bounds: BoundingBox,
        page_size: int = 50,
        virtual_window: int = 20,
    ) -> "TableComponent":
        columns_attr = getattr(dataframe, "columns", None)
        to_dict_fn = getattr(dataframe, "to_dict", None)
        if columns_attr is None or not callable(to_dict_fn):
            raise TypeError("dataframe must provide columns and to_dict methods")
        column_names = [str(name) for name in list(columns_attr)]
        rows_raw = to_dict_fn(orient="records")
        if not isinstance(rows_raw, list):
            raise TypeError("dataframe.to_dict(orient='records') must return a list")
        rows: list[dict[str, object]] = []
        for item in rows_raw:
            if not isinstance(item, Mapping):
                raise TypeError("dataframe record rows must be mappings")
            rows.append({str(k): v for k, v in item.items()})
        columns = tuple(TableColumn(column_id=name, label=name, key=name) for name in column_names)
        return cls(
            component_id=component_id,
            columns=columns,
            rows=tuple(rows),
            bounds=bounds,
            page_size=page_size,
            virtual_window=virtual_window,
        )

    def visual_bounds(self) -> BoundingBox:
        return self.bounds

    def snapshot_state(self) -> TableState:
        return TableState(
            sort_column_id=self.sort_column_id,
            sort_direction=self.sort_direction,
            page_index=self.page_index,
            page_size=self.page_size,
            virtual_offset=self.virtual_offset,
            virtual_window=self.virtual_window,
            focus_region=self.focus_region,
            focus_col=self.focus_col,
            focus_row=self.focus_row,
        )

    def page_count(self) -> int:
        return max(1, math.ceil(len(self.rows) / self.page_size))

    def set_rows(self, rows: Sequence[Mapping[str, object]]) -> "TableComponent":
        self.rows = tuple(dict(row) for row in rows)
        self._clamp_state()
        return self

    def sort_by(self, column_id: str, *, direction: SortDirection | None = None) -> "TableComponent":
        column = self._column_by_id(column_id)
        if column is None or not column.sortable:
            return self
        if direction is not None:
            self.sort_direction = direction
            self.sort_column_id = column_id
            return self
        if self.sort_column_id == column_id:
            self.sort_direction = "desc" if self.sort_direction == "asc" else "asc"
        else:
            self.sort_column_id = column_id
            self.sort_direction = "asc"
        return self

    def set_page(self, page_index: int) -> "TableComponent":
        self.page_index = int(page_index)
        self._clamp_state()
        return self

    def set_virtual_offset(self, offset: int) -> "TableComponent":
        self.virtual_offset = int(offset)
        self._clamp_state()
        return self

    def handle_key(self, key: str) -> bool:
        if key == "ArrowLeft":
            self.focus_col = max(0, self.focus_col - 1)
            return True
        if key == "ArrowRight":
            self.focus_col = min(len(self.columns) - 1, self.focus_col + 1)
            return True
        if key == "ArrowDown":
            return self._move_focus_down()
        if key == "ArrowUp":
            return self._move_focus_up()
        if key == "PageDown":
            self.page_index = min(self.page_count() - 1, self.page_index + 1)
            self.virtual_offset = 0
            self.focus_row = 0
            self.focus_region = "body"
            self._clamp_state()
            return True
        if key == "PageUp":
            self.page_index = max(0, self.page_index - 1)
            self.virtual_offset = 0
            self.focus_row = 0
            self.focus_region = "body"
            self._clamp_state()
            return True
        if key == "Home":
            self.page_index = 0
            self.virtual_offset = 0
            self.focus_row = 0
            self.focus_col = 0
            self.focus_region = "header"
            self._clamp_state()
            return True
        if key == "End":
            self.page_index = self.page_count() - 1
            self.virtual_offset = max(0, len(self._page_rows()) - self._effective_virtual_window())
            self.focus_row = max(0, self._visible_row_count() - 1)
            self.focus_col = len(self.columns) - 1
            self.focus_region = "body"
            self._clamp_state()
            return True
        if key in {"Enter", "Space"} and self.focus_region == "header":
            target = self.columns[self.focus_col]
            if target.sortable:
                self.sort_by(target.column_id)
                self._clamp_state()
                return True
        return False

    def visible_rows(self) -> tuple[Mapping[str, object], ...]:
        page_rows = self._page_rows()
        window = self._effective_virtual_window()
        start = min(max(0, self.virtual_offset), max(0, len(page_rows) - window))
        end = min(len(page_rows), start + window)
        return tuple(page_rows[start:end])

    def render_ascii(self) -> str:
        visible_rows = self.visible_rows()
        headers = [self._header_label(i, column) for i, column in enumerate(self.columns)]
        cells: list[list[str]] = []
        for row in visible_rows:
            cells.append([self._cell_text(row.get(column.key)) for column in self.columns])
        widths = []
        for col_idx, header in enumerate(headers):
            body_max = max((len(row[col_idx]) for row in cells), default=0)
            widths.append(min(28, max(4, len(header), body_max)))

        def _clip(value: str, width: int) -> str:
            if len(value) <= width:
                return value + (" " * (width - len(value)))
            if width <= 3:
                return value[:width]
            return value[: width - 3] + "..."

        border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
        header_line = "| " + " | ".join(_clip(headers[i], widths[i]) for i in range(len(widths))) + " |"
        lines = [
            f"table={self.component_id} sort={self.sort_column_id or '-'}:{self.sort_direction}",
            f"page={self.page_index + 1}/{self.page_count()} window={self.virtual_offset + 1}-{self.virtual_offset + len(visible_rows)}",
            border,
            header_line,
            border,
        ]
        for row_index, row in enumerate(cells):
            marker = ">" if self.focus_region == "body" and row_index == self.focus_row else " "
            lines.append(
                marker + " " + "| " + " | ".join(_clip(row[i], widths[i]) for i in range(len(widths))) + " |"
            )
        lines.append(border)
        return "\n".join(lines)

    def render_frame(
        self,
        frame: TableFrame,
        *,
        style: TableRenderStyle | None = None,
        column_widths: Mapping[str, float] | Sequence[float] | None = None,
        cell_color: CellColorResolver | None = None,
        z_index: int = 0,
    ) -> None:
        style = style or TableRenderStyle()
        bounds = self.visual_bounds()
        rows = self.visible_rows()
        column_width_values = self._resolve_column_widths(column_widths, rows, style)
        table_width = sum(column_width_values) if style.fit_content_width else bounds.width
        header_h = self._header_height(style)
        row_heights = self._row_heights(rows, style)
        table_height = header_h + sum(row_heights)
        if not style.fit_content_height and bounds.height > 0:
            table_height = min(bounds.height, table_height)

        frame.rect(x=bounds.x, y=bounds.y, width=table_width, height=table_height, color=style.background_color, z_index=z_index)
        frame.rect(
            x=bounds.x,
            y=bounds.y,
            width=table_width,
            height=min(header_h, table_height),
            color=style.header_background_color,
            z_index=z_index + 1,
        )

        cursor_x = bounds.x
        for column_index, column in enumerate(self.columns):
            col_width = column_width_values[column_index]
            header_lines = self._render_lines(self._visual_header_label(column), col_width, style, column_widths is None)
            header_text_h = len(header_lines) * self._line_height(style.header_font_size_px, style)
            header_y = bounds.y + max(style.padding_y, (header_h - header_text_h) / 2.0)
            self._draw_text_lines(
                frame,
                header_lines,
                x=cursor_x + style.padding_x,
                y=header_y,
                font_size_px=style.header_font_size_px,
                color=style.header_text_color,
                z_index=z_index + 2,
                cache_key_prefix=f"{self.component_id}_header_{column.column_id}",
                style=style,
            )
            cursor_x += col_width
            if column_index < len(self.columns) - 1:
                frame.rect(x=cursor_x, y=bounds.y, width=1.0, height=table_height, color=style.grid_color, z_index=z_index + 3)

        row_y = bounds.y + header_h
        for row_index, row in enumerate(rows):
            if row_y >= bounds.y + table_height:
                break
            row_h = min(row_heights[row_index], bounds.y + table_height - row_y)
            if row_index % 2 == 1:
                frame.rect(x=bounds.x, y=row_y, width=table_width, height=row_h, color=style.odd_row_background_color, z_index=z_index + 1)
            frame.rect(x=bounds.x, y=row_y, width=table_width, height=1.0, color=style.grid_color, z_index=z_index + 3)
            cursor_x = bounds.x
            for column_index, column in enumerate(self.columns):
                col_width = column_width_values[column_index]
                raw_text = self._cell_text(row.get(column.key))
                lines = self._render_lines(raw_text, col_width, style, column_widths is None)
                color = cell_color(column, row, raw_text) if cell_color is not None else None
                cell_text_h = len(lines) * self._line_height(style.body_font_size_px, style)
                cell_y = row_y + max(style.padding_y, (row_h - cell_text_h) / 2.0)
                self._draw_text_lines(
                    frame,
                    lines,
                    x=cursor_x + style.padding_x,
                    y=cell_y,
                    font_size_px=style.body_font_size_px,
                    color=color or style.body_text_color,
                    z_index=z_index + 2,
                    cache_key_prefix=f"{self.component_id}_cell_{row_index}_{column.column_id}",
                    style=style,
                )
                cursor_x += col_width
            row_y += row_h

    def rendered_height(self, *, style: TableRenderStyle | None = None) -> float:
        style = style or TableRenderStyle()
        return self._header_height(style) + sum(self._row_heights(self.visible_rows(), style))

    def _header_label(self, idx: int, column: TableColumn) -> str:
        sort_indicator = ""
        if self.sort_column_id == column.column_id:
            sort_indicator = "^" if self.sort_direction == "asc" else "v"
        focus_prefix = ">" if self.focus_region == "header" and self.focus_col == idx else " "
        return f"{focus_prefix}{column.label}{sort_indicator}"

    def _visual_header_label(self, column: TableColumn) -> str:
        sort_indicator = ""
        if self.sort_column_id == column.column_id:
            sort_indicator = " ^" if self.sort_direction == "asc" else " v"
        return f"{column.label}{sort_indicator}"

    def _column_by_id(self, column_id: str) -> TableColumn | None:
        for column in self.columns:
            if column.column_id == column_id:
                return column
        return None

    def _sorted_rows(self) -> list[Mapping[str, object]]:
        rows = list(self.rows)
        column = self._column_by_id(self.sort_column_id or "")
        if column is None or not column.sortable:
            return rows
        reverse = self.sort_direction == "desc"
        rows.sort(key=lambda row: _sort_key(row.get(column.key)), reverse=reverse)
        return rows

    def _page_rows(self) -> list[Mapping[str, object]]:
        rows = self._sorted_rows()
        start = self.page_index * self.page_size
        end = min(len(rows), start + self.page_size)
        return rows[start:end]

    def _visible_row_count(self) -> int:
        return len(self.visible_rows())

    def _effective_virtual_window(self) -> int:
        return max(1, min(self.virtual_window, self.page_size))

    def _move_focus_down(self) -> bool:
        visible_count = self._visible_row_count()
        if self.focus_region == "header":
            self.focus_region = "body"
            self.focus_row = 0
            self._clamp_state()
            return visible_count > 0
        if visible_count == 0:
            return False
        if self.focus_row < visible_count - 1:
            self.focus_row += 1
            return True
        page_rows = self._page_rows()
        max_offset = max(0, len(page_rows) - self._effective_virtual_window())
        if self.virtual_offset < max_offset:
            self.virtual_offset += 1
            self._clamp_state()
            return True
        if self.page_index < self.page_count() - 1:
            self.page_index += 1
            self.virtual_offset = 0
            self.focus_row = 0
            self._clamp_state()
            return True
        return False

    def _move_focus_up(self) -> bool:
        if self.focus_region == "header":
            return False
        if self.focus_row > 0:
            self.focus_row -= 1
            return True
        if self.virtual_offset > 0:
            self.virtual_offset -= 1
            self._clamp_state()
            return True
        if self.page_index > 0:
            self.page_index -= 1
            self.virtual_offset = max(0, len(self._page_rows()) - self._effective_virtual_window())
            self.focus_row = max(0, self._visible_row_count() - 1)
            self._clamp_state()
            return True
        self.focus_region = "header"
        self.focus_row = 0
        return True

    def _clamp_state(self) -> None:
        self.focus_col = min(max(0, self.focus_col), len(self.columns) - 1)
        self.page_index = min(max(0, self.page_index), self.page_count() - 1)
        page_rows = self._page_rows()
        window = self._effective_virtual_window()
        max_offset = max(0, len(page_rows) - window)
        self.virtual_offset = min(max(0, self.virtual_offset), max_offset)
        visible_count = self._visible_row_count()
        self.focus_row = min(max(0, self.focus_row), max(0, visible_count - 1))
        if visible_count == 0 and self.focus_region == "body":
            self.focus_region = "header"
            self.focus_row = 0

    @staticmethod
    def _cell_text(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            if math.isfinite(value):
                if abs(value - round(value)) <= 1e-9:
                    return str(int(round(value)))
                return f"{value:.4f}".rstrip("0").rstrip(".")
        return str(value)

    def _resolve_column_widths(
        self,
        column_widths: Mapping[str, float] | Sequence[float] | None,
        rows: Sequence[Mapping[str, object]],
        style: TableRenderStyle,
    ) -> tuple[float, ...]:
        width = max(1.0, self.bounds.width)
        if column_widths is None:
            return self._content_column_widths(rows, style)
        if isinstance(column_widths, Mapping):
            raw = [float(column_widths.get(column.column_id, 0.0)) for column in self.columns]
        else:
            raw = [float(value) for value in column_widths]
            if len(raw) != len(self.columns):
                raise ValueError("column_widths sequence length must match table columns")
        missing_indexes = [index for index, value in enumerate(raw) if value <= 0.0]
        used = sum(value for value in raw if value > 0.0)
        remaining = max(0.0, width - used)
        fill = remaining / len(missing_indexes) if missing_indexes else 0.0
        for index in missing_indexes:
            raw[index] = fill
        total = sum(raw)
        if total <= 0.0:
            even = width / len(self.columns)
            return tuple(even for _ in self.columns)
        if abs(total - width) > 1e-6:
            scale = width / total
            raw = [value * scale for value in raw]
        return tuple(raw)

    def _content_column_widths(self, rows: Sequence[Mapping[str, object]], style: TableRenderStyle) -> tuple[float, ...]:
        widths: list[float] = []
        for column in self.columns:
            max_chars = max(style.min_text_chars, self._max_line_length(self._visual_header_label(column)))
            for row in rows:
                max_chars = max(max_chars, self._max_line_length(self._cell_text(row.get(column.key))))
            widths.append(max_chars * max(1.0, style.approx_char_width_px) + style.padding_x * 2.0)
        return tuple(widths)

    def _header_height(self, style: TableRenderStyle) -> float:
        if not style.fit_content_height:
            return style.header_height
        max_lines = max((len(self._text_lines(self._visual_header_label(column))) for column in self.columns), default=1)
        return max(style.header_height, max_lines * self._line_height(style.header_font_size_px, style) + style.padding_y * 2.0)

    def _row_heights(self, rows: Sequence[Mapping[str, object]], style: TableRenderStyle) -> list[float]:
        if not rows:
            return [style.row_height]
        heights: list[float] = []
        for row in rows:
            if style.fit_content_height:
                max_lines = max((len(self._text_lines(self._cell_text(row.get(column.key)))) for column in self.columns), default=1)
                heights.append(max(style.row_height, max_lines * self._line_height(style.body_font_size_px, style) + style.padding_y * 2.0))
            else:
                heights.append(style.row_height)
        return heights

    def _render_lines(self, text: str, width: float, style: TableRenderStyle, content_fit: bool) -> list[str]:
        lines = self._text_lines(text)
        if content_fit:
            return lines
        usable_width = max(0.0, width - style.padding_x * 2.0)
        max_chars = max(style.min_text_chars, int(usable_width / max(1.0, style.approx_char_width_px)))
        return [self._clip_line_to_chars(line, max_chars) for line in lines]

    def _draw_text_lines(
        self,
        frame: TableFrame,
        lines: Sequence[str],
        *,
        x: float,
        y: float,
        font_size_px: float,
        color: tuple[int, int, int, int] | str,
        z_index: int,
        cache_key_prefix: str,
        style: TableRenderStyle,
    ) -> None:
        line_height = self._line_height(font_size_px, style)
        for line_index, line in enumerate(lines):
            frame.text(
                line,
                x=x,
                y=y + line_index * line_height,
                font_size_px=font_size_px,
                color=color,
                z_index=z_index,
                cache_key=f"{cache_key_prefix}_{line_index}_{line}",
            )

    @staticmethod
    def _text_lines(text: str) -> list[str]:
        lines = str(text).splitlines()
        return lines or [""]

    @classmethod
    def _max_line_length(cls, text: str) -> int:
        return max((len(line) for line in cls._text_lines(text)), default=0)

    @staticmethod
    def _clip_line_to_chars(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        if max_chars <= 1:
            return text[:max_chars]
        return text[: max_chars - 1] + "..."

    @staticmethod
    def _line_height(font_size_px: float, style: TableRenderStyle) -> float:
        return max(1.0, font_size_px * style.line_height_multiplier)


def _sort_key(value: object) -> tuple[int, float, str]:
    if value is None:
        return (2, 0.0, "")
    if isinstance(value, bool):
        return (0, float(int(value)), "")
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isfinite(numeric):
            return (0, numeric, "")
    return (1, 0.0, str(value))
