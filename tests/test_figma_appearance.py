"""FigmaApp appearance variants: one app holding light and dark designs.

The host appearance comes from `LUVATRIX_APPEARANCE` (test/headless override)
or the platform bridge; `set_appearance` swaps the rendered document while the
current screen, scroll position, and back history survive by frame name.
"""

from __future__ import annotations

import numpy as np
import pytest

from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_ui.figma import FigmaApp, FigmaDocument

from figma_fixtures import back, navigate, node, solid


def _variant_doc(bg: tuple[float, float, float], *, prefix: str = "") -> FigmaDocument:
    """A Home/Detail prototype; ``prefix`` keeps ids unique across variants."""
    home = node(
        f"{prefix}1:1",
        "FRAME",
        "Home",
        0,
        0,
        100,
        200,
        fills=[solid(*bg)],
        clipsContent=True,
        children=[
            node(f"{prefix}1:2", "RECTANGLE", "Go", 10, 150, 80, 30, fills=[solid(1, 0, 0)], interactions=navigate(f"{prefix}2:1")),
            node(f"{prefix}1:3", "RECTANGLE", "Open Sheet", 10, 100, 80, 30, fills=[solid(0, 0, 1)], interactions=[
                {
                    "trigger": {"type": "ON_CLICK"},
                    "actions": [{"type": "NODE", "destinationId": f"{prefix}3:1", "navigation": "OVERLAY", "transition": None}],
                }
            ]),
        ],
    )
    detail = node(
        f"{prefix}2:1",
        "FRAME",
        "Detail",
        0,
        0,
        100,
        400,
        fills=[solid(*bg)],
        clipsContent=True,
        overflowDirection="VERTICAL_SCROLLING",
        children=[
            node(f"{prefix}2:2", "RECTANGLE", "Back", 0, 0, 40, 40, fills=[solid(0, 1, 0)], interactions=back()),
        ],
    )
    sheet = node(f"{prefix}3:1", "FRAME", "Sheet", 0, 0, 100, 120, fills=[solid(*bg)], children=[])
    return FigmaDocument.from_dict(
        {
            "name": "Appearance",
            "document": {
                "id": "0:0",
                "type": "DOCUMENT",
                "name": "Document",
                "children": [
                    {
                        "id": "0:1",
                        "type": "CANVAS",
                        "name": "Page",
                        "flowStartingPoints": [{"nodeId": f"{prefix}1:1", "name": "Flow"}],
                        "children": [home, detail, sheet],
                    }
                ],
            },
        }
    )


class _FakeCtx:
    def __init__(self, width: int, height: int) -> None:
        self._snapshot = np.zeros((height, width, 4), dtype=np.uint8)
        self._events: list[HDIEvent] = []
        self.frames: list[np.ndarray] = []
        self.display_width_px, self.display_height_px = width, height

    def read_matrix_snapshot(self) -> np.ndarray:
        return self._snapshot

    def poll_hdi_events(self, max_events: int, frame: str | None = None) -> list[HDIEvent]:
        _ = (max_events, frame)
        events, self._events = self._events, []
        return events

    def submit_write_batch(self, batch) -> None:
        tensor = batch.operations[0].tensor_h_w_4
        self.frames.append(np.asarray(tensor.cpu() if hasattr(tensor, "cpu") else tensor).copy())

    def queue(self, *events: HDIEvent) -> None:
        self._events.extend(events)


LIGHT_BG = (1.0, 1.0, 1.0)
DARK_BG = (0.05, 0.05, 0.07)


def _app(ctx: _FakeCtx, **kwargs) -> FigmaApp:
    app = FigmaApp(_variant_doc(LIGHT_BG), dark=_variant_doc(DARK_BG, prefix="D:"), **kwargs)
    app.init(ctx)
    return app


def _bg_pixel(ctx: _FakeCtx) -> tuple[int, int, int, int]:
    return tuple(int(v) for v in ctx.frames[-1][5, 5])


@pytest.fixture(autouse=True)
def _clean_appearance_env(monkeypatch) -> None:
    monkeypatch.delenv("LUVATRIX_APPEARANCE", raising=False)
    monkeypatch.delenv("LUVATRIX_IOS_USER_INTERFACE_STYLE", raising=False)


def test_starts_in_the_light_appearance_by_default() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)

    app.loop(ctx, 0.016)

    assert app.appearance == "light"
    assert _bg_pixel(ctx) == (255, 255, 255, 255)


def test_set_appearance_renders_the_dark_design() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.loop(ctx, 0.016)

    assert app.set_appearance("dark") is True
    app.loop(ctx, 0.016)

    assert app.appearance == "dark"
    assert _bg_pixel(ctx) == (13, 13, 18, 255)

    assert app.set_appearance("light") is True
    app.loop(ctx, 0.016)
    assert _bg_pixel(ctx) == (255, 255, 255, 255)


def test_current_screen_maps_by_name_across_variant_ids() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.loop(ctx, 0.016)
    app.navigate("Detail")
    app.loop(ctx, 0.016)

    app.set_appearance("dark")

    assert app.current_frame_name == "Detail"
    assert app.current_frame_id == "D:2:1"


def test_scroll_position_survives_the_switch() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.loop(ctx, 0.016)
    app.navigate("Detail")
    app.loop(ctx, 0.016)
    app.scroll_by(120)

    app.set_appearance("dark")
    app.loop(ctx, 0.016)

    assert app.scroll_y == 120
    assert _bg_pixel(ctx) == (13, 13, 18, 255)


def test_back_history_survives_the_switch() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.loop(ctx, 0.016)
    app.navigate("Detail")
    app.loop(ctx, 0.016)

    app.set_appearance("dark")
    app.back()
    app.loop(ctx, 0.016)

    assert app.current_frame_name == "Home"
    assert app.appearance == "dark"
    assert _bg_pixel(ctx) == (13, 13, 18, 255)


def test_switching_closes_open_overlays() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.loop(ctx, 0.016)
    app.open_overlay("Sheet")
    app.loop(ctx, 0.016)
    assert app.overlay_frame_name == "Sheet"

    app.set_appearance("dark")

    assert app.overlay_frame_name is None


def test_repeated_or_unknown_appearance_is_a_noop() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)

    assert app.set_appearance("light") is False
    assert app.set_appearance("sepia") is False
    assert app.appearance == "light"


def test_switching_without_a_dark_variant_is_a_noop() -> None:
    ctx = _FakeCtx(100, 200)
    app = FigmaApp(_variant_doc(LIGHT_BG))
    app.init(ctx)
    app.loop(ctx, 0.016)

    assert app.set_appearance("dark") is False
    app.loop(ctx, 0.016)
    assert _bg_pixel(ctx) == (255, 255, 255, 255)


def test_env_override_forces_the_dark_appearance(monkeypatch) -> None:
    monkeypatch.setenv("LUVATRIX_APPEARANCE", "dark")
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)

    app.loop(ctx, 0.016)

    assert app.appearance == "dark"
    assert _bg_pixel(ctx) == (13, 13, 18, 255)


def test_update_follows_env_appearance_changes(monkeypatch) -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.loop(ctx, 0.016)
    assert app.appearance == "light"

    monkeypatch.setenv("LUVATRIX_APPEARANCE", "dark")
    app.update(0.016)
    assert app.appearance == "dark"

    monkeypatch.setenv("LUVATRIX_APPEARANCE", "light")
    app.update(0.016)
    assert app.appearance == "light"


def test_explicit_appearance_pins_until_the_env_overrides(monkeypatch) -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx, appearance="dark")
    app.loop(ctx, 0.016)
    assert app.appearance == "dark"

    # The trait bridge reporting light does not move a pinned app...
    monkeypatch.setenv("LUVATRIX_IOS_USER_INTERFACE_STYLE", "light")
    app.update(0.016)
    assert app.appearance == "dark"

    # ...but the explicit env override beats the pin.
    monkeypatch.setenv("LUVATRIX_APPEARANCE", "light")
    app.update(0.016)
    assert app.appearance == "light"
