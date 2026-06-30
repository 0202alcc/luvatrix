import { OPCODES, decodeCommandBuffer, normalizeCommandBuffer } from "./command-buffer.js?v=procedural-floor-20260603";

const RUNTIME_OPCODES = Object.freeze({
  ...OPCODES,
  CUBOID_3D: OPCODES.CUBOID_3D ?? 16,
  INFINITE_GRID_3D: OPCODES.INFINITE_GRID_3D ?? 17,
  SPHERE_3D: OPCODES.SPHERE_3D ?? 18,
  MODEL_3D: OPCODES.MODEL_3D ?? 20,
  ROUNDED_CUBOID_3D: OPCODES.ROUNDED_CUBOID_3D ?? 21,
  IMAGE_3D: OPCODES.IMAGE_3D ?? 22,
});

export class CanvasRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
  }

  static isSupported(canvas) {
    return Boolean(canvas.getContext("2d"));
  }

  render(rawBuffer, options = {}) {
    const buffer = normalizeCommandBuffer(rawBuffer);
    this._resize(buffer.width, buffer.height);
    if (options.transparent) {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }
    for (const command of decodeCommandBuffer(buffer)) {
      const a = command.args;
      if (command.opcode === OPCODES.CLEAR) {
        if (options.skipClear) {
          continue;
        }
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
      } else if (command.opcode === OPCODES.ROUNDED_RECT) {
        this.ctx.beginPath();
        roundedRectPath(this.ctx, a[0], a[1], a[2], a[3], a[4]);
        this.ctx.fillStyle = cssRgba(a, 5);
        this.ctx.fill();
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
        const rotationDeg = Number(a[8] || 0);
        if (rotationDeg) {
          this.ctx.save();
          this.ctx.translate(a[0], a[1]);
          this.ctx.rotate((rotationDeg * Math.PI) / 180);
          this.ctx.fillText(command.text, 0, 0, a[7] || undefined);
          this.ctx.restore();
        } else {
          this.ctx.fillText(command.text, a[0], a[1], a[7] || undefined);
        }
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

function roundedRectPath(ctx, x, y, width, height, radius) {
  const w = Math.max(0, Number(width || 0));
  const h = Math.max(0, Number(height || 0));
  const r = Math.max(0, Math.min(Number(radius || 0), w * 0.5, h * 0.5));
  if (typeof ctx.roundRect === "function") {
    ctx.roundRect(x, y, w, h, r);
    return;
  }
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

export class LayeredSceneRenderer {
  constructor(canvas2d, canvas3d = null) {
    this.canvas = canvas2d;
    this.canvas3d = canvas3d;
    this.canvas2d = new CanvasRenderer(canvas2d);
    this.webgl = canvas3d ? new CubeWebGlRenderer(canvas3d) : null;
  }

  static isSupported(canvas3d) {
    return Boolean(canvas3d?.getContext?.("webgl"));
  }

  render(rawBuffer) {
    const buffer = normalizeCommandBuffer(rawBuffer);
    const commands = decodeCommandBuffer(buffer);
    const has3d = commands.some((command) => command.opcode === OPCODES.CAMERA_3D || command.opcode === OPCODES.CUBE_3D || command.opcode === RUNTIME_OPCODES.CUBOID_3D || command.opcode === RUNTIME_OPCODES.ROUNDED_CUBOID_3D || command.opcode === RUNTIME_OPCODES.SPHERE_3D || command.opcode === RUNTIME_OPCODES.MODEL_3D || command.opcode === RUNTIME_OPCODES.IMAGE_3D || command.opcode === OPCODES.DOT_GRID_3D || command.opcode === OPCODES.DOT_PLANE_3D || command.opcode === OPCODES.INFINITE_DOT_PLANE_3D || command.opcode === RUNTIME_OPCODES.INFINITE_GRID_3D || command.opcode === OPCODES.LINE_3D || command.opcode === OPCODES.HORIZON_3D || command.opcode === OPCODES.TEXT_3D || command.opcode === OPCODES.GROUND_PLANE_3D || command.opcode === OPCODES.INFINITE_GROUND_3D);
    if (!has3d || !this.webgl?.isReady) {
      this.webgl?.clear(buffer);
      this.canvas2d.render(buffer);
      return;
    }
    this.webgl.render(buffer, commands);
    this.canvas2d.render(buffer, { skipClear: true, transparent: true });
  }
}

class CubeWebGlRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext("webgl", { alpha: false, antialias: true });
    this.isReady = Boolean(this.gl);
    if (!this.isReady) {
      return;
    }
    const gl = this.gl;
    this.program = createProgram(gl, VERTEX_SHADER, FRAGMENT_SHADER);
    this.horizonProgram = createProgram(gl, HORIZON_VERTEX_SHADER, HORIZON_FRAGMENT_SHADER);
    this.derivatives = typeof gl.getExtension === "function" ? gl.getExtension("OES_standard_derivatives") : null;
    this.proceduralWorldProgram = createProgram(gl, HORIZON_VERTEX_SHADER, this.derivatives ? PROCEDURAL_WORLD_FRAGMENT_SHADER : PROCEDURAL_WORLD_FRAGMENT_SHADER_FALLBACK);
    this.gridProgram = createProgram(gl, GRID_VERTEX_SHADER, this.derivatives ? GRID_FRAGMENT_SHADER : GRID_FRAGMENT_SHADER_FALLBACK);
    this.textProgram = createProgram(gl, TEXT_VERTEX_SHADER, TEXT_FRAGMENT_SHADER);
    this.imageProgram = createProgram(gl, TEXT_VERTEX_SHADER, IMAGE_FRAGMENT_SHADER);
    this.roundedTextureProgram = createProgram(gl, TEXT_VERTEX_SHADER, ROUNDED_TEXTURE_FRAGMENT_SHADER);
    this.aPosition = gl.getAttribLocation(this.program, "aPosition");
    this.uMvp = gl.getUniformLocation(this.program, "uMvp");
    this.uColor = gl.getUniformLocation(this.program, "uColor");
    this.uPointSize = gl.getUniformLocation(this.program, "uPointSize");
    this.horizonAPosition = gl.getAttribLocation(this.horizonProgram, "aPosition");
    this.horizonUSky = gl.getUniformLocation(this.horizonProgram, "uSky");
    this.horizonUSkyHorizon = gl.getUniformLocation(this.horizonProgram, "uSkyHorizon");
    this.horizonUGround = gl.getUniformLocation(this.horizonProgram, "uGround");
    this.horizonUHorizon = gl.getUniformLocation(this.horizonProgram, "uHorizon");
    this.horizonUHorizonY = gl.getUniformLocation(this.horizonProgram, "uHorizonY");
    this.horizonUWidth = gl.getUniformLocation(this.horizonProgram, "uHorizonWidth");
    this.worldAPosition = gl.getAttribLocation(this.proceduralWorldProgram, "aPosition");
    this.worldUSky = gl.getUniformLocation(this.proceduralWorldProgram, "uSky");
    this.worldUSkyHorizon = gl.getUniformLocation(this.proceduralWorldProgram, "uSkyHorizon");
    this.worldUGround = gl.getUniformLocation(this.proceduralWorldProgram, "uGround");
    this.worldUCameraPosition = gl.getUniformLocation(this.proceduralWorldProgram, "uCameraPosition");
    this.worldUCameraRight = gl.getUniformLocation(this.proceduralWorldProgram, "uCameraRight");
    this.worldUCameraUp = gl.getUniformLocation(this.proceduralWorldProgram, "uCameraUp");
    this.worldUCameraForward = gl.getUniformLocation(this.proceduralWorldProgram, "uCameraForward");
    this.worldUAspect = gl.getUniformLocation(this.proceduralWorldProgram, "uAspect");
    this.worldUTanHalfFov = gl.getUniformLocation(this.proceduralWorldProgram, "uTanHalfFov");
    this.worldUGroundY = gl.getUniformLocation(this.proceduralWorldProgram, "uGroundY");
    this.worldUZMax = gl.getUniformLocation(this.proceduralWorldProgram, "uZMax");
    this.worldUMinorSpacing = gl.getUniformLocation(this.proceduralWorldProgram, "uMinorSpacing");
    this.worldUMajorSpacing = gl.getUniformLocation(this.proceduralWorldProgram, "uMajorSpacing");
    this.worldUMinorColor = gl.getUniformLocation(this.proceduralWorldProgram, "uMinorColor");
    this.worldUMajorColor = gl.getUniformLocation(this.proceduralWorldProgram, "uMajorColor");
    this.worldUMinorWidth = gl.getUniformLocation(this.proceduralWorldProgram, "uMinorWidth");
    this.worldUMajorWidth = gl.getUniformLocation(this.proceduralWorldProgram, "uMajorWidth");
    this.gridAPosition = gl.getAttribLocation(this.gridProgram, "aPosition");
    this.gridUMvp = gl.getUniformLocation(this.gridProgram, "uMvp");
    this.gridUMinorSpacing = gl.getUniformLocation(this.gridProgram, "uMinorSpacing");
    this.gridUMajorSpacing = gl.getUniformLocation(this.gridProgram, "uMajorSpacing");
    this.gridUMinorColor = gl.getUniformLocation(this.gridProgram, "uMinorColor");
    this.gridUMajorColor = gl.getUniformLocation(this.gridProgram, "uMajorColor");
    this.gridUMinorWidth = gl.getUniformLocation(this.gridProgram, "uMinorWidth");
    this.gridUMajorWidth = gl.getUniformLocation(this.gridProgram, "uMajorWidth");
    this.gridUCameraXZ = gl.getUniformLocation(this.gridProgram, "uCameraXZ");
    this.gridUFadeDistance = gl.getUniformLocation(this.gridProgram, "uFadeDistance");
    this.textAPosition = gl.getAttribLocation(this.textProgram, "aPosition");
    this.textAUv = gl.getAttribLocation(this.textProgram, "aUv");
    this.textUMvp = gl.getUniformLocation(this.textProgram, "uMvp");
    this.textUColor = gl.getUniformLocation(this.textProgram, "uColor");
    this.textUTexture = gl.getUniformLocation(this.textProgram, "uTexture");
    this.imageAPosition = gl.getAttribLocation(this.imageProgram, "aPosition");
    this.imageAUv = gl.getAttribLocation(this.imageProgram, "aUv");
    this.imageUMvp = gl.getUniformLocation(this.imageProgram, "uMvp");
    this.imageUOpacity = gl.getUniformLocation(this.imageProgram, "uOpacity");
    this.imageUTexture = gl.getUniformLocation(this.imageProgram, "uTexture");
    this.roundedTextureAPosition = gl.getAttribLocation(this.roundedTextureProgram, "aPosition");
    this.roundedTextureAUv = gl.getAttribLocation(this.roundedTextureProgram, "aUv");
    this.roundedTextureUMvp = gl.getUniformLocation(this.roundedTextureProgram, "uMvp");
    this.roundedTextureUColor = gl.getUniformLocation(this.roundedTextureProgram, "uColor");
    this.roundedTextureUTexture = gl.getUniformLocation(this.roundedTextureProgram, "uTexture");
    this.roundedTextureURadius = gl.getUniformLocation(this.roundedTextureProgram, "uRadius");
    this.vertexBuffer = gl.createBuffer();
    this.indexBuffer = gl.createBuffer();
    this.edgeIndexBuffer = gl.createBuffer();
    this.roundedBoxVertexBuffer = gl.createBuffer();
    this.roundedBoxIndexBuffer = gl.createBuffer();
    this.roundedBoxEdgeIndexBuffer = gl.createBuffer();
    this.sphereVertexBuffer = gl.createBuffer();
    this.sphereIndexBuffer = gl.createBuffer();
    this.sphereEdgeIndexBuffer = gl.createBuffer();
    this.gridBuffer = gl.createBuffer();
    this.dotPlaneBuffer = gl.createBuffer();
    this.lineBuffer = gl.createBuffer();
    this.groundBuffer = gl.createBuffer();
    this.infiniteGroundBuffer = gl.createBuffer();
    this.infiniteGridBuffer = gl.createBuffer();
    this.horizonBuffer = gl.createBuffer();
    this.textBuffer = gl.createBuffer();
    this.gridCache = new Map();
    this.textCache = new Map();
    this.modelCache = new Map();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(CUBE_POSITIONS), gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(CUBE_TRIANGLES), gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.edgeIndexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(CUBE_EDGES), gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.roundedBoxVertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, ROUNDED_BOX_POSITIONS, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.roundedBoxIndexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, ROUNDED_BOX_TRIANGLES, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.roundedBoxEdgeIndexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, ROUNDED_BOX_EDGES, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.sphereVertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, SPHERE_POSITIONS, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.sphereIndexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, SPHERE_TRIANGLES, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.sphereEdgeIndexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, SPHERE_EDGES, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.horizonBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  }

  render(buffer, commands) {
    const gl = this.gl;
    resizeCanvas(this.canvas, buffer.width, buffer.height);
    const clear = commands.find((command) => command.opcode === OPCODES.CLEAR);
    if (clear) {
      gl.clearColor(clear.args[0], clear.args[1], clear.args[2], clear.args[3]);
    } else {
      gl.clearColor(0, 0, 0, 1);
    }
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    const cameraCommand = commands.find((command) => command.opcode === OPCODES.CAMERA_3D);
    const camera = parseCamera(cameraCommand?.args);
    const view = lookAt(camera.position, camera.target, camera.up);
    const projection = perspective(camera.fovDeg, this.canvas.width / Math.max(1, this.canvas.height), camera.near, camera.far);
    const viewProjection = multiply4(projection, view);
    const infiniteGroundCommand = commands.find((command) => command.opcode === OPCODES.INFINITE_GROUND_3D);
    const horizonGround = infiniteGroundCommand ? parseInfiniteGround(infiniteGroundCommand.args) : null;
    const infiniteGridCommand = commands.find((command) => command.opcode === RUNTIME_OPCODES.INFINITE_GRID_3D);
    const proceduralWorldGrid = infiniteGridCommand ? parseInfiniteGrid(infiniteGridCommand.args) : null;
    const horizonCommand = commands.find((command) => command.opcode === OPCODES.HORIZON_3D);
    const proceduralWorld = horizonCommand && horizonGround && proceduralWorldGrid;
    if (proceduralWorld) {
      this.drawProceduralWorld(parseHorizon(horizonCommand.args), horizonGround, proceduralWorldGrid, camera);
      gl.clear(gl.DEPTH_BUFFER_BIT);
    } else if (horizonCommand) {
      this.drawHorizon(parseHorizon(horizonCommand.args), camera, viewProjection, horizonGround);
      gl.clear(gl.DEPTH_BUFFER_BIT);
    } else {
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    }

    gl.useProgram(this.program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    gl.enableVertexAttribArray(this.aPosition);
    gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);

    for (const command of commands) {
      if (command.opcode === OPCODES.DOT_GRID_3D) {
        const grid = parseDotGrid(command.args);
        const points = this.gridPoints(grid);
        this.useSolidProgram();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.gridBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, points, gl.STATIC_DRAW);
        gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
        gl.uniformMatrix4fv(this.uMvp, false, viewProjection);
        gl.uniform4fv(this.uColor, grid.color);
        gl.uniform1f(this.uPointSize, grid.pointSize);
        gl.drawArrays(gl.POINTS, 0, points.length / 3);
      } else if (command.opcode === OPCODES.DOT_PLANE_3D) {
        const plane = parseDotPlane(command.args);
        const points = this.dotPlanePoints(plane);
        this.useSolidProgram();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.dotPlaneBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, points, gl.STATIC_DRAW);
        gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
        gl.uniformMatrix4fv(this.uMvp, false, viewProjection);
        gl.uniform4fv(this.uColor, plane.color);
        gl.uniform1f(this.uPointSize, plane.pointSize);
        gl.drawArrays(gl.POINTS, 0, points.length / 3);
      } else if (command.opcode === OPCODES.INFINITE_DOT_PLANE_3D) {
        const plane = parseInfiniteDotPlane(command.args);
        const points = this.infiniteDotPlanePoints(plane, camera);
        this.useSolidProgram();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.dotPlaneBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, points, gl.DYNAMIC_DRAW);
        gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
        gl.uniformMatrix4fv(this.uMvp, false, viewProjection);
        gl.uniform4fv(this.uColor, plane.color);
        gl.uniform1f(this.uPointSize, plane.pointSize);
        gl.drawArrays(gl.POINTS, 0, points.length / 3);
      } else if (command.opcode === RUNTIME_OPCODES.INFINITE_GRID_3D) {
        if (proceduralWorld) {
          continue;
        }
        this.drawInfiniteGrid(parseInfiniteGrid(command.args), camera, viewProjection, horizonGround);
      } else if (command.opcode === OPCODES.LINE_3D) {
        const line = parseLine(command.args);
        this.useSolidProgram();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.lineBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([...line.start, ...line.end]), gl.STATIC_DRAW);
        gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
        gl.uniformMatrix4fv(this.uMvp, false, viewProjection);
        gl.uniform4fv(this.uColor, line.color);
        gl.uniform1f(this.uPointSize, 1);
        gl.lineWidth(line.width);
        gl.drawArrays(gl.LINES, 0, 2);
      } else if (command.opcode === OPCODES.GROUND_PLANE_3D) {
        const ground = parseGroundPlane(command.args);
        this.useSolidProgram();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.groundBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, groundPlaneVertices(ground), gl.DYNAMIC_DRAW);
        gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
        gl.uniformMatrix4fv(this.uMvp, false, viewProjection);
        gl.uniform4fv(this.uColor, ground.color);
        gl.uniform1f(this.uPointSize, 1);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      } else if (command.opcode === OPCODES.INFINITE_GROUND_3D) {
        if (proceduralWorld) {
          continue;
        }
        const ground = parseInfiniteGround(command.args);
        this.useSolidProgram();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.infiniteGroundBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, infiniteGroundVertices(ground, camera), gl.DYNAMIC_DRAW);
        gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
        gl.uniformMatrix4fv(this.uMvp, false, viewProjection);
        gl.uniform4fv(this.uColor, ground.color);
        gl.uniform1f(this.uPointSize, 1);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      } else if (command.opcode === OPCODES.CUBE_3D) {
        this.useSolidProgram();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
        gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
        const cube = parseCube(command.args);
        const model = modelMatrix(cube.center, [cube.size, cube.size, cube.size], cube.rotation);
        const mvp = multiply4(viewProjection, model);
        gl.uniformMatrix4fv(this.uMvp, false, mvp);
        gl.uniform4fv(this.uColor, cube.color);
        gl.uniform1f(this.uPointSize, 1);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
        gl.drawElements(gl.TRIANGLES, CUBE_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);
        if (cube.edge[3] > 0) {
          gl.uniform4fv(this.uColor, cube.edge);
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.edgeIndexBuffer);
          gl.drawElements(gl.LINES, CUBE_EDGES.length, gl.UNSIGNED_SHORT, 0);
        }
      } else if (command.opcode === RUNTIME_OPCODES.CUBOID_3D) {
        this.useSolidProgram();
        const cuboid = parseCuboid(command.args);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
        gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
        const model = modelMatrix(cuboid.center, cuboid.size, cuboid.rotation);
        const mvp = multiply4(viewProjection, model);
        gl.uniformMatrix4fv(this.uMvp, false, mvp);
        gl.uniform4fv(this.uColor, cuboid.color);
        gl.uniform1f(this.uPointSize, 1);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
        gl.drawElements(gl.TRIANGLES, CUBE_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);
        if (cuboid.edge[3] > 0) {
          gl.uniform4fv(this.uColor, cuboid.edge);
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.edgeIndexBuffer);
          gl.drawElements(gl.LINES, CUBE_EDGES.length, gl.UNSIGNED_SHORT, 0);
        }
      } else if (command.opcode === RUNTIME_OPCODES.ROUNDED_CUBOID_3D) {
        this.drawRoundedCuboid3D(parseRoundedCuboid(command.args), viewProjection);
      } else if (command.opcode === RUNTIME_OPCODES.SPHERE_3D) {
        this.useSolidProgram();
        gl.bindBuffer(gl.ARRAY_BUFFER, this.sphereVertexBuffer);
        gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
        const sphere = parseSphere(command.args);
        const model = modelMatrix(sphere.center, [sphere.radius, sphere.radius, sphere.radius], [0, 0, 0]);
        const mvp = multiply4(viewProjection, model);
        gl.uniformMatrix4fv(this.uMvp, false, mvp);
        gl.uniform4fv(this.uColor, sphere.color);
        gl.uniform1f(this.uPointSize, 1);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.sphereIndexBuffer);
        gl.drawElements(gl.TRIANGLES, SPHERE_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);
        if (sphere.edge[3] > 0) {
          gl.uniform4fv(this.uColor, sphere.edge);
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.sphereEdgeIndexBuffer);
          gl.drawElements(gl.LINES, SPHERE_EDGES.length, gl.UNSIGNED_SHORT, 0);
        }
      } else if (command.opcode === RUNTIME_OPCODES.MODEL_3D) {
        this.drawModel3D(parseModel3D(command), viewProjection);
      } else if (command.opcode === RUNTIME_OPCODES.IMAGE_3D) {
        this.drawImage3D(parseImage3D(command), viewProjection);
      } else if (command.opcode === OPCODES.TEXT_3D) {
        this.drawText3D(parseText3D(command), viewProjection);
      }
    }
  }

  useSolidProgram() {
    const gl = this.gl;
    gl.useProgram(this.program);
    if (this.textAUv >= 0) {
      gl.disableVertexAttribArray(this.textAUv);
    }
    if (this.imageAUv >= 0) {
      gl.disableVertexAttribArray(this.imageAUv);
    }
    gl.enableVertexAttribArray(this.aPosition);
  }

  drawText3D(textNode, viewProjection) {
    const gl = this.gl;
    const texture = this.textTexture(textNode);
    const aspect = texture.width / Math.max(1, texture.height);
    const worldHeight = textNode.height;
    const worldWidth = worldHeight * aspect;
    gl.useProgram(this.textProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.textBuffer);
    gl.enableVertexAttribArray(this.textAPosition);
    gl.enableVertexAttribArray(this.textAUv);
    gl.vertexAttribPointer(this.textAPosition, 3, gl.FLOAT, false, 20, 0);
    gl.vertexAttribPointer(this.textAUv, 2, gl.FLOAT, false, 20, 12);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture.texture);
    gl.uniform1i(this.textUTexture, 0);
    const layers = Math.max(1, Math.min(16, Math.ceil(textNode.depth / Math.max(0.01, textNode.height * 0.08))));
    for (let i = layers; i >= 0; i -= 1) {
      const zOffset = -textNode.depth * (i / Math.max(1, layers));
      const color = i === 0 ? textNode.color : textNode.side;
      const vertices = textQuadVertices(textNode.position, worldWidth, worldHeight, zOffset);
      gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
      gl.uniformMatrix4fv(this.textUMvp, false, viewProjection);
      gl.uniform4fv(this.textUColor, color);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
  }

  drawModel3D(modelNode, viewProjection) {
    if (modelNode.asset === "__blank_app_icon__") {
      this.drawBlankAppIconModel3D(modelNode, viewProjection);
      return;
    }
    if (isSvgAsset(modelNode.asset)) {
      this.drawSvgModel3D(modelNode, viewProjection);
      return;
    }
    if (isImageAsset(modelNode.asset)) {
      this.drawImageCardModel3D(modelNode, viewProjection);
      return;
    }
    const gl = this.gl;
    const mesh = this.modelMesh(modelNode.asset);
    if (!mesh?.ready) {
      return;
    }
    this.useSolidProgram();
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.vertexBuffer);
    gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
    const model = modelMatrix(modelNode.center, modelNode.scale, modelNode.rotation);
    const mvp = multiply4(viewProjection, model);
    gl.uniformMatrix4fv(this.uMvp, false, mvp);
    gl.uniform4fv(this.uColor, modelNode.color);
    gl.uniform1f(this.uPointSize, 1);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.indexBuffer);
    gl.drawElements(gl.TRIANGLES, mesh.indexCount, mesh.indexType, 0);
    if (modelNode.edge[3] > 0 && mesh.edgeCount > 0) {
      gl.uniform4fv(this.uColor, modelNode.edge);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.edgeIndexBuffer);
      gl.drawElements(gl.LINES, mesh.edgeCount, mesh.indexType, 0);
    }
  }

  drawImage3D(imageNode, viewProjection) {
    const gl = this.gl;
    const texture = isSvgAsset(imageNode.asset) ? this.svgTexture(imageNode.asset) : this.imageTexture(imageNode.asset);
    const model = modelMatrix(imageNode.center, [1, 1, 1], imageNode.rotation);
    const mvp = multiply4(viewProjection, model);
    const vertices = textQuadVertices([0, 0, 0], imageNode.size[0], imageNode.size[1], 0.0);
    if (!texture?.ready) {
      return;
    }
    gl.useProgram(this.imageProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.textBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(this.imageAPosition);
    gl.enableVertexAttribArray(this.imageAUv);
    gl.vertexAttribPointer(this.imageAPosition, 3, gl.FLOAT, false, 20, 0);
    gl.vertexAttribPointer(this.imageAUv, 2, gl.FLOAT, false, 20, 12);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture.texture);
    gl.uniform1i(this.imageUTexture, 0);
    gl.uniformMatrix4fv(this.imageUMvp, false, mvp);
    gl.uniform1f(this.imageUOpacity, imageNode.opacity);
    gl.depthMask(false);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.depthMask(true);
  }

  drawBlankAppIconModel3D(modelNode, viewProjection) {
    const gl = this.gl;
    const width = modelNode.scale[0];
    const height = modelNode.scale[1] || width;
    const depth = modelNode.scale[2];
    const model = modelMatrix(modelNode.center, [width, height, depth], modelNode.rotation);
    const mvp = multiply4(viewProjection, model);
    this.useSolidProgram();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.roundedBoxVertexBuffer);
    gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
    gl.uniformMatrix4fv(this.uMvp, false, mvp);
    gl.uniform4fv(this.uColor, [
      Math.max(0, modelNode.color[0] * 0.72),
      Math.max(0, modelNode.color[1] * 0.72),
      Math.max(0, modelNode.color[2] * 0.78),
      modelNode.color[3],
    ]);
    gl.uniform1f(this.uPointSize, 1);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.roundedBoxIndexBuffer);
    gl.drawElements(gl.TRIANGLES, ROUNDED_BOX_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);

    if (modelNode.edge[3] > 0) {
      gl.bindBuffer(gl.ARRAY_BUFFER, this.roundedBoxVertexBuffer);
      gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.uniformMatrix4fv(this.uMvp, false, mvp);
      gl.uniform4fv(this.uColor, modelNode.edge);
      gl.uniform1f(this.uPointSize, 1);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.roundedBoxEdgeIndexBuffer);
      gl.drawElements(gl.LINES, ROUNDED_BOX_EDGES.length, gl.UNSIGNED_SHORT, 0);
    }
  }

  drawRoundedCuboid3D(cuboid, viewProjection) {
    const gl = this.gl;
    const model = modelMatrix(cuboid.center, cuboid.size, cuboid.rotation);
    const mvp = multiply4(viewProjection, model);
    this.useSolidProgram();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.roundedBoxVertexBuffer);
    gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
    gl.uniformMatrix4fv(this.uMvp, false, mvp);
    gl.uniform4fv(this.uColor, cuboid.color);
    gl.uniform1f(this.uPointSize, 1);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.roundedBoxIndexBuffer);
    gl.drawElements(gl.TRIANGLES, ROUNDED_BOX_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);
    if (cuboid.edge[3] > 0) {
      gl.uniform4fv(this.uColor, cuboid.edge);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.roundedBoxEdgeIndexBuffer);
      gl.drawElements(gl.LINES, ROUNDED_BOX_EDGES.length, gl.UNSIGNED_SHORT, 0);
    }
  }

  drawImageCardModel3D(modelNode, viewProjection) {
    const gl = this.gl;
    const texture = this.imageTexture(modelNode.asset);
    if (!texture?.ready) {
      return;
    }
    const width = modelNode.scale[0];
    const height = modelNode.scale[1] || width / Math.max(0.001, texture.aspect);
    const depth = modelNode.scale[2];
    const bodyScale = [width, height, depth];
    const model = modelMatrix(modelNode.center, bodyScale, modelNode.rotation);
    const mvp = multiply4(viewProjection, model);
    this.useSolidProgram();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.roundedBoxVertexBuffer);
    gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
    gl.uniformMatrix4fv(this.uMvp, false, mvp);
    gl.uniform4fv(this.uColor, [
      Math.max(0, modelNode.color[0] * 0.72),
      Math.max(0, modelNode.color[1] * 0.72),
      Math.max(0, modelNode.color[2] * 0.78),
      modelNode.color[3],
    ]);
    gl.uniform1f(this.uPointSize, 1);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.roundedBoxIndexBuffer);
    gl.drawElements(gl.TRIANGLES, ROUNDED_BOX_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);

    gl.useProgram(this.roundedTextureProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.textBuffer);
    gl.enableVertexAttribArray(this.roundedTextureAPosition);
    gl.enableVertexAttribArray(this.roundedTextureAUv);
    gl.vertexAttribPointer(this.roundedTextureAPosition, 3, gl.FLOAT, false, 20, 0);
    gl.vertexAttribPointer(this.roundedTextureAUv, 2, gl.FLOAT, false, 20, 12);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture.texture);
    gl.uniform1i(this.roundedTextureUTexture, 0);
    const frontModel = modelMatrix(modelNode.center, [1, 1, 1], modelNode.rotation);
    const frontMvp = multiply4(viewProjection, frontModel);
    const vertices = textQuadVertices([0, 0, depth * 0.512], width * 0.92, height * 0.92, 0.0);
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
    gl.uniformMatrix4fv(this.roundedTextureUMvp, false, frontMvp);
    gl.uniform4fv(this.roundedTextureUColor, [1, 1, 1, modelNode.color[3]]);
    gl.uniform1f(this.roundedTextureURadius, 0.255);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

    if (modelNode.edge[3] > 0) {
      this.useSolidProgram();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.roundedBoxVertexBuffer);
      gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);
      gl.uniformMatrix4fv(this.uMvp, false, mvp);
      gl.uniform4fv(this.uColor, modelNode.edge);
      gl.uniform1f(this.uPointSize, 1);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.roundedBoxEdgeIndexBuffer);
      gl.drawElements(gl.LINES, ROUNDED_BOX_EDGES.length, gl.UNSIGNED_SHORT, 0);
    }
  }

  drawSvgModel3D(modelNode, viewProjection) {
    const gl = this.gl;
    const texture = this.svgTexture(modelNode.asset);
    if (!texture?.ready) {
      return;
    }
    const width = modelNode.scale[0];
    const height = width / Math.max(0.001, texture.aspect);
    const depth = modelNode.scale[2];
    const layers = Math.max(3, Math.min(18, Math.ceil(depth / Math.max(0.04, width * 0.045))));
    gl.useProgram(this.textProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.textBuffer);
    gl.enableVertexAttribArray(this.textAPosition);
    gl.enableVertexAttribArray(this.textAUv);
    gl.vertexAttribPointer(this.textAPosition, 3, gl.FLOAT, false, 20, 0);
    gl.vertexAttribPointer(this.textAUv, 2, gl.FLOAT, false, 20, 12);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture.texture);
    gl.uniform1i(this.textUTexture, 0);
    const color = modelNode.color;
    const side = [
      Math.max(0, color[0] * 0.72),
      Math.max(0, color[1] * 0.72),
      Math.max(0, color[2] * 0.78),
      color[3],
    ];
    const model = modelMatrix(modelNode.center, [1, 1, 1], modelNode.rotation);
    const mvp = multiply4(viewProjection, model);
    if (modelNode.edge[3] > 0) {
      const outlinePad = Math.max(width, height) * 0.055;
      const vertices = textQuadVertices([0, 0, 0], width + outlinePad, height + outlinePad, 0.018);
      gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
      gl.uniformMatrix4fv(this.textUMvp, false, mvp);
      gl.uniform4fv(this.textUColor, modelNode.edge);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    for (let i = layers; i >= 0; i -= 1) {
      const zOffset = -depth * (i / Math.max(1, layers));
      const layerColor = i === 0 ? color : side;
      const vertices = textQuadVertices([0, 0, 0], width, height, zOffset);
      gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
      gl.uniformMatrix4fv(this.textUMvp, false, mvp);
      gl.uniform4fv(this.textUColor, layerColor);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
  }

  svgTexture(asset) {
    const cached = this.modelCache.get(`svg:${asset}`);
    if (cached) {
      return cached;
    }
    const entry = { ready: false };
    this.modelCache.set(`svg:${asset}`, entry);
    fetch(resolveAssetUrl(asset))
      .then((response) => {
        if (!response.ok) {
          throw new Error(`failed to load svg ${asset}: ${response.status}`);
        }
        return response.text();
      })
      .then((svgText) => loadSvgImage(svgText))
      .then((image) => {
        const gl = this.gl;
        const texture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        const iconImage = imageModelTextureSource(image);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, iconImage);
        Object.assign(entry, {
          ready: true,
          texture,
          width: iconImage.width,
          height: iconImage.height,
          aspect: iconImage.width / Math.max(1, iconImage.height),
        });
      })
      .catch((error) => {
        console.warn(error);
        this.modelCache.delete(`svg:${asset}`);
      });
    return entry;
  }

  imageTexture(asset) {
    const cached = this.modelCache.get(`image:${asset}`);
    if (cached) {
      return cached;
    }
    const entry = { ready: false };
    this.modelCache.set(`image:${asset}`, entry);
    loadImageAsset(asset)
      .then((image) => {
        const gl = this.gl;
        const texture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
        Object.assign(entry, {
          ready: true,
          texture,
          width: image.width,
          height: image.height,
          aspect: image.width / Math.max(1, image.height),
        });
      })
      .catch((error) => {
        console.warn(error);
        this.modelCache.delete(`image:${asset}`);
      });
    return entry;
  }


  modelMesh(asset) {
    if (!asset) {
      return null;
    }
    const cached = this.modelCache.get(asset);
    if (cached) {
      return cached;
    }
    const entry = { ready: false };
    this.modelCache.set(asset, entry);
    fetch(resolveAssetUrl(asset))
      .then((response) => {
        if (!response.ok) {
          throw new Error(`failed to load model ${asset}: ${response.status}`);
        }
        return response.text();
      })
      .then((text) => {
        Object.assign(entry, this.uploadObjMesh(parseObj(text)));
        entry.ready = true;
      })
      .catch((error) => {
        console.warn(error);
        this.modelCache.delete(asset);
      });
    return entry;
  }

  uploadObjMesh(mesh) {
    const gl = this.gl;
    const vertexBuffer = gl.createBuffer();
    const indexBuffer = gl.createBuffer();
    const edgeIndexBuffer = gl.createBuffer();
    const indexArray = mesh.vertices.length / 3 > 65535 ? new Uint32Array(mesh.indices) : new Uint16Array(mesh.indices);
    const edgeArray = mesh.vertices.length / 3 > 65535 ? new Uint32Array(mesh.edges) : new Uint16Array(mesh.edges);
    const indexType = indexArray instanceof Uint32Array ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT;
    if (indexType === gl.UNSIGNED_INT && !gl.getExtension("OES_element_index_uint")) {
      throw new Error("model requires uint32 indices but OES_element_index_uint is unavailable");
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, mesh.vertices, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indexArray, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, edgeIndexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, edgeArray, gl.STATIC_DRAW);
    return {
      vertexBuffer,
      indexBuffer,
      edgeIndexBuffer,
      indexCount: indexArray.length,
      edgeCount: edgeArray.length,
      indexType,
    };
  }

  textTexture(textNode) {
    const key = `${textNode.text}:${textNode.font}:${textNode.height}`;
    const cached = this.textCache.get(key);
    if (cached) {
      return cached;
    }
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    const fontSize = 96;
    ctx.font = `700 ${fontSize}px ${textNode.font}, Inter, system-ui, sans-serif`;
    const metrics = ctx.measureText(textNode.text);
    canvas.width = Math.max(8, Math.ceil(metrics.width + 32));
    canvas.height = Math.max(8, Math.ceil(fontSize * 1.35));
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = `700 ${fontSize}px ${textNode.font}, Inter, system-ui, sans-serif`;
    ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(255,255,255,1)";
    ctx.fillText(textNode.text, 16, canvas.height / 2);
    const gl = this.gl;
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
    const entry = { texture, width: canvas.width, height: canvas.height };
    if (this.textCache.size > 64) {
      this.textCache.clear();
    }
    this.textCache.set(key, entry);
    return entry;
  }

  drawHorizon(horizon, camera, viewProjection, ground = null) {
    const gl = this.gl;
    const dy = camera.target[1] - camera.position[1];
    const dx = camera.target[0] - camera.position[0];
    const dz = camera.target[2] - camera.position[2];
    const distance = Math.hypot(dx, dz) || 1;
    const pitch = Math.atan2(dy, distance);
    const fov = camera.fovDeg * Math.PI / 180;
    const pitchHorizonY = Math.tan(pitch) / Math.tan(fov * 0.5);
    const groundHorizonY = ground ? projectedGroundHorizonY(ground, camera, viewProjection) : null;
    const floorEdgeY = ground ? projectedFloorEdgeY(ground, camera, viewProjection) : null;
    const horizonY = Math.max(-0.95, Math.min(0.95, visualFloorHorizonY(groundHorizonY, floorEdgeY, pitchHorizonY)));
    gl.disable(gl.DEPTH_TEST);
    gl.useProgram(this.horizonProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.horizonBuffer);
    gl.enableVertexAttribArray(this.horizonAPosition);
    gl.vertexAttribPointer(this.horizonAPosition, 2, gl.FLOAT, false, 0, 0);
    gl.uniform4fv(this.horizonUSky, horizon.sky);
    gl.uniform4fv(this.horizonUSkyHorizon, horizon.skyHorizon);
    gl.uniform4fv(this.horizonUGround, horizon.ground);
    gl.uniform4fv(this.horizonUHorizon, horizon.horizon);
    gl.uniform1f(this.horizonUHorizonY, horizonY);
    gl.uniform1f(this.horizonUWidth, horizon.width);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.enable(gl.DEPTH_TEST);
  }

  drawProceduralWorld(horizon, ground, grid, camera) {
    const gl = this.gl;
    const basis = cameraBasis(camera);
    gl.disable(gl.DEPTH_TEST);
    gl.useProgram(this.proceduralWorldProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.horizonBuffer);
    gl.enableVertexAttribArray(this.worldAPosition);
    gl.vertexAttribPointer(this.worldAPosition, 2, gl.FLOAT, false, 0, 0);
    gl.uniform4fv(this.worldUSky, horizon.sky);
    gl.uniform4fv(this.worldUSkyHorizon, horizon.skyHorizon);
    gl.uniform4fv(this.worldUGround, ground.color);
    gl.uniform3fv(this.worldUCameraPosition, new Float32Array(camera.position));
    gl.uniform3fv(this.worldUCameraRight, new Float32Array(basis.right));
    gl.uniform3fv(this.worldUCameraUp, new Float32Array(basis.up));
    gl.uniform3fv(this.worldUCameraForward, new Float32Array(basis.forward));
    gl.uniform1f(this.worldUAspect, this.canvas.width / Math.max(1, this.canvas.height));
    gl.uniform1f(this.worldUTanHalfFov, Math.tan((camera.fovDeg * Math.PI / 180) * 0.5));
    gl.uniform1f(this.worldUGroundY, ground.y);
    gl.uniform1f(this.worldUZMax, ground.zMax);
    gl.uniform1f(this.worldUMinorSpacing, grid.minorSpacing);
    gl.uniform1f(this.worldUMajorSpacing, grid.majorSpacing);
    gl.uniform4fv(this.worldUMinorColor, grid.minorColor);
    gl.uniform4fv(this.worldUMajorColor, grid.majorColor);
    gl.uniform1f(this.worldUMinorWidth, grid.minorWidth);
    gl.uniform1f(this.worldUMajorWidth, grid.majorWidth);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.enable(gl.DEPTH_TEST);
  }

  drawInfiniteGrid(grid, camera, viewProjection, ground = null) {
    const gl = this.gl;
    const vertices = infiniteGridVertices(grid, camera, ground);
    gl.useProgram(this.gridProgram);
    if (this.textAUv >= 0) {
      gl.disableVertexAttribArray(this.textAUv);
    }
    if (this.imageAUv >= 0) {
      gl.disableVertexAttribArray(this.imageAUv);
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, this.infiniteGridBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(this.gridAPosition);
    gl.vertexAttribPointer(this.gridAPosition, 3, gl.FLOAT, false, 0, 0);
    gl.uniformMatrix4fv(this.gridUMvp, false, viewProjection);
    gl.uniform1f(this.gridUMinorSpacing, grid.minorSpacing);
    gl.uniform1f(this.gridUMajorSpacing, grid.majorSpacing);
    gl.uniform4fv(this.gridUMinorColor, grid.minorColor);
    gl.uniform4fv(this.gridUMajorColor, grid.majorColor);
    gl.uniform1f(this.gridUMinorWidth, grid.minorWidth);
    gl.uniform1f(this.gridUMajorWidth, grid.majorWidth);
    gl.uniform2fv(this.gridUCameraXZ, new Float32Array([camera.position[0], camera.position[2]]));
    gl.uniform1f(this.gridUFadeDistance, grid.renderDistance);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  gridPoints(grid) {
    const key = `${grid.center.join(",")}:${grid.extent}:${grid.spacing}`;
    const cached = this.gridCache.get(key);
    if (cached) {
      return cached;
    }
    const half = grid.extent * 0.5;
    const count = Math.max(1, Math.floor(grid.extent / grid.spacing));
    const start = -count * grid.spacing * 0.5;
    const values = [];
    for (let ix = 0; ix <= count; ix += 1) {
      for (let iy = 0; iy <= count; iy += 1) {
        for (let iz = 0; iz <= count; iz += 1) {
          const x = start + ix * grid.spacing;
          const y = start + iy * grid.spacing;
          const z = start + iz * grid.spacing;
          if (Math.abs(x) > half || Math.abs(y) > half || Math.abs(z) > half) {
            continue;
          }
          values.push(grid.center[0] + x, grid.center[1] + y, grid.center[2] + z);
        }
      }
    }
    const points = new Float32Array(values);
    if (this.gridCache.size > 32) {
      this.gridCache.clear();
    }
    this.gridCache.set(key, points);
    return points;
  }

  dotPlanePoints(plane) {
    const key = `${plane.center.join(",")}:${plane.width}:${plane.depth}:${plane.spacing}`;
    const cached = this.gridCache.get(key);
    if (cached) {
      return cached;
    }
    const xCount = Math.max(1, Math.floor(plane.width / plane.spacing));
    const zCount = Math.max(1, Math.floor(plane.depth / plane.spacing));
    const xStart = -xCount * plane.spacing * 0.5;
    const zStart = -zCount * plane.spacing * 0.5;
    const values = [];
    for (let ix = 0; ix <= xCount; ix += 1) {
      for (let iz = 0; iz <= zCount; iz += 1) {
        values.push(plane.center[0] + xStart + ix * plane.spacing, plane.center[1], plane.center[2] + zStart + iz * plane.spacing);
      }
    }
    const points = new Float32Array(values);
    if (this.gridCache.size > 32) {
      this.gridCache.clear();
    }
    this.gridCache.set(key, points);
    return points;
  }

  infiniteDotPlanePoints(plane, camera) {
    const spacing = plane.spacing;
    const minX = Math.floor((camera.position[0] - plane.renderDistance) / spacing) * spacing;
    const maxX = Math.ceil((camera.position[0] + plane.renderDistance) / spacing) * spacing;
    const minZ = Math.floor((camera.position[2] - plane.renderDistance) / spacing) * spacing;
    const maxZ = Math.ceil((camera.position[2] + plane.renderDistance) / spacing) * spacing;
    const values = [];
    for (let x = minX; x <= maxX; x += spacing) {
      for (let z = minZ; z <= maxZ; z += spacing) {
        values.push(x, plane.y, z);
      }
    }
    return new Float32Array(values);
  }

  clear(buffer) {
    const gl = this.gl;
    resizeCanvas(this.canvas, buffer.width, buffer.height);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
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

export async function createRenderer(canvas, status = null, options = {}) {
  if (LayeredSceneRenderer.isSupported(options.webglCanvas)) {
    status && (status.textContent = "WebGL scene renderer");
    return new LayeredSceneRenderer(canvas, options.webglCanvas);
  }
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

const VERTEX_SHADER = `
attribute vec3 aPosition;
uniform mat4 uMvp;
uniform float uPointSize;
void main() {
  gl_Position = uMvp * vec4(aPosition, 1.0);
  gl_PointSize = uPointSize;
}
`;

const FRAGMENT_SHADER = `
precision highp float;
uniform vec4 uColor;
void main() {
  gl_FragColor = uColor;
}
`;

const HORIZON_VERTEX_SHADER = `
attribute vec2 aPosition;
varying vec2 vUv;
void main() {
  vUv = aPosition;
  gl_Position = vec4(aPosition, 0.0, 1.0);
}
`;

const HORIZON_FRAGMENT_SHADER = `
precision highp float;
uniform vec4 uSky;
uniform vec4 uSkyHorizon;
uniform vec4 uGround;
uniform vec4 uHorizon;
uniform float uHorizonY;
uniform float uHorizonWidth;
varying vec2 vUv;
void main() {
  float skyT = pow(clamp((vUv.y - uHorizonY) / max(0.001, 1.0 - uHorizonY), 0.0, 1.0), 0.35);
  vec4 sky = mix(uSkyHorizon, uSky, skyT);
  vec4 base = vUv.y >= uHorizonY ? sky : uGround;
  float line = 1.0 - smoothstep(0.0, uHorizonWidth, abs(vUv.y - uHorizonY));
  gl_FragColor = mix(base, uHorizon, line * uHorizon.a);
}
`;

const PROCEDURAL_WORLD_FRAGMENT_SHADER = `
#extension GL_OES_standard_derivatives : enable
precision highp float;
uniform vec4 uSky;
uniform vec4 uSkyHorizon;
uniform vec4 uGround;
uniform vec3 uCameraPosition;
uniform vec3 uCameraRight;
uniform vec3 uCameraUp;
uniform vec3 uCameraForward;
uniform float uAspect;
uniform float uTanHalfFov;
uniform float uGroundY;
uniform float uZMax;
uniform float uMinorSpacing;
uniform float uMajorSpacing;
uniform vec4 uMinorColor;
uniform vec4 uMajorColor;
uniform float uMinorWidth;
uniform float uMajorWidth;
varying vec2 vUv;

float gridMask(vec2 p, float spacing, float width) {
  vec2 scaled = p / max(0.0001, spacing);
  vec2 cell = abs(fract(scaled - 0.5) - 0.5);
  vec2 fw = max(fwidth(scaled), vec2(0.0001));
  vec2 line = cell / fw;
  float nearest = min(line.x, line.y);
  return 1.0 - smoothstep(width, width + 1.0, nearest);
}

void main() {
  vec3 ray = normalize(
    uCameraForward +
    uCameraRight * (vUv.x * uAspect * uTanHalfFov) +
    uCameraUp * (vUv.y * uTanHalfFov)
  );
  float skyT = pow(clamp((vUv.y + 1.0) * 0.5, 0.0, 1.0), 0.6);
  vec4 sky = mix(uSkyHorizon, uSky, skyT);
  if (abs(ray.y) <= 0.00001) {
    gl_FragColor = sky;
    return;
  }
  float t = (uGroundY - uCameraPosition.y) / ray.y;
  vec3 hit = uCameraPosition + ray * t;
  if (t <= 0.0) {
    gl_FragColor = sky;
    return;
  }
  float minor = gridMask(hit.xz, uMinorSpacing, uMinorWidth);
  float major = gridMask(hit.xz, uMajorSpacing, uMajorWidth);
  vec4 grid = mix(uMinorColor, uMajorColor, major);
  float gridAlpha = max(minor * uMinorColor.a, major * uMajorColor.a);
  vec4 base = uGround;
  gl_FragColor = mix(base, vec4(grid.rgb, 1.0), clamp(gridAlpha, 0.0, 1.0));
}
`;

const PROCEDURAL_WORLD_FRAGMENT_SHADER_FALLBACK = `
precision highp float;
uniform vec4 uSky;
uniform vec4 uSkyHorizon;
uniform vec4 uGround;
uniform vec3 uCameraPosition;
uniform vec3 uCameraRight;
uniform vec3 uCameraUp;
uniform vec3 uCameraForward;
uniform float uAspect;
uniform float uTanHalfFov;
uniform float uGroundY;
uniform float uZMax;
uniform float uMinorSpacing;
uniform float uMajorSpacing;
uniform vec4 uMinorColor;
uniform vec4 uMajorColor;
uniform float uMinorWidth;
uniform float uMajorWidth;
varying vec2 vUv;

float gridMask(vec2 p, float spacing, float width) {
  vec2 cell = abs(fract(p / max(0.0001, spacing) - 0.5) - 0.5);
  float nearest = min(cell.x, cell.y);
  return 1.0 - smoothstep(0.0, width * 0.015, nearest);
}

void main() {
  vec3 ray = normalize(
    uCameraForward +
    uCameraRight * (vUv.x * uAspect * uTanHalfFov) +
    uCameraUp * (vUv.y * uTanHalfFov)
  );
  float skyT = pow(clamp((vUv.y + 1.0) * 0.5, 0.0, 1.0), 0.6);
  vec4 sky = mix(uSkyHorizon, uSky, skyT);
  if (abs(ray.y) <= 0.00001) {
    gl_FragColor = sky;
    return;
  }
  float t = (uGroundY - uCameraPosition.y) / ray.y;
  vec3 hit = uCameraPosition + ray * t;
  if (t <= 0.0) {
    gl_FragColor = sky;
    return;
  }
  float minor = gridMask(hit.xz, uMinorSpacing, uMinorWidth);
  float major = gridMask(hit.xz, uMajorSpacing, uMajorWidth);
  vec4 grid = mix(uMinorColor, uMajorColor, major);
  float gridAlpha = max(minor * uMinorColor.a, major * uMajorColor.a);
  gl_FragColor = mix(uGround, vec4(grid.rgb, 1.0), clamp(gridAlpha, 0.0, 1.0));
}
`;

const GRID_VERTEX_SHADER = `
attribute vec3 aPosition;
uniform mat4 uMvp;
varying vec2 vWorldXZ;
void main() {
  vWorldXZ = aPosition.xz;
  gl_Position = uMvp * vec4(aPosition, 1.0);
}
`;

const GRID_FRAGMENT_SHADER = `
#extension GL_OES_standard_derivatives : enable
precision highp float;
uniform float uMinorSpacing;
uniform float uMajorSpacing;
uniform vec4 uMinorColor;
uniform vec4 uMajorColor;
uniform float uMinorWidth;
uniform float uMajorWidth;
uniform vec2 uCameraXZ;
uniform float uFadeDistance;
varying vec2 vWorldXZ;

float gridMask(vec2 p, float spacing, float width) {
  vec2 scaled = p / max(0.0001, spacing);
  vec2 cell = abs(fract(scaled - 0.5) - 0.5);
  vec2 fw = max(fwidth(scaled), vec2(0.0001));
  vec2 line = cell / fw;
  float nearest = min(line.x, line.y);
  return 1.0 - smoothstep(width, width + 1.0, nearest);
}

void main() {
  float minor = gridMask(vWorldXZ, uMinorSpacing, uMinorWidth);
  float major = gridMask(vWorldXZ, uMajorSpacing, uMajorWidth);
  vec2 delta = abs(vWorldXZ - uCameraXZ);
  float dist = max(delta.x, delta.y);
  float fade = 1.0 - smoothstep(uFadeDistance * 0.72, uFadeDistance, dist);
  vec4 color = mix(uMinorColor, uMajorColor, major);
  color.a *= max(minor * uMinorColor.a, major * uMajorColor.a) * fade;
  if (color.a <= 0.005) {
    discard;
  }
  gl_FragColor = color;
}
`;

const GRID_FRAGMENT_SHADER_FALLBACK = `
precision highp float;
uniform float uMinorSpacing;
uniform float uMajorSpacing;
uniform vec4 uMinorColor;
uniform vec4 uMajorColor;
uniform float uMinorWidth;
uniform float uMajorWidth;
uniform vec2 uCameraXZ;
uniform float uFadeDistance;
varying vec2 vWorldXZ;

float gridMask(vec2 p, float spacing, float width) {
  vec2 cell = abs(fract(p / max(0.0001, spacing) - 0.5) - 0.5);
  float nearest = min(cell.x, cell.y);
  return 1.0 - smoothstep(0.0, width * 0.015, nearest);
}

void main() {
  float minor = gridMask(vWorldXZ, uMinorSpacing, uMinorWidth);
  float major = gridMask(vWorldXZ, uMajorSpacing, uMajorWidth);
  vec2 delta = abs(vWorldXZ - uCameraXZ);
  float dist = max(delta.x, delta.y);
  float fade = 1.0 - smoothstep(uFadeDistance * 0.72, uFadeDistance, dist);
  vec4 color = mix(uMinorColor, uMajorColor, major);
  color.a *= max(minor * uMinorColor.a, major * uMajorColor.a) * fade;
  if (color.a <= 0.005) {
    discard;
  }
  gl_FragColor = color;
}
`;

const TEXT_VERTEX_SHADER = `
attribute vec3 aPosition;
attribute vec2 aUv;
uniform mat4 uMvp;
varying vec2 vUv;
void main() {
  vUv = aUv;
  gl_Position = uMvp * vec4(aPosition, 1.0);
}
`;

const TEXT_FRAGMENT_SHADER = `
precision mediump float;
uniform sampler2D uTexture;
uniform vec4 uColor;
varying vec2 vUv;
void main() {
  float alpha = texture2D(uTexture, vUv).a * uColor.a;
  if (alpha <= 0.01) {
    discard;
  }
  gl_FragColor = vec4(uColor.rgb, alpha);
}
`;

const IMAGE_FRAGMENT_SHADER = `
precision mediump float;
uniform sampler2D uTexture;
uniform float uOpacity;
varying vec2 vUv;
void main() {
  vec4 tex = texture2D(uTexture, vUv);
  float alpha = tex.a * uOpacity;
  if (alpha <= 0.01) {
    discard;
  }
  gl_FragColor = vec4(tex.rgb, alpha);
}
`;

const ROUNDED_TEXTURE_FRAGMENT_SHADER = `
precision mediump float;
uniform sampler2D uTexture;
uniform vec4 uColor;
uniform float uRadius;
varying vec2 vUv;

float roundedRectMask(vec2 uv, float radius) {
  vec2 halfSize = vec2(0.5);
  vec2 q = abs(uv - halfSize) - (halfSize - vec2(radius));
  float dist = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;
  return 1.0 - smoothstep(0.0, 0.01, dist);
}

void main() {
  vec4 tex = texture2D(uTexture, vUv);
  float alpha = tex.a * uColor.a * roundedRectMask(vUv, uRadius);
  if (alpha <= 0.01) {
    discard;
  }
  gl_FragColor = vec4(tex.rgb * uColor.rgb, alpha);
}
`;

const CUBE_POSITIONS = [
  -0.5, -0.5, -0.5,
   0.5, -0.5, -0.5,
   0.5,  0.5, -0.5,
  -0.5,  0.5, -0.5,
  -0.5, -0.5,  0.5,
   0.5, -0.5,  0.5,
   0.5,  0.5,  0.5,
  -0.5,  0.5,  0.5,
];

const CUBE_TRIANGLES = [
  0, 1, 2, 0, 2, 3,
  4, 6, 5, 4, 7, 6,
  0, 4, 5, 0, 5, 1,
  3, 2, 6, 3, 6, 7,
  1, 5, 6, 1, 6, 2,
  0, 3, 7, 0, 7, 4,
];

const CUBE_EDGES = [
  0, 1, 1, 2, 2, 3, 3, 0,
  4, 5, 5, 6, 6, 7, 7, 4,
  0, 4, 1, 5, 2, 6, 3, 7,
];

const SPHERE_MESH = buildSphereMesh(24, 12);
const SPHERE_POSITIONS = SPHERE_MESH.positions;
const SPHERE_TRIANGLES = SPHERE_MESH.triangles;
const SPHERE_EDGES = SPHERE_MESH.edges;
const ROUNDED_BOX_MESH = buildRoundedBoxMesh(24, 0.44);
const ROUNDED_BOX_POSITIONS = ROUNDED_BOX_MESH.positions;
const ROUNDED_BOX_TRIANGLES = ROUNDED_BOX_MESH.triangles;
const ROUNDED_BOX_EDGES = ROUNDED_BOX_MESH.edges;

function buildRoundedBoxMesh(segmentsPerCorner, radius) {
  const segments = Math.max(2, Math.floor(segmentsPerCorner));
  const r = Math.max(0.001, Math.min(0.49, radius));
  const inner = 0.5 - r;
  const outline = [];
  const corners = [
    [inner, inner, 0, Math.PI * 0.5],
    [-inner, inner, Math.PI * 0.5, Math.PI],
    [-inner, -inner, Math.PI, Math.PI * 1.5],
    [inner, -inner, Math.PI * 1.5, Math.PI * 2],
  ];
  for (const [cx, cy, start, end] of corners) {
    for (let i = 0; i <= segments; i += 1) {
      if (outline.length > 0 && i === 0) {
        continue;
      }
      const t = i / segments;
      const angle = start + (end - start) * t;
      outline.push([cx + Math.cos(angle) * r, cy + Math.sin(angle) * r]);
    }
  }
  const positions = [];
  for (const [x, y] of outline) {
    positions.push(x, y, 0.5);
  }
  for (const [x, y] of outline) {
    positions.push(x, y, -0.5);
  }
  const frontCenter = outline.length * 2;
  const backCenter = frontCenter + 1;
  positions.push(0, 0, 0.5, 0, 0, -0.5);

  const triangles = [];
  const edges = [];
  const n = outline.length;
  for (let i = 0; i < n; i += 1) {
    const next = (i + 1) % n;
    const frontA = i;
    const frontB = next;
    const backA = i + n;
    const backB = next + n;
    triangles.push(frontCenter, frontA, frontB);
    triangles.push(backCenter, backB, backA);
    triangles.push(frontA, backA, backB, frontA, backB, frontB);
    edges.push(frontA, frontB, backA, backB);
    if (i % segments === 0) {
      edges.push(frontA, backA);
    }
  }
  return {
    positions: new Float32Array(positions),
    triangles: new Uint16Array(triangles),
    edges: new Uint16Array(edges),
  };
}

function buildSphereMesh(segments, rings) {
  const positions = [];
  const triangles = [];
  const edges = [];
  for (let ring = 0; ring <= rings; ring += 1) {
    const v = ring / rings;
    const phi = v * Math.PI;
    const y = Math.cos(phi);
    const radius = Math.sin(phi);
    for (let segment = 0; segment <= segments; segment += 1) {
      const u = segment / segments;
      const theta = u * Math.PI * 2;
      positions.push(Math.cos(theta) * radius, y, Math.sin(theta) * radius);
      if (segment < segments) {
        edges.push(ring * (segments + 1) + segment, ring * (segments + 1) + segment + 1);
      }
      if (ring < rings) {
        edges.push(ring * (segments + 1) + segment, (ring + 1) * (segments + 1) + segment);
      }
    }
  }
  for (let ring = 0; ring < rings; ring += 1) {
    for (let segment = 0; segment < segments; segment += 1) {
      const a = ring * (segments + 1) + segment;
      const b = a + 1;
      const c = a + segments + 1;
      const d = c + 1;
      triangles.push(a, c, b, b, c, d);
    }
  }
  return {
    positions: new Float32Array(positions),
    triangles: new Uint16Array(triangles),
    edges: new Uint16Array(edges),
  };
}

function createProgram(gl, vertexSource, fragmentSource) {
  const vertex = compileShader(gl, gl.VERTEX_SHADER, vertexSource);
  const fragment = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource);
  const program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(`WebGL program link failed: ${gl.getProgramInfoLog(program)}`);
  }
  return program;
}

function compileShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(`WebGL shader compile failed: ${gl.getShaderInfoLog(shader)}`);
  }
  return shader;
}

function parseCamera(args = []) {
  return {
    position: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 5)],
    target: [Number(args[3] ?? 0), Number(args[4] ?? 0), Number(args[5] ?? 0)],
    up: [Number(args[6] ?? 0), Number(args[7] ?? 1), Number(args[8] ?? 0)],
    fovDeg: Number(args[9] ?? 60),
    near: Number(args[10] ?? 0.1),
    far: Number(args[11] ?? 100),
  };
}

function parseCube(args) {
  return {
    center: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 0)],
    size: Number(args[3] ?? 1),
    rotation: [Number(args[4] ?? 0), Number(args[5] ?? 0), Number(args[6] ?? 0)],
    color: [Number(args[7] ?? 0.31), Number(args[8] ?? 0.71), Number(args[9] ?? 1), Number(args[10] ?? 1)],
    edge: [Number(args[11] ?? 1), Number(args[12] ?? 1), Number(args[13] ?? 1), Number(args[14] ?? 1)],
  };
}

function parseCuboid(args) {
  return {
    center: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 0)],
    size: [Number(args[3] ?? 1), Number(args[4] ?? 1), Number(args[5] ?? 1)],
    rotation: [Number(args[6] ?? 0), Number(args[7] ?? 0), Number(args[8] ?? 0)],
    color: [Number(args[9] ?? 0.31), Number(args[10] ?? 0.71), Number(args[11] ?? 1), Number(args[12] ?? 1)],
    edge: [Number(args[13] ?? 1), Number(args[14] ?? 1), Number(args[15] ?? 1), Number(args[16] ?? 1)],
  };
}

function parseRoundedCuboid(args) {
  return {
    center: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 0)],
    size: [Number(args[3] ?? 1), Number(args[4] ?? 1), Number(args[5] ?? 1)],
    rotation: [Number(args[6] ?? 0), Number(args[7] ?? 0), Number(args[8] ?? 0)],
    radius: Math.max(0.001, Number(args[9] ?? 0.25)),
    color: [Number(args[10] ?? 0.31), Number(args[11] ?? 0.71), Number(args[12] ?? 1), Number(args[13] ?? 1)],
    edge: [Number(args[14] ?? 1), Number(args[15] ?? 1), Number(args[16] ?? 1), Number(args[17] ?? 1)],
  };
}

function isAppIconCuboid(size) {
  const width = Math.abs(Number(size?.[0] ?? 0));
  const height = Math.abs(Number(size?.[1] ?? 0));
  const depth = Math.abs(Number(size?.[2] ?? 0));
  const face = Math.max(width, height);
  if (face <= 0) {
    return false;
  }
  const squareFace = Math.abs(width - height) <= face * 0.18;
  const shallowDepth = depth > 0 && depth <= face * 0.45;
  return squareFace && shallowDepth;
}

function parseSphere(args) {
  return {
    center: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 0)],
    radius: Math.max(0.001, Number(args[3] ?? 1)),
    color: [Number(args[4] ?? 0.96), Number(args[5] ?? 0.82), Number(args[6] ?? 0.57), Number(args[7] ?? 1)],
    edge: [Number(args[8] ?? 0), Number(args[9] ?? 0), Number(args[10] ?? 0), Number(args[11] ?? 0)],
  };
}

function parseDotGrid(args) {
  return {
    center: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 0)],
    extent: Math.max(0.001, Number(args[3] ?? 8)),
    spacing: Math.max(0.001, Number(args[4] ?? 0.5)),
    pointSize: Math.max(1, Number(args[5] ?? 2)),
    color: [Number(args[6] ?? 0.47), Number(args[7] ?? 0.67), Number(args[8] ?? 0.86), Number(args[9] ?? 0.47)],
  };
}

function parseDotPlane(args) {
  return {
    center: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 0)],
    width: Math.max(0.001, Number(args[3] ?? 8)),
    depth: Math.max(0.001, Number(args[4] ?? 8)),
    spacing: Math.max(0.001, Number(args[5] ?? 0.5)),
    pointSize: Math.max(1, Number(args[6] ?? 2)),
    color: [Number(args[7] ?? 0.55), Number(args[8] ?? 0.75), Number(args[9] ?? 0.88), Number(args[10] ?? 0.67)],
  };
}

function parseLine(args) {
  return {
    start: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 0)],
    end: [Number(args[3] ?? 0), Number(args[4] ?? 0), Number(args[5] ?? 0)],
    color: [Number(args[6] ?? 1), Number(args[7] ?? 1), Number(args[8] ?? 1), Number(args[9] ?? 1)],
    width: Math.max(1, Number(args[10] ?? 1)),
  };
}

function parseGroundPlane(args) {
  return {
    center: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? -20)],
    width: Math.max(0.001, Number(args[3] ?? 40)),
    depth: Math.max(0.001, Number(args[4] ?? 40)),
    color: [Number(args[5] ?? 0.1), Number(args[6] ?? 0.18), Number(args[7] ?? 0.13), Number(args[8] ?? 1)],
  };
}

function parseInfiniteGround(args) {
  return {
    y: Number(args[0] ?? 0),
    zMax: Number(args[1] ?? 0),
    renderDistance: Math.max(1, Number(args[2] ?? 120)),
    color: [Number(args[3] ?? 0.1), Number(args[4] ?? 0.18), Number(args[5] ?? 0.13), Number(args[6] ?? 1)],
  };
}

function parseInfiniteDotPlane(args) {
  return {
    y: Number(args[0] ?? 0),
    zMax: Number(args[1] ?? 0),
    spacing: Math.max(0.001, Number(args[2] ?? 0.5)),
    pointSize: Math.max(1, Number(args[3] ?? 2)),
    renderDistance: Math.max(1, Number(args[4] ?? 80)),
    color: [Number(args[5] ?? 0.55), Number(args[6] ?? 0.75), Number(args[7] ?? 0.88), Number(args[8] ?? 0.67)],
  };
}

function parseInfiniteGrid(args) {
  return {
    y: Number(args[0] ?? 0),
    minorSpacing: Math.max(0.001, Number(args[1] ?? 1)),
    majorSpacing: Math.max(0.001, Number(args[2] ?? 5)),
    renderDistance: Math.max(1, Number(args[3] ?? 180)),
    minorColor: [Number(args[4] ?? 0.8), Number(args[5] ?? 0.83), Number(args[6] ?? 0.85), Number(args[7] ?? 0.37)],
    majorColor: [Number(args[8] ?? 0.23), Number(args[9] ?? 0.46), Number(args[10] ?? 0.75), Number(args[11] ?? 0.57)],
    minorWidth: Math.max(0.001, Number(args[12] ?? 1)),
    majorWidth: Math.max(0.001, Number(args[13] ?? 1.35)),
  };
}

function parseHorizon(args) {
  return {
    sky: [Number(args[0] ?? 0.89), Number(args[1] ?? 0.93), Number(args[2] ?? 0.96), Number(args[3] ?? 1)],
    ground: [Number(args[4] ?? 0.93), Number(args[5] ?? 0.91), Number(args[6] ?? 0.86), Number(args[7] ?? 1)],
    horizon: [Number(args[8] ?? 0.59), Number(args[9] ?? 0.63), Number(args[10] ?? 0.66), Number(args[11] ?? 1)],
    skyHorizon: [Number(args[12] ?? args[0] ?? 0.89), Number(args[13] ?? args[1] ?? 0.93), Number(args[14] ?? args[2] ?? 0.96), Number(args[15] ?? args[3] ?? 1)],
    width: Math.max(0.001, Number(args[16] ?? 0.012)),
  };
}

function groundPlaneVertices(ground) {
  const x0 = ground.center[0] - ground.width * 0.5;
  const x1 = ground.center[0] + ground.width * 0.5;
  const y = ground.center[1];
  const z0 = ground.center[2] - ground.depth * 0.5;
  const z1 = ground.center[2] + ground.depth * 0.5;
  return new Float32Array([
    x0, y, z0,
    x1, y, z0,
    x0, y, z1,
    x1, y, z1,
  ]);
}

function infiniteGroundVertices(ground, camera) {
  const x0 = camera.position[0] - ground.renderDistance;
  const x1 = camera.position[0] + ground.renderDistance;
  const z0 = Math.min(camera.position[2] - ground.renderDistance, ground.zMax - ground.renderDistance);
  const z1 = ground.zMax;
  return new Float32Array([
    x0, ground.y, z0,
    x1, ground.y, z0,
    x0, ground.y, z1,
    x1, ground.y, z1,
  ]);
}

function infiniteGridVertices(grid, camera, ground = null) {
  const x0 = camera.position[0] - grid.renderDistance;
  const x1 = camera.position[0] + grid.renderDistance;
  const z0 = ground ? Math.min(camera.position[2] - grid.renderDistance, ground.zMax - grid.renderDistance) : camera.position[2] - grid.renderDistance;
  const z1 = ground ? ground.zMax : camera.position[2] + grid.renderDistance;
  return new Float32Array([
    x0, grid.y, z0,
    x1, grid.y, z0,
    x0, grid.y, z1,
    x1, grid.y, z1,
  ]);
}

function projectedGroundHorizonY(ground, camera, viewProjection) {
  const z = Math.min(camera.position[2] - ground.renderDistance, ground.zMax - ground.renderDistance);
  const clip = transformPoint4(viewProjection, [camera.position[0], ground.y, z]);
  if (!Number.isFinite(clip[3]) || Math.abs(clip[3]) < 1e-6) {
    return null;
  }
  const ndcY = clip[1] / clip[3];
  if (!Number.isFinite(ndcY)) {
    return null;
  }
  return ndcY;
}

function projectedFloorEdgeY(ground, camera, viewProjection) {
  const clip = transformPoint4(viewProjection, [camera.position[0], ground.y, ground.zMax]);
  if (!Number.isFinite(clip[3]) || Math.abs(clip[3]) < 1e-6) {
    return null;
  }
  const ndcY = clip[1] / clip[3];
  return Number.isFinite(ndcY) ? ndcY : null;
}

function visualFloorHorizonY(farEdgeY, nearEdgeY, fallbackY) {
  const skyLift = 0.28;
  if (Number.isFinite(nearEdgeY) && nearEdgeY >= -1.15 && nearEdgeY <= 1.15) {
    return nearEdgeY + skyLift;
  }
  if (Number.isFinite(farEdgeY)) {
    return farEdgeY + skyLift;
  }
  return fallbackY + skyLift;
}

function transformPoint4(matrix, point) {
  const x = point[0];
  const y = point[1];
  const z = point[2];
  return [
    matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
    matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
    matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    matrix[3] * x + matrix[7] * y + matrix[11] * z + matrix[15],
  ];
}

function parseText3D(command) {
  const args = command.args;
  return {
    text: command.text || "",
    font: command.font || "Inter",
    position: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 0)],
    height: Math.max(0.001, Number(args[3] ?? 0.4)),
    depth: Math.max(0, Number(args[4] ?? 0.12)),
    color: [Number(args[5] ?? 0.92), Number(args[6] ?? 0.96), Number(args[7] ?? 1), Number(args[8] ?? 1)],
    side: [Number(args[9] ?? 0.19), Number(args[10] ?? 0.3), Number(args[11] ?? 0.38), Number(args[12] ?? 1)],
  };
}

function parseModel3D(command) {
  const args = command.args;
  return {
    asset: command.asset || "",
    center: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 0)],
    scale: [Number(args[3] ?? 1), Number(args[4] ?? 1), Number(args[5] ?? 1)],
    rotation: [Number(args[6] ?? 0), Number(args[7] ?? 0), Number(args[8] ?? 0)],
    color: [Number(args[9] ?? 0.78), Number(args[10] ?? 0.57), Number(args[11] ?? 1), Number(args[12] ?? 1)],
    edge: [Number(args[13] ?? 0), Number(args[14] ?? 0), Number(args[15] ?? 0), Number(args[16] ?? 0)],
  };
}

function parseImage3D(command) {
  const args = command.args;
  const opacity = Math.max(0, Math.min(1, Number(args[8] ?? 1)));
  return {
    asset: command.asset || "",
    center: [Number(args[0] ?? 0), Number(args[1] ?? 0), Number(args[2] ?? 0)],
    size: [Math.max(0.001, Number(args[3] ?? 1)), Math.max(0.001, Number(args[4] ?? 1))],
    rotation: [Number(args[5] ?? 0), Number(args[6] ?? 0), Number(args[7] ?? 0)],
    opacity,
  };
}

function parseObj(text) {
  const sourceVertices = [];
  const vertices = [];
  const indices = [];
  const vertexMap = new Map();
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }
    const parts = line.split(/\s+/);
    if (parts[0] === "v" && parts.length >= 4) {
      sourceVertices.push([Number(parts[1]), Number(parts[2]), Number(parts[3])]);
    } else if (parts[0] === "f" && parts.length >= 4) {
      const face = parts.slice(1).map((part) => objVertexIndex(part, sourceVertices.length));
      for (let i = 1; i < face.length - 1; i += 1) {
        indices.push(modelVertex(face[0], sourceVertices, vertices, vertexMap));
        indices.push(modelVertex(face[i], sourceVertices, vertices, vertexMap));
        indices.push(modelVertex(face[i + 1], sourceVertices, vertices, vertexMap));
      }
    }
  }
  return {
    vertices: new Float32Array(vertices),
    indices,
    edges: modelEdges(indices),
  };
}

function isSvgAsset(asset) {
  return String(asset || "").toLowerCase().split("?")[0].endsWith(".svg");
}

function isImageAsset(asset) {
  return /\.(png|jpe?g|webp)$/i.test(String(asset || "").toLowerCase().split("?")[0]);
}

function loadImageAsset(asset) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`failed to decode image ${asset}`));
    image.src = resolveAssetUrl(asset);
  });
}

function loadSvgImage(svgText) {
  return new Promise((resolve, reject) => {
    const normalizedSvg = svgText.replace('xmlns="http://w3.org"', 'xmlns="http://www.w3.org/2000/svg"');
    const blob = new Blob([normalizedSvg], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("failed to decode svg image"));
    };
    image.src = url;
  });
}

function objVertexIndex(part, vertexCount) {
  const raw = Number(part.split("/")[0]);
  return raw < 0 ? vertexCount + raw : raw - 1;
}

function modelVertex(index, sourceVertices, vertices, vertexMap) {
  if (vertexMap.has(index)) {
    return vertexMap.get(index);
  }
  const vertex = sourceVertices[index] || [0, 0, 0];
  const out = vertices.length / 3;
  vertices.push(vertex[0], vertex[1], vertex[2]);
  vertexMap.set(index, out);
  return out;
}

function modelEdges(indices) {
  const seen = new Set();
  const edges = [];
  for (let i = 0; i < indices.length; i += 3) {
    addEdge(indices[i], indices[i + 1], seen, edges);
    addEdge(indices[i + 1], indices[i + 2], seen, edges);
    addEdge(indices[i + 2], indices[i], seen, edges);
  }
  return edges;
}

function addEdge(a, b, seen, edges) {
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  const key = `${lo}:${hi}`;
  if (seen.has(key)) {
    return;
  }
  seen.add(key);
  edges.push(a, b);
}

function resolveAssetUrl(asset) {
  if (/^(https?:)?\/\//.test(asset) || asset.startsWith("/") || asset.startsWith("./")) {
    return asset;
  }
  return asset;
}

function imageModelTextureSource(image) {
  const sourceWidth = image.width || 1;
  const sourceHeight = image.height || 1;
  const scanCanvas = document.createElement("canvas");
  scanCanvas.width = sourceWidth;
  scanCanvas.height = sourceHeight;
  const scanCtx = scanCanvas.getContext("2d", { willReadFrequently: true });
  scanCtx.drawImage(image, 0, 0);
  let data;
  try {
    data = scanCtx.getImageData(0, 0, sourceWidth, sourceHeight).data;
  } catch {
    return image;
  }

  const corner = pixelAt(data, sourceWidth, 0, 0);
  const step = Math.max(1, Math.floor(Math.max(sourceWidth, sourceHeight) / 256));
  let minX = sourceWidth;
  let minY = sourceHeight;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < sourceHeight; y += step) {
    for (let x = 0; x < sourceWidth; x += step) {
      const pixel = pixelAt(data, sourceWidth, x, y);
      const contrast = Math.max(
        Math.abs(pixel[0] - corner[0]),
        Math.abs(pixel[1] - corner[1]),
        Math.abs(pixel[2] - corner[2]),
      );
      const saturation = Math.max(pixel[0], pixel[1], pixel[2]) - Math.min(pixel[0], pixel[1], pixel[2]);
      if (pixel[3] > 12 && (contrast > 32 || saturation > 48)) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }
  }
  if (maxX < minX || maxY < minY) {
    return image;
  }

  const contentWidth = Math.max(1, maxX - minX + step);
  const contentHeight = Math.max(1, maxY - minY + step);
  const pad = Math.max(contentWidth, contentHeight) * 0.18;
  const cropSize = Math.max(contentWidth, contentHeight) + pad * 2;
  const cx = (minX + maxX) * 0.5;
  const cy = (minY + maxY) * 0.5;
  const sx = Math.max(0, cx - cropSize * 0.5);
  const sy = Math.max(0, cy - cropSize * 0.5);
  const sw = Math.min(sourceWidth - sx, cropSize);
  const sh = Math.min(sourceHeight - sy, cropSize);
  const size = 1024;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = `rgba(${corner[0]}, ${corner[1]}, ${corner[2]}, ${corner[3] / 255})`;
  ctx.fillRect(0, 0, size, size);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  const drawSize = size * 0.96;
  const dx = (size - drawSize) * 0.5;
  const dy = (size - drawSize) * 0.5;
  ctx.drawImage(image, sx, sy, sw, sh, dx, dy, drawSize, drawSize);
  return canvas;
}

function pixelAt(data, width, x, y) {
  const offset = (Math.max(0, y) * width + Math.max(0, x)) * 4;
  return [data[offset] || 0, data[offset + 1] || 0, data[offset + 2] || 0, data[offset + 3] || 0];
}

function textQuadVertices(position, width, height, zOffset) {
  const x0 = position[0] - width * 0.5;
  const x1 = position[0] + width * 0.5;
  const y0 = position[1] - height * 0.5;
  const y1 = position[1] + height * 0.5;
  const z = position[2] + zOffset;
  return new Float32Array([
    x0, y0, z, 0, 1,
    x1, y0, z, 1, 1,
    x0, y1, z, 0, 0,
    x1, y1, z, 1, 0,
  ]);
}

function modelMatrix(center, size, rotation) {
  const [rx, ry, rz] = rotation;
  const sx = Math.sin(rx), cx = Math.cos(rx);
  const sy = Math.sin(ry), cy = Math.cos(ry);
  const sz = Math.sin(rz), cz = Math.cos(rz);
  const scale = Array.isArray(size) ? size : [Number(size || 1), Number(size || 1), Number(size || 1)];
  const rotX = new Float32Array([1, 0, 0, 0, 0, cx, sx, 0, 0, -sx, cx, 0, 0, 0, 0, 1]);
  const rotY = new Float32Array([cy, 0, -sy, 0, 0, 1, 0, 0, sy, 0, cy, 0, 0, 0, 0, 1]);
  const rotZ = new Float32Array([cz, sz, 0, 0, -sz, cz, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  const sc = new Float32Array([scale[0], 0, 0, 0, 0, scale[1], 0, 0, 0, 0, scale[2], 0, 0, 0, 0, 1]);
  const tr = identity4();
  tr[12] = center[0];
  tr[13] = center[1];
  tr[14] = center[2];
  return multiply4(tr, multiply4(rotZ, multiply4(rotY, multiply4(rotX, sc))));
}

function perspective(fovDeg, aspect, near, far) {
  const f = 1.0 / Math.tan((Number(fovDeg) * Math.PI / 180) * 0.5);
  const nf = 1 / (Number(near) - Number(far));
  return new Float32Array([
    f / Math.max(1e-6, aspect), 0, 0, 0,
    0, f, 0, 0,
    0, 0, (far + near) * nf, -1,
    0, 0, (2 * far * near) * nf, 0,
  ]);
}

function lookAt(eye, target, upVector) {
  const z = normalize([eye[0] - target[0], eye[1] - target[1], eye[2] - target[2]]);
  const x = normalize(cross(upVector, z));
  const y = cross(z, x);
  return new Float32Array([
    x[0], y[0], z[0], 0,
    x[1], y[1], z[1], 0,
    x[2], y[2], z[2], 0,
    -dot(x, eye), -dot(y, eye), -dot(z, eye), 1,
  ]);
}

function cameraBasis(camera) {
  const forward = normalize([
    camera.target[0] - camera.position[0],
    camera.target[1] - camera.position[1],
    camera.target[2] - camera.position[2],
  ]);
  const right = normalize(cross(forward, camera.up));
  const up = normalize(cross(right, forward));
  return { forward, right, up };
}

function multiply4(a, b) {
  const out = new Float32Array(16);
  for (let col = 0; col < 4; col += 1) {
    for (let row = 0; row < 4; row += 1) {
      out[col * 4 + row] =
        a[0 * 4 + row] * b[col * 4 + 0] +
        a[1 * 4 + row] * b[col * 4 + 1] +
        a[2 * 4 + row] * b[col * 4 + 2] +
        a[3 * 4 + row] * b[col * 4 + 3];
    }
  }
  return out;
}

function identity4() {
  return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
}

function normalize(v) {
  const len = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / len, v[1] / len, v[2] / len];
}

function cross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

function dot(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function resizeCanvas(canvas, width, height) {
  const w = Math.max(1, Math.round(width));
  const h = Math.max(1, Math.round(height));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
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
