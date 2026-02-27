from __future__ import annotations

import argparse
from pathlib import Path
import random
import sys
import time
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from luvatrix_core.core import AppRuntime, HDIEvent, HDIEventSource, HDIThread, SensorManagerThread, WindowMatrix
from luvatrix_core.platform.macos import AppKitWindowSystem, MacOSWindowHDISource


APP_DIR = Path(__file__).resolve().parent / "input_sensor_logger"


class SimulatedHDISource(HDIEventSource):
    def __init__(self, size_provider: Callable[[], tuple[float, float]] | None = None) -> None:
        self._next_id = 1
        self._tick = 0
        self._size_provider = size_provider

    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        self._tick += 1
        out: list[HDIEvent] = []
        width = 800
        height = 500
        if self._size_provider is not None:
            width, height = self._size_provider()
            width = max(1, int(width))
            height = max(1, int(height))
        if self._tick % 3 == 0:
            x = float((self._tick * 9) % width)
            y = float((self._tick * 7) % height)
            out.append(
                HDIEvent(
                    event_id=self._next_id,
                    ts_ns=ts_ns,
                    window_id="logger-demo",
                    device="mouse",
                    event_type="pointer_move",
                    status="OK",
                    payload={"x": x, "y": y},
                )
            )
            self._next_id += 1
        if self._tick % 7 == 0:
            out.append(
                HDIEvent(
                    event_id=self._next_id,
                    ts_ns=ts_ns,
                    window_id="logger-demo",
                    device="keyboard",
                    event_type="key_down",
                    status="OK",
                    payload={"key": "a", "tick": self._tick},
                )
            )
            self._next_id += 1
        if self._tick % 11 == 0:
            out.append(
                HDIEvent(
                    event_id=self._next_id,
                    ts_ns=ts_ns,
                    window_id="logger-demo",
                    device="trackpad",
                    event_type="pressure",
                    status="OK",
                    payload={"pressure": round((self._tick % 10) / 10.0, 2), "stage": (self._tick % 3) + 1},
                )
            )
            self._next_id += 1
        if self._tick % 13 == 0:
            out.append(
                HDIEvent(
                    event_id=self._next_id,
                    ts_ns=ts_ns,
                    window_id="logger-demo",
                    device="trackpad",
                    event_type="pinch",
                    status="OK",
                    payload={"magnification": 0.01 * (self._tick % 5)},
                )
            )
            self._next_id += 1
        return out


class NullHDISource(HDIEventSource):
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


class DemoSensorProvider:
    def __init__(self, sensor_type: str) -> None:
        self.sensor_type = sensor_type

    def read(self) -> tuple[object, str]:
        if self.sensor_type == "thermal.temperature":
            return round(60.0 + random.random() * 20.0, 2), "C"
        if self.sensor_type == "power.voltage_current":
            return {"voltage": round(11.5 + random.random(), 2), "current": round(0.5 + random.random(), 3)}, "mixed"
        return {"ts_ns": time.time_ns()}, "raw"


class UnavailableSensorProvider:
    def __init__(self, sensor_type: str) -> None:
        self.sensor_type = sensor_type

    def read(self) -> tuple[object, str]:
        raise RuntimeError(f"{self.sensor_type} not implemented on this machine/runtime yet")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the minimal input + sensor logger app runtime example.")
    parser.add_argument("--ticks", type=int, default=600, help="Number of app loop ticks to run.")
    parser.add_argument("--fps", type=int, default=60, help="Target app loop FPS.")
    parser.add_argument(
        "--sensor",
        action="append",
        default=[],
        help="Sensor type to log (repeatable). Example: --sensor thermal.temperature",
    )
    parser.add_argument(
        "--simulate-hdi",
        action="store_true",
        help="Emit simulated mouse/keyboard events for testing.",
    )
    parser.add_argument(
        "--open-window",
        action="store_true",
        help="Open a macOS test window and gate mouse logs to active-window hover coordinates.",
    )
    parser.add_argument("--window-width", type=int, default=800)
    parser.add_argument("--window-height", type=int, default=500)
    parser.add_argument(
        "--simulate-sensors",
        action="store_true",
        help="Emit synthetic sensor values instead of UNAVAILABLE.",
    )
    args = parser.parse_args()

    sensors = args.sensor or ["thermal.temperature", "power.voltage_current"]
    window_system = None
    window_handle = None
    if args.open_window:
        window_system = AppKitWindowSystem()
        window_handle = window_system.create_window(
            args.window_width,
            args.window_height,
            "Luvatrix Input/Sensor Logger",
            use_metal_layer=False,
            preserve_aspect_ratio=False,
        )

    def geometry_provider() -> tuple[float, float, float, float]:
        if window_handle is None:
            return (0.0, 0.0, 10_000.0, 10_000.0)
        view = window_handle.window.contentView()
        bounds = view.bounds()
        return (0.0, 0.0, float(bounds.size.width), float(bounds.size.height))

    def active_provider() -> bool:
        if window_handle is None:
            return True
        try:
            return bool(window_handle.window.isKeyWindow()) and bool(window_system.is_window_open(window_handle))
        except Exception:
            return False

    def size_provider() -> tuple[float, float]:
        _, _, w, h = geometry_provider()
        return (w, h)

    if args.simulate_hdi:
        source = SimulatedHDISource(size_provider=size_provider)
    elif window_handle is not None:
        source = MacOSWindowHDISource(window_handle)
    else:
        source = NullHDISource()
    providers = {}
    for sensor_type in sensors:
        if args.simulate_sensors:
            providers[sensor_type] = DemoSensorProvider(sensor_type)
        else:
            providers[sensor_type] = UnavailableSensorProvider(sensor_type)

    matrix = WindowMatrix(height=1, width=1)
    hdi = HDIThread(
        source=source,
        poll_interval_s=1 / 240,
        window_active_provider=active_provider,
        window_geometry_provider=geometry_provider,
    )
    sensor_manager = SensorManagerThread(providers=providers, poll_interval_s=0.2)
    for sensor_type in sensors:
        sensor_manager.set_sensor_enabled(sensor_type, True, actor="example_runner")

    runtime = AppRuntime(
        matrix=matrix,
        hdi=hdi,
        sensor_manager=sensor_manager,
        capability_decider=lambda capability: True,
    )

    import os

    os.environ["LUVATRIX_LOGGER_SENSORS"] = ",".join(sensors)
    def on_tick() -> None:
        if window_system is not None:
            window_system.pump_events()

    def should_continue() -> bool:
        if window_handle is None:
            return True
        return bool(window_system.is_window_open(window_handle))

    try:
        runtime.run(
            APP_DIR,
            max_ticks=args.ticks,
            target_fps=args.fps,
            on_tick=on_tick,
            should_continue=should_continue,
        )
    except KeyboardInterrupt:
        print("stopped by user")
    finally:
        if hasattr(source, "close"):
            try:
                source.close()
            except Exception:
                pass
        if window_handle is not None:
            window_system.destroy_window(window_handle)


if __name__ == "__main__":
    main()
