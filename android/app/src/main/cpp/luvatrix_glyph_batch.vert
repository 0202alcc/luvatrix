#version 450

struct GlyphInstance {
    vec4 bounds;
    vec4 color;
    uvec4 atlas;
};

layout(std430, binding = 0) readonly buffer GlyphInstances {
    GlyphInstance instances[];
};

layout(location = 0) out vec2 vLocal;
layout(location = 1) out vec4 vColor;
layout(location = 2) flat out uvec4 vAtlas;

const vec2 kCorners[6] = vec2[](
    vec2(0.0, 0.0), vec2(1.0, 0.0), vec2(0.0, 1.0),
    vec2(0.0, 1.0), vec2(1.0, 0.0), vec2(1.0, 1.0)
);

void main() {
    GlyphInstance instance = instances[gl_InstanceIndex];
    vec2 corner = kCorners[gl_VertexIndex];
    vec2 position = instance.bounds.xy + corner * instance.bounds.zw;
    gl_Position = vec4(position.x * 2.0 - 1.0, 1.0 - position.y * 2.0, 0.0, 1.0);
    vLocal = corner;
    vColor = instance.color;
    vAtlas = instance.atlas;
}
