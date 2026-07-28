#version 450

struct RectInstance {
    vec4 rect;
    vec4 color;
};

layout(std430, binding = 0) readonly buffer RectInstances {
    RectInstance instances[];
};

layout(location = 0) out vec4 vColor;

void main() {
    const vec2 corners[6] = vec2[](
        vec2(0.0, 0.0), vec2(1.0, 0.0), vec2(1.0, 1.0),
        vec2(0.0, 0.0), vec2(1.0, 1.0), vec2(0.0, 1.0)
    );
    RectInstance instance = instances[gl_InstanceIndex];
    vec2 position = instance.rect.xy + (corners[gl_VertexIndex] * instance.rect.zw);
    gl_Position = vec4((position.x * 2.0) - 1.0, 1.0 - (position.y * 2.0), 0.0, 1.0);
    vColor = instance.color;
}
