from __future__ import annotations

import json
from pathlib import Path

import pytest

from luvatrix_ui.figma import FigmaApp, FigmaDocument
from luvatrix_ui.figma.tour import TOUR_ENV, TOUR_DIR_ENV, TOUR_RUN_ENV, TourError, load_tour_steps

from figma_fixtures import scrolling_file, two_screen_file
from test_figma_app import _FakeCtx


def _status(status_dir: Path) -> dict:
    return json.loads((status_dir / "status.json").read_text())


def _drive(app: FigmaApp, ctx: _FakeCtx, status_dir: Path, *, ack: bool = True, max_ticks: int = 400) -> list[dict]:
    """Loop the app like a device would while acting as the host that takes screenshots."""
    captures: list[dict] = []
    for _ in range(max_ticks):
        app.loop(ctx, 0.05)
        path = status_dir / "status.json"
        if not path.exists():
            continue
        status = _status(status_dir)
        if status["state"] == "capture" and not (status_dir / f"ack_{status['step']}").exists():
            if not captures or captures[-1]["step"] != status["step"]:
                captures.append({**status, "pixel": tuple(int(v) for v in ctx.frames[-1][150, 50])})
            if ack:
                (status_dir / f"ack_{status['step']}").write_text("ok")
        if status["state"] in {"done", "error"}:
            break
    return captures


def _start(monkeypatch, tmp_path: Path, steps: list, data=None, **env) -> tuple[FigmaApp, _FakeCtx, Path]:
    status_dir = tmp_path / "status"
    monkeypatch.setenv(TOUR_ENV, json.dumps(steps))
    monkeypatch.setenv(TOUR_DIR_ENV, str(status_dir))
    monkeypatch.setenv(TOUR_RUN_ENV, "run-1")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    ctx = _FakeCtx(100, 200, display=(50, 100))
    app = FigmaApp(FigmaDocument.from_dict(data or two_screen_file()))
    app.init(ctx)
    return app, ctx, status_dir


def test_load_tour_steps_accepts_inline_json_or_a_file(tmp_path: Path) -> None:
    steps = [{"tap": "Go Button"}, {"wait": 0.5}, {"scroll": 40}, {"capture": "after"}]
    path = tmp_path / "tour.json"
    path.write_text(json.dumps(steps))

    assert load_tour_steps(json.dumps(steps)) == steps
    assert load_tour_steps(str(path)) == steps
    assert load_tour_steps(json.dumps({"steps": steps})) == steps


@pytest.mark.parametrize("bad", ['[{"tap": 3}]', '[{"jump": "x"}]', '[{"wait": -1}]', '{"nope": 1}', "missing.json"])
def test_load_tour_steps_rejects_malformed_tours(bad: str, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(TourError):
        load_tour_steps(bad)


def test_without_the_env_var_the_app_runs_no_tour(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(TOUR_ENV, raising=False)
    monkeypatch.setenv(TOUR_DIR_ENV, str(tmp_path / "status"))
    ctx = _FakeCtx(100, 200)
    app = FigmaApp(FigmaDocument.from_dict(two_screen_file()))
    app.init(ctx)
    for _ in range(5):
        app.loop(ctx, 0.05)

    assert app.current_frame_id == "1:1"
    assert not (tmp_path / "status").exists()


def test_tour_taps_layers_and_pauses_for_each_capture_until_acked(tmp_path: Path, monkeypatch) -> None:
    steps = [{"capture": "home"}, {"tap": "Go Button"}, {"capture": "detail"}, {"tap": "Back"}, {"capture": "back"}]
    app, ctx, status_dir = _start(monkeypatch, tmp_path, steps)

    captures = _drive(app, ctx, status_dir)

    assert [(c["capture"], c["frame"], c["run"]) for c in captures] == [
        ("home", "Home", "run-1"),
        ("detail", "Detail", "run-1"),
        ("back", "Home", "run-1"),
    ]
    assert captures[1]["pixel"] == (0, 0, 255, 255)
    assert _status(status_dir)["state"] == "done"


def test_tour_waits_for_the_host_before_moving_past_a_capture(tmp_path: Path, monkeypatch) -> None:
    app, ctx, status_dir = _start(monkeypatch, tmp_path, [{"capture": "home"}, {"tap": "Go Button"}])

    captures = _drive(app, ctx, status_dir, ack=False, max_ticks=20)

    assert len(captures) == 1
    assert app.current_frame_id == "1:1"
    assert _status(status_dir)["state"] == "capture"


def test_unacked_capture_times_out_and_the_tour_continues(tmp_path: Path, monkeypatch) -> None:
    app, ctx, status_dir = _start(
        monkeypatch, tmp_path, [{"capture": "home"}, {"tap": "Go Button"}], LUVATRIX_FIGMA_TOUR_ACK_TIMEOUT="0.2"
    )

    _drive(app, ctx, status_dir, ack=False, max_ticks=40)

    assert app.current_frame_id == "2:1"
    status = _status(status_dir)
    assert status["state"] == "done"
    assert status["timed_out"] == ["home"]


def test_tour_scrolls_offscreen_targets_into_view_before_tapping(tmp_path: Path, monkeypatch) -> None:
    app, ctx, status_dir = _start(monkeypatch, tmp_path, [{"tap": "Deep Link"}, {"capture": "other"}], data=scrolling_file())

    captures = _drive(app, ctx, status_dir)

    assert app.current_frame_id == "5:1"
    assert captures[0]["frame"] == "Other"


def test_tour_scroll_step_moves_the_feed(tmp_path: Path, monkeypatch) -> None:
    app, ctx, status_dir = _start(monkeypatch, tmp_path, [{"scroll": 120}, {"capture": "scrolled"}], data=scrolling_file())

    _drive(app, ctx, status_dir)

    assert app.scroll_y == pytest.approx(120)


def test_tour_reports_an_unknown_tap_target_as_an_error(tmp_path: Path, monkeypatch) -> None:
    app, ctx, status_dir = _start(monkeypatch, tmp_path, [{"tap": "Nope"}, {"capture": "never"}])

    captures = _drive(app, ctx, status_dir)

    status = _status(status_dir)
    assert captures == []
    assert status["state"] == "error"
    assert "Nope" in status["error"]


def test_tour_cannot_tap_hidden_layers(tmp_path: Path, monkeypatch) -> None:
    app, ctx, status_dir = _start(monkeypatch, tmp_path, [{"tap": "Hidden"}, {"tap": "Go Button"}])

    _drive(app, ctx, status_dir)

    assert _status(status_dir)["state"] == "error"
    assert app.current_frame_id == "1:1"


def test_tour_taps_run_code_handlers(tmp_path: Path, monkeypatch) -> None:
    app, ctx, status_dir = _start(monkeypatch, tmp_path, [{"tap": "Go Button"}])
    tapped: list[str] = []
    app.on_tap("Go Button", lambda _app, name: tapped.append(name) or False)

    _drive(app, ctx, status_dir)

    assert tapped == ["Go Button"]
    assert app.current_frame_id == "1:1"
    assert _status(status_dir)["state"] == "done"


def test_tap_api_follows_the_prototype_link(tmp_path: Path) -> None:
    ctx = _FakeCtx(100, 200, display=(50, 100))
    app = FigmaApp(FigmaDocument.from_dict(two_screen_file()))
    app.init(ctx)
    app.loop(ctx, 0.05)

    app.tap("Go Button")

    assert app.current_frame_id == "2:1"
