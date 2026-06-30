from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile

from .build import build_web_app


def serve_web_app(app_dir: str | Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    with tempfile.TemporaryDirectory(prefix="luvatrix_web_") as tmp:
        result = build_web_app(app_dir, tmp)
        handler = partial(SimpleHTTPRequestHandler, directory=str(result.out_dir))
        server = ThreadingHTTPServer((host, int(port)), handler)
        print(f"[luvatrix] Browser-side web app ready at http://{host}:{int(port)}")
        print("[luvatrix] Serving static files only; app loop and rendering run in the browser.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
