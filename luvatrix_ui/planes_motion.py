"""Deterministic motion clock for route transitions and component animations.

Pure timing/interpolation only: no rendering, no runtime imports. The
planes runtime advances these clocks with the frame `dt` and applies the
resulting overrides (opacity multipliers, position offsets) to the present
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

from .planes_container import ComponentAnimation, Keyframe, RouteTransition


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def easing_progress(name: str, t: float) -> float:
    """Map raw progress `t` (any float) through the named easing curve."""
    clamped = _clamp01(t)
    if name == "linear":
        return clamped
    if name == "ease_in":
        return clamped * clamped
    if name == "ease_out":
        return 1.0 - (1.0 - clamped) * (1.0 - clamped)
    if name == "ease_in_out":
        if clamped < 0.5:
            return 2.0 * clamped * clamped
        return 1.0 - 2.0 * (1.0 - clamped) * (1.0 - clamped)
    raise ValueError(f"unknown easing `{name}`")


def interpolate_keyframes(keyframes: tuple[Keyframe, ...], t: float) -> dict[str, float]:
    """Piecewise-linear numeric interpolation over ordered keyframes.

    Before the first keyframe the first keyframe's props apply; after the
    last the last keyframe's props apply. All props must be numeric.
    """
    if not keyframes:
        return {}
    clamped = _clamp01(t)
    if clamped <= keyframes[0].at:
        return dict(keyframes[0].props)
    if clamped >= keyframes[-1].at:
        return dict(keyframes[-1].props)
    for index in range(len(keyframes) - 1):
        start = keyframes[index]
        end = keyframes[index + 1]
        if start.at <= clamped <= end.at:
            span = end.at - start.at
            local = 0.0 if span <= 0.0 else (clamped - start.at) / span
            props: dict[str, float] = {}
            for key in start.props:
                start_value = float(start.props[key])
                end_value = float(end.props.get(key, start_value))
                props[key] = start_value + (end_value - start_value) * local
            for key in end.props:
                if key not in props:
                    props[key] = float(end.props[key])
            return props
    return dict(keyframes[-1].props)


@dataclass
class TransitionPlayback:
    from_route: str
    to_route: str
    kind: str
    duration_ms: int
    easing: str
    elapsed_s: float = 0.0

    @classmethod
    def from_spec(cls, spec: RouteTransition) -> "TransitionPlayback":
        return cls(
            from_route="",
            to_route=spec.to_route,
            kind=spec.kind,
            duration_ms=int(spec.duration_ms),
            easing=str(spec.easing),
        )

    def advance(self, dt: float) -> bool:
        """Advance by `dt` seconds. Returns True when the transition finished."""
        self.elapsed_s += max(0.0, float(dt))
        return self.elapsed_s >= self.duration_s

    @property
    def duration_s(self) -> float:
        return max(1e-6, self.duration_ms / 1000.0)

    def raw_progress(self) -> float:
        return _clamp01(self.elapsed_s / self.duration_s)

    def eased_progress(self) -> float:
        return easing_progress(self.easing, self.raw_progress())

    def finished(self) -> bool:
        return self.elapsed_s >= self.duration_s


@dataclass
class AnimationPlayback:
    spec: ComponentAnimation
    elapsed_s: float = 0.0
    completed: bool = False

    def advance(self, dt: float) -> None:
        self.elapsed_s += max(0.0, float(dt))
        if self.loop_mode == "none" and self.active_elapsed_s >= self.duration_s:
            self.completed = True

    @property
    def duration_s(self) -> float:
        return max(1e-6, self.spec.duration_ms / 1000.0)

    @property
    def delay_s(self) -> float:
        return max(0.0, self.spec.delay_ms / 1000.0)

    @property
    def loop_mode(self) -> str:
        return str(self.spec.loop)

    @property
    def active_elapsed_s(self) -> float:
        return max(0.0, self.elapsed_s - self.delay_s)

    def in_delay(self) -> bool:
        return self.elapsed_s < self.delay_s

    def raw_progress(self) -> float:
        if self.in_delay():
            return 0.0
        active = self.active_elapsed_s / self.duration_s
        if self.loop_mode == "none":
            return _clamp01(active)
        if self.loop_mode == "repeat":
            return active % 1.0
        if self.loop_mode == "ping_pong":
            phase = active % 2.0
            return phase if phase <= 1.0 else 2.0 - phase
        return _clamp01(active)

    def finished(self) -> bool:
        return self.completed and self.loop_mode == "none"

    def eased_progress(self) -> float:
        return easing_progress(self.spec.easing, self.raw_progress())

    def props_at(self) -> dict[str, float]:
        return interpolate_keyframes(self.spec.keyframes, self.raw_progress())


@dataclass(frozen=True)
class MotionOverride:
    """Per-component render overrides for the current frame."""

    opacity_multiplier: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    scale: float | None = None
    rotation_deg: float | None = None


@dataclass
class MotionState:
    """All active motion for one runtime, advanced once per frame."""

    transition: TransitionPlayback | None = None
    prev_plane_ids: tuple[str, ...] = ()
    animations: dict[str, AnimationPlayback] = field(default_factory=dict)
    state_values: dict[str, object] = field(default_factory=dict)
    mounted_targets: set[str] = field(default_factory=set)
    just_completed: set[str] = field(default_factory=set)
    transition_just_completed: bool = False
    epoch: int = 0

    def start_transition(
        self,
        *,
        from_route: str,
        to_route: str,
        spec: RouteTransition | None,
        prev_plane_ids: tuple[str, ...],
    ) -> None:
        self.transition = None
        if spec is not None and spec.kind != "none":
            self.transition = TransitionPlayback(
                from_route=from_route,
                to_route=to_route,
                kind=str(spec.kind),
                duration_ms=int(spec.duration_ms),
                easing=str(spec.easing),
            )
        self.prev_plane_ids = tuple(prev_plane_ids)
        self.epoch += 1

    def start_animation(self, spec: ComponentAnimation) -> None:
        self.animations[str(spec.target)] = AnimationPlayback(spec=spec)
        self.epoch += 1

    def advance(self, dt: float) -> None:
        self.just_completed = set()
        self.transition_just_completed = False
        changed = False
        if self.transition is not None:
            if self.transition.advance(dt):
                self.transition = None
                self.prev_plane_ids = ()
                self.transition_just_completed = True
            changed = True
        for target, playback in list(self.animations.items()):
            before = playback.elapsed_s
            was_completed = playback.completed
            playback.advance(dt)
            if playback.completed and not was_completed:
                self.just_completed.add(target)
            if playback.elapsed_s != before:
                changed = True
        if changed:
            self.epoch += 1

    def transition_active(self) -> bool:
        return self.transition is not None

    def has_running_motion(self) -> bool:
        if self.transition is not None:
            return True
        return any(not playback.finished() for playback in self.animations.values())

    def transition_telemetry(self) -> dict[str, object] | None:
        if self.transition is None:
            return None
        return {
            "from_route": self.transition.from_route,
            "to_route": self.transition.to_route,
            "kind": self.transition.kind,
            "progress": round(self.transition.eased_progress(), 6),
            "duration_ms": self.transition.duration_ms,
        }

    def animation_telemetry(self) -> dict[str, float]:
        progress: dict[str, float] = {}
        for target, playback in self.animations.items():
            if playback.finished():
                continue
            progress[target] = round(playback.raw_progress(), 6)
        return progress

    def overrides(
        self,
        *,
        component_plane_ids: Mapping[str, str],
        entering_plane_ids: frozenset[str],
        exiting_plane_ids: frozenset[str],
    ) -> dict[str, MotionOverride]:
        resolved: dict[str, MotionOverride] = {}
        if self.transition is not None:
            progress = self.transition.eased_progress()
            entering_multiplier = progress if self.transition.kind == "fade" else 1.0
            exiting_multiplier = (1.0 - progress) if self.transition.kind == "fade" else 1.0
            enter_offset = self._transition_enter_offset(progress)
            exit_offset = self._transition_exit_offset(progress)
            for component_id, plane_id in component_plane_ids.items():
                if plane_id in entering_plane_ids:
                    resolved[component_id] = MotionOverride(
                        opacity_multiplier=entering_multiplier,
                        offset_x=enter_offset[0],
                        offset_y=enter_offset[1],
                    )
                elif plane_id in exiting_plane_ids:
                    resolved[component_id] = MotionOverride(
                        opacity_multiplier=exiting_multiplier,
                        offset_x=exit_offset[0],
                        offset_y=exit_offset[1],
                    )
        for target, playback in self.animations.items():
            existing = resolved.get(target, MotionOverride())
            # Finished playbacks persist their final keyframe props (rest state).
            props = playback.props_at()
            opacity = existing.opacity_multiplier
            if "opacity" in props:
                opacity = existing.opacity_multiplier * float(props["opacity"])
            offset_x = existing.offset_x + float(props.get("offset_x", 0.0))
            offset_y = existing.offset_y + float(props.get("offset_y", 0.0))
            scale = float(props["scale"]) if "scale" in props else existing.scale
            rotation = (
                float(props["rotation_deg"]) if "rotation_deg" in props else existing.rotation_deg
            )
            resolved[target] = MotionOverride(
                opacity_multiplier=opacity,
                offset_x=offset_x,
                offset_y=offset_y,
                scale=scale,
                rotation_deg=rotation,
            )
        return resolved

    def _transition_enter_offset(self, progress: float) -> tuple[float, float]:
        return self._slide_offset(self.transition.kind if self.transition else "", progress, entering=True)

    def _transition_exit_offset(self, progress: float) -> tuple[float, float]:
        return self._slide_offset(self.transition.kind if self.transition else "", progress, entering=False)

    @staticmethod
    def _slide_offset(kind: str, progress: float, *, entering: bool) -> tuple[float, float]:
        remaining = 1.0 - progress
        if kind == "slide_left":
            # New route slides in from the right edge; old route exits left.
            return (remaining if entering else -progress, 0.0)
        if kind == "slide_right":
            return (-remaining if entering else progress, 0.0)
        if kind == "slide_up":
            return (0.0, remaining if entering else -progress)
        if kind == "slide_down":
            return (0.0, -remaining if entering else progress)
        return (0.0, 0.0)


def is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))