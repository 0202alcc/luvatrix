from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
import io
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

API = "https://api.figma.com/v1"
Opener = Callable[..., Any]

APP_TOML = """app_id = "{app_id}"
protocol_version = "3"
entrypoint = "app_main:create"
platform_support = ["ios", "macos"]
required_capabilities = ["window.write"]
optional_capabilities = ["hdi.touch", "hdi.mouse", "hdi.trackpad"]

[display]
native_width = {width}
native_height = {height}
bar_color_rgba = [0, 0, 0, 255]
default_coordinate_frame = "screen_tl"
title = "{title}"

[render]
preferred = "matrix"
fallbacks = ["matrix"]
"""

APP_MAIN = '''from __future__ import annotations

from pathlib import Path

from luvatrix_ui.figma import FigmaApp

DESIGN = Path(__file__).resolve().parent / "design" / "figma_file.json"


def create() -> FigmaApp:
    return FigmaApp(DESIGN)
'''


class FigmaApiError(RuntimeError):
    pass


def parse_figma_link(link: str) -> tuple[str, list[str] | None]:
    """Return (file_key, node_ids) from a Figma URL or a bare file key."""
    if "://" not in link:
        return link.strip(), None
    parsed = urlparse(link)
    match = re.search(r"/(?:file|design|proto|board)/([A-Za-z0-9]+)", parsed.path)
    if match is None:
        raise FigmaApiError(f"not a Figma file link: {link}")
    node = parse_qs(parsed.query).get("node-id")
    ids = [node[0].replace("-", ":")] if node else None
    return match.group(1), ids


def _get(url: str, token: str | None, opener: Opener | None) -> bytes:
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    opener = opener or urlopen
    headers = {"X-Figma-Token": token} if token else {}
    try:
        with opener(Request(url, headers=headers), timeout=60) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise FigmaApiError(f"Figma API {exc.code} for {url}: {detail}") from exc
    except URLError as exc:
        raise FigmaApiError(f"could not reach {url}: {exc.reason}") from exc


def _image_refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key in ("fills", "strokes", "background"):
            for paint in node.get(key) or ():
                if isinstance(paint, dict) and paint.get("type") == "IMAGE" and paint.get("imageRef"):
                    yield str(paint["imageRef"])
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _image_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _image_refs(item)


def pull_design(
    file_key: str,
    out_dir: str | Path,
    *,
    token: str | None = None,
    node_ids: Iterable[str] | None = None,
    opener: Opener | None = None,
) -> Path:
    """Download a Figma file (or nodes) with vector geometry plus its image fills."""
    token = token or os.environ.get("FIGMA_TOKEN")
    if not token:
        raise FigmaApiError("set FIGMA_TOKEN (a Figma personal access token) or pass --token")
    out = Path(out_dir)
    ids = list(node_ids or ())
    if ids:
        url = f"{API}/files/{file_key}/nodes?" + urlencode({"ids": ",".join(ids), "geometry": "paths"})
    else:
        url = f"{API}/files/{file_key}?" + urlencode({"geometry": "paths"})
    payload = json.loads(_get(url, token, opener))
    if payload.get("err") or payload.get("status", 200) >= 400:
        raise FigmaApiError(f"Figma API error: {payload.get('err') or payload}")
    refs = sorted(set(_image_refs(payload)))
    if refs:
        images = json.loads(_get(f"{API}/files/{file_key}/images", token, opener))
        urls = (images.get("meta") or {}).get("images") or {}
        (out / "images").mkdir(parents=True, exist_ok=True)
        for ref in refs:
            if urls.get(ref):
                _save_image(_get(urls[ref], None, opener), out / "images", ref)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "figma_file.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _save_image(data: bytes, directory: Path, ref: str) -> Path:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            ext = {"JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif"}.get(str(img.format), ".png")
    except OSError:
        ext = ".png"
    path = directory / f"{ref}{ext}"
    path.write_bytes(data)
    return path


def render_design(design: str | Path, out_dir: str | Path, *, frame: str | None = None, scale: float = 2.0) -> list[Path]:
    """Render frames of a saved Figma export to PNG files named after each frame."""
    from PIL import Image

    from .document import FigmaDocument
    from .render import FigmaRenderer

    doc = FigmaDocument.load(design)
    renderer = FigmaRenderer(doc)
    frames = [doc.find_frame(frame)] if frame else doc.frames
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for target in frames:
        safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", target.name).strip() or target.id.replace(":", "-")
        path = out / f"{safe}.png"
        Image.fromarray(renderer.render(target.id, scale)).save(path)
        written.append(path)
    return written


def init_figma_app(app_dir: str | Path, *, app_id: str | None = None, width: int = 393, height: int = 852) -> Path:
    """Create a Luvatrix app folder that runs `design/figma_file.json` as a prototype."""
    root = Path(app_dir)
    if (root / "app.toml").exists():
        raise FileExistsError(f"{root / 'app.toml'} already exists")
    (root / "design").mkdir(parents=True, exist_ok=True)
    title = root.name.replace("_", " ").title()
    (root / "app.toml").write_text(
        APP_TOML.format(app_id=app_id or f"figma.{root.name}", width=width, height=height, title=title), encoding="utf-8"
    )
    (root / "app_main.py").write_text(APP_MAIN, encoding="utf-8")
    return root


def add_figma_parser(subparsers: Any) -> None:
    figma = subparsers.add_parser("figma", help="Pull, preview, and scaffold Figma prototype apps")
    sub = figma.add_subparsers(dest="figma_command", required=True)

    pull = sub.add_parser("pull", help="Download a Figma file (REST API, geometry=paths) and its images")
    pull.add_argument("link", help="Figma file URL or file key")
    pull.add_argument("--out", type=Path, required=True, help="Directory for figma_file.json and images/")
    pull.add_argument("--token", default=None, help="Personal access token (defaults to $FIGMA_TOKEN)")
    pull.add_argument("--ids", default=None, help="Comma-separated node ids to fetch instead of the whole file")

    render = sub.add_parser("render", help="Render frames of a saved Figma export to PNG")
    render.add_argument("design", type=Path, help="Path to figma_file.json")
    render.add_argument("--out", type=Path, required=True, help="Output directory for PNGs")
    render.add_argument("--frame", default=None, help="Frame name or id (default: every top-level frame)")
    render.add_argument("--scale", type=float, default=2.0, help="Pixels per Figma point")

    capture = sub.add_parser("capture", help="Capture a web page with headless Chrome into figma_file.json")
    capture.add_argument("url", help="Page URL to capture")
    capture.add_argument("--out", type=Path, required=True, help="Directory for figma_file.json, images/, clickables.json, capture_report.json")
    capture.add_argument("--pages", default=None, help="Comma-separated extra paths (or URLs) captured as additional frames")
    capture.add_argument("--click-map", type=Path, default=None, help="JSON file mapping \"<page> -> <selector>\" to a target page path")
    capture.add_argument("--viewport", default="393x852@3", help="WIDTHxHEIGHT[@SCALE] device metrics (default 393x852@3x)")
    capture.add_argument("--wait", type=float, default=2.0, help="Extra seconds to wait for the page to settle")
    capture.add_argument("--selector-ready", default=None, help="CSS selector to wait for before snapshotting")
    capture.add_argument("--full-page", dest="full_page", action="store_true", default=True, help="Capture the full scrollable page (default)")
    capture.add_argument("--viewport-only", dest="full_page", action="store_false", help="Capture only the pinned viewport")
    capture.add_argument("--chrome", default=None, help="Path to a Chrome binary (default: autodetect)")
    capture.add_argument("--cookie", action="append", default=None, metavar="NAME=VALUE", help="Send this cookie with every captured page (repeatable)")
    capture.add_argument("--color-scheme", choices=("light", "dark"), default=None, help="Emulate prefers-color-scheme so themed pages render that appearance")

    init = sub.add_parser("init-app", help="Create an app folder that runs design/figma_file.json")
    init.add_argument("app_dir", type=Path)
    init.add_argument("--app-id", default=None)
    init.add_argument("--width", type=int, default=393, help="Device width in points")
    init.add_argument("--height", type=int, default=852, help="Device height in points")

    tour = sub.add_parser("ios-tour", help="Run a scripted tour in the iOS Simulator and screenshot each capture")
    tour.add_argument("app_dir", type=Path)
    tour.add_argument("--tour", required=True, help="Tour JSON file, or inline JSON")
    tour.add_argument("--out", type=Path, required=True, help="Directory for screenshots, logs, and summary.json")
    tour.add_argument("--simulator", default="iPhone 17", help="Simulator device name")
    tour.add_argument("--native-project", type=Path, default=None, help="Native iOS project (default: <app_dir>/ios)")
    tour.add_argument("--render-scale", type=float, default=3.0)
    tour.add_argument("--timeout", type=float, default=900.0, help="Seconds for build, launch, and the whole tour")
    tour.add_argument("--keep-open", action="store_true", help="After the tour, relaunch the app fresh and leave it running in the simulator")
    tour.add_argument("--reset-simulator", action="store_true", help="Shut down and erase the simulator before the tour so no previous launch's retained environment leaks into the app")


def run_figma_command(args: Any) -> None:
    if args.figma_command == "pull":
        key, link_ids = parse_figma_link(args.link)
        ids = [i.strip() for i in args.ids.split(",")] if args.ids else link_ids
        path = pull_design(key, args.out, token=args.token, node_ids=ids)
        print(f"[luvatrix] Saved Figma design to {path}")
    elif args.figma_command == "render":
        for path in render_design(args.design, args.out, frame=args.frame, scale=args.scale):
            print(f"[luvatrix] Rendered {path}")
    elif args.figma_command == "capture":
        from . import capture

        pages = [p.strip() for p in args.pages.split(",")] if args.pages else []
        result = capture.capture_design(
            args.url,
            args.out,
            pages=pages,
            click_map_path=args.click_map,
            viewport=args.viewport,
            wait=args.wait,
            selector_ready=args.selector_ready,
            full_page=args.full_page,
            chrome_path=args.chrome,
            cookies=capture._parse_cookie_args(getattr(args, "cookie", None) or []),
            color_scheme=getattr(args, "color_scheme", None),
        )
        design = capture.write_capture(result, args.out)
        page_count = len(result.report.get("pages", ()))
        print(
            f"[luvatrix] Captured {page_count} page(s) to {design} "
            f"({len(result.images)} images, {len(result.clickables)} clickables)"
        )
    elif args.figma_command == "init-app":
        root = init_figma_app(args.app_dir, app_id=args.app_id, width=args.width, height=args.height)
        print(f"[luvatrix] Created Figma app at {root}; pull a design into {root / 'design'}")
    elif args.figma_command == "ios-tour":
        from . import ios_tour

        code = ios_tour.run_ios_tour(
            args.app_dir,
            args.tour,
            args.out,
            simulator=args.simulator,
            native_project=args.native_project,
            render_scale=args.render_scale,
            timeout=args.timeout,
            keep_open=args.keep_open,
            reset_simulator=args.reset_simulator,
        )
        raise SystemExit(code)
