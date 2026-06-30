#version 450

layout(push_constant) uniform CameraPush
{
    vec4 crop;
    vec4 meta;
    vec4 tuning;
    vec4 color;
} pc;

layout(binding = 0) uniform sampler2D cameraTex;

layout(location = 0) in vec2 vUv;
layout(location = 0) out vec4 outColor;

vec2 sensorUv(vec2 orientedUv)
{
    vec2 cropped = pc.crop.zw + (orientedUv * pc.crop.xy);
    int rotation = int(pc.meta.x + 0.5);
    if (rotation == 90) {
        return vec2(cropped.y, 1.0 - cropped.x);
    }
    if (rotation == 180) {
        return vec2(1.0 - cropped.x, 1.0 - cropped.y);
    }
    if (rotation == 270) {
        return vec2(1.0 - cropped.y, cropped.x);
    }
    return cropped;
}

float lumaOf(vec3 rgb)
{
    return dot(rgb, vec3(0.299, 0.587, 0.114));
}

vec3 recombineLumaChroma(float y, vec3 chroma)
{
    return vec3(y) + chroma;
}

void main()
{
    vec2 uv = sensorUv(vUv);
    vec2 dx = dFdx(uv);
    vec2 dy = dFdy(uv);
    float lumaMixBase = clamp(pc.meta.y, 0.0, 1.0);
    float chromaMixBase = clamp(pc.meta.z, 0.0, 1.0);
    float edgePreserve = clamp(pc.meta.w, 0.0, 1.0);
    float detailBoost = clamp(pc.tuning.x, 0.0, 1.0);
    float mode = pc.tuning.y;
    float colorContrast = clamp(pc.tuning.z, 0.75, 1.35);
    vec3 colorGain = max(pc.color.xyz, vec3(0.0));
    float colorBrightness = clamp(pc.color.w, -0.25, 0.25);

    vec4 c4 = texture(cameraTex, uv);
    vec3 c = c4.xyz;
    vec3 n = texture(cameraTex, uv - dy).xyz;
    vec3 s = texture(cameraTex, uv + dy).xyz;
    vec3 w = texture(cameraTex, uv - dx).xyz;
    vec3 e = texture(cameraTex, uv + dx).xyz;
    vec3 crossAvg = (n + s + w + e) * 0.25;
    vec3 diagAvg = crossAvg;
    vec3 smoothRgb = (c * 0.5) + (crossAvg * 0.5);
    vec3 minRgb = min(c, min(min(n, s), min(w, e)));
    vec3 maxRgb = max(c, max(max(n, s), max(w, e)));

    if (mode >= 0.5) {
        vec3 nw = texture(cameraTex, uv - dx - dy).xyz;
        vec3 ne = texture(cameraTex, uv + dx - dy).xyz;
        vec3 sw = texture(cameraTex, uv - dx + dy).xyz;
        vec3 se = texture(cameraTex, uv + dx + dy).xyz;
        diagAvg = (nw + ne + sw + se) * 0.25;
        smoothRgb = (c * 0.34) + (crossAvg * 0.42) + (diagAvg * 0.24);
        minRgb = min(minRgb, min(min(nw, ne), min(sw, se)));
        maxRgb = max(maxRgb, max(max(nw, ne), max(sw, se)));
    }
    if (mode >= 1.5 && mode < 2.5) {
        vec3 nn = texture(cameraTex, uv - (dy * 2.0)).xyz;
        vec3 ss = texture(cameraTex, uv + (dy * 2.0)).xyz;
        vec3 ww = texture(cameraTex, uv - (dx * 2.0)).xyz;
        vec3 ee = texture(cameraTex, uv + (dx * 2.0)).xyz;
        vec3 farAvg = (nn + ss + ww + ee) * 0.25;
        smoothRgb = (c * 0.18) + (crossAvg * 0.34) + (diagAvg * 0.22) + (farAvg * 0.26);
        minRgb = min(minRgb, min(min(nn, ss), min(ww, ee)));
        maxRgb = max(maxRgb, max(max(nn, ss), max(ww, ee)));
    } else if (mode >= 2.5) {
        smoothRgb = (c * 0.44) + (crossAvg * 0.36) + (diagAvg * 0.20);
    }

    float y = lumaOf(c);
    float smoothY = lumaOf(smoothRgb);
    float sampleContrast = max(max(abs(lumaOf(n) - y), abs(lumaOf(s) - y)), max(abs(lumaOf(w) - y), abs(lumaOf(e) - y)));
    float edge = smoothstep(0.02, 0.14, sampleContrast);
    float edgeReduction = edge * edgePreserve;
    float lumaMix = lumaMixBase * (1.0 - edgeReduction);
    float chromaMix = chromaMixBase * (1.0 - (edgeReduction * 0.35));
    vec3 chroma = c - vec3(y);
    vec3 smoothChroma = smoothRgb - vec3(smoothY);
    float filteredY = mix(y, smoothY, lumaMix);
    vec3 filteredChroma = mix(chroma, smoothChroma, vec3(chromaMix));
    vec3 filteredColor = recombineLumaChroma(filteredY, filteredChroma);

    float detail = y - smoothY;
    float detailGate = mix(0.55, 1.0, edge);
    filteredColor += vec3((detail * detailBoost) * detailGate);
    vec3 clampPad = vec3(0.035 + (0.035 * detailBoost));
    filteredColor = clamp(filteredColor, minRgb - clampPad, maxRgb + clampPad);
    filteredColor = ((filteredColor - vec3(0.5)) * colorContrast) + vec3(0.5);
    filteredColor = (filteredColor * colorGain) + vec3(colorBrightness);
    outColor = vec4(clamp(filteredColor, vec3(0.0), vec3(1.0)), c4.w);
}
