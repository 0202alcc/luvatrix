from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


DebugActionHandler = Callable[[dict[str, Any]], None]
DebugAvailabilityPredicate = Callable[[dict[str, Any]], bool]
DebugWarningSink = Callable[[str], None]


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
