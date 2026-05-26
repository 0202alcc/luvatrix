import { OPCODES, decodeCommandBuffer, normalizeCommandBuffer } from "./command-buffer.js";

export class CanvasRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
  }

  static isSupported(canvas) {
    return Boolean(canvas.getContext("2d"));
  }

  render(rawBuffer) {
    const buffer = normalizeCommandBuffer(rawBuffer);
    this._resize(buffer.width, buffer.height);
    for (const command of decodeCommandBuffer(buffer)) {
      const a = command.args;
      if (command.opcode === OPCODES.CLEAR) {
        this.ctx.fillStyle = cssRgba(a, 0);
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
      } else if (command.opcode === OPCODES.SHADER_RECT) {
        if (command.shader === "full_suite_background") {
          drawFullSuiteBackground(this.ctx, a);
        } else {
          this.ctx.fillStyle = cssRgba(a, 4);
          this.ctx.fillRect(a[0], a[1], a[2], a[3]);
        }
      } else if (command.opcode === OPCODES.RECT) {
        this.ctx.fillStyle = cssRgba(a, 4);
        this.ctx.fillRect(a[0], a[1], a[2], a[3]);
      } else if (command.opcode === OPCODES.CIRCLE) {
        this.ctx.beginPath();
        this.ctx.arc(a[0], a[1], a[2], 0, Math.PI * 2);
        this.ctx.fillStyle = cssRgba(a, 3);
        this.ctx.fill();
        if (a[11] > 0 && a[10] > 0) {
          this.ctx.strokeStyle = cssRgba(a, 7);
          this.ctx.lineWidth = a[11];
          this.ctx.stroke();
        }
      } else if (command.opcode === OPCODES.TEXT) {
        this.ctx.font = `${a[2]}px ${command.font}, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
        this.ctx.textBaseline = "top";
        this.ctx.fillStyle = cssRgba(a, 3);
        this.ctx.fillText(command.text, a[0], a[1], a[7] || undefined);
      }
    }
  }

  _resize(width, height) {
    const w = Math.max(1, Math.round(width));
    const h = Math.max(1, Math.round(height));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
  }
}

export class WebGpuRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.canvasFallback = new CanvasRenderer(canvas);
    this.device = null;
  }

  static isSupported(navigatorLike = globalThis.navigator) {
    return Boolean(navigatorLike?.gpu);
  }

  async init() {
    if (!WebGpuRenderer.isSupported()) {
      throw new Error("WebGPU is not available");
    }
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) {
      throw new Error("WebGPU adapter unavailable");
    }
    this.device = await adapter.requestDevice();
    return this;
  }

  render(rawBuffer) {
    // V1 keeps the command-buffer contract identical while GPU pipelines mature.
    this.canvasFallback.render(rawBuffer);
  }
}

export async function createRenderer(canvas, status = null) {
  if (WebGpuRenderer.isSupported()) {
    try {
      const renderer = await new WebGpuRenderer(canvas).init();
      status && (status.textContent = "WebGPU renderer");
      return renderer;
    } catch {
      status && (status.textContent = "Canvas renderer");
    }
  }
  status && (status.textContent = "Canvas renderer");
  return new CanvasRenderer(canvas);
}

function cssRgba(values, offset) {
  const r = Math.round(255 * Number(values[offset] || 0));
  const g = Math.round(255 * Number(values[offset + 1] || 0));
  const b = Math.round(255 * Number(values[offset + 2] || 0));
  const a = Number(values[offset + 3] ?? 1);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

function drawFullSuiteBackground(ctx, a) {
  const x = a[0], y = a[1], width = a[2], height = a[3];
  const t = Number(a[8] || 0);
  const rot = Number(a[9] || 0);
  const scroll = Number(a[10] || 0);
  const sampleW = Math.max(96, Math.min(360, Math.round(width / 3)));
  const sampleH = Math.max(96, Math.round(sampleW * height / Math.max(1, width)));
  const image = ctx.createImageData(sampleW, sampleH);
  const data = image.data;
  const phase = t * 0.0025 + rot * 0.01 + scroll * 0.002;
  let idx = 0;
  for (let yy = 0; yy < sampleH; yy += 1) {
    const ny = yy / Math.max(1, sampleH);
    for (let xx = 0; xx < sampleW; xx += 1) {
      const nx = xx / Math.max(1, sampleW);
      const wave = Math.sin((nx * 3.2 + ny * 2.4 + phase) * Math.PI * 2) * 0.055;
      const hue = fract(nx * 0.58 + ny * 0.42 + phase + wave);
      const value = clamp(0.78 + 0.16 * Math.sin((nx - ny + phase * 0.7) * Math.PI * 2), 0.35, 0.95);
      const [r, g, b] = hsvToRgb(hue, 0.82, value);
      data[idx++] = r;
      data[idx++] = g;
      data[idx++] = b;
      data[idx++] = 255;
    }
  }
  const scratch = getScratchCanvas(sampleW, sampleH);
  scratch.width = sampleW;
  scratch.height = sampleH;
  scratch.getContext("2d").putImageData(image, 0, 0);
  const prevSmoothing = ctx.imageSmoothingEnabled;
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(scratch, x, y, width, height);
  ctx.imageSmoothingEnabled = prevSmoothing;
}

let shaderScratchCanvas = null;

function getScratchCanvas(width, height) {
  if (shaderScratchCanvas === null) {
    shaderScratchCanvas = document.createElement("canvas");
  }
  shaderScratchCanvas.width = width;
  shaderScratchCanvas.height = height;
  return shaderScratchCanvas;
}

function hsvToRgb(h, s, v) {
  const i = Math.floor(h * 6);
  const f = h * 6 - i;
  const p = v * (1 - s);
  const q = v * (1 - f * s);
  const tv = v * (1 - (1 - f) * s);
  const rgb = [
    [v, tv, p],
    [q, v, p],
    [p, v, tv],
    [p, q, v],
    [tv, p, v],
    [v, p, q],
  ][i % 6];
  return rgb.map((channel) => Math.max(0, Math.min(255, Math.round(channel * 255))));
}

function fract(value) {
  return value - Math.floor(value);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}
