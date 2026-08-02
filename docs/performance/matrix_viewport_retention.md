# Retained Matrix Viewports

Matrix-first Android apps can keep a taller or wider Matrix in Vulkan memory
and move its visible window without rewriting the Matrix. This is intended for
scrolling content such as Schedule.

Configure a larger buffer in `app.toml`; values are Matrix pixels before
`render_scale` and must be at least the display extent.

```toml
[display]
matrix_content_width = 540
matrix_content_height = 2400
```

Move the viewport from the app without rebuilding the Matrix:

```python
app.set_matrix_viewport(0, scroll_y, 540, 1200)
```

`wrap_x` and `wrap_y` are available for cyclic content. Coordinates always use
Matrix pixel space. On Android Vulkan, the first frame uploads the full Matrix,
subsequent viewport-only frames issue a GPU texture-to-swapchain blit with no
RGBA/JNI payload. A `ReplaceRect` while the viewport is active uses the native
partial-upload path before that blit. Other targets preserve correctness with a
CPU crop until they implement a retained Matrix texture.

Run the contract-level traffic harness:

```sh
uv run python tools/perf/matrix_viewport_harness.py
```

For its default 540×2400 Matrix, `initial_upload_bytes` is 5,184,000 and
`viewport_update_upload_bytes` must remain zero. The elapsed time is host-side
contract overhead, not a substitute for device GPU profiling.
