#version 450

layout(location = 0) in vec2 vLocal;
layout(location = 1) in vec4 vColor;
layout(location = 2) flat in uvec4 vAtlas;
layout(location = 0) out vec4 outColor;

layout(std430, binding = 1) readonly buffer GlyphAtlas {
    uint rows[];
};

void main() {
    uint glyph_width = max(1u, vAtlas.y);
    uint glyph_height = max(1u, vAtlas.z);
    uint column = min(glyph_width - 1u, uint(vLocal.x * float(glyph_width)));
    uint row_index = min(glyph_height - 1u, uint(vLocal.y * float(glyph_height)));
    uint row = rows[vAtlas.x * 64u + row_index];
    uint bit = glyph_width - 1u - column;
    float coverage = (row & (1u << bit)) != 0u ? 1.0 : 0.0;
    outColor = vec4(vColor.rgb, vColor.a * coverage);
}
