//! Scene lowering: rasterize 2D scene nodes into an RGBA matrix buffer.
//!
//! Bit-exact port of the numpy paths in `luvatrix_core/core/scene_rasterizer.py`.
//! Node coordinates arrive pre-scaled to display space (the Python glue applies
//! sx/sy exactly like the Python rasterizer does).

#[derive(Debug)]
pub enum RasterOp {
    Clear { color: [u8; 4] },
    Rect { x: f64, y: f64, width: f64, height: f64, color: [u8; 4] },
    RoundedRect { x: f64, y: f64, width: f64, height: f64, radius: f64, color: [u8; 4] },
    Circle { cx: f64, cy: f64, radius: f64, stroke_width: f64, fill: [u8; 4], stroke: [u8; 4] },
    Rainbow { t: f64, rotation: f64, scroll_y: f64 },
    Paste { x: i64, y: i64, width: i64, height: i64, payload: Vec<u8> },
    MaskBlend { x: i64, y: i64, width: i64, height: i64, mask: Vec<u8>, color: [u8; 4] },
}

/// `round()` in Python is ties-to-even; match it for geometry snapping.
fn py_round(value: f64) -> i64 {
    value.round_ties_even() as i64
}

#[inline]
fn put_px(buf: &mut [u8], offset: usize, color: [u8; 4]) {
    buf[offset..offset + 4].copy_from_slice(&color);
}

/// f32 source-over used by the numpy rect/mask paths (weak scalar promotion
/// keeps the computation in float32; astype(uint8) truncates).
#[inline]
fn blend_channel_f32(src: u8, dst: u8, alpha_f64: f64) -> u8 {
    let alpha = alpha_f64 as f32;
    let one_minus = (1.0 - alpha_f64) as f32;
    let value = (src as f32) * alpha + (dst as f32) * one_minus;
    value.clamp(0.0, 255.0) as u8
}

#[inline]
fn blend_px_f32(buf: &mut [u8], offset: usize, color: [u8; 4], alpha_f64: f64) {
    for channel in 0..3 {
        buf[offset + channel] = blend_channel_f32(color[channel], buf[offset + channel], alpha_f64);
    }
    buf[offset + 3] = 255;
}

pub fn prepare(buf: &mut [u8]) {
    // `out[:, :, 3] = 255` before drawing, leaving stale RGB in reused buffers.
    for px in buf.chunks_exact_mut(4) {
        px[3] = 255;
    }
}

pub fn rasterize(buf: &mut [u8], width: i64, height: i64, ops: &[RasterOp]) {
    for op in ops {
        match op {
            RasterOp::Clear { color } => clear(buf, *color),
            RasterOp::Rect { x, y, width: w, height: h, color } => {
                draw_rect(buf, width, height, *x, *y, *w, *h, *color);
            }
            RasterOp::RoundedRect { x, y, width: w, height: h, radius, color } => {
                draw_rounded_rect(buf, width, height, *x, *y, *w, *h, *radius, *color);
            }
            RasterOp::Circle { cx, cy, radius, stroke_width, fill, stroke } => {
                draw_circle(buf, width, height, *cx, *cy, *radius, *stroke_width, *fill, *stroke);
            }
            RasterOp::Rainbow { t, rotation, scroll_y } => {
                draw_rainbow(buf, width, height, *t, *rotation, *scroll_y);
            }
            RasterOp::Paste { x, y, width: w, height: h, payload } => {
                paste(buf, width, height, *x, *y, *w, *h, payload);
            }
            RasterOp::MaskBlend { x, y, width: w, height: h, mask, color } => {
                mask_blend(buf, width, height, *x, *y, *w, *h, mask, *color);
            }
        }
    }
}

fn clear(buf: &mut [u8], color: [u8; 4]) {
    for px in buf.chunks_exact_mut(4) {
        px.copy_from_slice(&color);
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_rect(
    buf: &mut [u8],
    frame_w: i64,
    frame_h: i64,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    color: [u8; 4],
) {
    let x0 = 0.max(py_round(x));
    let y0 = 0.max(py_round(y));
    let x1 = frame_w.min(py_round(x + width));
    let y1 = frame_h.min(py_round(y + height));
    if x1 <= x0 || y1 <= y0 {
        return;
    }
    let alpha = f64::from(color[3]) / 255.0;
    let opaque = alpha >= 0.999;
    for py in y0..y1 {
        let row = (py * frame_w) as usize;
        for px in x0..x1 {
            let offset = (row + px as usize) * 4;
            if opaque {
                put_px(buf, offset, color);
            } else {
                blend_px_f32(buf, offset, color, alpha);
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_rounded_rect(
    buf: &mut [u8],
    frame_w: i64,
    frame_h: i64,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    radius: f64,
    color: [u8; 4],
) {
    let x0 = 0.max(x.floor() as i64);
    let y0 = 0.max(y.floor() as i64);
    let x1 = frame_w.min((x + width).ceil() as i64);
    let y1 = frame_h.min((y + height).ceil() as i64);
    if x1 <= x0 || y1 <= y0 {
        return;
    }
    let r = 0.0f64.max(radius.min(width * 0.5).min(height * 0.5));
    let alpha = f64::from(color[3]) / 255.0;
    let opaque = alpha >= 0.999;
    // np.clip(float32_pixels, left, right) casts the f64 bounds down to f32.
    let left = (x + r) as f32;
    let right = (x + width - r) as f32;
    let top = (y + r) as f32;
    let bottom = (y + height - r) as f32;
    let rr = r * r;
    for py in y0..y1 {
        for px in x0..x1 {
            let inside = if r <= 0.0 {
                true
            } else {
                let nearest_x = (px as f32).clamp(left, right) as f64;
                let nearest_y = (py as f32).clamp(top, bottom) as f64;
                let dx = px as f64 - nearest_x;
                let dy = py as f64 - nearest_y;
                dx * dx + dy * dy <= rr
            };
            if !inside {
                continue;
            }
            let offset = (py * frame_w + px) as usize * 4;
            if opaque {
                put_px(buf, offset, color);
            } else {
                blend_px_f32(buf, offset, color, alpha);
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_circle(
    buf: &mut [u8],
    frame_w: i64,
    frame_h: i64,
    cx: f64,
    cy: f64,
    radius: f64,
    stroke_width: f64,
    fill: [u8; 4],
    stroke: [u8; 4],
) {
    let radius = radius.max(0.0);
    let x0 = 0.max((cx - radius - stroke_width - 1.0).floor() as i64);
    let y0 = 0.max((cy - radius - stroke_width - 1.0).floor() as i64);
    let x1 = frame_w.min((cx + radius + stroke_width + 1.0).ceil() as i64);
    let y1 = frame_h.min((cy + radius + stroke_width + 1.0).ceil() as i64);
    if x1 <= x0 || y1 <= y0 {
        return;
    }
    let draw_stroke = stroke_width > 0.0 && stroke[3] > 0;
    for py in y0..y1 {
        for px in x0..x1 {
            let dx = px as f64 - cx;
            let dy = py as f64 - cy;
            let dist = (dx * dx + dy * dy).sqrt();
            let offset = (py * frame_w + px) as usize * 4;
            if dist <= radius {
                put_px(buf, offset, fill);
            } else if draw_stroke && dist <= radius + stroke_width {
                put_px(buf, offset, stroke);
            }
        }
    }
}

/// Floored modulo like numpy's `%` on floats (result takes the divisor's sign).
fn numpy_mod_f32(value: f32, divisor: f32) -> f32 {
    value - (value / divisor).floor() * divisor
}

fn draw_rainbow(buf: &mut [u8], frame_w: i64, frame_h: i64, t: f64, rotation: f64, scroll_y: f64) {
    let w = frame_w.max(1) as f32;
    let h = frame_h.max(1) as f32;
    let phase = (t * 0.0025 + rotation * 0.01 + scroll_y * 0.002) as f32;
    let two_pi = 2.0f32 * std::f32::consts::PI;
    for py in 0..frame_h {
        let ny = py as f32 / h;
        for px in 0..frame_w {
            let nx = px as f32 / w;
            let wave = ((nx * 3.2 + ny * 2.4 + phase) * two_pi).sin() * 0.055;
            let hue = numpy_mod_f32(nx * 0.58 + ny * 0.42 + phase + wave, 1.0);
            let value = (0.78f32 + 0.16 * ((nx - ny + phase * 0.7) * two_pi).sin()).clamp(0.35, 0.95);
            let h6 = hue * 6.0;
            let i = h6.floor() as i32;
            // numpy: float32 hue*6 minus int32 i promotes to float64.
            let f = h6 as f64 - i as f64;
            let p = f64::from(value * ((1.0f64 - 0.82f64) as f32));
            let q = f64::from(value) * (1.0 - f * 0.82);
            let tv = f64::from(value) * (1.0 - (1.0 - f) * 0.82);
            let v64 = f64::from(value);
            // np.choose(i % 6, choices) per channel:
            //   r: [value, q, p, p, tv, value]
            //   g: [tv, value, value, q, p, p]
            //   b: [p, p, tv, value, value, q]
            let (r, g, b) = match i.rem_euclid(6) {
                0 => (v64, tv, p),
                1 => (q, v64, p),
                2 => (p, v64, tv),
                3 => (p, q, v64),
                4 => (tv, p, v64),
                _ => (v64, p, q),
            };
            let offset = (py * frame_w + px) as usize * 4;
            buf[offset] = (r * 255.0).clamp(0.0, 255.0) as u8;
            buf[offset + 1] = (g * 255.0).clamp(0.0, 255.0) as u8;
            buf[offset + 2] = (b * 255.0).clamp(0.0, 255.0) as u8;
            buf[offset + 3] = 255;
        }
    }
}

fn paste(
    buf: &mut [u8],
    frame_w: i64,
    frame_h: i64,
    x: i64,
    y: i64,
    width: i64,
    height: i64,
    payload: &[u8],
) {
    let x0 = 0.max(x);
    let y0 = 0.max(y);
    let x1 = frame_w.min(x + width);
    let y1 = frame_h.min(y + height);
    if x1 <= x0 || y1 <= y0 {
        return;
    }
    let src_x0 = x0 - x;
    let src_y0 = y0 - y;
    let copy_w = (x1 - x0) as usize;
    for row in 0..(y1 - y0) {
        let src = ((src_y0 + row) * width + src_x0) as usize * 4;
        let dst = ((y0 + row) * frame_w + x0) as usize * 4;
        buf[dst..dst + copy_w * 4].copy_from_slice(&payload[src..src + copy_w * 4]);
    }
}

#[allow(clippy::too_many_arguments)]
fn mask_blend(
    buf: &mut [u8],
    frame_w: i64,
    frame_h: i64,
    x: i64,
    y: i64,
    width: i64,
    height: i64,
    mask: &[u8],
    color: [u8; 4],
) {
    let x0 = 0.max(x);
    let y0 = 0.max(y);
    let x1 = frame_w.min(x + width);
    let y1 = frame_h.min(y + height);
    if x1 <= x0 || y1 <= y0 {
        return;
    }
    let color_alpha = (f64::from(color[3]) / 255.0) as f32;
    let src = [color[0] as f32, color[1] as f32, color[2] as f32];
    let mut any_alpha = false;
    for py in y0..y1 {
        for px in x0..x1 {
            let coverage = mask[((py - y) * width + (px - x)) as usize];
            let alpha = (coverage as f32 / 255.0) * color_alpha;
            if alpha <= 0.0 {
                continue;
            }
            any_alpha = true;
            let offset = (py * frame_w + px) as usize * 4;
            for channel in 0..3 {
                let dst = buf[offset + channel] as f32;
                let value = src[channel] * alpha + dst * (1.0 - alpha);
                buf[offset + channel] = value.clamp(0.0, 255.0) as u8;
            }
        }
    }
    if !any_alpha {
        return;
    }
    for py in y0..y1 {
        for px in x0..x1 {
            buf[(py * frame_w + px) as usize * 4 + 3] = 255;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rect_opaque_writes_all_channels() {
        let mut buf = vec![0u8; 4 * 4 * 4];
        draw_rect(&mut buf, 4, 4, 1.0, 1.0, 2.0, 2.0, [9, 8, 7, 255]);
        assert_eq!(&buf[(1 * 4 + 1) * 4..(1 * 4 + 1) * 4 + 4], &[9, 8, 7, 255]);
        assert_eq!(&buf[0..4], &[0, 0, 0, 0]);
    }

    #[test]
    fn rect_ties_even_rounding() {
        let mut buf = vec![0u8; 8 * 4];
        // Python round(2.5) == 2 and round(2.5 + 1.0) == round(3.5) == 4,
        // so the rect spans pixels [2, 4).
        draw_rect(&mut buf, 8, 1, 2.5, 0.0, 1.0, 1.0, [5, 5, 5, 255]);
        assert_eq!(&buf[8..12], &[5, 5, 5, 255]); // pixel 2
        assert_eq!(&buf[12..16], &[5, 5, 5, 255]); // pixel 3
        assert_eq!(&buf[4..8], &[0, 0, 0, 0]); // pixel 1 untouched
        assert_eq!(&buf[16..20], &[0, 0, 0, 0]); // pixel 4 untouched
    }

    #[test]
    fn circle_direct_assignment() {
        let mut buf = vec![0u8; 5 * 5 * 4];
        draw_circle(&mut buf, 5, 5, 2.0, 2.0, 1.5, 0.0, [1, 2, 3, 200], [0, 0, 0, 0]);
        assert_eq!(&buf[(2 * 5 + 2) * 4..(2 * 5 + 2) * 4 + 4], &[1, 2, 3, 200]);
    }
}
