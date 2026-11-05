//! Alpha compositing primitives, bit-exact ports of the Cython reference in
//! `luvatrix_core/_accel_native.pyx` (and the pure-Python fallback in
//! `luvatrix_core/accel.py`).

#[allow(clippy::too_many_arguments)]
pub fn alpha_blit_rgba_u8(
    destination: &mut [u8],
    destination_width: usize,
    source: &[u8],
    source_width: usize,
    mask: Option<&[u8]>,
    mask_width: usize,
    mask_channels: usize,
    destination_x0: usize,
    destination_y0: usize,
    source_x0: usize,
    source_y0: usize,
    copy_width: usize,
    copy_height: usize,
) {
    for row in 0..copy_height {
        for column in 0..copy_width {
            let source_pixel = ((source_y0 + row) * source_width + source_x0 + column) * 4;
            let destination_pixel =
                ((destination_y0 + row) * destination_width + destination_x0 + column) * 4;
            let source_alpha = match mask {
                Some(mask) => {
                    let mask_pixel =
                        ((source_y0 + row) * mask_width + source_x0 + column) * mask_channels;
                    let coverage = i32::from(mask[mask_pixel]);
                    (i32::from(source[source_pixel + 3]) * coverage + 127) / 255
                }
                None => i32::from(source[source_pixel + 3]),
            };
            if source_alpha <= 0 {
                continue;
            }
            let destination_alpha = i32::from(destination[destination_pixel + 3]);
            let output_alpha =
                source_alpha + (destination_alpha * (255 - source_alpha) + 127) / 255;
            let denominator = output_alpha * 255;
            for channel in 0..3 {
                let numerator = i32::from(source[source_pixel + channel]) * source_alpha * 255
                    + i32::from(destination[destination_pixel + channel])
                        * destination_alpha
                        * (255 - source_alpha);
                let output = if denominator <= 0 {
                    0
                } else {
                    (numerator + denominator / 2) / denominator
                };
                destination[destination_pixel + channel] = output.clamp(0, 255) as u8;
            }
            destination[destination_pixel + 3] = output_alpha as u8;
        }
    }
}

fn round_half_even(value: f64) -> i64 {
    // Matches the Cython `_round_half_even`: floor + fraction comparison.
    let whole = value.floor();
    let fraction = value - whole;
    let whole_i = whole as i64;
    if fraction > 0.5 || (fraction == 0.5 && whole_i % 2 != 0) {
        whole_i + 1
    } else {
        whole_i
    }
}

#[allow(clippy::too_many_arguments)]
pub fn blend_solid_mask_rgba_u8(
    destination: &mut [u8],
    frame_width: usize,
    frame_height: usize,
    mask: &[u8],
    mask_width: usize,
    mask_height: usize,
    x: i64,
    y: i64,
    color: [u8; 4],
) {
    for mask_y in 0..mask_height {
        let frame_y = y + mask_y as i64;
        if frame_y < 0 || frame_y >= frame_height as i64 {
            continue;
        }
        for mask_x in 0..mask_width {
            let frame_x = x + mask_x as i64;
            if frame_x < 0 || frame_x >= frame_width as i64 {
                continue;
            }
            let coverage = i32::from(mask[mask_y * mask_width + mask_x]);
            if coverage <= 0 {
                continue;
            }
            let source_alpha = (coverage as f64 / 255.0) * (f64::from(color[3]) / 255.0);
            let pixel = (frame_y as usize * frame_width + frame_x as usize) * 4;
            let destination_alpha = f64::from(destination[pixel + 3]) / 255.0;
            let output_alpha = source_alpha + destination_alpha * (1.0 - source_alpha);
            let safe_alpha = if output_alpha > 1e-6 { output_alpha } else { 1.0 };
            for channel in 0..3 {
                let output = (f64::from(color[channel]) * source_alpha
                    + f64::from(destination[pixel + channel])
                        * destination_alpha
                        * (1.0 - source_alpha))
                    / safe_alpha;
                destination[pixel + channel] = round_half_even(output).clamp(0, 255) as u8;
            }
            destination[pixel + 3] = round_half_even(output_alpha * 255.0).clamp(0, 255) as u8;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opaque_source_overwrites() {
        let mut dst = vec![0u8; 4 * 4 * 4];
        let mut src = vec![0u8; 4 * 4];
        for px in src.chunks_mut(4) {
            px[0] = 200;
            px[1] = 100;
            px[2] = 50;
            px[3] = 255;
        }
        alpha_blit_rgba_u8(&mut dst, 4, &src, 2, None, 0, 1, 1, 1, 0, 0, 2, 2);
        assert_eq!(&dst[5 * 4..5 * 4 + 4], &[200, 100, 50, 255]);
    }

    #[test]
    fn zero_alpha_is_noop() {
        let mut dst = vec![7u8; 4 * 4];
        let src = vec![0u8; 4 * 4];
        alpha_blit_rgba_u8(&mut dst, 1, &src, 1, None, 0, 1, 0, 0, 0, 0, 1, 1);
        assert_eq!(dst, vec![7u8; 4 * 4]);
    }
}
