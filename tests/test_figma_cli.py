from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

from PIL import Image
import pytest

from luvatrix.app import validate_app_install
from luvatrix_ui.figma import FigmaDocument
from luvatrix_ui.figma.cli import FigmaApiError, init_figma_app, parse_figma_link, pull_design, render_design

from figma_fixtures import two_screen_file


class _Response(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200) -> None:
        super().__init__(body)
        self.status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _png_bytes(color=(0, 0, 255, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeFigma:
    def __init__(self, file_payload: dict) -> None:
        self.file_payload = file_payload
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, request, timeout: float = 0):
        url = request.full_url
        self.requests.append((url, dict(request.header_items())))
        if "/images" in url and "api.figma.com" in url:
            return _Response(json.dumps({"meta": {"images": {"ref1": "https://cdn.example/ref1"}}}).encode())
        if url.startswith("https://cdn.example/"):
            return _Response(_png_bytes())
        return _Response(json.dumps(self.file_payload).encode())


def _with_image_fill() -> dict:
    data = two_screen_file()
    home = data["document"]["children"][0]["children"][1]
    home["children"][0]["fills"] = [{"type": "IMAGE", "imageRef": "ref1", "scaleMode": "FILL"}]
    return data


@pytest.mark.parametrize(
    ("link", "key", "ids"),
    [
        ("AbC123", "AbC123", None),
        ("https://www.figma.com/design/AbC123/My-App?node-id=12-34&t=x", "AbC123", ["12:34"]),
        ("https://www.figma.com/file/AbC123/My-App", "AbC123", None),
        ("https://www.figma.com/proto/AbC123/My-App?node-id=1-2", "AbC123", ["1:2"]),
    ],
)
def test_parse_figma_link(link: str, key: str, ids) -> None:
    assert parse_figma_link(link) == (key, ids)


def test_pull_saves_the_file_with_geometry_and_image_fills(tmp_path: Path) -> None:
    fake = _FakeFigma(_with_image_fill())

    path = pull_design("AbC123", tmp_path, token="secret", opener=fake)

    assert path == tmp_path / "figma_file.json"
    file_url, headers = fake.requests[0]
    assert file_url.startswith("https://api.figma.com/v1/files/AbC123?")
    assert "geometry=paths" in file_url
    assert headers.get("X-figma-token") == "secret"
    assert (tmp_path / "images" / "ref1.png").is_file()
    doc = FigmaDocument.load(path)
    assert doc.image_path("ref1") == tmp_path / "images" / "ref1.png"


def test_pull_with_node_ids_uses_the_nodes_endpoint(tmp_path: Path) -> None:
    home = two_screen_file()["document"]["children"][0]["children"][1]
    fake = _FakeFigma({"name": "N", "nodes": {"1:1": {"document": home}}})

    pull_design("AbC123", tmp_path, token="t", node_ids=["1:1"], opener=fake)

    assert "/v1/files/AbC123/nodes?" in fake.requests[0][0]
    assert "ids=1%3A1" in fake.requests[0][0]


def test_pull_requires_a_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)

    with pytest.raises(FigmaApiError, match="FIGMA_TOKEN"):
        pull_design("AbC123", tmp_path, token=None, opener=_FakeFigma({}))


def test_render_design_writes_one_png_per_frame(tmp_path: Path) -> None:
    design = tmp_path / "figma_file.json"
    design.write_text(json.dumps(two_screen_file()), encoding="utf-8")

    written = render_design(design, tmp_path / "out", scale=2.0)

    assert sorted(p.name for p in written) == ["Detail.png", "Home.png"]
    with Image.open(tmp_path / "out" / "Home.png") as img:
        assert img.size == (200, 400)


def test_render_design_can_pick_one_frame(tmp_path: Path) -> None:
    design = tmp_path / "figma_file.json"
    design.write_text(json.dumps(two_screen_file()), encoding="utf-8")

    written = render_design(design, tmp_path / "out", frame="Detail")

    assert [p.name for p in written] == ["Detail.png"]


def test_init_figma_app_creates_a_runnable_ios_app(tmp_path: Path) -> None:
    app_dir = tmp_path / "my_app"

    init_figma_app(app_dir, app_id="demo.figma")

    assert (app_dir / "design").is_dir()
    assert validate_app_install(app_dir, render="ios-simulator").ok
    (app_dir / "design" / "figma_file.json").write_text(json.dumps(two_screen_file()), encoding="utf-8")
    sys.path.insert(0, str(app_dir))
    try:
        import app_main  # type: ignore[import-not-found]

        assert app_main.create().current_frame_id == "1:1"
    finally:
        sys.path.remove(str(app_dir))
        sys.modules.pop("app_main", None)


def test_main_cli_figma_render(tmp_path: Path) -> None:
    from main import main

    design = tmp_path / "figma_file.json"
    design.write_text(json.dumps(two_screen_file()), encoding="utf-8")
    argv = ["luvatrix", "figma", "render", str(design), "--out", str(tmp_path / "png"), "--frame", "Home"]

    with patch.object(sys, "argv", argv):
        main()

    assert (tmp_path / "png" / "Home.png").is_file()


def test_main_cli_figma_ios_tour_passes_options_and_exits_with_the_tour_result(tmp_path: Path) -> None:
    from main import main

    tour = tmp_path / "tour.json"
    tour.write_text('[{"capture": "start"}]', encoding="utf-8")
    argv = [
        "luvatrix", "figma", "ios-tour", "examples/figma_app",
        "--tour", str(tour), "--out", str(tmp_path / "shots"),
        "--simulator", "iPhone 17", "--native-project", "examples/figma_app/ios",
        "--render-scale", "2", "--timeout", "120",
    ]

    with patch.object(sys, "argv", argv), patch("luvatrix_ui.figma.ios_tour.run_ios_tour", return_value=1) as run:
        with pytest.raises(SystemExit) as exit_info:
            main()

    assert exit_info.value.code == 1
    run.assert_called_once_with(
        Path("examples/figma_app"),
        str(tour),
        tmp_path / "shots",
        simulator="iPhone 17",
        native_project=Path("examples/figma_app/ios"),
        render_scale=2.0,
        timeout=120.0,
        keep_open=False,
        reset_simulator=False,
    )


def test_main_cli_figma_ios_tour_forwards_keep_open(tmp_path: Path) -> None:
    from main import main

    tour = tmp_path / "tour.json"
    tour.write_text('[{"capture": "start"}]', encoding="utf-8")
    argv = [
        "luvatrix", "figma", "ios-tour", "examples/nomic_app",
        "--tour", str(tour), "--out", str(tmp_path / "shots"),
        "--keep-open",
    ]

    with patch.object(sys, "argv", argv), patch("luvatrix_ui.figma.ios_tour.run_ios_tour", return_value=0) as run:
        with pytest.raises(SystemExit) as exit_info:
            main()

    assert exit_info.value.code == 0
    assert run.call_args.kwargs["keep_open"] is True


def test_main_cli_figma_ios_tour_forwards_reset_simulator(tmp_path: Path) -> None:
    from main import main

    tour = tmp_path / "tour.json"
    tour.write_text('[{"capture": "start"}]', encoding="utf-8")
    argv = [
        "luvatrix", "figma", "ios-tour", "examples/nomic_app",
        "--tour", str(tour), "--out", str(tmp_path / "shots"),
        "--reset-simulator",
    ]

    with patch.object(sys, "argv", argv), patch("luvatrix_ui.figma.ios_tour.run_ios_tour", return_value=0) as run:
        with pytest.raises(SystemExit) as exit_info:
            main()

    assert exit_info.value.code == 0
    assert run.call_args.kwargs["reset_simulator"] is True
