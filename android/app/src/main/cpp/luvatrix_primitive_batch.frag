#version 450

layout(location = 0) in vec2 vLocal;
layout(location = 1) flat in vec4 vFill;
layout(location = 2) flat in vec4 vStroke;
layout(location = 3) flat in vec4 vParams;
layout(location = 0) out vec4 outColor;

void main() {
    if (vParams.x < 0.5) {
        outColor = vFill;
        return;
    }

    float distance_to_center = length((vLocal * 2.0) - vec2(1.0));
    float edge = fwidth(distance_to_center);
    float visible = 1.0 - smoothstep(1.0 - edge, 1.0 + edge, distance_to_center);
    float fill = 1.0 - smoothstep(vParams.y - edge, vParams.y + edge, distance_to_center);
    vec4 color = mix(vStroke, vFill, fill);
    outColor = vec4(color.rgb, color.a * visible);
}
