import assert from "node:assert/strict";
import test from "node:test";

import { decodeCommandBuffer, OPCODES } from "../../luvatrix_core/platform/web/runtime_assets/runtime/command-buffer.js";
import { CanvasRenderer, LayeredSceneRenderer, WebGpuRenderer } from "../../luvatrix_core/platform/web/runtime_assets/runtime/renderers.js";

test("decoder handles v1 command headers", () => {
  const decoded = decodeCommandBuffer({
    headers: new Uint32Array([
      OPCODES.CLEAR, 0, 4, 0,
      OPCODES.CAMERA_3D, 12, 12, 0,
      OPCODES.CUBE_3D, 24, 15, 0,
      OPCODES.TEXT, 4, 8, 0, 1,
    ]),
    floats: new Float32Array([
      0, 0, 0, 1,
      10, 20, 12, 1, 1, 1, 1, 0,
      0, 0, 5, 0, 0, 0, 0, 1, 0, 60, 0.1, 100,
      0, 0, 0, 1, 0.1, 0.2, 0.3, 0.3, 0.7, 1, 1, 1, 1, 1, 1,
    ]),
    strings: ["hello", "system"],
  });

  assert.equal(decoded.length, 4);
  assert.equal(decoded[1].opcode, OPCODES.CAMERA_3D);
  assert.equal(decoded[2].opcode, OPCODES.CUBE_3D);
  assert.equal(decoded[3].text, "hello");
  assert.equal(decoded[3].font, "system");
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

test("layered renderer routes 3d commands to webgl and overlay commands to 2d", () => {
  const calls = [];
  const ctx2d = {
    fillStyle: "",
    font: "",
    textBaseline: "",
    clearRect: (...args) => calls.push(["clearRect", ...args]),
    fillRect: (...args) => calls.push(["fillRect", ...args]),
    fillText: (...args) => calls.push(["fillText", ...args]),
    beginPath: () => {},
    arc: () => {},
    fill: () => {},
  };
  const gl = fakeGl(calls);
  const canvas2d = { width: 1, height: 1, getContext: (kind) => kind === "2d" ? ctx2d : null };
  const canvas3d = { width: 1, height: 1, getContext: (kind) => kind === "webgl" ? gl : null };
  const renderer = new LayeredSceneRenderer(canvas2d, canvas3d);

  renderer.render({
    width: 64,
    height: 64,
    headers: new Uint32Array([
      OPCODES.CLEAR, 0, 4, 0,
      OPCODES.CAMERA_3D, 4, 12, 0,
      OPCODES.CUBE_3D, 16, 15, 0,
      OPCODES.TEXT, 31, 8, 0, 1,
    ]),
    floats: new Float32Array([
      0.01, 0.02, 0.03, 1,
      0, 0, 5, 0, 0, 0, 0, 1, 0, 60, 0.1, 100,
      0, 0, 0, 1, 0.1, 0.2, 0.3, 0.3, 0.7, 1, 1, 1, 1, 1, 1,
      4, 5, 12, 1, 1, 1, 1, 0,
    ]),
    strings: ["overlay", "system"],
  });

  assert.equal(calls.filter((call) => call[0] === "drawElements").length, 2);
  assert.ok(calls.some((call) => call[0] === "clearRect"));
  assert.ok(calls.some((call) => call[0] === "fillText"));
});

function fakeGl(calls) {
  let next = 1;
  return {
    VERTEX_SHADER: 1,
    FRAGMENT_SHADER: 2,
    COMPILE_STATUS: 3,
    LINK_STATUS: 4,
    ARRAY_BUFFER: 5,
    ELEMENT_ARRAY_BUFFER: 6,
    STATIC_DRAW: 7,
    FLOAT: 8,
    TRIANGLES: 9,
    LINES: 10,
    UNSIGNED_SHORT: 11,
    POINTS: 12,
    TRIANGLE_STRIP: 13,
    BLEND: 0x0be2,
    SRC_ALPHA: 0x0302,
    ONE_MINUS_SRC_ALPHA: 0x0303,
    DYNAMIC_DRAW: 0x88e8,
    TEXTURE0: 0x84c0,
    TEXTURE_2D: 0x0de1,
    COLOR_BUFFER_BIT: 0x4000,
    DEPTH_BUFFER_BIT: 0x0100,
    DEPTH_TEST: 0x0b71,
    getExtension: () => null,
    createShader: () => ({ id: next++ }),
    shaderSource: () => {},
    compileShader: () => {},
    getShaderParameter: () => true,
    getShaderInfoLog: () => "",
    createProgram: () => ({ id: next++ }),
    attachShader: () => {},
    linkProgram: () => {},
    getProgramParameter: () => true,
    getProgramInfoLog: () => "",
    getAttribLocation: () => 0,
    getUniformLocation: () => ({}),
    createBuffer: () => ({ id: next++ }),
    bindBuffer: () => {},
    bufferData: () => {},
    enable: () => {},
    viewport: (...args) => calls.push(["viewport", ...args]),
    clearColor: (...args) => calls.push(["clearColor", ...args]),
    clear: (...args) => calls.push(["clear", ...args]),
    useProgram: () => {},
    enableVertexAttribArray: () => {},
    vertexAttribPointer: () => {},
    uniformMatrix4fv: () => {},
    uniform4fv: () => {},
    uniform1f: () => {},
    uniform1i: () => {},
    blendFunc: () => {},
    lineWidth: () => {},
    drawArrays: (...args) => calls.push(["drawArrays", ...args]),
    drawElements: (...args) => calls.push(["drawElements", ...args]),
    activeTexture: () => {},
    bindTexture: () => {},
    disableVertexAttribArray: () => {},
    depthMask: () => {},
  };
}
