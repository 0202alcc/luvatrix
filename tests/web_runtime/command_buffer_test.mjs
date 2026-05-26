import assert from "node:assert/strict";
import test from "node:test";

import { decodeCommandBuffer, OPCODES } from "../../luvatrix_core/platform/web/runtime_assets/runtime/command-buffer.js";
import { CanvasRenderer, WebGpuRenderer } from "../../luvatrix_core/platform/web/runtime_assets/runtime/renderers.js";

test("decoder handles v1 command headers", () => {
  const decoded = decodeCommandBuffer({
    headers: new Uint32Array([
      OPCODES.CLEAR, 0, 4, 0,
      OPCODES.TEXT, 4, 8, 0, 1,
    ]),
    floats: new Float32Array([0, 0, 0, 1, 10, 20, 12, 1, 1, 1, 1, 0]),
    strings: ["hello", "system"],
  });

  assert.equal(decoded.length, 2);
  assert.equal(decoded[1].text, "hello");
  assert.equal(decoded[1].font, "system");
});

test("canvas fallback consumes command buffer", () => {
  const calls = [];
  const ctx = {
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 0,
    font: "",
    fillRect: (...args) => calls.push(["fillRect", ...args]),
    beginPath: () => calls.push(["beginPath"]),
    arc: (...args) => calls.push(["arc", ...args]),
    fill: () => calls.push(["fill"]),
    stroke: () => calls.push(["stroke"]),
    fillText: (...args) => calls.push(["fillText", ...args]),
    createLinearGradient: () => ({ addColorStop: () => {} }),
    moveTo: () => {},
    lineTo: () => {},
  };
  const canvas = { width: 1, height: 1, getContext: () => ctx };
  const renderer = new CanvasRenderer(canvas);
  renderer.render({
    width: 32,
    height: 16,
    headers: new Uint32Array([OPCODES.CLEAR, 0, 4, 0]),
    floats: new Float32Array([0, 0, 0, 1]),
    strings: [],
  });

  assert.equal(canvas.width, 32);
  assert.equal(canvas.height, 16);
  assert.deepEqual(calls[0], ["fillRect", 0, 0, 32, 16]);
});

test("webgpu support reports false without navigator gpu", () => {
  assert.equal(WebGpuRenderer.isSupported({}), false);
  assert.equal(WebGpuRenderer.isSupported({ gpu: {} }), true);
});
