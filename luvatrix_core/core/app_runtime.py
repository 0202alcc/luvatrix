from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import logging
import time
import tomllib
from typing import Callable, Protocol

import torch

from .hdi_thread import HDIEvent, HDIThread
from .protocol_governance import CURRENT_PROTOCOL_VERSION, check_protocol_compatibility
from .sensor_manager import SensorManagerThread, SensorSample
from .window_matrix import CallBlitEvent, WindowMatrix, WriteBatch

LOGGER = logging.getLogger(__name__)
APP_PROTOCOL_VERSION = CURRENT_PROTOCOL_VERSION


class AppLifecycle(Protocol):
    def init(self, ctx: "AppContext") -> None:
        ...

    def loop(self, ctx: "AppContext", dt: float) -> None:
        ...

    def stop(self, ctx: "AppContext") -> None:
        ...


@dataclass(frozen=True)
class AppManifest:
    app_id: str
    protocol_version: str
    entrypoint: str
    required_capabilities: list[str]
    optional_capabilities: list[str]
    min_runtime_protocol_version: str | None = None
    max_runtime_protocol_version: str | None = None


@dataclass
class AppContext:
    matrix: WindowMatrix
    hdi: HDIThread
    sensor_manager: SensorManagerThread
    granted_capabilities: set[str]
    security_audit_logger: Callable[[dict[str, object]], None] | None = None
    sensor_read_min_interval_s: float = 0.2
    _last_sensor_read_ns: dict[str, int] = field(default_factory=dict)

    def submit_write_batch(self, batch: WriteBatch) -> CallBlitEvent:
        self._require_capability("window.write")
        return self.matrix.submit_write_batch(batch)

    def poll_hdi_events(self, max_events: int) -> list[HDIEvent]:
        if max_events <= 0:
            raise ValueError("max_events must be > 0")
        events = self.hdi.poll_events(max_events=max_events)
        return [self._gate_hdi_event(event) for event in events]

    def read_sensor(self, sensor_type: str) -> SensorSample:
        if not self._has_sensor_capability(sensor_type):
            self._audit_security("sensor_denied_capability", sensor_type=sensor_type)
            return SensorSample(
                sample_id=0,
                ts_ns=time.time_ns(),
                sensor_type=sensor_type,
                status="DENIED",
                value=None,
                unit=None,
            )
        now_ns = time.time_ns()
        min_delta_ns = int(self.sensor_read_min_interval_s * 1_000_000_000)
        last_ns = self._last_sensor_read_ns.get(sensor_type, 0)
        if now_ns - last_ns < min_delta_ns:
            self._audit_security("sensor_denied_rate_limit", sensor_type=sensor_type)
            return SensorSample(
                sample_id=0,
                ts_ns=now_ns,
                sensor_type=sensor_type,
                status="DENIED",
                value=None,
                unit=None,
            )
        self._last_sensor_read_ns[sensor_type] = now_ns
        sample = self.sensor_manager.read_sensor(sensor_type)
        return _sanitize_sensor_sample(sample, self.granted_capabilities)

    def read_matrix_snapshot(self) -> torch.Tensor:
        return self.matrix.read_snapshot()

    def has_capability(self, capability: str) -> bool:
        return capability in self.granted_capabilities

    def _require_capability(self, capability: str) -> None:
        if capability not in self.granted_capabilities:
            raise PermissionError(f"missing capability: {capability}")

    def _gate_hdi_event(self, event: HDIEvent) -> HDIEvent:
        required = f"hdi.{event.device}"
        if required in self.granted_capabilities:
            return event
        return HDIEvent(
            event_id=event.event_id,
            ts_ns=event.ts_ns,
            window_id=event.window_id,
            device=event.device,
            event_type=event.event_type,
            status="DENIED",
            payload=None,
        )

    def _has_sensor_capability(self, sensor_type: str) -> bool:
        if "sensor.*" in self.granted_capabilities:
            return True
        if sensor_type in self.granted_capabilities:
            return True
        prefix = sensor_type.split(".", 1)[0]
        return f"sensor.{prefix}" in self.granted_capabilities

    def _audit_security(self, action: str, *, sensor_type: str) -> None:
        if self.security_audit_logger is None:
            return
        self.security_audit_logger(
            {
                "ts_ns": time.time_ns(),
                "action": action,
                "sensor_type": sensor_type,
                "actor": "app_context",
            }
        )


class AppRuntime:
    def __init__(
        self,
        matrix: WindowMatrix,
        hdi: HDIThread,
        sensor_manager: SensorManagerThread,
        capability_decider: Callable[[str], bool] | None = None,
        capability_audit_logger: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._matrix = matrix
        self._hdi = hdi
        self._sensor_manager = sensor_manager
        self._capability_decider = capability_decider or (lambda capability: True)
        self._capability_audit_logger = capability_audit_logger
        self._last_error: Exception | None = None

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def load_manifest(self, app_dir: str | Path) -> AppManifest:
        app_path = Path(app_dir)
        manifest_path = app_path / "app.toml"
        if not manifest_path.exists():
            raise FileNotFoundError(f"app manifest not found: {manifest_path}")
        with manifest_path.open("rb") as f:
            raw = tomllib.load(f)
        try:
            app_id = str(raw["app_id"])
            protocol_version = str(raw["protocol_version"])
            entrypoint = str(raw["entrypoint"])
        except KeyError as exc:
            raise ValueError(f"manifest missing required field: {exc.args[0]}") from exc
        required = _coerce_string_list(raw.get("required_capabilities", []), "required_capabilities")
        optional = _coerce_string_list(raw.get("optional_capabilities", []), "optional_capabilities")
        min_runtime_protocol_version = _coerce_optional_str(
            raw.get("min_runtime_protocol_version"), "min_runtime_protocol_version"
        )
        max_runtime_protocol_version = _coerce_optional_str(
            raw.get("max_runtime_protocol_version"), "max_runtime_protocol_version"
        )
        manifest = AppManifest(
            app_id=app_id,
            protocol_version=protocol_version,
            entrypoint=entrypoint,
            required_capabilities=required,
            optional_capabilities=optional,
            min_runtime_protocol_version=min_runtime_protocol_version,
            max_runtime_protocol_version=max_runtime_protocol_version,
        )
        self._validate_manifest(manifest)
        return manifest

    def run(
        self,
        app_dir: str | Path,
        *,
        max_ticks: int = 1,
        target_fps: int = 60,
        on_tick: Callable[[], None] | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> None:
        if max_ticks <= 0:
            raise ValueError("max_ticks must be > 0")
        if target_fps <= 0:
            raise ValueError("target_fps must be > 0")

        app_path = Path(app_dir).resolve()
        manifest = self.load_manifest(app_path)
        granted = self.resolve_capabilities(manifest)
        ctx = self.build_context(granted_capabilities=granted)
        lifecycle = self.load_lifecycle(app_path, manifest.entrypoint)

        target_dt = 1.0 / float(target_fps)
        self._hdi.start()
        self._sensor_manager.start()
        started = False
        try:
            lifecycle.init(ctx)
            started = True
            last = time.perf_counter()
            for _ in range(max_ticks):
                if should_continue is not None and not should_continue():
                    break
                if on_tick is not None:
                    on_tick()
                now = time.perf_counter()
                dt = max(0.0, now - last)
                last = now
                lifecycle.loop(ctx, dt)
                elapsed = time.perf_counter() - now
                sleep_for = target_dt - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)
        except Exception as exc:  # noqa: BLE001
            self._last_error = exc
            raise
        finally:
            if started:
                try:
                    lifecycle.stop(ctx)
                except Exception as exc:  # noqa: BLE001
                    self._last_error = exc
                    raise
            self._hdi.stop()
            self._sensor_manager.stop()

    def resolve_capabilities(self, manifest: AppManifest) -> set[str]:
        granted: set[str] = set()
        denied_required: list[str] = []
        for capability in manifest.required_capabilities:
            if self._capability_decider(capability):
                granted.add(capability)
                self._audit_capability("granted_required", capability)
            else:
                denied_required.append(capability)
                self._audit_capability("denied_required", capability)
        if denied_required:
            raise PermissionError(
                "required capabilities denied: " + ", ".join(sorted(denied_required))
            )
        for capability in manifest.optional_capabilities:
            if self._capability_decider(capability):
                granted.add(capability)
                self._audit_capability("granted_optional", capability)
            else:
                self._audit_capability("denied_optional", capability)
        return granted

    def build_context(self, granted_capabilities: set[str]) -> AppContext:
        return AppContext(
            matrix=self._matrix,
            hdi=self._hdi,
            sensor_manager=self._sensor_manager,
            granted_capabilities=granted_capabilities,
            security_audit_logger=self._capability_audit_logger,
        )

    def load_lifecycle(self, app_dir: Path, entrypoint: str) -> AppLifecycle:
        module_name, symbol_name = _parse_entrypoint(entrypoint)
        module = _load_module_from_app_dir(app_dir, module_name)
        if not hasattr(module, symbol_name):
            raise ValueError(f"entrypoint symbol not found: {entrypoint}")
        symbol = getattr(module, symbol_name)
        lifecycle = symbol() if callable(symbol) else symbol
        for method_name in ("init", "loop", "stop"):
            method = getattr(lifecycle, method_name, None)
            if method is None or not callable(method):
                raise ValueError(f"entrypoint lifecycle missing callable `{method_name}`: {entrypoint}")
        return lifecycle

    def _validate_manifest(self, manifest: AppManifest) -> None:
        compat = check_protocol_compatibility(
            manifest.protocol_version,
            min_runtime_version=manifest.min_runtime_protocol_version,
            max_runtime_version=manifest.max_runtime_protocol_version,
        )
        if not compat.accepted:
            raise ValueError(compat.warning or "protocol compatibility check failed")
        if compat.warning:
            LOGGER.warning("%s", compat.warning)
        _parse_entrypoint(manifest.entrypoint)

    def _audit_capability(self, action: str, capability: str) -> None:
        if self._capability_audit_logger is None:
            return
        self._capability_audit_logger(
            {
                "ts_ns": time.time_ns(),
                "action": action,
                "capability": capability,
                "actor": "app_runtime",
            }
        )


def _coerce_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings")
        out.append(item)
    return out


def _coerce_optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string if provided")
    return value


def _parse_entrypoint(entrypoint: str) -> tuple[str, str]:
    if ":" not in entrypoint:
        raise ValueError("entrypoint must use `module:symbol` format")
    module_name, symbol_name = entrypoint.split(":", 1)
    module_name = module_name.strip()
    symbol_name = symbol_name.strip()
    if not module_name or not symbol_name:
        raise ValueError("entrypoint must include non-empty module and symbol")
    return module_name, symbol_name


def _load_module_from_app_dir(app_dir: Path, module_name: str):
    rel_parts = module_name.split(".")
    module_path = app_dir.joinpath(*rel_parts).with_suffix(".py")
    if not module_path.exists():
        raise ValueError(f"entrypoint module file not found: {module_name}")
    unique_name = f"luvatrix_app_{abs(hash((str(app_dir), module_name)))}"
    spec = importlib.util.spec_from_file_location(unique_name, module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"unable to load entrypoint module: {module_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sanitize_sensor_sample(sample: SensorSample, granted_capabilities: set[str]) -> SensorSample:
    if sample.status != "OK" or sample.value is None:
        return sample
    if "sensor.high_precision" in granted_capabilities:
        return sample
    value = sample.value
    if sample.sensor_type == "thermal.temperature" and isinstance(value, (int, float)):
        value = round(float(value) * 2.0) / 2.0
    elif sample.sensor_type == "power.voltage_current" and isinstance(value, dict):
        out: dict[str, object] = {}
        for k, v in value.items():
            if isinstance(v, (int, float)):
                out[k] = round(float(v), 1)
            else:
                out[k] = v
        value = out
    elif sample.sensor_type == "sensor.motion" and isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(v, (int, float)):
                out[k] = round(float(v), 0)
            else:
                out[k] = v
        value = out
    return SensorSample(
        sample_id=sample.sample_id,
        ts_ns=sample.ts_ns,
        sensor_type=sample.sensor_type,
        status=sample.status,
        value=value,
        unit=sample.unit,
    )
