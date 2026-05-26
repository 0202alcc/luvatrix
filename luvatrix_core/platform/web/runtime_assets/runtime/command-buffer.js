export const OPCODES = Object.freeze({
  CLEAR: 1,
  SHADER_RECT: 2,
  RECT: 3,
  CIRCLE: 4,
  TEXT: 5,
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
    if (opcode === OPCODES.TEXT) {
      const fontId = headers[i++] ?? 0;
      commands.push({ opcode, args, text: strings[meta0] || "", font: strings[fontId] || "sans-serif" });
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
