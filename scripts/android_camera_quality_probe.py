from __future__ import annotations

import argparse
import dataclasses
import math
from pathlib import Path
import subprocess
import time
from typing import Iterable

from PIL import Image


@dataclasses.dataclass(frozen=True)
class Rect:
    left: float
    top: float
    right: float
    bottom: float

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        x0 = max(0, min(width - 1, int(round(self.left * width))))
        y0 = max(0, min(height - 1, int(round(self.top * height))))
        x1 = max(x0 + 1, min(width, int(round(self.right * width))))
        y1 = max(y0 + 1, min(height, int(round(self.bottom * height))))
        return x0, y0, x1, y1


def _run_adb(args: list[str], *, serial: str | None = None, stdout=None) -> subprocess.CompletedProcess[bytes]:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    return subprocess.run(cmd, check=True, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE)


def _capture_png(path: Path, *, serial: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as out:
        _run_adb(["exec-out", "screencap", "-p"], serial=serial, stdout=out)


def _axis_clusters(counts: list[int], *, min_count: int, min_width: int) -> list[tuple[int, int]]:
    clusters: list[tuple[int, int]] = []
    start: int | None = None
    for idx, count in enumerate(counts):
        if count >= min_count and start is None:
            start = idx
        elif count < min_count and start is not None:
            if idx - start >= min_width:
                clusters.append((start, idx))
            start = None
    if start is not None and len(counts) - start >= min_width:
        clusters.append((start, len(counts)))
    return clusters


def _detect_button_centers(image: Image.Image) -> list[list[tuple[int, int]]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    px = rgb.load()
    mask: set[tuple[int, int]] = set()
    for y in range(height // 2, height):
        for x in range(width):
            r, g, b = px[x, y]
            if r < 35 and 80 <= g <= 180 and 85 <= b <= 190:
                mask.add((x, y))
    x_counts = [0] * width
    y_counts = [0] * height
    for x, y in mask:
        x_counts[x] += 1
        y_counts[y] += 1
    x_clusters = _axis_clusters(x_counts, min_count=max(8, height // 60), min_width=max(20, width // 40))
    y_clusters = _axis_clusters(y_counts, min_count=max(8, width // 60), min_width=max(20, height // 80))
    x_centers = [int(round((left + right) / 2.0)) for left, right in x_clusters[:4]]
    y_centers = [int(round((top + bottom) / 2.0)) for top, bottom in y_clusters[:3]]
    return [[(x, y) for x in x_centers] for y in y_centers]


def _tap_sharp_button(*, serial: str | None, screenshot: Path) -> None:
    with Image.open(screenshot) as image:
        centers = _detect_button_centers(image)
    if not centers or len(centers[0]) < 3:
        raise RuntimeError("Could not detect the camera app button grid in the screenshot")
    x, y = centers[0][2]
    _run_adb(["shell", "input", "touchscreen", "tap", str(x), str(y)], serial=serial)


def _luma_rgb(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _std(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _quality_metrics(image: Image.Image, roi: Rect, *, sample_step: int) -> dict[str, float]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    x0, y0, x1, y1 = roi.pixels(width, height)
    px = rgb.load()
    luma_values: list[float] = []
    chroma_values: list[float] = []
    luma_hp: list[float] = []
    chroma_hp: list[float] = []
    color_spread: list[float] = []
    edge_samples: list[float] = []
    step = max(1, int(sample_step))
    for y in range(y0 + step, y1 - step, step):
        for x in range(x0 + step, x1 - step, step):
            r, g, b = px[x, y]
            luma = _luma_rgb(r, g, b)
            cb = b - luma
            cr = r - luma
            chroma = math.sqrt(cb * cb + cr * cr)
            luma_values.append(luma)
            chroma_values.append(chroma)
            color_spread.append(max(r, g, b) - min(r, g, b))

            neighbors = (px[x - step, y], px[x + step, y], px[x, y - step], px[x, y + step])
            n_luma = [_luma_rgb(*neighbor) for neighbor in neighbors]
            n_chroma = []
            for nr, ng, nb in neighbors:
                nl = _luma_rgb(nr, ng, nb)
                n_chroma.append(math.sqrt((nb - nl) ** 2 + (nr - nl) ** 2))
            luma_hp.append(abs(luma - _mean(n_luma)))
            chroma_hp.append(abs(chroma - _mean(n_chroma)))
            edge_samples.append(max(n_luma) - min(n_luma))

    return {
        "roi_x0": float(x0),
        "roi_y0": float(y0),
        "roi_x1": float(x1),
        "roi_y1": float(y1),
        "samples": float(len(luma_values)),
        "luma_mean": _mean(luma_values),
        "luma_std": _std(luma_values),
        "luma_hp_mean": _mean(luma_hp),
        "chroma_mean": _mean(chroma_values),
        "chroma_std": _std(chroma_values),
        "chroma_hp_mean": _mean(chroma_hp),
        "rgb_spread_mean": _mean(color_spread),
        "edge_mean": _mean(edge_samples),
    }


def _parse_roi(value: str) -> Rect:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ROI must be left,top,right,bottom fractions")
    left, top, right, bottom = parts
    if not (0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0):
        raise argparse.ArgumentTypeError("ROI fractions must satisfy 0 <= left < right <= 1 and 0 <= top < bottom <= 1")
    return Rect(left, top, right, bottom)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture fixed-scene Android camera screenshots and score preview grain.")
    parser.add_argument("--serial", default=None, help="ADB serial. Defaults to the only connected device.")
    parser.add_argument("--out", type=Path, default=Path("artifacts/android_camera_quality"), help="Output directory.")
    parser.add_argument("--roi", type=_parse_roi, default=Rect(0.10, 0.26, 0.90, 0.68), help="ROI fractions: left,top,right,bottom.")
    parser.add_argument("--sample-step", type=int, default=4, help="Pixel step for metrics.")
    parser.add_argument("--count", type=int, default=1, help="Captures per preset/state.")
    parser.add_argument("--cycle-sharp", type=int, default=0, help="Tap the sharp button between capture groups this many times.")
    parser.add_argument("--settle", type=float, default=1.0, help="Seconds to wait after tapping sharp.")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    probe_path = args.out / "probe_000.png"
    _capture_png(probe_path, serial=args.serial)

    rows: list[tuple[str, dict[str, float]]] = []
    total_groups = max(1, args.cycle_sharp + 1)
    for group in range(total_groups):
        if group > 0:
            previous = args.out / f"group{group - 1:02d}_capture{max(0, args.count - 1):02d}.png"
            _tap_sharp_button(serial=args.serial, screenshot=previous)
            time.sleep(max(0.0, args.settle))
        for idx in range(max(1, args.count)):
            name = f"group{group:02d}_capture{idx:02d}"
            path = args.out / f"{name}.png"
            if group == 0 and idx == 0:
                probe_path.replace(path)
            else:
                _capture_png(path, serial=args.serial)
            with Image.open(path) as image:
                metrics = _quality_metrics(image, args.roi, sample_step=args.sample_step)
            rows.append((name, metrics))

    header = (
        "name,samples,luma_mean,luma_hp_mean,chroma_mean,chroma_hp_mean,"
        "rgb_spread_mean,edge_mean,roi"
    )
    print(header)
    for name, metrics in rows:
        roi_text = (
            f"{int(metrics['roi_x0'])}:{int(metrics['roi_y0'])}:"
            f"{int(metrics['roi_x1'])}:{int(metrics['roi_y1'])}"
        )
        print(
            f"{name},{metrics['samples']:.0f},{metrics['luma_mean']:.2f},"
            f"{metrics['luma_hp_mean']:.3f},{metrics['chroma_mean']:.3f},"
            f"{metrics['chroma_hp_mean']:.3f},{metrics['rgb_spread_mean']:.3f},"
            f"{metrics['edge_mean']:.3f},{roi_text}"
        )


if __name__ == "__main__":
    main()
