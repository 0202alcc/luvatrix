import { createInputAdapter } from "./input.js?v=procedural-floor-20260603";
import { createRenderer } from "./renderers.js?v=procedural-floor-20260603";
import "./spotify-bridge.js?v=spotify-island-20260526";

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";

async function main() {
  const canvas = document.getElementById("stage");
  const canvas3d = document.getElementById("stage3d");
  const status = document.getElementById("status");
  const cacheKey = Date.now().toString(36);
  const manifest = await fetch(cacheBust("./app_manifest.json", cacheKey), { cache: "no-store" }).then((r) => r.json());
  document.title = manifest.web?.title || manifest.display?.title || manifest.app_id || "Luvatrix";
  const viewport = displayViewportSize();
  const width = viewport.width || manifest.display?.native_width || 1080;
  const height = viewport.height || manifest.display?.native_height || 2400;
  canvas.width = width;
  canvas.height = height;
  if (canvas3d) {
    canvas3d.width = width;
    canvas3d.height = height;
  }

  const input = createInputAdapter(canvas);
  const renderer = await createRenderer(canvas, status, { webglCanvas: canvas3d });
  const pyodide = await loadPyodideRuntime(manifest, status);

  const entrypoint = manifest.entrypoint;
  pyodide.globals.set("luvatrix_input_snapshot", () => input.snapshot());
  pyodide.globals.set("luvatrix_display_size", [width, height]);
  pyodide.globals.set("luvatrix_manifest_json", JSON.stringify(manifest));
  pyodide.runPython(`
import importlib, json, sys
sys.path.insert(0, "/home/pyodide/app")
sys.path.insert(0, "/home/pyodide/py")
module_name, symbol_name = ${JSON.stringify(entrypoint)}.split(":", 1)
_luvatrix_app = getattr(importlib.import_module(module_name), symbol_name)()
_luvatrix_app.init_browser(
    width=${JSON.stringify(width)},
    height=${JSON.stringify(height)},
    input_provider=luvatrix_input_snapshot,
    manifest=json.loads(luvatrix_manifest_json),
)
`);

  let last = performance.now();
  function tick(now) {
    const dt = Math.max(0, (now - last) / 1000);
    last = now;
    const frame = pyodide.runPython(`_luvatrix_app.loop_browser(${JSON.stringify(dt)})`);
    renderer.render(toCommandBuffer(frame));
    input.endFrame();
    requestAnimationFrame(tick);
  }
  if (status) {
    status.textContent = `${status.textContent || "Renderer"} | browser-side runtime`;
    status.dataset.ready = "true";
  }
  requestAnimationFrame(tick);
}

function displayViewportSize() {
  const source = globalThis.visualViewport || globalThis;
  return {
    width: Math.max(1, Math.round(Number(source.innerWidth || source.width || 0))),
    height: Math.max(1, Math.round(Number(source.innerHeight || source.height || 0))),
  };
}

async function loadPyodideRuntime(manifest, status) {
  status && (status.textContent = "Loading Pyodide...");
  await import(PYODIDE_URL);
  const pyodide = await globalThis.loadPyodide();
  const packages = manifest.web?.pyodide_packages || [];
  if (packages.length) {
    await pyodide.loadPackage(packages);
  }
  await pyodide.FS.mkdirTree("/home/pyodide/py");
  await pyodide.FS.mkdirTree("/home/pyodide/app");
  const cacheKey = Date.now().toString(36);
  await copyTree(pyodide, "./py_manifest.json", "/home/pyodide/py", cacheKey);
  await copyAppFiles(pyodide, manifest, cacheKey);
  status && (status.textContent = "Starting app...");
  return pyodide;
}

async function copyTree(pyodide, manifestUrl, destRoot, cacheKey) {
  const files = await fetch(cacheBust(manifestUrl, cacheKey), { cache: "no-store" }).then((r) => r.json());
  for (const file of files) {
    const data = await fetch(cacheBust(file.url, cacheKey), { cache: "no-store" }).then((r) => r.arrayBuffer());
    const target = `${destRoot}/${file.path}`;
    ensureDir(pyodide, target.split("/").slice(0, -1).join("/"));
    pyodide.FS.writeFile(target, new Uint8Array(data));
  }
}

async function copyAppFiles(pyodide, manifest, cacheKey) {
  await copyTree(pyodide, "./app_files.json", "/home/pyodide/app", cacheKey);
}

function cacheBust(url, key) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}v=${encodeURIComponent(key)}`;
}

function ensureDir(pyodide, dir) {
  const parts = dir.split("/").filter(Boolean);
  let current = "";
  for (const part of parts) {
    current += `/${part}`;
    try {
      pyodide.FS.mkdir(current);
    } catch {}
  }
}

function toCommandBuffer(proxy) {
  const object = proxy.toJs ? proxy.toJs({ dict_converter: Object.fromEntries }) : proxy;
  proxy.destroy?.();
  return {
    headers: new Uint32Array(object.headers || []),
    floats: new Float32Array(object.floats || []),
    strings: object.strings || [],
    width: object.width || 1,
    height: object.height || 1,
  };
}

main().catch((error) => {
  console.error(error);
  const status = document.getElementById("status");
  if (status) {
    status.textContent = `Luvatrix web runtime error: ${error.message || error}`;
    status.dataset.error = "true";
  }
});
