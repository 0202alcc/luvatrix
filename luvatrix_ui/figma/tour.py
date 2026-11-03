"""Scripted prototype tours, so a host can drive and screenshot a running Figma app.

A tour is a JSON list of steps, given inline or as a file path in
``LUVATRIX_FIGMA_TOUR``:

    {"tap": "Layer Name"}   tap a layer (scrolled into view first if needed)
    {"scroll": 120}         scroll the current frame by design units
    {"wait": 0.5}           let time pass
    {"capture": "home"}     pause until the host screenshots the screen

At each capture the app writes ``status.json`` into ``LUVATRIX_FIGMA_TOUR_DIR``
(default ``<tempdir>/luvatrix_tour``) and waits for the host to create
``ack_<step>``, or for ``LUVATRIX_FIGMA_TOUR_ACK_TIMEOUT`` seconds. The final
status is ``done`` or ``error``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app import FigmaApp

TOUR_ENV = "LUVATRIX_FIGMA_TOUR"
TOUR_DIR_ENV = "LUVATRIX_FIGMA_TOUR_DIR"
TOUR_RUN_ENV = "LUVATRIX_FIGMA_TOUR_RUN"
TOUR_ACK_TIMEOUT_ENV = "LUVATRIX_FIGMA_TOUR_ACK_TIMEOUT"
DEFAULT_ACK_TIMEOUT = 30.0
STATUS_FILE = "status.json"


class TourError(ValueError):
    pass


def default_status_dir() -> Path:
    return Path(tempfile.gettempdir()) / "luvatrix_tour"


def load_tour_steps(spec: str) -> list[dict[str, Any]]:
    """Parse a tour given as inline JSON or as a path to a JSON file."""
    text = spec.strip()
    if not text.startswith(("[", "{")):
        try:
            text = Path(text).read_text()
        except OSError as exc:
            raise TourError(f"cannot read tour file {spec!r}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TourError(f"tour is not valid JSON: {exc}") from exc
    if isinstance(data, dict):
        if "steps" not in data:
            raise TourError("tour object needs a 'steps' list")
        data = data["steps"]
    if not isinstance(data, list):
        raise TourError("tour must be a list of steps")
    for index, step in enumerate(data):
        _validate_step(index, step)
    return data


def _validate_step(index: int, step: Any) -> None:
    if not isinstance(step, dict) or len(step) != 1:
        raise TourError(f"step {index} must be an object with exactly one key")
    (kind, value), = step.items()
    if kind in {"tap", "capture"}:
        ok = isinstance(value, str) and bool(value)
    elif kind == "scroll":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif kind == "wait":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    else:
        raise TourError(f"step {index} has unknown kind {kind!r}")
    if not ok:
        raise TourError(f"step {index} has an invalid {kind!r} value: {value!r}")


class Tour:
    """Runs tour steps from FigmaApp.update, one per tick once the screen is idle."""

    def __init__(
        self,
        steps: list[dict[str, Any]],
        status_dir: Path,
        *,
        run_id: str = "",
        ack_timeout: float = DEFAULT_ACK_TIMEOUT,
    ) -> None:
        self.steps = steps
        self.status_dir = Path(status_dir)
        self.run_id = run_id
        self.ack_timeout = ack_timeout
        self.index = 0
        self.finished = False
        self.timed_out: list[str] = []
        self._waited = 0.0
        self._waiting_ack = False

    @classmethod
    def from_env(cls, environ: Any = None) -> Tour | None:
        env = os.environ if environ is None else environ
        spec = env.get(TOUR_ENV)
        if not spec:
            return None
        status_dir = Path(env[TOUR_DIR_ENV]) if env.get(TOUR_DIR_ENV) else default_status_dir()
        tour = cls(
            [],
            status_dir,
            run_id=env.get(TOUR_RUN_ENV, ""),
            ack_timeout=float(env.get(TOUR_ACK_TIMEOUT_ENV) or DEFAULT_ACK_TIMEOUT),
        )
        status_dir.mkdir(parents=True, exist_ok=True)
        for stale in status_dir.glob("ack_*"):
            stale.unlink()
        print(f"[figma-tour] run={tour.run_id} status_dir={status_dir}", flush=True)
        try:
            tour.steps = load_tour_steps(spec)
        except TourError as exc:
            tour._fail(str(exc), frame="")
        return tour

    def tick(self, app: FigmaApp, dt: float) -> None:
        if self.finished or app.busy:
            return
        if self.index >= len(self.steps):
            self._write("done", frame=app.current_frame_name)
            self.finished = True
            print("[figma-tour] done", flush=True)
            return
        (kind, value), = self.steps[self.index].items()
        if kind == "capture":
            self._capture(app, str(value), dt)
            return
        if kind == "wait":
            self._waited += dt
            if self._waited < float(value):
                return
        elif kind == "scroll":
            app.scroll_by(float(value))
        elif kind == "tap":
            try:
                app.tap(str(value))
            except KeyError:
                self._fail(f"no tappable layer named {value!r} on frame {app.current_frame_name!r}", app.current_frame_name)
                return
        print(f"[figma-tour] step {self.index}: {kind} {value}", flush=True)
        self._advance()

    def _capture(self, app: FigmaApp, name: str, dt: float) -> None:
        if not self._waiting_ack:
            self._waiting_ack = True
            self._waited = 0.0
            self._write("capture", frame=app.current_frame_name, capture=name)
            print(f"[figma-tour] step {self.index}: capture {name} ({app.current_frame_name})", flush=True)
            return
        if (self.status_dir / f"ack_{self.index}").exists():
            self._advance()
            return
        self._waited += dt
        if self._waited >= self.ack_timeout:
            print(f"[figma-tour] capture {name} was not acknowledged; continuing", flush=True)
            self.timed_out.append(name)
            self._advance()

    def _advance(self) -> None:
        self.index += 1
        self._waited = 0.0
        self._waiting_ack = False

    def _fail(self, message: str, frame: str) -> None:
        self.finished = True
        self._write("error", frame=frame, error=message)
        print(f"[figma-tour] error: {message}", flush=True)

    def _write(self, state: str, **fields: Any) -> None:
        status = {"run": self.run_id, "step": self.index, "state": state, "timed_out": self.timed_out, **fields}
        self.status_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.status_dir / f".{STATUS_FILE}.tmp"
        tmp.write_text(json.dumps(status))
        os.replace(tmp, self.status_dir / STATUS_FILE)
