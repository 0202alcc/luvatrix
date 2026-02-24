from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
from typing import Any
import atexit


class JsonlAuditSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, entry: dict[str, Any]) -> None:
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True))
                f.write("\n")

    def summarize(self) -> dict[str, Any]:
        action_counts: dict[str, int] = {}
        sensor_counts: dict[str, int] = {}
        total = 0
        if not self.path.exists():
            return {"total": 0, "by_action": action_counts, "by_sensor": sensor_counts}
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                total += 1
                action = str(row.get("action", ""))
                sensor = str(row.get("sensor_type", ""))
                action_counts[action] = action_counts.get(action, 0) + 1
                sensor_counts[sensor] = sensor_counts.get(sensor, 0) + 1
        return {"total": total, "by_action": action_counts, "by_sensor": sensor_counts}

    def prune(self, *, max_rows: int | None = None) -> int:
        if max_rows is None or max_rows <= 0 or not self.path.exists():
            return 0
        rows = [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(rows) <= max_rows:
            return 0
        kept = rows[-max_rows:]
        with self.path.open("w", encoding="utf-8") as f:
            for row in kept:
                f.write(row)
                f.write("\n")
        return len(rows) - len(kept)


class SQLiteAuditSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = sqlite3.connect(self.path, check_same_thread=False)
        self._init_db()
        atexit.register(self.close)

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ns INTEGER,
                action TEXT,
                sensor_type TEXT,
                actor TEXT,
                payload_json TEXT
            )
            """
        )
        self._conn.commit()

    def log(self, entry: dict[str, Any]) -> None:
        payload = json.dumps(entry, separators=(",", ":"), sort_keys=True)
        with self._lock:
            if self._conn is None:
                return
            self._conn.execute(
                "INSERT INTO audit_events (ts_ns, action, sensor_type, actor, payload_json) VALUES (?, ?, ?, ?, ?)",
                (
                    int(entry.get("ts_ns", 0)),
                    str(entry.get("action", "")),
                    str(entry.get("sensor_type", "")),
                    str(entry.get("actor", "")),
                    payload,
                )
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is None:
                return
            self._conn.close()
            self._conn = None

    def summarize(self) -> dict[str, Any]:
        with self._lock:
            if self._conn is None:
                return {"total": 0, "by_action": {}, "by_sensor": {}}
            total = int(self._conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
            by_action = {
                str(row[0]): int(row[1])
                for row in self._conn.execute("SELECT action, COUNT(*) FROM audit_events GROUP BY action")
            }
            by_sensor = {
                str(row[0]): int(row[1])
                for row in self._conn.execute("SELECT sensor_type, COUNT(*) FROM audit_events GROUP BY sensor_type")
            }
            return {"total": total, "by_action": by_action, "by_sensor": by_sensor}

    def prune(self, *, max_rows: int | None = None) -> int:
        if max_rows is None or max_rows <= 0:
            return 0
        with self._lock:
            if self._conn is None:
                return 0
            total = int(self._conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
            overflow = total - max_rows
            if overflow <= 0:
                return 0
            self._conn.execute(
                "DELETE FROM audit_events WHERE id IN (SELECT id FROM audit_events ORDER BY id ASC LIMIT ?)",
                (overflow,),
            )
            self._conn.commit()
            return overflow
