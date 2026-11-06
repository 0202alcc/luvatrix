//! WindowMatrix write-op engine: in-place application of Replace*/Push*/ShiftFrame
//! operations with WindowMatrix-compatible dirty-rect semantics.

#[derive(Debug)]
pub enum Op<'a> {
    ReplaceRect { x: i64, y: i64, width: i64, height: i64, payload: &'a [u8] },
    ReplaceRow { index: i64, payload: &'a [u8] },
    ReplaceColumn { index: i64, payload: &'a [u8] },
    PushRow { index: i64, payload: &'a [u8] },
    PushColumn { index: i64, payload: &'a [u8] },
    Shift { dx: i64, dy: i64, fill: [u8; 4] },
    /// Row-major 4x4 color matrix: out channel k = sum_j px_j * matrix[k*4+j].
    Multiply { matrix: [f32; 16] },
}

pub type DirtyRect = Option<(i64, i64, i64, i64)>;

fn validate_index(index: i64, upper_bound: i64, label: &str) -> Result<(), String> {
    if index < 0 || index >= upper_bound {
        return Err(format!("{label} out of range: {index}"));
    }
    Ok(())
}

fn validate_rect(
    x: i64,
    y: i64,
    width: i64,
    height: i64,
    matrix_width: i64,
    matrix_height: i64,
) -> Result<(), String> {
    if width <= 0 || height <= 0 {
        return Err("rect width/height must be > 0".to_string());
    }
    if x < 0 || y < 0 {
        return Err("rect x/y must be >= 0".to_string());
    }
    if x + width > matrix_width || y + height > matrix_height {
        return Err("rect exceeds matrix bounds".to_string());
    }
    Ok(())
}

fn union_dirty_rect(first: DirtyRect, second: DirtyRect) -> DirtyRect {
    let (first, second) = match (first, second) {
        (None, _) | (_, None) => return None,
        (Some(a), Some(b)) => (a, b),
    };
    if first.2 == 0 || first.3 == 0 {
        return Some(second);
    }
    if second.2 == 0 || second.3 == 0 {
        return Some(first);
    }
    let left = first.0.min(second.0);
    let top = first.1.min(second.1);
    let right = (first.0 + first.2).max(second.0 + second.2);
    let bottom = (first.1 + first.3).max(second.1 + second.3);
    Some((left, top, right - left, bottom - top))
}

/// Mirrors `_dirty_rect_for_operations` in window_matrix.py.
pub fn dirty_rect_for_ops(ops: &[Op<'_>], matrix_width: i64, matrix_height: i64) -> DirtyRect {
    let mut rect: DirtyRect = Some((0, 0, 0, 0));
    for op in ops {
        let candidate = match op {
            Op::Shift { .. } | Op::Multiply { .. } => return None,
            Op::ReplaceRect { x, y, width, height, .. } => Some((*x, *y, *width, *height)),
            Op::ReplaceColumn { index, .. } => Some((*index, 0, 1, matrix_height)),
            Op::PushColumn { index, .. } => Some((*index, 0, matrix_width - index, matrix_height)),
            Op::ReplaceRow { index, .. } => Some((0, *index, matrix_width, 1)),
            Op::PushRow { index, .. } => Some((0, *index, matrix_width, matrix_height - index)),
        };
        rect = union_dirty_rect(rect, candidate);
    }
    rect
}

/// Validate every op up-front so a failing batch never partially mutates the
/// matrix (same observable behavior as the staged-clone path).
pub fn validate_ops(ops: &[Op<'_>], width: i64, height: i64) -> Result<(), String> {
    for op in ops {
        match op {
            Op::ReplaceRect { x, y, width: w, height: h, payload } => {
                validate_rect(*x, *y, *w, *h, width, height)?;
                if payload.len() != (*w * *h * 4) as usize {
                    return Err(format!(
                        "rect payload length mismatch: {} != {}",
                        payload.len(),
                        *w * *h * 4
                    ));
                }
            }
            Op::ReplaceRow { index, payload } | Op::PushRow { index, payload } => {
                validate_index(*index, height, "row index")?;
                if payload.len() != (width * 4) as usize {
                    return Err(format!(
                        "row payload length mismatch: {} != {}",
                        payload.len(),
                        width * 4
                    ));
                }
            }
            Op::ReplaceColumn { index, payload } | Op::PushColumn { index, payload } => {
                validate_index(*index, width, "column index")?;
                if payload.len() != (height * 4) as usize {
                    return Err(format!(
                        "column payload length mismatch: {} != {}",
                        payload.len(),
                        height * 4
                    ));
                }
            }
            Op::Shift { .. } => {}
            Op::Multiply { matrix } => {
                if matrix.iter().any(|value| !value.is_finite()) {
                    return Err("color_matrix_4x4 must contain only finite values".to_string());
                }
            }
        }
    }
    Ok(())
}

fn fill_region(buf: &mut [u8], matrix_width: i64, x0: i64, y0: i64, w: i64, h: i64, fill: [u8; 4]) {
    if w <= 0 || h <= 0 {
        return;
    }
    for row in y0..y0 + h {
        let start = (row * matrix_width + x0) as usize * 4;
        let end = start + w as usize * 4;
        let line = &mut buf[start..end];
        for px in line.chunks_exact_mut(4) {
            px.copy_from_slice(&fill);
        }
    }
}

/// Apply validated ops in place. Returns the batch dirty rect (None = global).
pub fn apply_ops(buf: &mut [u8], width: i64, height: i64, ops: &[Op<'_>]) -> DirtyRect {
    let w = width as usize;
    let h = height as usize;
    for op in ops {
        match op {
            Op::ReplaceRect { x, y, width: rw, height: rh, payload } => {
                let (x, y, rw, rh) = (*x as usize, *y as usize, *rw as usize, *rh as usize);
                for row in 0..rh {
                    let dst = ((y + row) * w + x) * 4;
                    let src = row * rw * 4;
                    buf[dst..dst + rw * 4].copy_from_slice(&payload[src..src + rw * 4]);
                }
            }
            Op::ReplaceRow { index, payload } => {
                let start = *index as usize * w * 4;
                buf[start..start + w * 4].copy_from_slice(payload);
            }
            Op::ReplaceColumn { index, payload } => {
                let col = *index as usize;
                for row in 0..h {
                    let dst = (row * w + col) * 4;
                    buf[dst..dst + 4].copy_from_slice(&payload[row * 4..row * 4 + 4]);
                }
            }
            Op::PushRow { index, payload } => {
                let index = *index as usize;
                let row_bytes = w * 4;
                if index < h - 1 {
                    let start = index * row_bytes;
                    let len = (h - 1 - index) * row_bytes;
                    unsafe {
                        std::ptr::copy(
                            buf.as_ptr().add(start),
                            buf.as_mut_ptr().add(start + row_bytes),
                            len,
                        );
                    }
                }
                let start = index * row_bytes;
                buf[start..start + row_bytes].copy_from_slice(payload);
            }
            Op::PushColumn { index, payload } => {
                let index = *index as usize;
                if index < w - 1 {
                    let len = (w - 1 - index) * 4;
                    for row in 0..h {
                        let src = (row * w + index) * 4;
                        unsafe {
                            std::ptr::copy(
                                buf.as_ptr().add(src),
                                buf.as_mut_ptr().add(src + 4),
                                len,
                            );
                        }
                    }
                }
                for row in 0..h {
                    let dst = (row * w + index) * 4;
                    buf[dst..dst + 4].copy_from_slice(&payload[row * 4..row * 4 + 4]);
                }
            }
            Op::Shift { dx, dy, fill } => {
                shift_frame(buf, width, height, *dx, *dy, *fill);
            }
            Op::Multiply { matrix } => {
                // float32 matmul like torch/numpy, then round-ties-even, clip,
                // truncate (mirrors WindowMatrix._apply_operation).
                for px in buf.chunks_exact_mut(4) {
                    let p = [px[0] as f32, px[1] as f32, px[2] as f32, px[3] as f32];
                    for (k, channel) in px.iter_mut().enumerate() {
                        let row = &matrix[k * 4..k * 4 + 4];
                        let acc = ((p[0] * row[0] + p[1] * row[1]) + p[2] * row[2]) + p[3] * row[3];
                        *channel = acc.round_ties_even().clamp(0.0, 255.0) as u8;
                    }
                }
            }
        }
    }
    dirty_rect_for_ops(ops, width, height)
}

fn shift_frame(buf: &mut [u8], width: i64, height: i64, dx: i64, dy: i64, fill: [u8; 4]) {
    let w = width as usize;
    if dx.abs() >= width || dy.abs() >= height {
        fill_region(buf, width, 0, 0, width, height, fill);
        return;
    }
    let src_x = 0.max(-dx);
    let dst_x = 0.max(dx);
    let move_w = width - dx.abs();
    let src_y = 0.max(-dy);
    let dst_y = 0.max(dy);
    let move_h = height - dy.abs();
    if move_w > 0 && move_h > 0 {
        // Iterate destination rows so each write never clobbers an unread
        // source row: bottom-up when shifting down, top-down otherwise.
        let indices: Vec<i64> = if dy > 0 {
            (0..move_h).rev().collect()
        } else {
            (0..move_h).collect()
        };
        for i in indices {
            let sy = (src_y + i) as usize;
            let dy_row = (dst_y + i) as usize;
            let src_off = (sy * w + src_x as usize) * 4;
            let dst_off = (dy_row * w + dst_x as usize) * 4;
            unsafe {
                std::ptr::copy(
                    buf.as_ptr().add(src_off),
                    buf.as_mut_ptr().add(dst_off),
                    move_w as usize * 4,
                );
            }
            // Fill the horizontal strip vacated within a moved row.
            if dx > 0 {
                fill_region(buf, width, 0, dst_y + i, dx, 1, fill);
            } else if dx < 0 {
                fill_region(buf, width, width + dx, dst_y + i, -dx, 1, fill);
            }
        }
    }
    // Fill the vacated row band.
    if dy > 0 {
        fill_region(buf, width, 0, 0, width, dy, fill);
    } else if dy < 0 {
        fill_region(buf, width, 0, height + dy, width, -dy, fill);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn px(v: u8) -> [u8; 4] {
        [v, v, v, 255]
    }

    #[test]
    fn shift_down_fills_top_rows() {
        let mut buf = vec![0u8; 4 * 4 * 4];
        for (i, chunk) in buf.chunks_exact_mut(4).enumerate() {
            chunk.copy_from_slice(&px(i as u8));
        }
        apply_ops(&mut buf, 4, 4, &[Op::Shift { dx: 0, dy: 1, fill: px(9) }]);
        assert_eq!(&buf[0..4], &px(9));
        assert_eq!(&buf[16..20], &px(0)); // old row 0 pixel 0 now at row 1
        assert_eq!(&buf[20..24], &px(1));
    }

    #[test]
    fn shift_beyond_bounds_fills_everything() {
        let mut buf = vec![3u8; 4 * 4 * 4];
        apply_ops(&mut buf, 4, 4, &[Op::Shift { dx: 4, dy: 0, fill: px(7) }]);
        assert!(buf.chunks_exact(4).all(|c| c == px(7)));
    }

    #[test]
    fn push_row_shifts_down() {
        let mut buf = vec![0u8; 3 * 3 * 4];
        for (i, chunk) in buf.chunks_exact_mut(4).enumerate() {
            chunk.copy_from_slice(&px(i as u8));
        }
        let mut payload = Vec::new();
        for _ in 0..3 {
            payload.extend_from_slice(&px(5));
        }
        apply_ops(&mut buf, 3, 3, &[Op::PushRow { index: 0, payload: &payload }]);
        assert_eq!(&buf[12..16], &px(0));
        assert_eq!(&buf[24..28], &px(3));
        assert_eq!(&buf[0..4], &px(5));
    }
}
