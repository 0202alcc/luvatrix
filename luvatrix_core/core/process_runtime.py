from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

import torch

from .app_runtime import AppContext
from .window_matrix import FullRewrite, WriteBatch


class ProcessLifecycleClient:
    """Host-side lifecycle bridge for protocol-v2 process apps over stdio JSONL."""

    def __init__(self, command: list[str], *, cwd: Path, protocol_version: str = "2") -> None:
        if not command:
            raise ValueError("process command must not be empty")
        self._command = list(command)
        self._cwd = cwd
        self._protocol_version = protocol_version
        self._proc: subprocess.Popen[str] | None = None

    def init(self, ctx: AppContext) -> None:
        self._proc = subprocess.Popen(
            self._command,
            cwd=str(self._cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self._build_process_env(),
        )
        self._send(
            {
                "type": "host.hello",
                "protocol_version": self._protocol_version,
                "matrix": {"width": ctx.matrix.width, "height": ctx.matrix.height},
                "capabilities": sorted(ctx.granted_capabilities),
            }
        )
        msg = self._recv()
        if msg.get("type") != "app.init_ok":
            raise RuntimeError(f"unexpected process init response: {msg}")

    def loop(self, ctx: AppContext, dt: float) -> None:
        self._send({"type": "host.tick", "dt": float(dt)})
        msg = self._recv()
        if msg.get("type") != "app.commands":
            raise RuntimeError(f"unexpected process tick response: {msg}")
        self._apply_commands(ctx, msg)

    def stop(self, ctx: AppContext) -> None:
        _ = ctx
        if self._proc is None:
            return
        try:
            try:
                self._send({"type": "host.stop"})
                _ = self._recv()
            except (BrokenPipeError, RuntimeError):
                pass
        finally:
            proc = self._proc
            self._proc = None
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def _apply_commands(self, ctx: AppContext, msg: dict[str, Any]) -> None:
        ops = msg.get("ops", [])
        if not isinstance(ops, list):
            raise RuntimeError("app.commands.ops must be a list")
        for op in ops:
            if not isinstance(op, dict):
                raise RuntimeError("command op must be object")
            if op.get("op") != "solid_fill":
                raise RuntimeError(f"unsupported process op: {op.get('op')}")
            rgba = op.get("rgba")
            if (
                not isinstance(rgba, list)
                or len(rgba) != 4
                or any((not isinstance(v, int) or v < 0 or v > 255) for v in rgba)
            ):
                raise RuntimeError("solid_fill.rgba must be 4 uint8 ints")
            frame = torch.zeros((ctx.matrix.height, ctx.matrix.width, 4), dtype=torch.uint8)
            frame[:, :, 0] = rgba[0]
            frame[:, :, 1] = rgba[1]
            frame[:, :, 2] = rgba[2]
            frame[:, :, 3] = rgba[3]
            ctx.submit_write_batch(WriteBatch([FullRewrite(frame)]))

    def _send(self, payload: dict[str, Any]) -> None:
        proc = self._require_proc()
        if proc.stdin is None:
            raise RuntimeError("process stdin unavailable")
        proc.stdin.write(json.dumps(payload, sort_keys=True) + "\n")
        proc.stdin.flush()

    def _recv(self) -> dict[str, Any]:
        proc = self._require_proc()
        if proc.stdout is None:
            raise RuntimeError("process stdout unavailable")
        line = proc.stdout.readline()
        if not line:
            stderr = ""
            if proc.stderr is not None:
                stderr = proc.stderr.read()
            raise RuntimeError(f"process protocol ended unexpectedly: {stderr.strip()}")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid process protocol message: {line!r}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("process message must be object")
        return payload

    def _require_proc(self) -> subprocess.Popen[str]:
        if self._proc is None:
            raise RuntimeError("process lifecycle is not initialized")
        return self._proc

    def _build_process_env(self) -> dict[str, str]:
        env = dict(os.environ)
        path_entries = []
        existing = env.get("PYTHONPATH")
        if existing:
            path_entries.extend([p for p in existing.split(os.pathsep) if p])
        repo_root = str(Path.cwd())
        if repo_root not in path_entries:
            path_entries.insert(0, repo_root)
        env["PYTHONPATH"] = os.pathsep.join(path_entries)
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env
