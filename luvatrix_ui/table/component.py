from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Literal, Mapping, Sequence

from luvatrix_ui.component_schema import BoundingBox, ComponentBase


SortDirection = Literal["asc", "desc"]
FocusRegion = Literal["header", "body"]


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

    def _header_label(self, idx: int, column: TableColumn) -> str:
        sort_indicator = ""
        if self.sort_column_id == column.column_id:
            sort_indicator = "^" if self.sort_direction == "asc" else "v"
        focus_prefix = ">" if self.focus_region == "header" and self.focus_col == idx else " "
        return f"{focus_prefix}{column.label}{sort_indicator}"

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
