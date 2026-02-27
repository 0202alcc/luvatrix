from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .interaction import HDIPressEvent


ButtonState = Literal["idle", "hover", "press_down", "press_hold", "disabled"]


@dataclass
class ButtonModel:
    """Default v0 button state model driven by HDI hover/press signals."""

    disabled: bool = False
    hovered: bool = False
    state: ButtonState = "idle"

    def __post_init__(self) -> None:
        self._sync_state()

    def set_disabled(self, disabled: bool) -> ButtonState:
        self.disabled = disabled
        if disabled:
            self.state = "disabled"
            return self.state
        self._sync_state()
        return self.state

    def set_hovered(self, hovered: bool) -> ButtonState:
        self.hovered = hovered
        if self.disabled:
            self.state = "disabled"
            return self.state
        if not hovered and self.state in ("press_down", "press_hold"):
            self.state = "idle"
            return self.state
        self._sync_state()
        return self.state

    def on_press(self, press: HDIPressEvent) -> ButtonState:
        if self.disabled:
            self.state = "disabled"
            return self.state
        if press.phase == "down":
            if self.hovered:
                self.state = "press_down"
            return self.state
        if press.phase in ("hold_start", "hold_tick"):
            if self.state in ("press_down", "press_hold"):
                self.state = "press_hold"
            return self.state
        if press.phase in ("up", "cancel"):
            self._sync_state()
            return self.state
        if press.phase in ("repeat", "hold_end", "single", "double"):
            return self.state
        self._sync_state()
        return self.state

    def _sync_state(self) -> None:
        if self.disabled:
            self.state = "disabled"
        elif self.hovered:
            self.state = "hover"
        else:
            self.state = "idle"
