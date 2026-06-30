from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from luvatrix_ui import TableColumn, TableComponent
from luvatrix_ui.component_schema import BoundingBox


class TableComponentTests(unittest.TestCase):
    def test_render_frame_draws_table_primitives(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeFrame:
            def rect(self, **kwargs: object) -> None:
                calls.append(("rect", kwargs))

            def text(self, text: str, **kwargs: object) -> None:
                calls.append(("text", {"text": text, **kwargs}))

        table = TableComponent(
            component_id="prices",
            columns=(
                TableColumn(column_id="product", label="Product", key="product", sortable=False),
                TableColumn(column_id="price", label="Price", key="price", sortable=False),
            ),
            rows=(
                {"product": "BTC-USD", "price": "50000"},
                {"product": "ETH-USD", "price": "2500"},
            ),
            bounds=BoundingBox(x=10.0, y=20.0, width=200.0, height=120.0, frame="screen_tl"),
            page_size=10,
            virtual_window=5,
        )

        table.render_frame(FakeFrame(), column_widths={"product": 120.0, "price": 80.0})

        rect_calls = [payload for kind, payload in calls if kind == "rect"]
        text_calls = [payload for kind, payload in calls if kind == "text"]
        self.assertGreaterEqual(len(rect_calls), 4)
        self.assertEqual(text_calls[0]["text"], "Product")
        self.assertEqual(text_calls[1]["text"], "Price")
        self.assertIn("BTC-USD", [call["text"] for call in text_calls])

    def test_render_frame_content_fits_by_default(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeFrame:
            def rect(self, **kwargs: object) -> None:
                calls.append(("rect", kwargs))

            def text(self, text: str, **kwargs: object) -> None:
                calls.append(("text", {"text": text, **kwargs}))

        long_value = "2026-06-13 14:53:51 UTC"
        table = TableComponent(
            component_id="fit",
            columns=(
                TableColumn(column_id="status", label="Status", key="status", sortable=False),
                TableColumn(column_id="timestamp", label="Timestamp", key="timestamp", sortable=False),
            ),
            rows=({"status": "Live", "timestamp": long_value},),
            bounds=BoundingBox(x=0.0, y=0.0, width=80.0, height=40.0, frame="screen_tl"),
            page_size=10,
            virtual_window=5,
        )

        table.render_frame(FakeFrame())

        rect_calls = [payload for kind, payload in calls if kind == "rect"]
        text_values = [str(payload["text"]) for kind, payload in calls if kind == "text"]
        self.assertGreater(float(rect_calls[0]["width"]), 80.0)
        self.assertIn(long_value, text_values)
        self.assertNotIn("2026-06-13 14:53:5...", text_values)

    def test_render_frame_content_fit_does_not_fill_available_bounds(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeFrame:
            def rect(self, **kwargs: object) -> None:
                calls.append(("rect", kwargs))

            def text(self, text: str, **kwargs: object) -> None:
                calls.append(("text", {"text": text, **kwargs}))

        table = TableComponent(
            component_id="shrink",
            columns=(
                TableColumn(column_id="state", label="State", key="state", sortable=False),
                TableColumn(column_id="price", label="Price", key="price", sortable=False),
            ),
            rows=({"state": "Live", "price": "-"},),
            bounds=BoundingBox(x=0.0, y=0.0, width=800.0, height=200.0, frame="screen_tl"),
            page_size=10,
            virtual_window=5,
        )

        table.render_frame(FakeFrame())

        rect_calls = [payload for kind, payload in calls if kind == "rect"]
        self.assertLess(float(rect_calls[0]["width"]), 200.0)

    def test_render_frame_content_fits_multiline_row_height_by_default(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeFrame:
            def rect(self, **kwargs: object) -> None:
                calls.append(("rect", kwargs))

            def text(self, text: str, **kwargs: object) -> None:
                calls.append(("text", {"text": text, **kwargs}))

        table = TableComponent(
            component_id="multiline",
            columns=(TableColumn(column_id="note", label="Note", key="note", sortable=False),),
            rows=({"note": "first\nsecond\nthird"},),
            bounds=BoundingBox(x=0.0, y=0.0, width=120.0, height=40.0, frame="screen_tl"),
            page_size=10,
            virtual_window=5,
        )

        table.render_frame(FakeFrame())

        rect_calls = [payload for kind, payload in calls if kind == "rect"]
        text_values = [str(payload["text"]) for kind, payload in calls if kind == "text"]
        self.assertGreater(float(rect_calls[0]["height"]), 76.0)
        self.assertIn("first", text_values)
        self.assertIn("second", text_values)
        self.assertIn("third", text_values)

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

    def test_from_csv_loads_rows_and_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "data.csv"
            csv_path.write_text("symbol,qty\nAAPL,10\nMSFT,20\n", encoding="utf-8")
            table = TableComponent.from_csv(
                csv_path,
                component_id="csv",
                bounds=BoundingBox(x=0.0, y=0.0, width=100.0, height=40.0, frame="screen_tl"),
                page_size=10,
                virtual_window=5,
            )
        self.assertEqual([column.column_id for column in table.columns], ["symbol", "qty"])
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(str(table.rows[0]["symbol"]), "AAPL")

    def test_from_dataframe_loads_pandas(self) -> None:
        try:
            import pandas as pd
        except Exception:
            self.skipTest("pandas is not installed")
        df = pd.DataFrame({"symbol": ["AAPL", "MSFT"], "qty": [10, 20]})
        table = TableComponent.from_dataframe(
            df,
            component_id="df",
            bounds=BoundingBox(x=0.0, y=0.0, width=100.0, height=40.0, frame="screen_tl"),
            page_size=10,
            virtual_window=5,
        )
        self.assertEqual([column.column_id for column in table.columns], ["symbol", "qty"])
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(int(table.rows[1]["qty"]), 20)


if __name__ == "__main__":
    unittest.main()
