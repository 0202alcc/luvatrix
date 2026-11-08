// Static-tier core: renders a compiled container bundle with no Python.
//
// This module is pure (no DOM) so it runs in the browser entry
// (luvatrix-static.js) and in node parity tests. The motion math mirrors
// luvatrix_ui/planes_motion.py exactly — easings, transition playback,
// keyframe interpolation, loop modes, rest-state persistence — and the
// emitted command buffers mirror luvatrix_ui/planes_web.py
// (WebCommandBufferBuilder + WebAppContext) so the static and Pyodide
// tiers produce identical frames for identical bundles.

export const OP = Object.freeze({
  CLEAR: 1,
  RECT: 3,
  CIRCLE: 4,
  TEXT: 5,
  ROUNDED_RECT: 19,
  IMAGE: 23,
});

const DEFAULT_FONT_FAMILY = "Comic Mono";

function clamp01(value) {
  return Math.max(0.0, Math.min(1.0, value));
}

// Mirrors Python round(): half-to-even.
function pyRound(value) {
  const floor = Math.floor(value);
  const frac = value - floor;
  if (frac > 0.5) return floor + 1;
  if (frac < 0.5) return floor;
  return floor % 2 === 0 ? floor + 1 : floor;
}

function easingProgress(name, t) {
  const c = clamp01(t);
  if (name === "linear") return c;
  if (name === "ease_in") return c * c;
  if (name === "ease_out") return 1.0 - (1.0 - c) * (1.0 - c);
  if (name === "ease_in_out") {
    if (c < 0.5) return 2.0 * c * c;
    return 1.0 - 2.0 * (1.0 - c) * (1.0 - c);
  }
  throw new Error(`unknown easing ${name}`);
}

function interpolateKeyframes(keyframes, t) {
  if (!keyframes.length) return {};
  const clamped = clamp01(t);
  if (clamped <= keyframes[0].at) return { ...keyframes[0].props };
  if (clamped >= keyframes[keyframes.length - 1].at) return { ...keyframes[keyframes.length - 1].props };
  for (let i = 0; i < keyframes.length - 1; i += 1) {
    const start = keyframes[i];
    const end = keyframes[i + 1];
    if (start.at <= clamped && clamped <= end.at) {
      const span = end.at - start.at;
      const local = span <= 0.0 ? 0.0 : (clamped - start.at) / span;
      const props = {};
      for (const key of Object.keys(start.props)) {
        const startValue = Number(start.props[key]);
        const endValue = Number(end.props[key] ?? start.props[key]);
        props[key] = startValue + (endValue - startValue) * local;
      }
      for (const key of Object.keys(end.props)) {
        if (!(key in props)) props[key] = Number(end.props[key]);
      }
      return props;
    }
  }
  return { ...keyframes[keyframes.length - 1].props };
}

function slideOffset(kind, progress, entering) {
  const remaining = 1.0 - progress;
  if (kind === "slide_left") return [entering ? remaining : -progress, 0.0];
  if (kind === "slide_right") return [entering ? -remaining : progress, 0.0];
  if (kind === "slide_up") return [0.0, entering ? remaining : -progress];
  if (kind === "slide_down") return [0.0, entering ? -remaining : progress];
  return [0.0, 0.0];
}

function hexToRgba(colorHex, opacity) {
  let raw = String(colorHex || "").trim().replace(/^#/, "");
  let baseAlpha = 255;
  if (raw.length === 8) {
    baseAlpha = parseInt(raw.slice(6, 8), 16);
    raw = raw.slice(0, 6);
  }
  if (raw.length !== 6) raw = "F5FBFF";
  const alpha = Math.round(baseAlpha * clamp01(Number(opacity)));
  return [
    parseInt(raw.slice(0, 2), 16),
    parseInt(raw.slice(2, 4), 16),
    parseInt(raw.slice(4, 6), 16),
    alpha,
  ];
}

function rgbaFloats(rgba) {
  return rgba.map((ch) => Math.max(0.0, Math.min(1.0, ch / 255.0)));
}

class StaticBufferBuilder {
  constructor(width, height) {
    this.width = Math.max(1, Math.round(width));
    this.height = Math.max(1, Math.round(height));
    this.headers = [];
    this.floats = [];
    this.strings = [];
    this._stringIds = new Map();
  }

  _intern(value) {
    const existing = this._stringIds.get(value);
    if (existing !== undefined) return existing;
    const id = this.strings.length;
    this.strings.push(value);
    this._stringIds.set(value, id);
    return id;
  }

  clear(colorRgba) {
    this.headers.push(OP.CLEAR, this.floats.length, 4, 0);
    this.floats.push(...rgbaFloats(colorRgba));
  }

  text(text, { x, y, fontFamily = DEFAULT_FONT_FAMILY, fontSizePx, colorRgba, maxWidthPx = 0, rotationDeg = 0 }) {
    const textId = this._intern(String(text));
    const fontId = this._intern(String(fontFamily));
    const start = this.floats.length;
    this.floats.push(
      Number(x),
      Number(y),
      Number(fontSizePx),
      ...rgbaFloats(colorRgba),
      Number(maxWidthPx) || 0.0,
      Number(rotationDeg) || 0.0,
    );
    this.headers.push(OP.TEXT, start, this.floats.length - start, textId, fontId);
  }

  image({ x, y, width, height, opacity, asset }) {
    const assetId = this._intern(String(asset));
    const start = this.floats.length;
    this.floats.push(Number(x), Number(y), Number(width), Number(height), clamp01(Number(opacity)));
    this.headers.push(OP.IMAGE, start, this.floats.length - start, assetId);
  }

  finish() {
    return {
      headers: this.headers,
      floats: this.floats,
      strings: this.strings,
      width: this.width,
      height: this.height,
    };
  }
}

export function createStaticCore(bundle) {
  if (!bundle || typeof bundle !== "object") {
    throw new Error("static core requires a bundle object");
  }
  const planes = new Map(bundle.planes.map((plane) => [plane.id, plane]));
  const routes = new Map(bundle.routes.map((route) => [route.id, route]));
  const sourceOrder = new Map(bundle.components.map((component, index) => [component, index]));
  // Mirrors the Python draw order: (attach_rank, plane_global_z,
  // component_local_z, mount_order, component_id).
  const components = [...bundle.components].sort((a, b) => {
    const planeA = planes.get(a.plane_id)?.global_z ?? 0;
    const planeB = planes.get(b.plane_id)?.global_z ?? 0;
    if (planeA !== planeB) return planeA - planeB;
    if (a.z !== b.z) return a.z - b.z;
    const orderA = sourceOrder.get(a) ?? 0;
    const orderB = sourceOrder.get(b) ?? 0;
    if (orderA !== orderB) return orderA - orderB;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });

  const animationsByTarget = new Map();
  for (const animation of bundle.animations || []) {
    animationsByTarget.set(animation.target, animation);
  }

  const state = {
    route: bundle.entry_route,
    transition: null,
    prevPlaneIds: [],
    playbacks: new Map(),
    mountedOnce: new Set(),
  };

  function routePlaneIds(routeId) {
    const route = routes.get(routeId);
    return route ? [...route.active_planes] : [];
  }

  function activePlaneIds() {
    const active = new Set(routePlaneIds(state.route));
    if (state.transition) {
      for (const planeId of state.prevPlaneIds) active.add(planeId);
    }
    return active;
  }

  function startAnimation(animation) {
    state.playbacks.set(animation.target, { spec: animation, elapsed: 0.0, completed: false });
  }

  function animationTargetsRoute(animation, planeIds) {
    const component = bundle.components.find((c) => c.id === animation.target);
    if (!component) return false;
    return planeIds.includes(component.plane_id);
  }

  function activateRoute(routeId) {
    const route = routes.get(routeId);
    if (!route) throw new Error(`unknown route ${routeId}`);
    const fromRouteId = state.route;
    const fromRoute = routes.get(fromRouteId);
    const spec =
      fromRoute && fromRoute.transitions.find((t) => t.to_route === routeId) ? fromRoute.transitions.find((t) => t.to_route === routeId) : null;
    const prevPlanes = routePlaneIds(fromRouteId);
    state.route = routeId;
    state.prevPlaneIds = prevPlanes;
    state.transition =
      spec && spec.kind !== "none"
        ? {
            fromRoute: fromRouteId,
            toRoute: routeId,
            kind: spec.kind,
            durationMs: spec.duration_ms,
            easing: spec.easing,
            elapsed: 0.0,
          }
        : null;
    for (const animation of bundle.animations || []) {
      if (animation.trigger === "route_exit" && animationTargetsRoute(animation, prevPlanes)) {
        startAnimation(animation);
      } else if (animation.trigger === "route_enter" && animationTargetsRoute(animation, route.active_planes)) {
        startAnimation(animation);
      }
    }
  }

  function fireTrigger(triggerName) {
    const route = routes.get(state.route);
    if (!route) return false;
    const spec = (route.transitions || []).find((t) => t.trigger === triggerName);
    if (!spec) return false;
    activateRoute(spec.to_route);
    return true;
  }

  function advance(dt) {
    if (state.transition) {
      state.transition.elapsed += Math.max(0.0, dt);
      const durationS = Math.max(1e-6, state.transition.durationMs / 1000.0);
      if (state.transition.elapsed >= durationS) {
        state.transition = null;
        state.prevPlaneIds = [];
      }
    }
    for (const playback of state.playbacks.values()) {
      playback.elapsed += Math.max(0.0, dt);
      if (playback.spec.loop === "none") {
        const durationS = Math.max(1e-6, playback.spec.duration_ms / 1000.0);
        const delayS = Math.max(0.0, (playback.spec.delay_ms || 0) / 1000.0);
        if (playback.elapsed - delayS >= durationS) {
          playback.completed = true;
        }
      }
    }
    // on_mount animations start when their target first becomes active.
    const active = activePlaneIds();
    for (const animation of bundle.animations || []) {
      if (animation.trigger !== "on_mount" || state.mountedOnce.has(animation.target)) continue;
      const component = bundle.components.find((c) => c.id === animation.target);
      if (component && active.has(component.plane_id)) {
        state.mountedOnce.add(animation.target);
        startAnimation(animation);
      }
    }
  }

  function transitionProgress() {
    if (!state.transition) return null;
    const durationS = Math.max(1e-6, state.transition.durationMs / 1000.0);
    const raw = clamp01(state.transition.elapsed / durationS);
    return easingProgress(state.transition.easing, raw);
  }

  function playbackProps(playback) {
    const durationS = Math.max(1e-6, playback.spec.duration_ms / 1000.0);
    const delayS = Math.max(0.0, (playback.spec.delay_ms || 0) / 1000.0);
    const active = playback.elapsed - delayS;
    let raw;
    if (playback.elapsed < delayS) {
      raw = 0.0;
    } else if (playback.spec.loop === "repeat") {
      raw = active / durationS % 1.0;
    } else if (playback.spec.loop === "ping_pong") {
      const phase = (active / durationS) % 2.0;
      raw = phase <= 1.0 ? phase : 2.0 - phase;
    } else {
      raw = clamp01(active / durationS);
    }
    return interpolateKeyframes(playback.spec.keyframes || [], raw);
  }

  function overrides() {
    const result = new Map();
    if (state.transition) {
      const progress = easingProgress(state.transition.easing, clamp01(state.transition.elapsed / Math.max(1e-6, state.transition.durationMs / 1000.0)));
      const fade = state.transition.kind === "fade";
      const active = activePlaneIds();
      const entering = new Set([...active].filter((id) => !state.prevPlaneIds.includes(id)));
      const exiting = new Set(state.prevPlaneIds.filter((id) => active.has(id)));
      for (const component of components) {
        if (entering.has(component.plane_id)) {
          const [ox, oy] = slideOffset(state.transition.kind, progress, true);
          result.set(component.id, {
            opacity: fade ? progress : 1.0,
            offsetX: ox,
            offsetY: oy,
          });
        } else if (exiting.has(component.plane_id)) {
          const [ox, oy] = slideOffset(state.transition.kind, progress, false);
          result.set(component.id, {
            opacity: fade ? 1.0 - progress : 1.0,
            offsetX: ox,
            offsetY: oy,
          });
        }
      }
    }
    for (const [target, playback] of state.playbacks) {
      const props = playbackProps(playback);
      const existing = result.get(target) || { opacity: 1.0, offsetX: 0.0, offsetY: 0.0 };
      const opacity = "opacity" in props ? existing.opacity * Number(props.opacity) : existing.opacity;
      const offsetX = existing.offsetX + Number(props.offset_x || 0.0);
      const offsetY = existing.offsetY + Number(props.offset_y || 0.0);
      result.set(target, { opacity, offsetX, offsetY });
    }
    return result;
  }

  function tick(dt) {
    advance(dt);
    const active = activePlaneIds();
    const overrideMap = overrides();
    const builder = new StaticBufferBuilder(bundle.display.width, bundle.display.height);
    builder.clear(hexToRgba(bundle.page_background, 1.0));
    for (const component of components) {
      if (!active.has(component.plane_id)) continue;
      const override = overrideMap.get(component.id) || { opacity: 1.0, offsetX: 0.0, offsetY: 0.0 };
      const opacity = clamp01(Number(component.opacity) * override.opacity);
      const x = Number(component.x) + override.offsetX;
      const y = Number(component.y) + override.offsetY;
      if (component.type === "text") {
        builder.text(String(component.text), {
          x,
          y,
          fontSizePx: Number(component.font_size_px),
          colorRgba: hexToRgba(component.color_hex, opacity),
        });
      } else if (component.type === "svg") {
        builder.image({
          x,
          y,
          width: Number(component.width),
          height: Number(component.height),
          opacity,
          asset: component.svg_data_url,
        });
      }
    }
    return builder.finish();
  }

  function resolveGeometry(component, canvasWidth, canvasHeight) {
    let x = Number(component.x);
    let y = Number(component.y);
    let width = Number(component.width);
    let height = Number(component.height);
    if (component.unit === "vw") {
      x = (x / 100.0) * canvasWidth;
      width = (width / 100.0) * canvasWidth;
    } else if (component.unit === "vh") {
      y = (y / 100.0) * canvasHeight;
      height = (height / 100.0) * canvasHeight;
    }
    return { x, y, width, height };
  }

  function hitTest(px, py, canvasWidth, canvasHeight) {
    const active = activePlaneIds();
    for (let i = components.length - 1; i >= 0; i -= 1) {
      const component = components[i];
      if (!active.has(component.plane_id)) continue;
      if (!component.trigger) continue;
      const geo = resolveGeometry(component, canvasWidth, canvasHeight);
      if (px >= geo.x && px <= geo.x + geo.width && py >= geo.y && py <= geo.y + geo.height) {
        return component;
      }
    }
    return null;
  }

  return {
    bundle,
    get route() {
      return state.route;
    },
    activateRoute,
    fireTrigger,
    tick,
    hitTest,
  };
}
