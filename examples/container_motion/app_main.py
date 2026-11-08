from __future__ import annotations

from pathlib import Path

from luvatrix_ui.planes_runtime import PlaneApp, load_plane_app

APP_DIR = Path(__file__).resolve().parent
TOGGLE_INTERVAL_S = 1.2


class ContainerMotionApp:
    """App protocol wrapper that alternates container routes on a timer."""

    def __init__(self) -> None:
        self._app: PlaneApp = load_plane_app(APP_DIR / "container.json", handlers={})
        self._elapsed_s = 0.0
        self._next_toggle_s = TOGGLE_INTERVAL_S

    def init(self, ctx) -> None:
        self._app.init(ctx)

    def loop(self, ctx, dt: float) -> None:
        self._elapsed_s += float(dt)
        if self._elapsed_s >= self._next_toggle_s:
            current = str(self._app.state.get("active_route", "home"))
            self._app.activate_route("settings" if current == "home" else "home")
            self._next_toggle_s = self._elapsed_s + TOGGLE_INTERVAL_S
        self._app.loop(ctx, dt)

    def stop(self, ctx) -> None:
        self._app.stop(ctx)


def create() -> ContainerMotionApp:
    return ContainerMotionApp()
