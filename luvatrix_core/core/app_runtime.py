from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import logging
import platform
import sys
import time
import tomllib
from typing import Callable, Protocol

import torch

from .hdi_thread import HDIEvent, HDIThread
from .coordinates import CoordinateFrameRegistry
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
    platform_support: list[str]
    variants: list["AppVariant"]
    min_runtime_protocol_version: str | None = None
    max_runtime_protocol_version: str | None = None


@dataclass(frozen=True)
class AppVariant:
    variant_id: str
    os: list[str]
    arch: list[str]
    module_root: str | None = None
    entrypoint: str | None = None


@dataclass(frozen=True)
class ResolvedAppVariant:
    variant_id: str
    entrypoint: str
    module_dir: Path


@dataclass
class AppContext:
    matrix: WindowMatrix
    hdi: HDIThread
    sensor_manager: SensorManagerThread
    granted_capabilities: set[str]
    security_audit_logger: Callable[[dict[str, object]], None] | None = None
    sensor_read_min_interval_s: float = 0.2
    coordinate_frames: CoordinateFrameRegistry | None = None
    _last_sensor_read_ns: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.coordinate_frames is None:
            self.coordinate_frames = CoordinateFrameRegistry(width=self.matrix.width, height=self.matrix.height)

    def submit_write_batch(self, batch: WriteBatch) -> CallBlitEvent:
        self._require_capability("window.write")
        return self.matrix.submit_write_batch(batch)

    def poll_hdi_events(self, max_events: int, frame: str | None = None) -> list[HDIEvent]:
        if max_events <= 0:
            raise ValueError("max_events must be > 0")
        events = self.hdi.poll_events(max_events=max_events)
        gated = [self._gate_hdi_event(event) for event in events]
        return [self._transform_hdi_event(event, frame=frame) for event in gated]

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

    @property
    def default_coordinate_frame(self) -> str:
        assert self.coordinate_frames is not None
        return self.coordinate_frames.default_frame

    def set_default_coordinate_frame(self, frame_name: str) -> None:
        assert self.coordinate_frames is not None
        self.coordinate_frames.set_default_frame(frame_name)

    def define_coordinate_frame(
        self,
        name: str,
        origin: tuple[float, float],
        basis_x: tuple[float, float],
        basis_y: tuple[float, float],
    ) -> None:
        assert self.coordinate_frames is not None
        self.coordinate_frames.define_frame(name=name, origin=origin, basis_x=basis_x, basis_y=basis_y)

    def to_render_coords(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        assert self.coordinate_frames is not None
        return self.coordinate_frames.to_render_coords((float(x), float(y)), frame=frame)

    def from_render_coords(self, x: float, y: float, frame: str | None = None) -> tuple[float, float]:
        assert self.coordinate_frames is not None
        return self.coordinate_frames.from_render_coords((float(x), float(y)), frame=frame)

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

    def _transform_hdi_event(self, event: HDIEvent, frame: str | None) -> HDIEvent:
        if self.coordinate_frames is None:
            return event
        if event.payload is None or not isinstance(event.payload, dict):
            return event
        payload = dict(event.payload)
        if "x" in payload and "y" in payload:
            try:
                x = float(payload["x"])
                y = float(payload["y"])
                tx, ty = self.coordinate_frames.from_render_coords((x, y), frame=frame)
                payload["x"] = tx
                payload["y"] = ty
            except (TypeError, ValueError):
                return event
        if "delta_x" in payload and "delta_y" in payload:
            try:
                dx = float(payload["delta_x"])
                dy = float(payload["delta_y"])
                tdx, tdy = self.coordinate_frames.transform_vector(
                    (dx, dy),
                    from_frame="screen_tl",
                    to_frame=frame,
                )
                payload["delta_x"] = tdx
                payload["delta_y"] = tdy
            except (TypeError, ValueError):
                return event
        return HDIEvent(
            event_id=event.event_id,
            ts_ns=event.ts_ns,
            window_id=event.window_id,
            device=event.device,
            event_type=event.event_type,
            status=event.status,
            payload=payload,
        )


class AppRuntime:
    def __init__(
        self,
        matrix: WindowMatrix,
        hdi: HDIThread,
        sensor_manager: SensorManagerThread,
        capability_decider: Callable[[str], bool] | None = None,
        capability_audit_logger: Callable[[dict[str, object]], None] | None = None,
        host_os: str | None = None,
        host_arch: str | None = None,
    ) -> None:
        self._matrix = matrix
        self._hdi = hdi
        self._sensor_manager = sensor_manager
        self._capability_decider = capability_decider or (lambda capability: True)
        self._capability_audit_logger = capability_audit_logger
        self._host_os = _normalize_os_name(host_os or platform.system())
        self._host_arch = _normalize_arch_name(host_arch or platform.machine())
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
        platform_support = _coerce_string_list(raw.get("platform_support", []), "platform_support")
        variants = _coerce_variants(raw.get("variants", []))
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
            platform_support=platform_support,
            variants=variants,
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
        resolved = self.resolve_variant(app_path, manifest)
        lifecycle = self.load_lifecycle(resolved.module_dir, resolved.entrypoint)

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
            coordinate_frames=CoordinateFrameRegistry(width=self._matrix.width, height=self._matrix.height),
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

    def resolve_variant(self, app_dir: Path, manifest: AppManifest) -> ResolvedAppVariant:
        if manifest.platform_support and self._host_os not in manifest.platform_support:
            raise RuntimeError(
                f"app `{manifest.app_id}` does not support host os `{self._host_os}`; "
                f"supported={','.join(sorted(manifest.platform_support))}"
            )
        if not manifest.variants:
            return ResolvedAppVariant(
                variant_id="default",
                entrypoint=manifest.entrypoint,
                module_dir=app_dir,
            )

        candidates: list[AppVariant] = []
        for variant in manifest.variants:
            if self._host_os not in variant.os:
                continue
            if variant.arch and self._host_arch not in variant.arch:
                continue
            candidates.append(variant)
        if not candidates:
            raise RuntimeError(
                f"no app variant for host os={self._host_os} arch={self._host_arch} in `{manifest.app_id}`"
            )

        candidates.sort(key=lambda v: (0 if v.arch else 1, v.variant_id))
        selected = candidates[0]
        module_dir = app_dir
        if selected.module_root:
            candidate = (app_dir / selected.module_root).resolve()
            app_root = app_dir.resolve()
            if candidate != app_root and app_root not in candidate.parents:
                raise ValueError(f"variant `{selected.variant_id}` module_root escapes app directory")
            module_dir = candidate
        return ResolvedAppVariant(
            variant_id=selected.variant_id,
            entrypoint=selected.entrypoint or manifest.entrypoint,
            module_dir=module_dir,
        )

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
        for os_name in manifest.platform_support:
            _normalize_os_name(os_name)
        variant_ids: set[str] = set()
        for variant in manifest.variants:
            if variant.variant_id in variant_ids:
                raise ValueError(f"duplicate variant id: {variant.variant_id}")
            variant_ids.add(variant.variant_id)
            if not variant.os:
                raise ValueError(f"variant `{variant.variant_id}` must declare at least one os")
            for os_name in variant.os:
                _normalize_os_name(os_name)
            for arch_name in variant.arch:
                _normalize_arch_name(arch_name)
        _parse_entrypoint(manifest.entrypoint)
        for variant in manifest.variants:
            if variant.entrypoint is not None:
                _parse_entrypoint(variant.entrypoint)

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


def _coerce_variants(value: object) -> list[AppVariant]:
    if not isinstance(value, list):
        raise ValueError("variants must be a list")
    variants: list[AppVariant] = []
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("variants entries must be tables")
        try:
            variant_id = str(item["id"])
        except KeyError as exc:
            raise ValueError(f"variants[{idx}] missing required field: {exc.args[0]}") from exc
        os_list = _coerce_string_list(item.get("os", []), f"variants[{idx}].os")
        arch_list = _coerce_string_list(item.get("arch", []), f"variants[{idx}].arch")
        module_root = _coerce_optional_str(item.get("module_root"), f"variants[{idx}].module_root")
        entrypoint = _coerce_optional_str(item.get("entrypoint"), f"variants[{idx}].entrypoint")
        variants.append(
            AppVariant(
                variant_id=variant_id,
                os=[_normalize_os_name(x) for x in os_list],
                arch=[_normalize_arch_name(x) for x in arch_list],
                module_root=module_root,
                entrypoint=entrypoint,
            )
        )
    return variants


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
    # Register before execution so decorators/introspection (e.g. dataclasses)
    # can resolve cls.__module__ during module import.
    sys.modules[unique_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(unique_name, None)
        raise
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
    elif sample.sensor_type in {"camera.device", "microphone.device", "speaker.device"} and isinstance(value, dict):
        value = {
            "available": bool(value.get("available", False)),
            "device_count": int(value.get("device_count", 0)),
            "default_present": bool(value.get("default_present", False)),
        }
    return SensorSample(
        sample_id=sample.sample_id,
        ts_ns=sample.ts_ns,
        sensor_type=sample.sensor_type,
        status=sample.status,
        value=value,
        unit=sample.unit,
    )


def _normalize_os_name(value: str) -> str:
    normalized = value.strip().lower().replace("_", "").replace("-", "")
    aliases = {
        "darwin": "macos",
        "macos": "macos",
        "osx": "macos",
        "mac": "macos",
        "windows": "windows",
        "win": "windows",
        "linux": "linux",
        "android": "android",
        "ios": "ios",
        "web": "web",
        "wasm": "web",
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported os identifier: {value}")
    return aliases[normalized]


def _normalize_arch_name(value: str) -> str:
    normalized = value.strip().lower().replace("_", "").replace("-", "")
    aliases = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x8664": "x86_64",
        "amd64": "x86_64",
        "x64": "x86_64",
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported arch identifier: {value}")
    return aliases[normalized]
