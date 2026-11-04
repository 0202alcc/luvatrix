from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tomllib

from luvatrix.app import validate_app_install
from luvatrix_core.core.app_runtime import AppRuntime
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_ui.figma import FigmaDocument

from test_figma_app import _FakeCtx, _tap

APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "figma_app"
DESIGN = APP_DIR / "design" / "figma_file.json"


def _load_app_main():
    spec = importlib.util.spec_from_file_location("figma_app_main", APP_DIR / "app_main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


def _center(doc: FigmaDocument, frame_name: str, node_name: str) -> tuple[float, float]:
    spot = next(s for s in doc.targets(doc.frame_by_name(frame_name).id, frozenset({node_name})) if s.node_name == node_name)
    return spot.x + spot.width / 2, spot.y + spot.height / 2


def test_manifest_targets_ios_and_macos_with_touch_input() -> None:
    manifest = tomllib.loads((APP_DIR / "app.toml").read_text(encoding="utf-8"))

    assert manifest["platform_support"] == ["ios", "macos"]
    assert manifest["entrypoint"] == "app_main:create"
    assert "hdi.touch" in manifest["optional_capabilities"]


def test_validates_for_ios_simulator_and_device() -> None:
    for render in ("ios-simulator", "ios-device"):
        assert validate_app_install(APP_DIR, render=render).ok


def test_design_covers_every_prototype_feature_starting_at_welcome() -> None:
    doc = FigmaDocument.load(DESIGN)

    assert [f.name for f in doc.frames] == ["Welcome", "Home", "Plant Detail", "Profile", "Water Sheet", "Gallery"]
    assert doc.frame(doc.start_frame_id).name == "Welcome"
    assert doc.frame_by_name("Home").scrolls_vertically
    assert doc.frame_by_name("Gallery").scrolls_horizontally
    assert any(p.suffix == ".png" for p in (DESIGN.parent / "images").iterdir())


def test_runtime_renders_the_welcome_screen_as_ios() -> None:
    matrix = WindowMatrix(852, 393)
    runtime = AppRuntime(
        matrix=matrix,
        hdi=HDIThread(source=_NoopHDISource()),
        sensor_manager=SensorManagerThread(providers={}),
        host_os="ios",
    )

    runtime.run(APP_DIR, max_ticks=1, target_fps=1000)

    snap = matrix.read_snapshot()
    button = tuple(int(v) for v in snap[741, 60])
    assert button[0] < 40 and button[1] < 50
    assert int(snap[400, 196, 1]) > 200


def test_tapping_through_the_prototype() -> None:
    app = _load_app_main().create()
    doc = app.document
    ctx = _FakeCtx(393, 852)
    app.init(ctx)
    app.loop(ctx, 0.016)

    for frame, node, expected in (
        ("Welcome", "Get Started", "Home"),
        ("Home", "Card Monstera", "Plant Detail"),
        ("Plant Detail", "Back Button", "Home"),
        ("Home", "Tab Profile", "Profile"),
        ("Profile", "Tab Home", "Home"),
    ):
        _tap(ctx, *_center(doc, frame, node))
        for _ in range(40):
            app.loop(ctx, 0.05)
        assert app.current_frame_name == expected, (frame, node)


def test_water_now_binding_updates_the_label() -> None:
    app = _load_app_main().create()
    ctx = _FakeCtx(393, 852)
    app.init(ctx)
    app.navigate("Plant Detail")
    app.loop(ctx, 0.016)
    before = ctx.frames[-1].copy()

    _tap(ctx, *_center(app.document, "Plant Detail", "Water Now"))
    app.loop(ctx, 0.016)

    assert app.current_frame_name == "Plant Detail"
    assert app.text("Water Label") == "Watered today"
    assert (ctx.frames[-1] != before).any()


def test_example_tour_visits_every_screen_and_waters_the_plant(tmp_path: Path, monkeypatch) -> None:
    import json

    from luvatrix_ui.figma.tour import TOUR_DIR_ENV, TOUR_ENV

    status_dir = tmp_path / "status"
    monkeypatch.setenv(TOUR_ENV, str(APP_DIR / "tour.json"))
    monkeypatch.setenv(TOUR_DIR_ENV, str(status_dir))
    ctx = _FakeCtx(393 * 2, 852 * 2, display=(393, 852))
    app = _load_app_main().create()
    app.init(ctx)

    captures: list[tuple[str, str]] = []
    for _ in range(2000):
        app.loop(ctx, 0.05)
        status_path = status_dir / "status.json"
        if not status_path.exists():
            continue
        status = json.loads(status_path.read_text())
        if status["state"] == "capture" and not (status_dir / f"ack_{status['step']}").exists():
            captures.append((status["capture"], status["frame"]))
            (status_dir / f"ack_{status['step']}").write_text("ok")
        if status["state"] in {"done", "error"}:
            break

    assert status["state"] == "done", status
    assert [frame for _, frame in captures] == [
        "Welcome",
        "Home",
        "Home",
        "Plant Detail",
        "Plant Detail",
        "Plant Detail",
        "Home",
        "Home",
        "Home",
        "Gallery",
        "Profile",
    ]
    assert app.text("Water Label") == "Watered today"
