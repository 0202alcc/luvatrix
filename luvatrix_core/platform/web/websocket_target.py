from __future__ import annotations

import asyncio
import http
import io
import threading
from typing import Callable

from luvatrix_core.targets.base import DisplayFrame, RenderTarget

_CLIENT_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <title>Luvatrix</title>
  <style>
    body { margin: 0; background: #000; display: flex; justify-content: center; align-items: center; height: 100vh; overflow: hidden; }
    canvas { max-width: 100%; max-height: 100vh; image-rendering: pixelated; }
  </style>
</head>
<body>
<canvas id="c"></canvas>
<script>
  const canvas = document.getElementById('c');
  const ctx = canvas.getContext('2d');

  function connect() {
    const ws = new WebSocket(`ws://${window.location.hostname}:{port}`);
    ws.binaryType = 'blob';
    ws.onmessage = async (e) => {
      const bmp = await createImageBitmap(e.data);
      if (canvas.width !== bmp.width || canvas.height !== bmp.height) {
        canvas.width = bmp.width;
        canvas.height = bmp.height;
      }
      ctx.drawImage(bmp, 0, 0);
    };
    ws.onclose = () => setTimeout(connect, 1000);
    ws.onerror = () => ws.close();
  }

  connect();
</script>
</body>
</html>
"""


class _SingleClientTarget(RenderTarget):
    """RenderTarget for one WebSocket connection. Thread-safe: present_frame() may
    be called from any thread; WS sends are scheduled onto the asyncio event loop."""

    def __init__(self, websocket, loop: asyncio.AbstractEventLoop) -> None:
        self._ws = websocket
        self._loop = loop
        self._closed = threading.Event()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self._closed.set()

    def should_close(self) -> bool:
        return self._closed.is_set()

    def mark_closed(self) -> None:
        self._closed.set()

    def present_frame(self, frame: DisplayFrame) -> None:
        from PIL import Image
        img = Image.fromarray(frame.rgba.numpy(), "RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        asyncio.run_coroutine_threadsafe(self._ws.send(buf.getvalue()), self._loop)


class WebSessionServer:
    """Accepts WebSocket connections and spawns an independent app session per client.

    session_factory receives a _SingleClientTarget and must block until the session
    is complete (i.e. call runtime.run_app() synchronously). It is called in a
    daemon thread per connection.
    """

    def __init__(
        self,
        session_factory: Callable[[_SingleClientTarget], None],
        host: str = "0.0.0.0",
        port: int = 8765,
    ) -> None:
        self._session_factory = session_factory
        self._host = host
        self._port = port

    def run(self) -> None:
        asyncio.run(self._serve())

    async def _serve(self) -> None:
        import websockets

        html_bytes = _CLIENT_HTML.replace("{port}", str(self._port)).encode()

        async def process_request(path, headers):
            if headers.get("Upgrade", "").lower() != "websocket":
                return (
                    http.HTTPStatus.OK,
                    [("Content-Type", "text/html; charset=utf-8")],
                    html_bytes,
                )

        async with websockets.serve(
            self._handle_connection, self._host, self._port,
            process_request=process_request,
        ):
            await asyncio.Future()

    async def _handle_connection(self, websocket, path="") -> None:
        loop = asyncio.get_running_loop()
        target = _SingleClientTarget(websocket, loop)
        thread = threading.Thread(
            target=self._session_factory, args=(target,), daemon=True,
        )
        thread.start()
        try:
            await websocket.wait_closed()
        finally:
            target.mark_closed()
            thread.join(timeout=5)
