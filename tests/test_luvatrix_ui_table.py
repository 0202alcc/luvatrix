from __future__ import annotations

import unittest

from luvatrix_ui import TableColumn, TableComponent
from luvatrix_ui.component_schema import BoundingBox


class TableComponentTests(unittest.TestCase):
    def test_sorting_and_render_are_deterministic(self) -> None:
        table = TableComponent(
            component_id="orders",
            columns=(
                TableColumn(column_id="symbol", label="Symbol", key="symbol"),
                TableColumn(column_id="qty", label="Qty", key="qty"),
            ),
            rows=(
                {"symbol": "MSFT", "qty": 20},
                {"symbol": "AAPL", "qty": 5},
                {"symbol": "NVDA", "qty": 10},
            ),
            bounds=BoundingBox(x=0.0, y=0.0, width=100.0, height=40.0, frame="screen_tl"),
            page_size=10,
            virtual_window=5,
        )
        table.sort_by("qty", direction="asc")
        visible = table.visible_rows()
        self.assertEqual([int(row["qty"]) for row in visible], [5, 10, 20])

        first = table.render_ascii()
        second = table.render_ascii()
        self.assertEqual(first, second)

    def test_pagination_and_virtualization(self) -> None:
        rows = tuple({"id": i, "value": i * 10} for i in range(25))
        table = TableComponent(
            component_id="metrics",
            columns=(
                TableColumn(column_id="id", label="ID", key="id"),
                TableColumn(column_id="value", label="Value", key="value"),
            ),
            rows=rows,
            bounds=BoundingBox(x=0.0, y=0.0, width=100.0, height=40.0, frame="screen_tl"),
            page_size=10,
            virtual_window=4,
        )
        table.set_page(2)
        self.assertEqual([int(r["id"]) for r in table.visible_rows()], [20, 21, 22, 23])
        table.set_virtual_offset(3)
        self.assertEqual([int(r["id"]) for r in table.visible_rows()], [21, 22, 23, 24])

    def test_keyboard_navigation_baseline(self) -> None:
        rows = tuple({"id": i, "name": f"item-{i}"} for i in range(6))
        table = TableComponent(
            component_id="keyboard",
            columns=(
                TableColumn(column_id="id", label="ID", key="id"),
                TableColumn(column_id="name", label="Name", key="name"),
            ),
            rows=rows,
            bounds=BoundingBox(x=0.0, y=0.0, width=100.0, height=40.0, frame="screen_tl"),
            page_size=3,
            virtual_window=2,
        )
        self.assertTrue(table.handle_key("ArrowRight"))
        self.assertEqual(table.snapshot_state().focus_col, 1)
        self.assertTrue(table.handle_key("Enter"))
        self.assertEqual(table.snapshot_state().sort_column_id, "name")
        self.assertTrue(table.handle_key("ArrowDown"))
        self.assertEqual(table.snapshot_state().focus_region, "body")
        self.assertTrue(table.handle_key("ArrowDown"))
        self.assertEqual(table.snapshot_state().focus_row, 1)
        self.assertTrue(table.handle_key("ArrowDown"))
        self.assertEqual(table.snapshot_state().virtual_offset, 1)
        self.assertTrue(table.handle_key("PageDown"))
        self.assertEqual(table.snapshot_state().page_index, 1)


if __name__ == "__main__":
    unittest.main()
