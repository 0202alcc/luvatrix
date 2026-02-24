from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

from luvatrix_core.core.audit import JsonlAuditSink, SQLiteAuditSink


class AuditSinkTests(unittest.TestCase):
    def test_jsonl_sink_persists_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "audit.jsonl"
            sink = JsonlAuditSink(path)
            sink.log({"ts_ns": 1, "action": "disabled", "sensor_type": "thermal.temperature", "actor": "test"})
            rows = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(rows), 1)
            payload = json.loads(rows[0])
            self.assertEqual(payload["action"], "disabled")

    def test_sqlite_sink_persists_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "audit.db"
            sink = SQLiteAuditSink(path)
            sink.log({"ts_ns": 2, "action": "enable_denied", "sensor_type": "sensor.custom", "actor": "test"})
            with closing(sqlite3.connect(path)) as conn:
                row = conn.execute(
                    "SELECT action, sensor_type, actor FROM audit_events ORDER BY id DESC LIMIT 1"
                ).fetchone()
            sink.close()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row[0], "enable_denied")
            self.assertEqual(row[1], "sensor.custom")
            self.assertEqual(row[2], "test")

    def test_jsonl_summarize_and_prune(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "audit.jsonl"
            sink = JsonlAuditSink(path)
            sink.log({"ts_ns": 1, "action": "a", "sensor_type": "s1", "actor": "x"})
            sink.log({"ts_ns": 2, "action": "a", "sensor_type": "s2", "actor": "x"})
            sink.log({"ts_ns": 3, "action": "b", "sensor_type": "s2", "actor": "x"})
            summary = sink.summarize()
            self.assertEqual(summary["total"], 3)
            self.assertEqual(summary["by_action"]["a"], 2)
            deleted = sink.prune(max_rows=2)
            self.assertEqual(deleted, 1)
            self.assertEqual(sink.summarize()["total"], 2)

    def test_sqlite_summarize_and_prune(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "audit.db"
            sink = SQLiteAuditSink(path)
            sink.log({"ts_ns": 1, "action": "a", "sensor_type": "s1", "actor": "x"})
            sink.log({"ts_ns": 2, "action": "a", "sensor_type": "s2", "actor": "x"})
            sink.log({"ts_ns": 3, "action": "b", "sensor_type": "s2", "actor": "x"})
            summary = sink.summarize()
            self.assertEqual(summary["total"], 3)
            self.assertEqual(summary["by_action"]["a"], 2)
            deleted = sink.prune(max_rows=2)
            self.assertEqual(deleted, 1)
            self.assertEqual(sink.summarize()["total"], 2)
            sink.close()


if __name__ == "__main__":
    unittest.main()
