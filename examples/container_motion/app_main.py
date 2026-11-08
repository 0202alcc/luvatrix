from __future__ import annotations

from pathlib import Path

from luvatrix_ui.planes_runtime import PlaneApp, load_plane_app
from luvatrix_ui.planes_web import PlaneWebApp

APP_DIR = Path(__file__).resolve().parent
TOGGLE_INTERVAL_S = 1.2


class ContainerMotionApp:
    """Container demo with a dual contract.

    Native targets drive `init(ctx)` / `loop(ctx, dt)` / `stop(ctx)`; the
    browser runtime (`serve-web` / `build-web`) drives `init_browser` /
    `loop_browser(dt)` through the web command-buffer bridge. Both paths
    alternate the `home` and `settings` routes on a timer, exercising the
    fade/slide transitions and the route_enter keyframe animation.
    """

    def __init__(self) -> None:
        self._app: PlaneApp = load_plane_app(APP_DIR / "container.json", handlers={})
        self._web: PlaneWebApp | None = None
        self._elapsed_s = 0.0
        self._next_toggle_s = TOGGLE_INTERVAL_S

    def _toggle_route(self, web: PlaneWebApp | None) -> None:
        if web is not None:
            state = web.state
            activate = web.activate_route
        else:
            state = self._app.state
            activate = self._app.activate_route
        current = str(state.get("active_route", "home"))
        activate("settings" if current == "home" else "home")

    # -- native app protocol lifecycle ---------------------------------------

    def init(self, ctx) -> None:
        self._app.init(ctx)

    def loop(self, ctx, dt: float) -> None:
        self._elapsed_s += float(dt)
        if self._elapsed_s >= self._next_toggle_s:
            self._toggle_route(None)
            self._next_toggle_s = self._elapsed_s + TOGGLE_INTERVAL_S
        self._app.loop(ctx, dt)

    def stop(self, ctx) -> None:
        self._app.stop(ctx)

    # -- browser contract (Pyodide, via luvatrix-web.js) ----------------------

    def init_browser(self, *, width: int, height: int, input_provider, manifest: dict | None = None) -> None:
        self._web = PlaneWebApp(APP_DIR / "container.json", handlers={})
        self._web.init_browser(
            width=width,
            height=height,
            input_provider=input_provider,
            manifest=manifest or {},
        )
        self._elapsed_s = 0.0
        self._next_toggle_s = TOGGLE_INTERVAL_S

    def loop_browser(self, dt: float) -> dict[str, object]:
        if self._web is None:
            raise RuntimeError("init_browser must run before loop_browser")
        self._elapsed_s += float(dt)
        if self._elapsed_s >= self._next_toggle_s:
            self._toggle_route(self._web)
            self._next_toggle_s = self._elapsed_s + TOGGLE_INTERVAL_S
        return self._web.loop_browser(dt)

    def teardown_browser(self) -> None:
        if self._web is not None:
            self._web.teardown_browser()


def create() -> ContainerMotionApp:
    return ContainerMotionApp()
