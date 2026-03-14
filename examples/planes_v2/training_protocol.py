
from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from luvatrix_core.core.coordinates import CoordinateFrameRegistry
from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_ui.planes_runtime import load_plane_app


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return bool(default)


APP_SPECS: dict[str, dict[str, Any]] = {
  "camera_overlay_basics": {
    "actions": [
      "toggle_overlay"
    ],
    "checks": {
      "overlay_toggled": True
    },
    "concepts": [
      "Camera overlay attachment",
      "Overlay state toggles",
      "Independent overlay rendering"
    ],
    "objective": "Toggle camera overlay HUD visibility while maintaining world-plane content."
  },
  "coordinate_playground": {
    "actions": [
      "capture_coordinates"
    ],
    "checks": {
      "captured_coordinates_set": True
    },
    "concepts": [
      "Pointer event routing",
      "Coordinate capture",
      "State-to-UI feedback loop"
    ],
    "objective": "Capture pointer coordinates and store the latest sampled click location."
  },
  "debug_capture_workflow": {
    "actions": [
      "debug_screenshot",
      "debug_record",
      "debug_replay",
      "debug_frame_step",
      "debug_perf_hud",
      "debug_bundle"
    ],
    "checks": {
      "bundle_exported": True,
      "frame_step_count": 1,
      "perf_hud_toggled": True,
      "record_toggled": True,
      "replay_started": True,
      "screenshot_taken": True
    },
    "concepts": [
      "Debug capture lifecycle",
      "Record/replay toggles",
      "Bundle export readiness"
    ],
    "objective": "Execute full debug capture workflow controls (screenshot, record, replay, frame-step, perf-hud, bundle)."
  },
  "hello_plane": {
    "actions": [
      "cycle_hover_profile"
    ],
    "action_component_ids": {
      "cycle_hover_profile": "stained_glass_button"
    },
    "checks": {
      "profile_cycle_count": 1
    },
    "concepts": [
      "Plane runtime bootstrapping",
      "Pointer-relative refraction animation",
      "Profile cycle event handling",
      "Deterministic state snapshots"
    ],
    "objective": "Render a starter plane app and cycle hover-refraction profiles through direct click interaction."
  },
  "input_sensor_overlay_logger": {
    "actions": [
      "log_input",
      "refresh_sensors"
    ],
    "checks": {
      "input_logged": True,
      "sensor_refresh_count": 1
    },
    "concepts": [
      "Input event logging",
      "Overlay + sensor co-visualization",
      "Stable event ledger output"
    ],
    "objective": "Log input overlay actions and sensor snapshots into an in-app event ledger."
  },
  "interactive_components": {
    "actions": [
      "cycle_component"
    ],
    "action_repeats": {
      "cycle_component": 2
    },
    "checks": {
      "active_component_mode": "advanced"
    },
    "concepts": [
      "Interactive component state machine",
      "Mode cycling",
      "UI status updates"
    ],
    "objective": "Cycle component interaction modes and persist the current mode."
  },
  "multi_plane_layout": {
    "actions": [
      "activate_plane_primary",
      "activate_plane_secondary"
    ],
    "checks": {
      "plane_switch_count": 2
    },
    "concepts": [
      "Planes v2 multi-plane layout",
      "Plane focus controls",
      "Route active-plane behavior"
    ],
    "objective": "Switch focus across primary and secondary planes in a multi-plane route.",
    "planes": [
      "primary",
      "secondary"
    ]
  },
  "planes_v2_poc_plus": {
    "actions": [
      "route_home",
      "route_settings",
      "route_analytics"
    ],
    "checks": {
      "active_route_path": "/analytics"
    },
    "concepts": [
      "Planes v2 route switching",
      "Route-specific plane activation",
      "Navigation telemetry"
    ],
    "objective": "Navigate `/home`, `/settings`, `/analytics` routes and persist active route telemetry.",
    "planes": [
      "home",
      "settings",
      "analytics"
    ],
    "routes": [
      "/home",
      "/settings",
      "/analytics"
    ]
  },
  "scroll_and_pan_plane": {
    "actions": [
      "scroll_plane"
    ],
    "checks": {
      "scroll_recorded": True
    },
    "concepts": [
      "Viewport clipping",
      "Scroll handlers",
      "Pan delta accumulation"
    ],
    "needs_viewport": True,
    "objective": "Drive viewport scrolling and pan telemetry with scroll events."
  },
  "sensor_status_dashboard": {
    "actions": [
      "refresh_sensors"
    ],
    "action_repeats": {
      "refresh_sensors": 2
    },
    "checks": {
      "sensor_refresh_count": 2
    },
    "concepts": [
      "Sensor dashboard card updates",
      "Refresh command handlers",
      "Deterministic telemetry ticks"
    ],
    "objective": "Refresh synthetic sensor status cards and show deterministic dashboard telemetry."
  }
}


HELLO_HOVER_PROFILES: list[dict[str, Any]] = [
  {
    "id": "prism_drift",
    "label": "Prism Drift",
    "base": {
      "kernel_size": 5,
      "sigma_px": 1.5,
      "downsample_factor": 2,
      "backdrop_cache_enabled": True,
      "refract_px": 3.2,
      "refract_calm_radius": 0.9,
      "refract_transition": 0.03,
      "chromatic_aberration_px": 0.08,
      "pane_mix": 0.36,
      "color_filter_rgb": [1.22, 0.8, 0.8],
      "tint_delta_rgba": [42, -20, -22, 0],
    },
    "hover_gain": {
      "refract_px": 2.1,
      "chromatic_aberration_px": 0.11,
      "pane_mix": 0.08,
      "tint_xy_scale": [12.0, 8.0],
    },
  },
  {
    "id": "calm_lens",
    "label": "Calm Lens",
    "base": {
      "kernel_size": 5,
      "sigma_px": 1.3,
      "downsample_factor": 2,
      "backdrop_cache_enabled": True,
      "refract_px": 1.5,
      "refract_calm_radius": 0.95,
      "refract_transition": 0.04,
      "chromatic_aberration_px": 0.03,
      "pane_mix": 0.3,
      "color_filter_rgb": [1.1, 0.88, 0.9],
      "tint_delta_rgba": [18, -8, -8, 0],
    },
    "hover_gain": {
      "refract_px": 1.0,
      "chromatic_aberration_px": 0.04,
      "pane_mix": 0.05,
      "tint_xy_scale": [8.0, 6.0],
    },
  },
  {
    "id": "ripple_push",
    "label": "Ripple Push",
    "base": {
      "kernel_size": 5,
      "sigma_px": 1.7,
      "downsample_factor": 2,
      "backdrop_cache_enabled": True,
      "refract_px": 4.6,
      "refract_calm_radius": 0.85,
      "refract_transition": 0.02,
      "chromatic_aberration_px": 0.14,
      "pane_mix": 0.48,
      "color_filter_rgb": [1.28, 0.74, 0.72],
      "tint_delta_rgba": [58, -30, -34, 0],
    },
    "hover_gain": {
      "refract_px": 2.5,
      "chromatic_aberration_px": 0.16,
      "pane_mix": 0.11,
      "tint_xy_scale": [16.0, 11.0],
    },
  },
  {
    "id": "edge_spark",
    "label": "Edge Spark",
    "base": {
      "kernel_size": 5,
      "sigma_px": 1.4,
      "downsample_factor": 2,
      "backdrop_cache_enabled": True,
      "refract_px": 2.3,
      "refract_calm_radius": 0.78,
      "refract_transition": 0.015,
      "chromatic_aberration_px": 0.2,
      "pane_mix": 0.62,
      "color_filter_rgb": [1.34, 0.68, 0.66],
      "tint_delta_rgba": [72, -38, -42, 0],
    },
    "hover_gain": {
      "refract_px": 1.8,
      "chromatic_aberration_px": 0.18,
      "pane_mix": 0.12,
      "tint_xy_scale": [19.0, 14.0],
    },
  },
  {
    "id": "frost_glow",
    "label": "Frost Glow",
    "base": {
      "kernel_size": 5,
      "sigma_px": 1.4,
      "downsample_factor": 2,
      "backdrop_cache_enabled": True,
      "refract_px": 2.8,
      "refract_calm_radius": 0.93,
      "refract_transition": 0.05,
      "chromatic_aberration_px": 0.06,
      "pane_mix": 0.27,
      "color_filter_rgb": [1.06, 0.97, 1.05],
      "tint_delta_rgba": [12, 2, 14, 0],
    },
    "hover_gain": {
      "refract_px": 1.3,
      "chromatic_aberration_px": 0.05,
      "pane_mix": 0.07,
      "tint_xy_scale": [10.0, 12.0],
    },
  },
]


@dataclass
class _Matrix:
    width: int
    height: int


class _ValidationCtx:
    def __init__(self, width: int = 640, height: int = 360) -> None:
        self.matrix = _Matrix(width=width, height=height)
        self._events: list[HDIEvent] = []

    def begin_ui_frame(self, renderer, *, content_width_px, content_height_px, clear_color, dirty_rects=None, scroll_shift=None) -> None:
        _ = (renderer, content_width_px, content_height_px, clear_color, dirty_rects, scroll_shift)

    def mount_component(self, component) -> None:
        _ = component

    def finalize_ui_frame(self) -> None:
        return None

    def poll_hdi_events(self, max_events: int):
        out = list(self._events[: max(0, int(max_events))])
        self._events = self._events[max(0, int(max_events)) :]
        return out

    def queue(self, event: HDIEvent) -> None:
        self._events.append(event)

    def pending_hdi_events(self) -> int:
        return len(self._events)

    def consume_hdi_telemetry(self) -> dict[str, int]:
        return {}


def _find_component(planes_payload: dict[str, Any], component_id: str) -> dict[str, Any]:
    components = planes_payload.get('components', [])
    if not isinstance(components, list):
        raise RuntimeError('invalid components payload')
    for component in components:
        if isinstance(component, dict) and component.get('id') == component_id:
            return component
    raise RuntimeError(f'missing component: {component_id}')


def _set_text(app: Any, component_id: str, value: str) -> None:
    try:
        component = _find_component(app._planes, component_id)
    except RuntimeError:
        return
    props = component.get('props')
    if not isinstance(props, dict):
        props = {}
        component['props'] = props
    props['text'] = value
    component_index = getattr(app, '_component_index', None)
    if isinstance(component_index, dict):
        runtime_comp = component_index.get(component_id)
        runtime_style = getattr(runtime_comp, 'style', None)
        if isinstance(runtime_style, dict):
            runtime_style['text'] = value


def _set_component_props(app: Any, component_id: str, updates: dict[str, Any]) -> None:
    try:
        component = _find_component(app._planes, component_id)
    except RuntimeError:
        return
    props = component.get('props')
    if not isinstance(props, dict):
        props = {}
        component['props'] = props
    props.update(updates)
    component_index = getattr(app, '_component_index', None)
    if isinstance(component_index, dict):
        runtime_comp = component_index.get(component_id)
        runtime_style = getattr(runtime_comp, 'style', None)
        if isinstance(runtime_style, dict):
            runtime_style.update(updates)


def _ctx_dimensions(ctx: Any) -> tuple[float, float]:
    matrix = getattr(ctx, 'matrix', None)
    width = max(1.0, float(getattr(matrix, 'width', 960)))
    height = max(1.0, float(getattr(matrix, 'height', 540)))
    return (width, height)


def _hello_profile_count() -> int:
    return len(HELLO_HOVER_PROFILES)


def _hello_profile_label(index: int) -> str:
    total = _hello_profile_count()
    if total <= 0:
        return 'Profile 1/1'
    idx = int(index) % total
    profile = HELLO_HOVER_PROFILES[idx]
    return f"Profile {idx + 1}/{total}: {profile['label']}"


def _hello_apply_hover_profile(app: Any, state: dict[str, Any], *, width: float, height: float) -> None:
    if _hello_profile_count() <= 0:
        return
    idx = int(state.get('hover_profile_index', 0)) % _hello_profile_count()
    profile = HELLO_HOVER_PROFILES[idx]
    base = dict(profile.get('base', {}))
    gain = profile.get('hover_gain', {}) if isinstance(profile.get('hover_gain'), dict) else {}

    hover_id = str(state.get('hover_component_id', ''))
    pointer = state.get('last_pointer_xy')
    hover_active = hover_id == 'stained_glass_button' and isinstance(pointer, tuple) and len(pointer) == 2

    dynamic = dict(base)
    if hover_active:
        px = float(pointer[0])
        py = float(pointer[1])
        cx = float(width) * 0.5
        cy = float(height) * 0.5
        half_w = 140.0
        half_h = 42.0
        nx = max(-1.0, min(1.0, (px - cx) / max(1.0, half_w)))
        ny = max(-1.0, min(1.0, (py - cy) / max(1.0, half_h)))
        step = 0.08
        nx = round(nx / step) * step
        ny = round(ny / step) * step
        radial = max(0.0, 1.0 - min(1.0, math.sqrt((nx * nx) + (ny * ny))))
        theta = math.atan2(ny, nx if abs(nx) > 1e-6 else 1e-6)
        swirl = math.cos(theta)
        dynamic['refract_px'] = float(base.get('refract_px', 2.0)) + (float(gain.get('refract_px', 0.0)) * radial)
        dynamic['chromatic_aberration_px'] = float(base.get('chromatic_aberration_px', 0.0)) + (
            float(gain.get('chromatic_aberration_px', 0.0)) * radial
        )
        dynamic['pane_mix'] = min(
            0.95,
            max(0.05, float(base.get('pane_mix', 0.35)) + (float(gain.get('pane_mix', 0.0)) * radial)),
        )
        tint = list(base.get('tint_delta_rgba', [0, 0, 0, 0]))
        while len(tint) < 4:
            tint.append(0)
        tint_scale = gain.get('tint_xy_scale', [0.0, 0.0])
        sx = float(tint_scale[0]) if isinstance(tint_scale, list) and len(tint_scale) >= 1 else 0.0
        sy = float(tint_scale[1]) if isinstance(tint_scale, list) and len(tint_scale) >= 2 else 0.0
        tint[0] = float(tint[0]) + (nx * sx)
        tint[1] = float(tint[1]) + (ny * sy)
        tint[2] = float(tint[2]) + (swirl * (sx * 0.35))
        dynamic['tint_delta_rgba'] = tint

    dynamic['material_profile'] = 'water_button'
    dynamic['draggable'] = False
    dynamic['label'] = _hello_profile_label(idx)
    dynamic['label_color_hex'] = '#FFF6F4'
    style_sig = (
      idx,
      bool(hover_active),
      round(float(dynamic.get('refract_px', 0.0)), 3),
      round(float(dynamic.get('chromatic_aberration_px', 0.0)), 3),
      round(float(dynamic.get('pane_mix', 0.0)), 3),
      tuple(round(float(v), 2) for v in dynamic.get('tint_delta_rgba', [0, 0, 0, 0])),
    )
    if state.get('_hello_last_style_sig') != style_sig:
      _set_component_props(app, 'stained_glass_button', dynamic)
      state['_hello_last_style_sig'] = style_sig
      forced = state.get('force_component_dirty_ids')
      if not isinstance(forced, list):
        forced = []
        state['force_component_dirty_ids'] = forced
      if 'stained_glass_button' not in forced:
        forced.append('stained_glass_button')
    state['active_hover_profile'] = profile['id']
    subtitle = f"Hover + click test | {_hello_profile_label(idx)}"
    if bool(state.get('input_debug_enabled', False)):
      hover_id = str(state.get('hover_component_id', '') or '-')
      pointer = state.get('last_pointer_xy')
      if isinstance(pointer, tuple) and len(pointer) == 2:
          pointer_label = f"{float(pointer[0]):.1f},{float(pointer[1]):.1f}"
      else:
          pointer_label = "-"
      subtitle = f"{subtitle} | hover={hover_id} | ptr={pointer_label}"
    if state.get('_hello_last_subtitle') != subtitle:
      _set_text(app, 'subtitle_text', subtitle)
      state['_hello_last_subtitle'] = subtitle
      forced = state.get('force_component_dirty_ids')
      if not isinstance(forced, list):
        forced = []
        state['force_component_dirty_ids'] = forced
      if 'subtitle_text' not in forced:
        forced.append('subtitle_text')


def _handler(action: str):
    def _inner(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
        app_state.setdefault('actions', []).append(action)
        app_state['last_action'] = action
        if action == 'toggle_theme':
            current = str(app_state.get('active_theme', 'default'))
            app_state['active_theme'] = 'training_alt' if current == 'default' else 'default'
            app_state['theme_toggled'] = True
        elif action == 'cycle_hover_profile':
            total = max(1, _hello_profile_count())
            current = int(app_state.get('hover_profile_index', 0))
            app_state['hover_profile_index'] = (current + 1) % total
            app_state['profile_cycle_count'] = int(app_state.get('profile_cycle_count', 0)) + 1
        elif action == 'capture_coordinates':
            payload = event_ctx.get('payload', {})
            if isinstance(payload, dict):
                app_state['captured_coordinates'] = [float(payload.get('x', 0.0)), float(payload.get('y', 0.0))]
                app_state['captured_coordinates_set'] = True
        elif action == 'toggle_overlay':
            app_state['overlay_visible'] = not bool(app_state.get('overlay_visible', True))
            app_state['overlay_toggled'] = True
        elif action == 'activate_plane_primary':
            app_state['active_plane'] = 'primary'
            app_state['plane_switch_count'] = int(app_state.get('plane_switch_count', 0)) + 1
        elif action == 'activate_plane_secondary':
            app_state['active_plane'] = 'secondary'
            app_state['plane_switch_count'] = int(app_state.get('plane_switch_count', 0)) + 1
        elif action == 'scroll_plane':
            payload = event_ctx.get('payload', {})
            if isinstance(payload, dict):
                px = float(payload.get('delta_x', 0.0))
                py = float(payload.get('delta_y', 0.0))
                app_state['last_scroll_delta'] = [px, py]
                app_state['scroll_recorded'] = True
        elif action == 'cycle_component':
            order = ['basic', 'intermediate', 'advanced']
            current = str(app_state.get('active_component_mode', 'basic'))
            idx = order.index(current) if current in order else 0
            app_state['active_component_mode'] = order[(idx + 1) % len(order)]
        elif action == 'refresh_sensors':
            app_state['sensor_refresh_count'] = int(app_state.get('sensor_refresh_count', 0)) + 1
            app_state['sensor_snapshot'] = {
                'temperature_c': 21.5,
                'humidity_pct': 48.0,
                'refresh': app_state['sensor_refresh_count'],
            }
        elif action == 'log_input':
            app_state['input_logged'] = True
            app_state.setdefault('input_log', []).append({'event': event_ctx.get('event_type', 'click')})
        elif action == 'debug_screenshot':
            app_state['screenshot_taken'] = True
        elif action == 'debug_record':
            app_state['record_toggled'] = True
        elif action == 'debug_replay':
            app_state['replay_started'] = True
        elif action == 'debug_frame_step':
            app_state['frame_step_count'] = int(app_state.get('frame_step_count', 0)) + 1
        elif action == 'debug_perf_hud':
            app_state['perf_hud_toggled'] = True
        elif action == 'debug_bundle':
            app_state['bundle_exported'] = True
        elif action == 'route_home':
            app_state['active_route_path'] = '/home'
        elif action == 'route_settings':
            app_state['active_route_path'] = '/settings'
        elif action == 'route_analytics':
            app_state['active_route_path'] = '/analytics'
        app_state['status_text'] = f'last_action={action}'
    return _inner


def _build_handlers(spec: dict[str, Any]) -> dict[str, Any]:
    handlers: dict[str, Any] = {}
    for action in spec.get('actions', []):
        handlers[f'handlers::{action}'] = _handler(action)
    return handlers


def _event_for_component(planes_payload: dict[str, Any], component_id: str, *, event_id: int, event_type: str) -> list[HDIEvent]:
    def _scalar(raw: Any, default: float) -> float:
        if isinstance(raw, dict):
            if 'value' in raw:
                return _scalar(raw.get('value'), default)
            return float(default)
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            txt = raw.strip().lower()
            if txt.endswith('vw'):
                return 640.0 * (float(txt[:-2]) / 100.0)
            if txt.endswith('vh'):
                return 360.0 * (float(txt[:-2]) / 100.0)
            if txt.endswith('%'):
                return float(default) * (float(txt[:-1]) / 100.0)
            return float(txt)
        return float(default)

    component = _find_component(planes_payload, component_id)
    position = component.get('position', {})
    size = component.get('size', {})
    width = _scalar(size.get('width', 120), 120.0)
    height = _scalar(size.get('height', 28), 28.0)
    x = _scalar(position.get('x', 0), 0.0) + (width / 2.0)
    y = _scalar(position.get('y', 0), 0.0) + (height / 2.0)
    from_frame = str(position.get('frame', 'screen_tl'))
    try:
        planes = planes_payload.get('planes', [])
        if isinstance(planes, list) and planes and isinstance(planes[0], dict):
            default_frame = str(planes[0].get('default_frame', 'screen_tl'))
            matrix_w = int(planes[0].get('size', {}).get('width', {}).get('value', 640))
            matrix_h = int(planes[0].get('size', {}).get('height', {}).get('value', 360))
        else:
            plane = planes_payload.get('plane', {})
            default_frame = str(plane.get('default_frame', 'screen_tl')) if isinstance(plane, dict) else 'screen_tl'
            matrix_w = 640
            matrix_h = 360
        reg = CoordinateFrameRegistry(width=max(1, matrix_w), height=max(1, matrix_h), default_frame=default_frame)
        x, y = reg.transform_point((x, y), from_frame=from_frame, to_frame='screen_tl')
    except Exception:
        pass
    out = [
        HDIEvent(
            event_id=event_id,
            ts_ns=event_id,
            window_id='validation',
            device='mouse',
            event_type='pointer_move',
            status='OK',
            payload={'x': x, 'y': y},
        )
    ]
    if event_type == 'scroll':
        out.append(
            HDIEvent(
                event_id=event_id + 1,
                ts_ns=event_id + 1,
                window_id='validation',
                device='trackpad',
                event_type='scroll',
                status='OK',
                payload={'x': x, 'y': y, 'delta_x': 3.0, 'delta_y': -7.0},
            )
        )
    else:
        out.append(
            HDIEvent(
                event_id=event_id + 1,
                ts_ns=event_id + 1,
                window_id='validation',
                device='mouse',
                event_type='click',
                status='OK',
                payload={'x': x, 'y': y},
            )
        )
    return out


def build_app(app_dir: Path):
    app_id = app_dir.name
    spec = APP_SPECS[app_id]
    plane_path = app_dir / 'plane.json'
    handlers = _build_handlers(spec)
    app = load_plane_app(plane_path, handlers=handlers, strict=True)

    if app_id == 'hello_plane':
        def _cycle_hover_profile(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
            payload = event_ctx.get('payload', {})
            phase = str(payload.get('phase', '')).lower() if isinstance(payload, dict) else ''
            if phase and phase not in {'up', 'single'}:
                return
            now_s = time.perf_counter()
            last_s = float(app_state.get('_hover_profile_last_click_s', -1.0))
            if last_s >= 0.0 and (now_s - last_s) < 0.12:
                return
            app_state['_hover_profile_last_click_s'] = now_s
            app_state.setdefault('actions', []).append('cycle_hover_profile')
            app_state['last_action'] = 'cycle_hover_profile'
            total = max(1, _hello_profile_count())
            current = int(app_state.get('hover_profile_index', 0))
            app_state['hover_profile_index'] = (current + 1) % total
            app_state['profile_cycle_count'] = int(app_state.get('profile_cycle_count', 0)) + 1
            if isinstance(payload, dict) and 'x' in payload and 'y' in payload:
                app_state['last_pointer_xy'] = (float(payload['x']), float(payload['y']))
            w = float(app_state.get('window_w', 960.0))
            h = float(app_state.get('window_h', 540.0))
            _hello_apply_hover_profile(app, app_state, width=w, height=h)
            app_state['status_text'] = 'last_action=cycle_hover_profile'

        handlers_map = getattr(app, '_handlers', None)
        if isinstance(handlers_map, dict):
            handlers_map['handlers::cycle_hover_profile'] = _cycle_hover_profile

    original_init = app.init
    original_loop = app.loop

    def _init(ctx: Any) -> None:
        original_init(ctx)
        app.state.setdefault('active_component_mode', 'basic')
        app.state.setdefault('overlay_visible', True)
        app.state.setdefault('active_route_path', '/home')
        if app_id == 'hello_plane':
            app.state['input_debug_enabled'] = _env_flag("LUVATRIX_DEBUG_INPUT", default=False)
        app.state.setdefault('hover_profile_index', 0)
        app.state.setdefault('profile_cycle_count', 0)
        width, height = _ctx_dimensions(ctx)
        app.state['window_w'] = width
        app.state['window_h'] = height
        if app_id == 'hello_plane':
            _hello_apply_hover_profile(app, app.state, width=width, height=height)
        _set_text(app, 'status_text', 'ready')

    def _loop(ctx: Any, dt: float) -> None:
        width, height = _ctx_dimensions(ctx)
        app.state['window_w'] = width
        app.state['window_h'] = height
        if app_id == 'hello_plane':
            _hello_apply_hover_profile(app, app.state, width=width, height=height)
        original_loop(ctx, dt)

    app.init = _init
    app.loop = _loop
    return app


def _validation_component_sequence(spec: dict[str, Any]) -> list[tuple[str, str]]:
    sequence: list[tuple[str, str]] = []
    component_targets = spec.get('action_component_ids', {})
    for action in spec.get('actions', []):
        repeats = int(spec.get('action_repeats', {}).get(action, 1))
        repeats = max(1, repeats)
        target_component = None
        if isinstance(component_targets, dict):
            raw_target = component_targets.get(action)
            if isinstance(raw_target, str) and raw_target.strip():
                target_component = raw_target.strip()
        if action == 'scroll_plane':
            for _ in range(repeats):
                sequence.append(('scroll', 'scroll_canvas'))
        else:
            for _ in range(repeats):
                sequence.append(('click', target_component or f'btn_{action}'))
    return sequence


def run_validation(app_dir: Path) -> Path:
    app_id = app_dir.name
    spec = APP_SPECS[app_id]
    app = build_app(app_dir)
    ctx = _ValidationCtx()
    app.init(ctx)

    eid = 10
    for event_type, component_id in _validation_component_sequence(spec):
        try:
            events = _event_for_component(app._planes, component_id, event_id=eid, event_type=event_type)
        except RuntimeError:
            continue
        for event in events:
            ctx.queue(event)
            eid += 1
        app.loop(ctx, 0.016)

    checks = spec.get('checks', {})
    results: dict[str, bool] = {}
    for key, expected in checks.items():
        results[key] = app.state.get(key) == expected

    payload: dict[str, Any] = {
        'app_id': app_id,
        'artifact_version': 'v2',
        'validation_command': f'PYTHONPATH=. uv run python examples/planes_v2/{app_id}/app_main.py --validate',
        'interactive_checks': results,
        'all_checks_passed': all(results.values()) if results else True,
        'actions_executed': list(app.state.get('actions', [])),
        'status_text': app.state.get('status_text', ''),
        'required_features': list(checks.keys()),
    }
    if 'routes' in spec:
        payload['routes'] = list(spec['routes'])
        payload['active_route_path'] = app.state.get('active_route_path')

    fingerprint_input = json.dumps(payload, sort_keys=True).encode('utf-8')
    payload['deterministic_fingerprint'] = sha256(fingerprint_input).hexdigest()
    payload['status'] = 'PASS' if payload['all_checks_passed'] else 'FAIL'

    artifact_path = app_dir / 'validation_artifact.json'
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding='utf-8')
    return artifact_path


def cli_main(app_dir: Path) -> int:
    parser = argparse.ArgumentParser(description='Run interactive planes training app or deterministic validation')
    parser.add_argument('--validate', action='store_true', help='Execute interactive validation sequence and write artifact')
    args = parser.parse_args()

    if args.validate:
        output = run_validation(app_dir)
        print(f'VALIDATION_ARTIFACT={output}')
        return 0

    app = build_app(app_dir)
    print(json.dumps({'app_id': app_dir.name, 'entrypoint': 'create', 'runtime': 'interactive', 'state_keys': sorted(app.state.keys())}))
    return 0
