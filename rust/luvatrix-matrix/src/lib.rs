//! `luvatrix_core._matrix_rs` — optional Rust matrix core.
//!
//! Exposes the same primitives as the Cython `_accel_native` extension plus the
//! WindowMatrix write-op engine and the 2D scene lowering, all operating on
//! caller-owned RGBA u8 buffers via the buffer protocol.

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyTuple};

mod blend;
mod ops;
mod raster;

fn writable_u8(obj: &Bound<'_, PyAny>) -> PyResult<(PyBuffer<u8>, *mut u8, usize)> {
    let buf = PyBuffer::<u8>::get(obj)?;
    if buf.readonly() {
        return Err(PyValueError::new_err("destination buffer must be writable"));
    }
    if !buf.is_c_contiguous() {
        return Err(PyValueError::new_err("destination buffer must be C-contiguous"));
    }
    let len = buf.item_count();
    let ptr = buf.buf_ptr() as *mut u8;
    Ok((buf, ptr, len))
}

fn readable_u8(obj: &Bound<'_, PyAny>) -> PyResult<(PyBuffer<u8>, *const u8, usize)> {
    let buf = PyBuffer::<u8>::get(obj)?;
    if !buf.is_c_contiguous() {
        return Err(PyValueError::new_err("source buffer must be C-contiguous"));
    }
    let len = buf.item_count();
    let ptr = buf.buf_ptr() as *const u8;
    Ok((buf, ptr, len))
}

fn non_negative(value: i64, label: &str) -> PyResult<usize> {
    if value < 0 {
        return Err(PyValueError::new_err(format!("{label} must be >= 0: {value}")));
    }
    Ok(value as usize)
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn alpha_blit_rgba_u8(
    destination: &Bound<'_, PyAny>,
    destination_width: i64,
    source: &Bound<'_, PyAny>,
    source_width: i64,
    mask: Option<&Bound<'_, PyAny>>,
    mask_width: i64,
    mask_channels: i64,
    destination_x0: i64,
    destination_y0: i64,
    source_x0: i64,
    source_y0: i64,
    copy_width: i64,
    copy_height: i64,
) -> PyResult<()> {
    let destination_width = non_negative(destination_width, "destination_width")?;
    let source_width = non_negative(source_width, "source_width")?;
    let mask_width = non_negative(mask_width, "mask_width")?;
    let mask_channels = non_negative(mask_channels, "mask_channels")?.max(1);
    let destination_x0 = non_negative(destination_x0, "destination_x0")?;
    let destination_y0 = non_negative(destination_y0, "destination_y0")?;
    let source_x0 = non_negative(source_x0, "source_x0")?;
    let source_y0 = non_negative(source_y0, "source_y0")?;
    let copy_width = non_negative(copy_width, "copy_width")?;
    let copy_height = non_negative(copy_height, "copy_height")?;

    let (_dst_guard, dst_ptr, dst_len) = writable_u8(destination)?;
    let (_src_guard, src_ptr, src_len) = readable_u8(source)?;
    let (_mask_guard, mask_ptr, mask_len) = match mask {
        Some(mask_obj) => {
            let (guard, ptr, len) = readable_u8(mask_obj)?;
            (Some(guard), Some(ptr), len)
        }
        None => (None, None, 0),
    };
    unsafe {
        let dst = std::slice::from_raw_parts_mut(dst_ptr, dst_len);
        let src = std::slice::from_raw_parts(src_ptr, src_len);
        let mask_slice = mask_ptr.map(|ptr| std::slice::from_raw_parts(ptr, mask_len));
        blend::alpha_blit_rgba_u8(
            dst,
            destination_width,
            src,
            source_width,
            mask_slice,
            mask_width,
            mask_channels,
            destination_x0,
            destination_y0,
            source_x0,
            source_y0,
            copy_width,
            copy_height,
        );
    }
    Ok(())
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn blend_solid_mask_rgba_u8(
    destination: &Bound<'_, PyAny>,
    frame_width: i64,
    frame_height: i64,
    mask: &Bound<'_, PyAny>,
    mask_width: i64,
    mask_height: i64,
    x: i64,
    y: i64,
    red: i64,
    green: i64,
    blue: i64,
    alpha: i64,
) -> PyResult<()> {
    let frame_width = non_negative(frame_width, "frame_width")?;
    let frame_height = non_negative(frame_height, "frame_height")?;
    let mask_width = non_negative(mask_width, "mask_width")?;
    let mask_height = non_negative(mask_height, "mask_height")?;
    for (value, label) in [(red, "red"), (green, "green"), (blue, "blue"), (alpha, "alpha")] {
        if !(0..=255).contains(&value) {
            return Err(PyValueError::new_err(format!("{label} must be in [0, 255]: {value}")));
        }
    }
    let (_dst_guard, dst_ptr, dst_len) = writable_u8(destination)?;
    let (_mask_guard, mask_ptr, mask_len) = readable_u8(mask)?;
    unsafe {
        let dst = std::slice::from_raw_parts_mut(dst_ptr, dst_len);
        let mask_slice = std::slice::from_raw_parts(mask_ptr, mask_len);
        blend::blend_solid_mask_rgba_u8(
            dst,
            frame_width,
            frame_height,
            mask_slice,
            mask_width,
            mask_height,
            x,
            y,
            [red as u8, green as u8, blue as u8, alpha as u8],
        );
    }
    Ok(())
}

/// Owns the buffer-protocol guards for the duration of one native call so op
/// payloads are read zero-copy straight out of Python-owned memory.
struct PayloadStore {
    guards: Vec<PyBuffer<u8>>,
    spans: Vec<(usize, usize)>,
}

impl PayloadStore {
    fn new() -> Self {
        Self { guards: Vec::new(), spans: Vec::new() }
    }

    fn stage(&mut self, obj: &Bound<'_, PyAny>) -> PyResult<usize> {
        let (buf, ptr, len) = readable_u8(obj)?;
        self.guards.push(buf);
        self.spans.push((ptr as usize, len));
        Ok(self.spans.len() - 1)
    }

    /// Returns a view of a staged payload with a caller-chosen lifetime.
    ///
    /// The slice points into Python memory kept alive by `self.guards`;
    /// pushing more guards never moves that memory, so the slice stays valid
    /// until the store is dropped. Callers must not let it outlive the store;
    /// in this crate every op is consumed before the store is dropped.
    fn slice<'a>(&self, idx: usize) -> &'a [u8] {
        let (ptr, len) = self.spans[idx];
        unsafe { std::slice::from_raw_parts(ptr as *const u8, len) }
    }
}

fn extract_color(tuple: &Bound<'_, PyTuple>, index: usize) -> PyResult<u8> {
    let value: i64 = tuple.get_item(index)?.extract()?;
    if !(0..=255).contains(&value) {
        return Err(PyValueError::new_err(format!("color channel out of range: {value}")));
    }
    Ok(value as u8)
}

fn color4(tuple: &Bound<'_, PyTuple>, base: usize) -> PyResult<[u8; 4]> {
    Ok([
        extract_color(tuple, base)?,
        extract_color(tuple, base + 1)?,
        extract_color(tuple, base + 2)?,
        extract_color(tuple, base + 3)?,
    ])
}

fn parse_ops<'a>(
    py_ops: &Bound<'_, PyList>,
    store: &'a mut PayloadStore,
) -> PyResult<Vec<ops::Op<'a>>> {
    let mut out = Vec::with_capacity(py_ops.len());
    for item in py_ops.iter() {
        let tuple = item.downcast::<PyTuple>()?;
        let kind: i64 = tuple.get_item(0)?.extract()?;
        let op = match kind {
            1 => {
                let idx = store.stage(&tuple.get_item(5)?)?;
                ops::Op::ReplaceRect {
                    x: tuple.get_item(1)?.extract()?,
                    y: tuple.get_item(2)?.extract()?,
                    width: tuple.get_item(3)?.extract()?,
                    height: tuple.get_item(4)?.extract()?,
                    payload: store.slice(idx),
                }
            }
            2 => {
                let idx = store.stage(&tuple.get_item(2)?)?;
                ops::Op::ReplaceRow {
                    index: tuple.get_item(1)?.extract()?,
                    payload: store.slice(idx),
                }
            }
            3 => {
                let idx = store.stage(&tuple.get_item(2)?)?;
                ops::Op::ReplaceColumn {
                    index: tuple.get_item(1)?.extract()?,
                    payload: store.slice(idx),
                }
            }
            4 => {
                let idx = store.stage(&tuple.get_item(2)?)?;
                ops::Op::PushRow {
                    index: tuple.get_item(1)?.extract()?,
                    payload: store.slice(idx),
                }
            }
            5 => {
                let idx = store.stage(&tuple.get_item(2)?)?;
                ops::Op::PushColumn {
                    index: tuple.get_item(1)?.extract()?,
                    payload: store.slice(idx),
                }
            }
            6 => ops::Op::Shift {
                dx: tuple.get_item(1)?.extract()?,
                dy: tuple.get_item(2)?.extract()?,
                fill: color4(tuple, 3)?,
            },
            other => {
                return Err(PyValueError::new_err(format!(
                    "unsupported encoded op kind: {other}"
                )))
            }
        };
        out.push(op);
    }
    Ok(out)
}

#[pyfunction]
fn apply_ops(
    destination: &Bound<'_, PyAny>,
    width: i64,
    height: i64,
    py_ops: &Bound<'_, PyList>,
) -> PyResult<Option<(i64, i64, i64, i64)>> {
    if width <= 0 || height <= 0 {
        return Err(PyValueError::new_err("width and height must be > 0"));
    }
    let mut store = PayloadStore::new();
    let parsed = parse_ops(py_ops, &mut store)?;
    ops::validate_ops(&parsed, width, height).map_err(PyValueError::new_err)?;
    let (_guard, ptr, len) = writable_u8(destination)?;
    let expected = (width * height * 4) as usize;
    if len != expected {
        return Err(PyValueError::new_err(format!(
            "destination buffer length mismatch: {len} != {expected}"
        )));
    }
    let slice = unsafe { std::slice::from_raw_parts_mut(ptr, len) };
    Ok(ops::apply_ops(slice, width, height, &parsed))
}

fn parse_raster_ops<'a>(
    py_ops: &Bound<'_, PyList>,
    store: &'a mut PayloadStore,
) -> PyResult<Vec<raster::RasterOp<'a>>> {
    let mut out = Vec::with_capacity(py_ops.len());
    for item in py_ops.iter() {
        let tuple = item.downcast::<PyTuple>()?;
        let kind: i64 = tuple.get_item(0)?.extract()?;
        let op = match kind {
            0 => raster::RasterOp::Clear { color: color4(tuple, 1)? },
            1 => raster::RasterOp::Rect {
                x: tuple.get_item(1)?.extract()?,
                y: tuple.get_item(2)?.extract()?,
                width: tuple.get_item(3)?.extract()?,
                height: tuple.get_item(4)?.extract()?,
                color: color4(tuple, 5)?,
            },
            2 => raster::RasterOp::RoundedRect {
                x: tuple.get_item(1)?.extract()?,
                y: tuple.get_item(2)?.extract()?,
                width: tuple.get_item(3)?.extract()?,
                height: tuple.get_item(4)?.extract()?,
                radius: tuple.get_item(5)?.extract()?,
                color: color4(tuple, 6)?,
            },
            3 => raster::RasterOp::Circle {
                cx: tuple.get_item(1)?.extract()?,
                cy: tuple.get_item(2)?.extract()?,
                radius: tuple.get_item(3)?.extract()?,
                stroke_width: tuple.get_item(4)?.extract()?,
                fill: color4(tuple, 5)?,
                stroke: color4(tuple, 9)?,
            },
            4 => raster::RasterOp::Rainbow {
                t: tuple.get_item(1)?.extract()?,
                rotation: tuple.get_item(2)?.extract()?,
                scroll_y: tuple.get_item(3)?.extract()?,
            },
            5 => {
                let idx = store.stage(&tuple.get_item(5)?)?;
                raster::RasterOp::Paste {
                    x: tuple.get_item(1)?.extract()?,
                    y: tuple.get_item(2)?.extract()?,
                    width: tuple.get_item(3)?.extract()?,
                    height: tuple.get_item(4)?.extract()?,
                    payload: store.slice(idx),
                }
            }
            6 => {
                let idx = store.stage(&tuple.get_item(5)?)?;
                raster::RasterOp::MaskBlend {
                    x: tuple.get_item(1)?.extract()?,
                    y: tuple.get_item(2)?.extract()?,
                    width: tuple.get_item(3)?.extract()?,
                    height: tuple.get_item(4)?.extract()?,
                    mask: store.slice(idx),
                    color: color4(tuple, 6)?,
                }
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "unsupported raster op kind: {other}"
                )))
            }
        };
        out.push(op);
    }
    Ok(out)
}

#[pyfunction]
fn rasterize(
    destination: &Bound<'_, PyAny>,
    width: i64,
    height: i64,
    py_ops: &Bound<'_, PyList>,
) -> PyResult<()> {
    if width <= 0 || height <= 0 {
        return Err(PyValueError::new_err("width and height must be > 0"));
    }
    let mut store = PayloadStore::new();
    let parsed = parse_raster_ops(py_ops, &mut store)?;
    let (_guard, ptr, len) = writable_u8(destination)?;
    let expected = (width * height * 4) as usize;
    if len != expected {
        return Err(PyValueError::new_err(format!(
            "destination buffer length mismatch: {len} != {expected}"
        )));
    }
    let slice = unsafe { std::slice::from_raw_parts_mut(ptr, len) };
    raster::prepare(slice);
    raster::rasterize(slice, width, height, &parsed);
    Ok(())
}

#[pymodule(gil_used = false)]
fn _matrix_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(alpha_blit_rgba_u8, m)?)?;
    m.add_function(wrap_pyfunction!(blend_solid_mask_rgba_u8, m)?)?;
    m.add_function(wrap_pyfunction!(apply_ops, m)?)?;
    m.add_function(wrap_pyfunction!(rasterize, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
