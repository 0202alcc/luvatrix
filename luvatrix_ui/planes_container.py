"""Luvatrix app container schema.

The container is the first-class bundle format that promotes per-plane Planes
JSON into a complete app document: app metadata, planes/components, routes,
route transitions, component animations, and script references. The document
is language-neutral: render geometry compiles through the existing Planes
pipeline while logic stays behind named function bindings.

Container documents carry `container_protocol_version` plus the keys of a
Planes payload (`app`, `plane`/`planes`, `routes`, `scripts`,
`components`). Container-only keys (`animations`, per-route `transitions`)
are validated and normalized here, then stripped before the payload is
handed to `luvatrix_ui.planes_protocol.compile_planes_to_ui_ir`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .planes_protocol import PlanesValidationError, resolve_web_metadata

CONTAINER_PROTOCOL_VERSION = "0.1.0"

TRANSITION_KINDS = frozenset(
    {
        "none",
        "fade",
        "slide_left",
        "slide_right",
        "slide_up",
        "slide_down",
    }
)

TRANSITION_DEFAULT_KIND = "fade"
TRANSITION_DEFAULT_DURATION_MS = 200
TRANSITION_DEFAULT_EASING = "ease_in_out"

ANIMATION_KINDS = frozenset({"fade", "slide", "scale", "rotate"})
ANIMATION_TRIGGERS = frozenset({"route_enter", "route_exit", "on_mount", "on_state"})
ANIMATION_LOOP_MODES = frozenset({"none", "repeat", "ping_pong"})
ANIMATION_DEFAULT_LOOP = "none"

EASINGS = frozenset({"linear", "ease_in", "ease_out", "ease_in_out"})

CONTAINER_ONLY_KEYS = frozenset({"container_protocol_version", "animations"})


@dataclass(frozen=True)
class Keyframe:
    at: float
    props: dict[str, float]

    def __post_init__(self) -> None:
        if not 0.0 <= self.at <= 1.0:
            raise PlanesValidationError("keyframe.at must be within [0, 1]")
        if not self.props:
            raise PlanesValidationError("keyframe.props must not be empty")


@dataclass(frozen=True)
class RouteTransition:
    trigger: str
    to_route: str
    kind: str
    duration_ms: int
    easing: str


@dataclass(frozen=True)
class ContainerRoute:
    id: str
    default: bool
    active_planes: tuple[str, ...]
    transitions: tuple[RouteTransition, ...] = ()


@dataclass(frozen=True)
class ComponentAnimation:
    target: str
    trigger: str
    kind: str
    duration_ms: int
    easing: str
    delay_ms: int = 0
    loop: str = ANIMATION_DEFAULT_LOOP
    keyframes: tuple[Keyframe, ...] = ()
    state_key: str | None = None


@dataclass(frozen=True)
class CompiledAppContainer:
    app_id: str
    entry_route: str
    routes: tuple[ContainerRoute, ...]
    animations: tuple[ComponentAnimation, ...]
    planes_payload: dict[str, Any]
    diagnostics: tuple[str, ...] = field(default_factory=tuple)

    def resolve_route(self, route_id: str) -> ContainerRoute:
        for route in self.routes:
            if route.id == route_id:
                return route
        raise KeyError(f"unknown route `{route_id}`")

    def transitions_from(self, route_id: str) -> tuple[RouteTransition, ...]:
        return self.resolve_route(route_id).transitions


def validate_container_payload(payload: Mapping[str, Any], *, strict: bool = True) -> None:
    compile_container(payload, strict=strict)


def compile_container(
    payload: Mapping[str, Any],
    *,
    strict: bool = True,
) -> CompiledAppContainer:
    if not isinstance(payload, Mapping):
        raise PlanesValidationError("container payload must be an object")

    version = payload.get("container_protocol_version")
    if not isinstance(version, str) or not version.strip():
        raise PlanesValidationError("container_protocol_version must be a non-empty string")

    app = _expect_obj(payload.get("app"), "app")
    resolve_web_metadata(app)
    app_id = _require_str(app.get("id"), "app.id")

    routes_raw = payload.get("routes")
    if not isinstance(routes_raw, list) or not routes_raw:
        raise PlanesValidationError("routes must be a non-empty list")

    planes_raw = payload.get("planes")
    monolith_plane = payload.get("plane")
    if planes_raw is not None:
        if not isinstance(planes_raw, list) or not planes_raw:
            raise PlanesValidationError("planes must be a non-empty list")
        plane_ids = tuple(
            _require_str(_expect_obj(plane, f"planes[{i}]").get("id"), f"planes[{i}].id")
            for i, plane in enumerate(planes_raw)
        )
        has_v2 = True
    elif monolith_plane is not None:
        plane_ids = (
            _require_str(_expect_obj(monolith_plane, "plane").get("id"), "plane.id"),
        )
        has_v2 = False
    else:
        raise PlanesValidationError("container payload must include `planes` or `plane`")

    defaults = [route for route in routes_raw if isinstance(route, Mapping) and route.get("default")]
    if not defaults:
        raise PlanesValidationError("routes must declare exactly one default route")
    if len(defaults) > 1:
        raise PlanesValidationError("routes must declare exactly one default route")

    route_ids = _collect_route_ids(routes_raw)
    routes = tuple(_compile_route(raw, index, plane_ids, route_ids) for index, raw in enumerate(routes_raw))
    entry_route = routes[0].id if defaults[0] is routes_raw[0] else _find_default_route_id(routes_raw)

    animations = _compile_animations(payload.get("animations", []), payload.get("components", []))
    planes_payload = _strip_container_keys(payload)

    _validate_planes_payload(planes_payload, strict=strict)

    return CompiledAppContainer(
        app_id=app_id,
        entry_route=entry_route,
        routes=routes,
        animations=animations,
        planes_payload=planes_payload,
    )


def _compile_route(
    raw: Any,
    index: int,
    plane_ids: tuple[str, ...],
    route_ids: frozenset[str],
) -> ContainerRoute:
    route = _expect_obj(raw, f"routes[{index}]")
    route_id = _require_str(route.get("id"), f"routes[{index}].id")
    active_planes_raw = route.get("active_planes", [])
    if not isinstance(active_planes_raw, list):
        raise PlanesValidationError(f"routes[{index}].active_planes must be a list")
    active_planes: list[str] = []
    for plane_index, plane_id in enumerate(active_planes_raw):
        if not isinstance(plane_id, str) or not plane_id.strip():
            raise PlanesValidationError(f"routes[{index}].active_planes[{plane_index}] must be a non-empty string")
        if plane_id not in plane_ids:
            raise PlanesValidationError(
                f"routes[{index}] references unknown plane `{plane_id}`"
            )
        active_planes.append(plane_id)

    transitions_raw = route.get("transitions", [])
    if not isinstance(transitions_raw, list):
        raise PlanesValidationError(f"routes[{index}].transitions must be a list")
    transitions = tuple(
        _compile_transition(raw_transition, f"routes[{index}].transitions[{i}]", route_ids)
        for i, raw_transition in enumerate(transitions_raw)
    )
    triggers = [transition.trigger for transition in transitions]
    if len(set(triggers)) != len(triggers):
        raise PlanesValidationError(f"routes[{index}] has duplicate transition triggers")

    return ContainerRoute(
        id=route_id,
        default=bool(route.get("default", False)),
        active_planes=tuple(active_planes),
        transitions=transitions,
    )


def _compile_transition(raw: Any, name: str, route_ids: frozenset[str]) -> RouteTransition:
    transition = _expect_obj(raw, name)
    trigger = _require_str(transition.get("trigger"), f"{name}.trigger")
    to_route = _require_str(transition.get("to_route"), f"{name}.to_route")
    if to_route not in route_ids:
        raise PlanesValidationError(f"{name} references unknown route `{to_route}`")
    kind = transition.get("kind", TRANSITION_DEFAULT_KIND)
    if kind not in TRANSITION_KINDS:
        raise PlanesValidationError(f"{name}.kind must be one of {sorted(TRANSITION_KINDS)}")
    duration_ms = _coerce_duration(transition.get("duration_ms", TRANSITION_DEFAULT_DURATION_MS), f"{name}.duration_ms")
    easing = transition.get("easing", TRANSITION_DEFAULT_EASING)
    if easing not in EASINGS:
        raise PlanesValidationError(f"{name}.easing must be one of {sorted(EASINGS)}")
    return RouteTransition(trigger=trigger, to_route=to_route, kind=str(kind), duration_ms=duration_ms, easing=str(easing))


def _compile_animations(raw_animations: Any, components_raw: Any) -> tuple[ComponentAnimation, ...]:
    if not isinstance(raw_animations, list):
        raise PlanesValidationError("animations must be a list")
    component_ids = _collect_component_ids(components_raw)
    return tuple(
        _compile_animation(raw, index, component_ids)
        for index, raw in enumerate(raw_animations)
    )


def _compile_animation(raw: Any, index: int, component_ids: frozenset[str]) -> ComponentAnimation:
    animation = _expect_obj(raw, f"animations[{index}]")
    target = _require_str(animation.get("target"), f"animations[{index}].target")
    if component_ids and target not in component_ids:
        raise PlanesValidationError(f"animations[{index}] targets unknown component `{target}`")
    trigger = _require_str(animation.get("trigger"), f"animations[{index}].trigger")
    if trigger not in ANIMATION_TRIGGERS:
        raise PlanesValidationError(f"animations[{index}].trigger must be one of {sorted(ANIMATION_TRIGGERS)}")
    kind = _require_str(animation.get("kind"), f"animations[{index}].kind")
    if kind not in ANIMATION_KINDS:
        raise PlanesValidationError(f"animations[{index}].kind must be one of {sorted(ANIMATION_KINDS)}")
    duration_ms = _coerce_duration(animation.get("duration_ms"), f"animations[{index}].duration_ms")
    delay_ms = animation.get("delay_ms", 0)
    if not isinstance(delay_ms, int) or delay_ms < 0:
        raise PlanesValidationError(f"animations[{index}].delay_ms must be a non-negative integer")
    easing = animation.get("easing", TRANSITION_DEFAULT_EASING)
    if easing not in EASINGS:
        raise PlanesValidationError(f"animations[{index}].easing must be one of {sorted(EASINGS)}")
    loop = animation.get("loop", ANIMATION_DEFAULT_LOOP)
    if loop not in ANIMATION_LOOP_MODES:
        raise PlanesValidationError(f"animations[{index}].loop must be one of {sorted(ANIMATION_LOOP_MODES)}")
    state_key = animation.get("state_key")
    if trigger == "on_state":
        if not isinstance(state_key, str) or not state_key.strip():
            raise PlanesValidationError(
                f"animations[{index}].state_key must be a non-empty string when trigger is `on_state`"
            )
    elif state_key is not None:
        raise PlanesValidationError(
            f"animations[{index}].state_key is only valid when trigger is `on_state`"
        )
    keyframes = _compile_keyframes(animation.get("keyframes", []), f"animations[{index}].keyframes")
    return ComponentAnimation(
        target=target,
        trigger=trigger,
        kind=kind,
        duration_ms=duration_ms,
        easing=str(easing),
        delay_ms=delay_ms,
        loop=str(loop),
        keyframes=keyframes,
        state_key=str(state_key) if state_key is not None else None,
    )


def _compile_keyframes(raw_keyframes: Any, name: str) -> tuple[Keyframe, ...]:
    if not isinstance(raw_keyframes, list):
        raise PlanesValidationError(f"{name} must be a list")
    keyframes: list[Keyframe] = []
    last_at: float | None = None
    for index, raw in enumerate(raw_keyframes):
        keyframe_obj = _expect_obj(raw, f"{name}[{index}]")
        at = keyframe_obj.get("at")
        if not isinstance(at, (int, float)) or isinstance(at, bool):
            raise PlanesValidationError(f"{name}[{index}].at must be a number")
        props = keyframe_obj.get("props")
        if not isinstance(props, Mapping):
            raise PlanesValidationError(f"{name}[{index}].props must be an object")
        normalized_props = {
            str(key): _coerce_number(value, f"{name}[{index}].props[{key}]")
            for key, value in props.items()
        }
        keyframe = Keyframe(at=float(at), props=normalized_props)
        if last_at is not None and keyframe.at < last_at:
            raise PlanesValidationError(f"{name} keyframes must be ordered by ascending `at`")
        last_at = keyframe.at
        keyframes.append(keyframe)
    return tuple(keyframes)


PLANES_PROTOCOL_VERSION_DEFAULT = "0.2.0-dev"


def _strip_container_keys(payload: Mapping[str, Any]) -> dict[str, Any]:
    stripped = dict(payload)
    stripped.pop("container_protocol_version", None)
    stripped.pop("animations", None)
    if not stripped.get("planes_protocol_version"):
        stripped["planes_protocol_version"] = PLANES_PROTOCOL_VERSION_DEFAULT
    routes = stripped.get("routes")
    if isinstance(routes, list):
        stripped["routes"] = [
            {key: value for key, value in route.items() if key != "transitions"}
            if isinstance(route, Mapping)
            else route
            for route in routes
        ]
    return stripped


def _validate_planes_payload(planes_payload: dict[str, Any], *, strict: bool) -> None:
    from .planes_protocol import validate_planes_payload as validate_planes

    validate_planes(planes_payload, strict=strict)


def _collect_route_ids(routes_raw: list[Any]) -> frozenset[str]:
    ids: list[str] = []
    for index, raw in enumerate(routes_raw):
        route = _expect_obj(raw, f"routes[{index}]")
        ids.append(_require_str(route.get("id"), f"routes[{index}].id"))
    duplicates = {route_id for route_id in ids if ids.count(route_id) > 1}
    if duplicates:
        raise PlanesValidationError(f"route ids must be unique; duplicates: {sorted(duplicates)}")
    return frozenset(ids)


def _collect_component_ids(components_raw: Any) -> frozenset[str]:
    if not isinstance(components_raw, list):
        return frozenset()
    ids: list[str] = []
    for index, raw in enumerate(components_raw):
        component = _expect_obj(raw, f"components[{index}]")
        ids.append(_require_str(component.get("id"), f"components[{index}].id"))
    return frozenset(ids)


def _find_default_route_id(routes_raw: list[Any]) -> str:
    for raw in routes_raw:
        route = _expect_obj(raw, "routes[i]")
        if route.get("default"):
            return _require_str(route.get("id"), "routes[i].id")
    raise PlanesValidationError("routes must declare exactly one default route")


def _expect_obj(raw: Any, name: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise PlanesValidationError(f"{name} must be an object")
    return dict(raw)


def _require_str(raw: Any, name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise PlanesValidationError(f"{name} must be a non-empty string")
    return raw


def _coerce_duration(raw: Any, name: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or int(raw) <= 0:
        raise PlanesValidationError(f"{name} must be a positive integer")
    return int(raw)


def _coerce_number(raw: Any, name: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise PlanesValidationError(f"{name} must be a number")
    return float(raw)