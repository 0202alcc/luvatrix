#version 450

struct PrimitiveInstance {
    vec4 bounds;
    vec4 fill;
    vec4 stroke;
    vec4 params;
};

layout(std430, binding = 0) readonly buffer PrimitiveInstances {
    PrimitiveInstance instances[];
};

layout(location = 0) out vec2 vLocal;
layout(location = 1) flat out vec4 vFill;
layout(location = 2) flat out vec4 vStroke;
layout(location = 3) flat out vec4 vParams;

void main() {
    const vec2 corners[6] = vec2[](
        vec2(0.0, 0.0), vec2(1.0, 0.0), vec2(1.0, 1.0),
        vec2(0.0, 0.0), vec2(1.0, 1.0), vec2(0.0, 1.0)
    );
    PrimitiveInstance instance = instances[gl_InstanceIndex];
    vLocal = corners[gl_VertexIndex];
    vec2 position = instance.bounds.xy + (vLocal * instance.bounds.zw);
    gl_Position = vec4((position.x * 2.0) - 1.0, 1.0 - (position.y * 2.0), 0.0, 1.0);
    vFill = instance.fill;
    vStroke = instance.stroke;
    vParams = instance.params;
}
