from __future__ import annotations

import os
import time

import torch

from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch


def _parse_sensors_from_env() -> list[str]:
    raw = os.getenv("LUVATRIX_LOGGER_SENSORS", "thermal.temperature,power.voltage_current")
    out = [s.strip() for s in raw.split(",") if s.strip()]
    if not out:
        return ["thermal.temperature", "power.voltage_current"]
    return out


class InputSensorLoggerApp:
    def __init__(self) -> None:
        self._sensors = _parse_sensors_from_env()
        self._sensor_interval_s = float(os.getenv("LUVATRIX_LOGGER_SENSOR_INTERVAL", "0.5"))
        self._last_sensor_log = 0.0

    def init(self, ctx) -> None:
        print("[logger-app] init")
        print(f"[logger-app] sensors={self._sensors}")
        snap = ctx.read_matrix_snapshot()
        h, w, _ = snap.shape
        ctx.submit_write_batch(
            WriteBatch([FullRewrite(torch.zeros((h, w, 4), dtype=torch.uint8))])
        )

    def loop(self, ctx, dt: float) -> None:
        events = ctx.poll_hdi_events(max_events=128)
        for event in events:
            print(
                "[hdi]",
                f"device={event.device}",
                f"type={event.event_type}",
                f"status={event.status}",
                f"payload={event.payload}",
            )
        now = time.perf_counter()
        if now - self._last_sensor_log >= self._sensor_interval_s:
            self._last_sensor_log = now
            for sensor in self._sensors:
                sample = ctx.read_sensor(sensor)
                print(
                    "[sensor]",
                    f"type={sample.sensor_type}",
                    f"status={sample.status}",
                    f"value={sample.value}",
                    f"unit={sample.unit}",
                )

    def stop(self, ctx) -> None:
        print("[logger-app] stop")


def create():
    return InputSensorLoggerApp()
