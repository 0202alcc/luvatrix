
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_ui.planes_runtime import load_plane_app


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
      "toggle_theme"
    ],
    "checks": {
      "theme_toggled": True
    },
    "concepts": [
      "Plane runtime bootstrapping",
      "Theme toggle event handling",
      "Deterministic state snapshots"
    ],
    "objective": "Render a starter plane app and toggle themes through direct click interaction."
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
    component = _find_component(app._planes, component_id)
    props = component.get('props')
    if not isinstance(props, dict):
        props = {}
        component['props'] = props
    props['text'] = value


def _handler(action: str):
    def _inner(event_ctx: dict[str, Any], app_state: dict[str, Any]) -> None:
        app_state.setdefault('actions', []).append(action)
        app_state['last_action'] = action
        if action == 'toggle_theme':
            current = str(app_state.get('active_theme', 'default'))
            app_state['active_theme'] = 'training_alt' if current == 'default' else 'default'
            app_state['theme_toggled'] = True
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
    component = _find_component(planes_payload, component_id)
    position = component.get('position', {})
    size = component.get('size', {})
    width = float(size.get('width', {}).get('value', 120))
    height = float(size.get('height', {}).get('value', 28))
    x = float(position.get('x', 0)) + (width / 2.0)
    y = float(position.get('y', 0)) + (height / 2.0)
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
    app = load_plane_app(plane_path, handlers=_build_handlers(spec), strict=True)

    original_init = app.init

    def _init(ctx: Any) -> None:
        original_init(ctx)
        app.state.setdefault('active_component_mode', 'basic')
        app.state.setdefault('overlay_visible', True)
        app.state.setdefault('active_route_path', '/home')
        _set_text(app, 'status_text', 'ready')

    app.init = _init
    return app


def _validation_component_sequence(spec: dict[str, Any]) -> list[tuple[str, str]]:
    sequence: list[tuple[str, str]] = []
    for action in spec.get('actions', []):
        repeats = int(spec.get('action_repeats', {}).get(action, 1))
        repeats = max(1, repeats)
        if action == 'scroll_plane':
            for _ in range(repeats):
                sequence.append(('scroll', 'scroll_canvas'))
        else:
            for _ in range(repeats):
                sequence.append(('click', f'btn_{action}'))
    return sequence


def run_validation(app_dir: Path) -> Path:
    app_id = app_dir.name
    spec = APP_SPECS[app_id]
    app = build_app(app_dir)
    ctx = _ValidationCtx()
    app.init(ctx)

    eid = 10
    for event_type, component_id in _validation_component_sequence(spec):
        for event in _event_for_component(app._planes, component_id, event_id=eid, event_type=event_type):
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
        'validation_command': f'PYTHONPATH=. uv run python examples/app_protocol/{app_id}/app_main.py --validate',
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
