from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_ui.figma import FigmaApp, FigmaDocument

from figma_fixtures import two_screen_file


class _FakeCtx:
    def __init__(self, width: int, height: int, *, display: tuple[int, int] | None = None) -> None:
        self._snapshot = np.zeros((height, width, 4), dtype=np.uint8)
        self._events: list[HDIEvent] = []
        self.frames: list[np.ndarray] = []
        self.display_width_px, self.display_height_px = display or (width, height)

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


def _touch(phase: str, x: float, y: float) -> HDIEvent:
    return HDIEvent(1, 1, "w", "touch", "touch", "OK", {"touch_id": 1, "phase": phase, "x": x, "y": y})


def _click(phase: str, x: float, y: float) -> HDIEvent:
    return HDIEvent(1, 1, "w", "mouse", "click", "OK", {"button": 0, "phase": phase, "x": x, "y": y})


def _tap(ctx: _FakeCtx, x: float, y: float) -> None:
    ctx.queue(_touch("down", x, y), _touch("up", x, y))


def _app(ctx: _FakeCtx, **kwargs) -> FigmaApp:
    app = FigmaApp(FigmaDocument.from_dict(two_screen_file()), **kwargs)
    app.init(ctx)
    return app


def test_first_loop_renders_the_start_frame_to_the_matrix() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)

    app.loop(ctx, 0.016)

    assert app.current_frame_id == "1:1"
    frame = ctx.frames[-1]
    assert frame.shape == (200, 100, 4)
    assert tuple(frame[165, 50]) == (255, 0, 0, 255)


def test_idle_loops_do_not_resubmit_frames() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.loop(ctx, 0.016)

    app.loop(ctx, 0.016)
    app.loop(ctx, 0.016)

    assert len(ctx.frames) == 1


def test_tapping_a_prototype_link_navigates_and_back_returns() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.loop(ctx, 0.016)

    _tap(ctx, 50, 165)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "2:1"
    assert tuple(ctx.frames[-1][150, 10]) == (0, 0, 255, 255)

    _tap(ctx, 20, 20)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "1:1"
    assert tuple(ctx.frames[-1][165, 50]) == (255, 0, 0, 255)


def test_legacy_transition_links_navigate() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx, start="Detail")
    app.loop(ctx, 0.016)

    _tap(ctx, 70, 120)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "1:1"


def test_back_with_no_history_stays_put() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx, start="Detail")
    app.loop(ctx, 0.016)

    _tap(ctx, 20, 20)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "2:1"


def test_dragging_off_the_hotspot_cancels_the_tap() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.loop(ctx, 0.016)

    ctx.queue(_touch("down", 50, 165), _touch("move", 50, 60), _touch("up", 50, 60))
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "1:1"


def test_mouse_clicks_navigate() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.loop(ctx, 0.016)

    ctx.queue(_click("down", 50, 165), _click("up", 50, 165))
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "2:1"


def test_frame_is_scaled_to_fit_and_letterboxed() -> None:
    ctx = _FakeCtx(300, 200)
    app = _app(ctx, background=(10, 20, 30, 255))

    app.loop(ctx, 0.016)

    frame = ctx.frames[-1]
    assert tuple(frame[100, 20]) == (10, 20, 30, 255)
    assert tuple(frame[165, 150]) == (255, 0, 0, 255)
    assert tuple(frame[100, 150]) == (255, 255, 255, 255)


def test_taps_map_from_display_points_to_retina_matrix_pixels() -> None:
    ctx = _FakeCtx(200, 400, display=(100, 200))
    app = _app(ctx)
    app.loop(ctx, 0.016)

    assert tuple(ctx.frames[-1][330, 100]) == (255, 0, 0, 255)

    _tap(ctx, 50, 165)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "2:1"


def test_tap_handlers_receive_the_tapped_node_name() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    seen: list[str] = []
    app.on_tap("Go Button", lambda target, name: seen.append(name))
    app.loop(ctx, 0.016)

    _tap(ctx, 50, 165)
    app.loop(ctx, 0.016)

    assert seen == ["Go Button"]
    assert app.current_frame_id == "2:1"


def test_tap_handler_returning_false_suppresses_navigation() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)
    app.on_tap("Go Button", lambda target, name: False)
    app.loop(ctx, 0.016)

    _tap(ctx, 50, 165)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "1:1"


def test_navigate_by_name_and_unknown_names_raise() -> None:
    ctx = _FakeCtx(100, 200)
    app = _app(ctx)

    app.navigate("Detail")

    assert app.current_frame_id == "2:1"
    with pytest.raises(KeyError):
        app.navigate("Nope")


def test_app_loads_a_design_path_relative_to_its_module(tmp_path: Path) -> None:
    path = tmp_path / "design.json"
    path.write_text(json.dumps(two_screen_file()), encoding="utf-8")
    ctx = _FakeCtx(100, 200)

    app = FigmaApp(path)
    app.init(ctx)
    app.loop(ctx, 0.016)

    assert app.current_frame_id == "1:1"
    assert len(ctx.frames) == 1
