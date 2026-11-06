//! Present-path kernels: viewport crop and RGBA<->BGRA swizzle.
//!
//! Both are pure byte movement, so parity with the Python references is
//! bit-exact by construction. Sources may carry arbitrary buffer-protocol
//! strides (bytes, possibly negative); destinations are always C-contiguous
//! because the caller allocates them.

/// Source view over a strided `(H, W, 4)` uint8 buffer.
pub struct StridedFrame<'a> {
    pub data: &'a [u8],
    /// Byte offset of element (0, 0, 0) within `data`.
    pub origin: isize,
    pub row_stride: isize,
    pub col_stride: isize,
    pub channel_stride: isize,
    pub height: usize,
    pub width: usize,
}

impl<'a> StridedFrame<'a> {
    #[inline]
    fn pixel(&self, y: usize, x: usize) -> &'a [u8] {
        let offset = self.origin
            + y as isize * self.row_stride
            + x as isize * self.col_stride;
        let channel = self.channel_stride;
        if channel == 1 {
            &self.data[offset as usize..offset as usize + 4]
        } else {
            // General (unusual) channel stride: gather via a small copy.
            // Kept out of the hot path by `pixel_is_packed`.
            unreachable!("pixel() requires packed channels; use gather_pixel")
        }
    }

    #[inline]
    fn gather_pixel(&self, y: usize, x: usize) -> [u8; 4] {
        let base = self.origin
            + y as isize * self.row_stride
            + x as isize * self.col_stride;
        let c = self.channel_stride;
        [
            self.data[base as usize],
            self.data[(base + c) as usize],
            self.data[(base + 2 * c) as usize],
            self.data[(base + 3 * c) as usize],
        ]
    }

    #[inline]
    fn channels_packed(&self) -> bool {
        self.channel_stride == 1
    }

    #[inline]
    fn cols_packed(&self) -> bool {
        self.col_stride == 4 && self.channel_stride == 1
    }
}

/// Crop a `(H, W, 4)` viewport out of `src`, wrapping per axis when requested.
///
/// Bit-exact with `display_runtime._crop_viewport`'s Python reference loop:
/// non-wrapped axes must already be in bounds (the WindowMatrix viewport
/// normalizer guarantees this), wrapped axes use Python-style modulo
/// (`rem_euclid`), so negative origins wrap the same way.
#[allow(clippy::too_many_arguments)]
pub fn crop_viewport_rgba_u8(
    src: &StridedFrame,
    x: i64,
    y: i64,
    width: usize,
    height: usize,
    wrap_x: bool,
    wrap_y: bool,
    dst: &mut [u8],
) -> Result<(), String> {
    let src_w = src.width as i64;
    let src_h = src.height as i64;
    let width_i = width as i64;
    let height_i = height as i64;
    if !wrap_x && (x < 0 || x + width_i > src_w) {
        return Err(format!("viewport x bounds exceed source dimensions: x={x} width={width} source_width={src_w}"));
    }
    if !wrap_y && (y < 0 || y + height_i > src_h) {
        return Err(format!("viewport y bounds exceed source dimensions: y={y} height={height} source_height={src_h}"));
    }
    if dst.len() != width * height * 4 {
        return Err(format!("destination buffer length mismatch: {} != {}", dst.len(), width * height * 4));
    }

    let packed = src.channels_packed();
    for dy in 0..height {
        let sy = if wrap_y {
            (y + dy as i64).rem_euclid(src_h) as usize
        } else {
            (y + dy as i64) as usize
        };
        let dst_row = &mut dst[dy * width * 4..(dy + 1) * width * 4];
        if src.cols_packed() {
            // Row fast path: contiguous 4-byte pixels, wrap handled as two runs.
            let row_base = (src.origin + sy as isize * src.row_stride) as usize;
            if wrap_x {
                for dx in 0..width {
                    let sx = (x + dx as i64).rem_euclid(src_w) as usize;
                    let so = row_base + sx * 4;
                    dst_row[dx * 4..dx * 4 + 4].copy_from_slice(&src.data[so..so + 4]);
                }
            } else {
                let so = row_base + x as usize * 4;
                dst_row.copy_from_slice(&src.data[so..so + width * 4]);
            }
        } else if packed {
            for dx in 0..width {
                let sx = if wrap_x {
                    (x + dx as i64).rem_euclid(src_w) as usize
                } else {
                    (x + dx as i64) as usize
                };
                dst_row[dx * 4..dx * 4 + 4].copy_from_slice(src.pixel(sy, sx));
            }
        } else {
            for dx in 0..width {
                let sx = if wrap_x {
                    (x + dx as i64).rem_euclid(src_w) as usize
                } else {
                    (x + dx as i64) as usize
                };
                let px = src.gather_pixel(sy, sx);
                dst_row[dx * 4..dx * 4 + 4].copy_from_slice(&px);
            }
        }
    }
    Ok(())
}

/// Swap the R and B channels of an `(H, W, 4)` frame (RGBA<->BGRA).
///
/// Bit-exact with the numpy reference `src[:, :, [2, 1, 0, 3]]`.
pub fn swizzle_rgba_bgra_u8(src: &StridedFrame, dst: &mut [u8]) -> Result<(), String> {
    if dst.len() != src.width * src.height * 4 {
        return Err(format!("destination buffer length mismatch: {} != {}", dst.len(), src.width * src.height * 4));
    }
    let width = src.width;
    let packed = src.channels_packed();
    for sy in 0..src.height {
        let dst_row = &mut dst[sy * width * 4..(sy + 1) * width * 4];
        if src.cols_packed() {
            let row_base = (src.origin + sy as isize * src.row_stride) as usize;
            let row = &src.data[row_base..row_base + width * 4];
            for (dx, px) in row.chunks_exact(4).enumerate() {
                dst_row[dx * 4] = px[2];
                dst_row[dx * 4 + 1] = px[1];
                dst_row[dx * 4 + 2] = px[0];
                dst_row[dx * 4 + 3] = px[3];
            }
        } else if packed {
            for sx in 0..width {
                let px = src.pixel(sy, sx);
                dst_row[sx * 4] = px[2];
                dst_row[sx * 4 + 1] = px[1];
                dst_row[sx * 4 + 2] = px[0];
                dst_row[sx * 4 + 3] = px[3];
            }
        } else {
            for sx in 0..width {
                let px = src.gather_pixel(sy, sx);
                dst_row[sx * 4] = px[2];
                dst_row[sx * 4 + 1] = px[1];
                dst_row[sx * 4 + 2] = px[0];
                dst_row[sx * 4 + 3] = px[3];
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame(width: usize, height: usize) -> Vec<u8> {
        let mut data = vec![0u8; width * height * 4];
        for (i, v) in data.iter_mut().enumerate() {
            *v = (i % 251) as u8;
        }
        data
    }

    fn packed(src: &[u8], width: usize, height: usize) -> StridedFrame<'_> {
        StridedFrame {
            data: src,
            origin: 0,
            row_stride: width as isize * 4,
            col_stride: 4,
            channel_stride: 1,
            height,
            width,
        }
    }

    #[test]
    fn crop_without_wrap_matches_manual_indexing() {
        let src = frame(4, 3);
        let view = packed(&src, 4, 3);
        let mut dst = vec![0u8; 2 * 2 * 4];
        crop_viewport_rgba_u8(&view, 1, 1, 2, 2, false, false, &mut dst).unwrap();
        for dy in 0..2 {
            for dx in 0..2 {
                let so = ((1 + dy) * 4 + (1 + dx)) * 4;
                assert_eq!(&dst[(dy * 2 + dx) * 4..(dy * 2 + dx) * 4 + 4], &src[so..so + 4]);
            }
        }
    }

    #[test]
    fn crop_wrap_uses_python_modulo_for_negative_origins() {
        let src = frame(4, 3);
        let view = packed(&src, 4, 3);
        let mut dst = vec![0u8; 3 * 3 * 4];
        crop_viewport_rgba_u8(&view, -1, -1, 3, 3, true, true, &mut dst).unwrap();
        for dy in 0..3i64 {
            for dx in 0..3i64 {
                let sx = (dx - 1).rem_euclid(4) as usize;
                let sy = (dy - 1).rem_euclid(3) as usize;
                let so = (sy * 4 + sx) * 4;
                let di = (dy as usize * 3 + dx as usize) * 4;
                assert_eq!(&dst[di..di + 4], &src[so..so + 4]);
            }
        }
    }

    #[test]
    fn crop_rejects_out_of_bounds_without_wrap() {
        let src = frame(4, 4);
        let view = packed(&src, 4, 4);
        let mut dst = vec![0u8; 4 * 4 * 4];
        assert!(crop_viewport_rgba_u8(&view, 3, 0, 4, 4, false, false, &mut dst).is_err());
        assert!(crop_viewport_rgba_u8(&view, -1, 0, 4, 4, false, false, &mut dst).is_err());
        assert!(crop_viewport_rgba_u8(&view, 0, 0, 4, 4, false, false, &mut dst[..8]).is_err());
    }

    #[test]
    fn crop_reads_strided_source() {
        // Emulate a row-strided view (every other row of a taller buffer).
        let tall = frame(4, 6);
        let view = StridedFrame {
            data: &tall,
            origin: 0,
            row_stride: 2 * 4 * 4,
            col_stride: 4,
            channel_stride: 1,
            height: 3,
            width: 4,
        };
        let mut dst = vec![0u8; 4 * 3 * 4];
        crop_viewport_rgba_u8(&view, 0, 0, 4, 3, false, false, &mut dst).unwrap();
        for dy in 0..3 {
            let so = dy * 2 * 4 * 4;
            assert_eq!(&dst[dy * 16..(dy + 1) * 16], &tall[so..so + 16]);
        }
    }

    #[test]
    fn swizzle_swaps_red_and_blue() {
        let src = frame(5, 3);
        let view = packed(&src, 5, 3);
        let mut dst = vec![0u8; src.len()];
        swizzle_rgba_bgra_u8(&view, &mut dst).unwrap();
        for px in 0..15 {
            let o = px * 4;
            assert_eq!(dst[o], src[o + 2]);
            assert_eq!(dst[o + 1], src[o + 1]);
            assert_eq!(dst[o + 2], src[o]);
            assert_eq!(dst[o + 3], src[o + 3]);
        }
    }
}
