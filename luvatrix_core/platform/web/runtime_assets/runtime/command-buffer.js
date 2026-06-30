export const OPCODES = Object.freeze({
  CLEAR: 1,
  SHADER_RECT: 2,
  RECT: 3,
  CIRCLE: 4,
  TEXT: 5,
  CAMERA_3D: 6,
  CUBE_3D: 7,
  DOT_GRID_3D: 8,
  LINE_3D: 9,
  HORIZON_3D: 10,
  TEXT_3D: 11,
  GROUND_PLANE_3D: 12,
  DOT_PLANE_3D: 13,
  INFINITE_GROUND_3D: 14,
  INFINITE_DOT_PLANE_3D: 15,
  CUBOID_3D: 16,
  INFINITE_GRID_3D: 17,
  SPHERE_3D: 18,
  ROUNDED_RECT: 19,
  MODEL_3D: 20,
  ROUNDED_CUBOID_3D: 21,
  IMAGE_3D: 22,
});

export const SHADERS = Object.freeze({
  1: "solid",
  2: "full_suite_background",
});

export function decodeCommandBuffer(buffer) {
  const headers = buffer.headers instanceof Uint32Array ? buffer.headers : new Uint32Array(buffer.headers || []);
  const floats = buffer.floats instanceof Float32Array ? buffer.floats : new Float32Array(buffer.floats || []);
  const strings = Array.from(buffer.strings || []);
  const commands = [];
  for (let i = 0; i < headers.length;) {
    const opcode = headers[i++];
    const floatStart = headers[i++] ?? 0;
    const floatCount = headers[i++] ?? 0;
    const meta0 = headers[i++] ?? 0;
    const args = floats.subarray(floatStart, floatStart + floatCount);
    if (opcode === OPCODES.TEXT || opcode === OPCODES.TEXT_3D) {
      const fontId = headers[i++] ?? 0;
      commands.push({ opcode, args, text: strings[meta0] || "", font: strings[fontId] || "sans-serif" });
    } else if (opcode === OPCODES.MODEL_3D || opcode === OPCODES.IMAGE_3D) {
      commands.push({ opcode, args, asset: strings[meta0] || "" });
    } else {
      commands.push({ opcode, args, meta: meta0, shader: SHADERS[meta0] || "" });
    }
  }
  return commands;
}

export function normalizeCommandBuffer(buffer) {
  return {
    headers: buffer.headers instanceof Uint32Array ? buffer.headers : new Uint32Array(buffer.headers || []),
    floats: buffer.floats instanceof Float32Array ? buffer.floats : new Float32Array(buffer.floats || []),
    strings: Array.from(buffer.strings || []),
    width: Number(buffer.width || 1),
    height: Number(buffer.height || 1),
  };
}
