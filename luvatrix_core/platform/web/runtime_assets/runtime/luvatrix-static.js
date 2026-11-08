// Static-tier browser entry: loads a compiled container bundle and renders
// it with the Canvas command-buffer pipeline — no Pyodide, no Python.
//
// The app opt-in is `[web] static_container` in app.toml; build-web then
// emits `static_bundle.json` and points index.html at this entry.

import { createInputAdapter } from "./input.js?v=static-20261108c";
import { createRenderer } from "./renderers.js?v=static-20261108c";
import { createStaticCore } from "./static-core.js?v=static-20261108c";

async function main() {
  const canvas = document.getElementById("stage");
  const status = document.getElementById("status");
  const cacheKey = Date.now().toString(36);
  const bundle = await fetch(cacheBust("./static_bundle.json", cacheKey), { cache: "no-store" }).then((r) => {
    if (!r.ok) throw new Error(`failed to load static bundle: ${r.status}`);
    return r.json();
  });
  document.title = bundle.app?.title || "Luvatrix";
  const viewport = displayViewportSize();
  const designWidth = bundle.display?.width || viewport.width;
  const designHeight = bundle.display?.height || viewport.height;
  const fitScale = Math.min(viewport.width / designWidth, viewport.height / designHeight);
  const dpr = Number(window.devicePixelRatio || 1);
  const renderScale = fitScale * dpr;
  canvas.width = Math.max(1, Math.round(designWidth * renderScale));
  canvas.height = Math.max(1, Math.round(designHeight * renderScale));
  canvas.style.width = `${Math.round(designWidth * fitScale)}px`;
  canvas.style.height = `${Math.round(designHeight * fitScale)}px`;
  canvas.style.position = "absolute";
  canvas.style.left = "50%";
  canvas.style.top = "50%";
  canvas.style.transform = "translate(-50%, -50%)";

  const core = createStaticCore(bundle);
  const input = createInputAdapter(canvas);
  const renderer = await createRenderer(canvas, status, { webglCanvas: null });

  function toDesignCoords(canvasX, canvasY) {
    return {
      x: (canvasX / canvas.width) * designWidth,
      y: (canvasY / canvas.height) * designHeight,
    };
  }

  activateFromHash();
  window.addEventListener("hashchange", activateFromHash);

  function activateFromHash() {
    const routeId = decodeURIComponent(window.location.hash.replace(/^#/, "")).trim();
    if (routeId && routeId !== core.route) {
      try {
        core.activateRoute(routeId);
      } catch {
        // Unknown hash route: keep the current route.
      }
    }
  }

  function onActivation(routeId) {
    const hash = `#${encodeURIComponent(routeId)}`;
    if (window.location.hash !== hash) {
      window.history.replaceState(null, "", hash);
    }
  }

  let last = performance.now();
  function tickFrame(now) {
    const dt = Math.max(0, (now - last) / 1000);
    last = now;
    const snapshot = input.snapshot();
    if (snapshot.left_clicked && snapshot.mouse_in_window) {
      const point = toDesignCoords(snapshot.mouse_x, snapshot.mouse_y);
      const target = core.hitTest(point.x, point.y);
      if (target && target.trigger) {
        core.fireTrigger(target.trigger);
        onActivation(core.route);
      }
    }
    const buffer = core.tick(dt);
    renderer.render(buffer, { scale: renderScale });
    input.endFrame();
    requestAnimationFrame(tickFrame);
  }
  if (status) {
    status.textContent = "Static runtime (no Python)";
    status.dataset.ready = "true";
  }
  requestAnimationFrame(tickFrame);
}

function displayViewportSize() {
  const source = globalThis.visualViewport || globalThis;
  return {
    width: Math.max(1, Math.round(Number(source.innerWidth || source.width || 0))),
    height: Math.max(1, Math.round(Number(source.innerHeight || source.height || 0))),
  };
}

function cacheBust(url, key) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}v=${encodeURIComponent(key)}`;
}

main().catch((error) => {
  console.error(error);
  const status = document.getElementById("status");
  if (status) {
    status.textContent = `Luvatrix static runtime error: ${error.message || error}`;
    status.dataset.error = "true";
  }
});
