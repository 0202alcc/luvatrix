from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class HostHello:
    protocol_version: str
    width: int
    height: int
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class TickEvent:
    dt: float


class ProcessApp(Protocol):
    def init(self, hello: HostHello) -> None:
        ...

    def tick(self, event: TickEvent) -> list[dict[str, Any]]:
        ...

    def stop(self) -> None:
        ...


def run_stdio_jsonl(app: ProcessApp) -> None:
    hello_msg = _read_obj()
    if hello_msg.get("type") != "host.hello":
        raise RuntimeError(f"expected host.hello, got {hello_msg}")
    matrix = hello_msg.get("matrix", {})
    app.init(
        HostHello(
            protocol_version=str(hello_msg.get("protocol_version", "")),
            width=int(matrix.get("width", 0)),
            height=int(matrix.get("height", 0)),
            capabilities=tuple(sorted(str(x) for x in hello_msg.get("capabilities", []))),
        )
    )
    _write_obj({"type": "app.init_ok"})

    while True:
        msg = _read_obj()
        msg_type = msg.get("type")
        if msg_type == "host.tick":
            ops = app.tick(TickEvent(dt=float(msg.get("dt", 0.0))))
            _write_obj({"type": "app.commands", "ops": ops})
            continue
        if msg_type == "host.stop":
            app.stop()
            _write_obj({"type": "app.stop_ok"})
            return
        raise RuntimeError(f"unsupported host message: {msg}")


def _read_obj() -> dict[str, Any]:
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("stdin closed")
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise RuntimeError("protocol payload must be object")
    return payload


def _write_obj(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()
