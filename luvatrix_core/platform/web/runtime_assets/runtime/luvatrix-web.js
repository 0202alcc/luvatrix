import { createInputAdapter } from "./input.js";
import { createRenderer } from "./renderers.js";

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";

async function main() {
  const canvas = document.getElementById("stage");
  const status = document.getElementById("status");
  const manifest = await fetch("./app_manifest.json").then((r) => r.json());
  document.title = manifest.web?.title || manifest.display?.title || manifest.app_id || "Luvatrix";
  const width = manifest.display?.native_width || 1080;
  const height = manifest.display?.native_height || 2400;
  canvas.width = width;
  canvas.height = height;

  const input = createInputAdapter(canvas);
  const renderer = await createRenderer(canvas, status);
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
  await copyTree(pyodide, "./py_manifest.json", "/home/pyodide/py");
  await copyAppFiles(pyodide, manifest);
  status && (status.textContent = "Starting app...");
  return pyodide;
}

async function copyTree(pyodide, manifestUrl, destRoot) {
  const files = await fetch(manifestUrl).then((r) => r.json());
  for (const file of files) {
    const data = await fetch(file.url).then((r) => r.arrayBuffer());
    const target = `${destRoot}/${file.path}`;
    ensureDir(pyodide, target.split("/").slice(0, -1).join("/"));
    pyodide.FS.writeFile(target, new Uint8Array(data));
  }
}

async function copyAppFiles(pyodide) {
  await copyTree(pyodide, "./app_files.json", "/home/pyodide/app");
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
  }
});
