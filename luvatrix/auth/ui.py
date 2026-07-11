"""Small app-facing UI models for authentication controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from luvatrix.app import InputState

from .sign_in import GoogleSignInController, GoogleSignInState


class AuthButtonFrame(Protocol):
    def rect(self, **kwargs: object) -> None: ...

    def text(self, text: str, **kwargs: object) -> None: ...


@dataclass
class GoogleSignInButton:
    """Pointer-driven state for an in-app Google sign-in control."""

    controller: GoogleSignInController

    def render(
        self,
        frame: AuthButtonFrame,
        *,
        x: float,
        y: float,
        width: float = 220.0,
        height: float = 44.0,
        z_index: int = 0,
    ) -> None:
        background = (235, 235, 235, 255) if self.disabled else (255, 255, 255, 255)
        foreground = (95, 99, 104, 255) if self.disabled else (60, 64, 67, 255)
        frame.rect(x=x, y=y, width=width, height=height, color=background, z_index=z_index)
        mark_size = min(20.0, max(12.0, height - 18.0))
        frame.text(
            "G",
            x=x + 14.0,
            y=y + (height - mark_size) * 0.5,
            font_size_px=mark_size,
            color=(66, 133, 244, 255),
            z_index=z_index + 1,
        )
        frame.text(
            self.label,
            x=x + 46.0,
            y=y + max(8.0, (height - 16.0) * 0.5),
            font_size_px=14.0,
            color=foreground,
            z_index=z_index + 1,
        )

    @property
    def disabled(self) -> bool:
        return self.controller.busy

    @property
    def label(self) -> str:
        return {
            GoogleSignInState.OPENING: "Opening Google...",
            GoogleSignInState.WAITING: "Waiting for Google...",
            GoogleSignInState.EXCHANGING: "Signing in...",
            GoogleSignInState.LOADING_PROFILE: "Loading account...",
            GoogleSignInState.SIGNED_IN: "Signed in with Google",
            GoogleSignInState.FAILED: "Try Google sign-in again",
            GoogleSignInState.CANCELLED: "Sign in with Google",
            GoogleSignInState.IDLE: "Sign in with Google",
        }[self.controller.state]

    def update(
        self,
        state: InputState,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> bool:
        if self.disabled or not state.left_clicked or not state.mouse_in_window:
            return False
        inside = x <= state.mouse_x <= x + max(0.0, width) and y <= state.mouse_y <= y + max(0.0, height)
        if not inside:
            return False
        if self.controller.signed_in:
            self.controller.sign_out()
        else:
            self.controller.sign_in()
        return True
