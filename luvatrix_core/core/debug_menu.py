from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


DebugActionHandler = Callable[[dict[str, Any]], None]
DebugAvailabilityPredicate = Callable[[dict[str, Any]], bool]
DebugWarningSink = Callable[[str], None]


@dataclass(frozen=True)
class DebugMenuActionSpec:
    menu_id: str
    capability_id: str
    label: str


@dataclass(frozen=True)
class DebugMenuAdapterSpec:
    platform: str
    supported: bool
    supported_menu_ids: tuple[str, ...]
    declared_capabilities: tuple[str, ...]
    unsupported_reason: str | None = None


DEFAULT_DEBUG_MENU_ACTIONS: tuple[DebugMenuActionSpec, ...] = (
    DebugMenuActionSpec(
        menu_id="debug.menu.capture.screenshot",
        capability_id="debug.capture.screenshot",
        label="Capture Screenshot",
    ),
    DebugMenuActionSpec(
        menu_id="debug.menu.capture.record.toggle",
        capability_id="debug.capture.record",
        label="Toggle Window Recording",
    ),
    DebugMenuActionSpec(
        menu_id="debug.menu.overlay.toggle",
        capability_id="debug.overlay.render",
        label="Toggle Overlay Tooling",
    ),
    DebugMenuActionSpec(
        menu_id="debug.menu.replay.start",
        capability_id="debug.replay.start",
        label="Start Replay",
    ),
    DebugMenuActionSpec(
        menu_id="debug.menu.perf.hud.toggle",
        capability_id="debug.perf.hud",
        label="Toggle Perf HUD",
    ),
)


@dataclass(frozen=True)
class DebugMenuDispatchResult:
    action_id: str
    status: str
    warning: str | None = None


@dataclass(frozen=True)
class _RegisteredAction:
    handler: DebugActionHandler
    is_enabled: DebugAvailabilityPredicate


class DebugMenuDispatcher:
    """Crash-proof dispatch contract for debug menu actions."""

    def __init__(self, warning_sink: DebugWarningSink | None = None) -> None:
        self._warning_sink = warning_sink
        self._actions: dict[str, _RegisteredAction] = {}

    def register(
        self,
        action_id: str,
        handler: DebugActionHandler,
        *,
        is_enabled: DebugAvailabilityPredicate | None = None,
    ) -> None:
        normalized = action_id.strip()
        if not normalized:
            raise ValueError("action_id must be non-empty")
        if normalized in self._actions:
            raise ValueError(f"action_id already registered: {normalized}")
        self._actions[normalized] = _RegisteredAction(
            handler=handler,
            is_enabled=is_enabled or (lambda _ctx: True),
        )

    def dispatch(self, action_id: str, context: dict[str, Any] | None = None) -> DebugMenuDispatchResult:
        normalized = action_id.strip()
        if not normalized:
            warning = "empty action id"
            self._warn(warning)
            return DebugMenuDispatchResult(action_id=action_id, status="NOOP", warning=warning)
        action = self._actions.get(normalized)
        if action is None:
            warning = f"unknown action: {normalized}"
            self._warn(warning)
            return DebugMenuDispatchResult(action_id=normalized, status="NOOP", warning=warning)

        payload = context or {}
        if not action.is_enabled(payload):
            warning = f"disabled action: {normalized}"
            self._warn(warning)
            return DebugMenuDispatchResult(action_id=normalized, status="DISABLED", warning=warning)
        try:
            action.handler(payload)
        except Exception as exc:  # defensive fallback is required for crash-proof dispatch
            warning = f"handler failure for {normalized}: {exc.__class__.__name__}"
            self._warn(warning)
            return DebugMenuDispatchResult(action_id=normalized, status="NOOP", warning=warning)
        return DebugMenuDispatchResult(action_id=normalized, status="EXECUTED")

    def _warn(self, message: str) -> None:
        if self._warning_sink is not None:
            self._warning_sink(message)


def build_debug_capability_registry(
    actions: tuple[DebugMenuActionSpec, ...] = DEFAULT_DEBUG_MENU_ACTIONS,
) -> dict[str, str]:
    validate_debug_menu_actions(actions)
    return {action.menu_id: action.capability_id for action in actions}


def validate_debug_menu_actions(actions: tuple[DebugMenuActionSpec, ...]) -> None:
    if not actions:
        raise ValueError("debug menu actions must be non-empty")
    seen_menu: set[str] = set()
    seen_capability: set[str] = set()
    for action in actions:
        if not _looks_canonical_id(action.menu_id, expected_prefix="debug.menu."):
            raise ValueError(f"invalid menu id: {action.menu_id}")
        if not _looks_canonical_id(action.capability_id, expected_prefix="debug."):
            raise ValueError(f"invalid capability id: {action.capability_id}")
        if action.menu_id in seen_menu:
            raise ValueError(f"duplicate menu id: {action.menu_id}")
        if action.capability_id in seen_capability:
            raise ValueError(f"duplicate capability id: {action.capability_id}")
        seen_menu.add(action.menu_id)
        seen_capability.add(action.capability_id)


def _looks_canonical_id(value: str, *, expected_prefix: str) -> bool:
    if not value.startswith(expected_prefix):
        return False
    if value.lower() != value:
        return False
    if ".." in value or value.endswith(".") or value.startswith("."):
        return False
    return all(ch.islower() or ch.isdigit() or ch in {".", "_"} for ch in value)


def default_debug_menu_adapter_specs() -> tuple[DebugMenuAdapterSpec, ...]:
    registry = build_debug_capability_registry()
    menu_ids = tuple(registry.keys())
    capabilities = tuple(registry.values())
    return (
        DebugMenuAdapterSpec(
            platform="macos",
            supported=True,
            supported_menu_ids=menu_ids,
            declared_capabilities=capabilities,
            unsupported_reason=None,
        ),
        DebugMenuAdapterSpec(
            platform="windows",
            supported=False,
            supported_menu_ids=(),
            declared_capabilities=("debug.adapter.windows.stub",),
            unsupported_reason="macOS-first phase: explicit stub only",
        ),
        DebugMenuAdapterSpec(
            platform="linux",
            supported=False,
            supported_menu_ids=(),
            declared_capabilities=("debug.adapter.linux.stub",),
            unsupported_reason="macOS-first phase: explicit stub only",
        ),
    )


def debug_menu_adapter_capability_matrix() -> dict[str, dict[str, object]]:
    matrix: dict[str, dict[str, object]] = {}
    for spec in default_debug_menu_adapter_specs():
        matrix[spec.platform] = {
            "supported": spec.supported,
            "supported_menu_ids": list(spec.supported_menu_ids),
            "declared_capabilities": list(spec.declared_capabilities),
            "unsupported_reason": spec.unsupported_reason,
        }
    return matrix
