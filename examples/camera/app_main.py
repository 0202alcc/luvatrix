from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Iterable

from luvatrix_core.core.sensor_manager import SensorSample
from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch


PLANNED_FRAME_MODES = (
    "YUV_420_888 live preview",
    "RAW_SENSOR capture",
)

CAMERA_SENSOR_CANDIDATES = (
    "camera.permission",
    "camera.device",
    "display.refresh",
)

HUD_MODES = ("collapsed", "compact", "debug")


@dataclass(frozen=True)
class CameraModeStatus:
    name: str
    state: str
    detail: str


@dataclass(frozen=True)
class TouchButton:
    action: str
    label: str
    x0: float
    y0: float
    x1: float
    y1: float

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


def format_camera_status_lines(samples: Iterable[SensorSample]) -> list[str]:
    by_type = {sample.sensor_type: sample for sample in samples}
    sensor_lines: list[str] = []
    for sensor_type in CAMERA_SENSOR_CANDIDATES:
        sample = by_type.get(sensor_type)
        if sample is None:
            sensor_lines.append(f"{sensor_type}: not sampled")
            continue
        sensor_lines.append(_format_sensor_sample_line(sample))

    camera = _camera_payload(by_type.get("camera.device"))
    if camera:
        inventory = camera.get("inventory") if isinstance(camera.get("inventory"), dict) else {}
        cameras = inventory.get("cameras") if isinstance(inventory.get("cameras"), list) else []
        active = camera.get("active_camera_ids") if isinstance(camera.get("active_camera_ids"), list) else []
        sensor_lines.append(
            "rear cameras: "
            f"{len(_rear_camera_ids(cameras))} active={','.join(str(x) for x in active) or '-'} "
            f"mode={camera.get('mode', '-')}"
        )
        physical_lines = _physical_camera_lines(cameras)
        sensor_lines.extend(physical_lines)
        sensor_lines.extend(_resolution_probe_lines(cameras, inventory))
        verdict = _hidden_sensor_verdict(cameras)
        if verdict:
            sensor_lines.append(verdict)
        probe_lines = _hidden_probe_lines(inventory.get("hidden_camera_probes"))
        sensor_lines.extend(probe_lines)
        sensor_lines.append(
            "dual preview: "
            f"{'supported' if camera.get('dual_supported') else 'unsupported'} "
            f"{'active' if camera.get('dual_active') else 'inactive'}"
        )
        matrix_line = _camera_matrix_line(camera)
        if matrix_line:
            sensor_lines.append(matrix_line)
        sensor_lines.extend(_raw_capture_lines(camera.get("raw_capture")))
        display = _display_payload(by_type.get("display.refresh"))
        sensor_lines.extend(_display_refresh_lines(display, camera))
        sensor_lines.extend(_preview_diagnostic_lines(camera))

    return sensor_lines


def format_camera_compact_status_lines(samples: Iterable[SensorSample], *, action_status: str = "") -> list[str]:
    by_type = {sample.sensor_type: sample for sample in samples}
    camera = _camera_payload(by_type.get("camera.device"))
    display = _display_payload(by_type.get("display.refresh"))
    if not camera:
        return ["camera: waiting for telemetry"]
    return _independent_variable_lines(camera, display)


def format_camera_collapsed_status_lines(samples: Iterable[SensorSample], *, action_status: str = "") -> list[str]:
    by_type = {sample.sensor_type: sample for sample in samples}
    camera = _camera_payload(by_type.get("camera.device"))
    display = _display_payload(by_type.get("display.refresh"))
    if not camera:
        return ["camera: waiting"]
    return _independent_variable_lines(camera, display)


def planned_camera_mode_statuses() -> list[CameraModeStatus]:
    return [
        CameraModeStatus(
            name="YUV_420_888 live preview",
            state="bridge pending",
            detail="reserved for continuous Android Camera2 ImageReader frames",
        ),
        CameraModeStatus(
            name="RAW_SENSOR capture",
            state="bridge pending",
            detail="reserved for devices advertising true RAW capability",
        ),
    ]


def _camera_payload(sample: SensorSample | None) -> dict[str, object]:
    if sample is None or not isinstance(sample.value, dict):
        return {}
    return sample.value


def _display_payload(sample: SensorSample | None) -> dict[str, object]:
    if sample is None or not isinstance(sample.value, dict):
        return {}
    return sample.value


def _rear_camera_ids(cameras: object) -> list[str]:
    if not isinstance(cameras, list):
        return []
    out: list[str] = []
    for item in cameras:
        if isinstance(item, dict) and item.get("facing") == "back":
            camera_id = item.get("camera_id", item.get("id"))
            if camera_id is not None:
                out.append(str(camera_id))
    return out


def _camera_matrix_line(camera: dict[str, object]) -> str:
    for source_key, slot_key in (("streams", "primary"), ("native", "slots")):
        source = camera.get(source_key)
        if not isinstance(source, dict):
            continue
        slot = source.get(slot_key)
        if source_key == "native" and isinstance(slot, dict):
            slot = slot.get("primary")
        if not isinstance(slot, dict):
            continue
        width = slot.get("width")
        height = slot.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return f"primary YUV matrix: {width}x{height}"
    return ""


def _raw_capture_lines(raw_capture: object) -> list[str]:
    if not isinstance(raw_capture, dict):
        return []
    status = str(raw_capture.get("status", "-"))
    lines = [f"RAW capture: {status}"]
    width = raw_capture.get("width")
    height = raw_capture.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        lines.append(f"RAW size: {width}x{height}")
    orientation = _raw_orientation_line(raw_capture)
    if orientation:
        lines.append(orientation)
    lens = _raw_lens_line(raw_capture)
    if lens:
        lines.append(lens)
    preview_path = raw_capture.get("preview_png_path")
    if isinstance(preview_path, str) and preview_path:
        lines.append(f"preview: {preview_path.rsplit('/', 1)[-1]}")
    preview_error = raw_capture.get("preview_export_error")
    if raw_capture.get("preview_export_status") == "error" and isinstance(preview_error, str) and preview_error:
        lines.append(f"preview error: {preview_error[:80]}")
    dng_path = raw_capture.get("last_dng_path")
    if isinstance(dng_path, str) and dng_path:
        lines.append(f"saved: {dng_path.rsplit('/', 1)[-1]}")
    error = raw_capture.get("last_error")
    if isinstance(error, str) and error:
        lines.append(f"RAW error: {error[:80]}")
    return lines


def _raw_orientation_line(raw_capture: dict[str, object]) -> str:
    sensor = raw_capture.get("sensor_orientation_degrees")
    display = raw_capture.get("display_rotation_degrees")
    rotate = raw_capture.get("raw_to_display_rotation_degrees")
    if all(isinstance(value, int) for value in (sensor, display, rotate)):
        return f"RAW orientation: sensor {sensor} display {display} rotate {rotate}"
    return ""


def _raw_lens_line(raw_capture: dict[str, object]) -> str:
    focal = _format_floatish(raw_capture.get("lens_focal_length_mm"), digits=1)
    aperture = _format_floatish(raw_capture.get("lens_aperture"), digits=1)
    if focal and aperture:
        return f"RAW lens: {focal}mm f/{aperture}"
    if focal:
        return f"RAW lens: {focal}mm"
    if aperture:
        return f"RAW lens: f/{aperture}"
    return ""


def _independent_variable_lines(camera: dict[str, object], display: dict[str, object]) -> list[str]:
    controls = camera.get("preview_controls") if isinstance(camera.get("preview_controls"), dict) else {}
    gpu = camera.get("gpu_preview") if isinstance(camera.get("gpu_preview"), dict) else {}
    lines: list[str] = []
    quality = camera.get("preview_quality")
    target = camera.get("preview_target_mode")
    pipeline = camera.get("preview_pipeline_mode")
    if isinstance(quality, str) and quality:
        lines.append(f"quality={quality}")
    if isinstance(target, str) and target:
        lines.append(f"target={target}")
    if isinstance(pipeline, str) and pipeline:
        lines.append(f"pipeline={pipeline}")
    layers = gpu.get("convolution_layers")
    fit_blend = _format_floatish(gpu.get("crop_fit_blend"), digits=2)
    if isinstance(layers, int):
        line = f"layer={layers}"
        if fit_blend:
            line += f" fit={fit_blend}"
        lines.append(line)
    sharpness = gpu.get("filter_preset", gpu.get("downsample_filter"))
    sharp_bits: list[str] = []
    if isinstance(sharpness, str) and sharpness:
        sharp_bits.append(str(sharpness))
    taps = gpu.get("filter_taps", gpu.get("downsample_taps"))
    strength = _format_floatish(gpu.get("downsample_strength"), digits=2)
    luma = _format_floatish(gpu.get("luma_smoothing"), digits=2)
    chroma = _format_floatish(gpu.get("chroma_smoothing"), digits=2)
    edge = _format_floatish(gpu.get("edge_preserve"), digits=2)
    if isinstance(taps, int):
        sharp_bits.append(f"taps={taps}")
    if luma:
        sharp_bits.append(f"luma={luma}")
    if chroma:
        sharp_bits.append(f"chroma={chroma}")
    if edge:
        sharp_bits.append(f"edge={edge}")
    if strength:
        sharp_bits.append(f"str={strength}")
    if sharp_bits:
        lines.append("sharp=" + " ".join(sharp_bits))
    wb = gpu.get("color_mode")
    wb_bits: list[str] = []
    if isinstance(wb, str) and wb:
        wb_bits.append(wb)
    red_gain = _format_floatish(gpu.get("red_gain"), digits=2)
    green_gain = _format_floatish(gpu.get("green_gain"), digits=2)
    blue_gain = _format_floatish(gpu.get("blue_gain"), digits=2)
    if red_gain and green_gain and blue_gain:
        wb_bits.append(f"rgb={red_gain}/{green_gain}/{blue_gain}")
    if wb_bits:
        lines.append("wb=" + " ".join(wb_bits))
    lines.extend(_manual_control_lines(controls))
    return lines


def _manual_control_lines(controls: dict[str, object]) -> list[str]:
    if not controls:
        return ["manual=unknown"]
    mode = str(controls.get("mode", "auto"))
    iso = controls.get("requested_iso")
    shutter = _format_shutter(controls.get("requested_shutter_ns"))
    focus = _format_floatish(controls.get("requested_focus_distance_diopters"), digits=1)
    lines = [f"manual={mode}"]
    if isinstance(iso, int) and iso > 0:
        actual_iso = controls.get("actual_iso")
        actual = f" actual={actual_iso}" if isinstance(actual_iso, int) and actual_iso > 0 else ""
        lines.append(f"iso req={iso}{actual}")
    if shutter:
        actual_shutter = _format_shutter(controls.get("actual_exposure_time_ns"))
        actual = f" actual={actual_shutter}" if actual_shutter else ""
        lines.append(f"shutter req={shutter}{actual}")
    if focus:
        actual_focus = _format_floatish(controls.get("actual_focus_distance_diopters"), digits=1)
        actual = f" actual={actual_focus}d" if actual_focus else ""
        lines.append(f"focus req={focus}d{actual}")
    return lines


def _preview_renderer_line(camera: dict[str, object]) -> str:
    renderer = camera.get("preview_renderer")
    gpu_ready = bool(camera.get("preview_gpu_ready"))
    private_preview = camera.get("private_preview") if isinstance(camera.get("private_preview"), dict) else {}
    if renderer == "gpu_private_vulkan" and gpu_ready:
        width = private_preview.get("width")
        height = private_preview.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return f"preview: gpu private {width}x{height}"
        return "preview: gpu private"
    if renderer == "fallback_cpu_yuv":
        return "preview: cpu yuv fallback"
    if isinstance(renderer, str) and renderer:
        return f"preview: {renderer} gpu={'yes' if gpu_ready else 'no'}"
    return ""


def _preview_perf_line(camera: dict[str, object]) -> str:
    private_preview = camera.get("private_preview") if isinstance(camera.get("private_preview"), dict) else {}
    gpu = camera.get("gpu_preview") if isinstance(camera.get("gpu_preview"), dict) else {}
    camera_fps = _format_floatish(private_preview.get("fps_estimate"), digits=1)
    import_fps = _format_floatish(gpu.get("import_fps"), digits=1)
    draw_fps = _format_floatish(gpu.get("draw_fps"), digits=1)
    draw_ms = _format_floatish(gpu.get("last_draw_ms"), digits=1)
    parts: list[str] = []
    if camera_fps:
        parts.append(f"cam {camera_fps}")
    if import_fps:
        parts.append(f"imp {import_fps}")
    if draw_fps:
        parts.append(f"draw {draw_fps}")
    if draw_ms:
        parts.append(f"{draw_ms}ms")
    if not parts:
        return ""
    return "perf: " + " ".join(parts)


def _preview_fps_summary(camera: dict[str, object]) -> str:
    private_preview = camera.get("private_preview") if isinstance(camera.get("private_preview"), dict) else {}
    gpu = camera.get("gpu_preview") if isinstance(camera.get("gpu_preview"), dict) else {}
    camera_fps = _format_floatish(private_preview.get("fps_estimate"), digits=1)
    import_fps = _format_floatish(gpu.get("import_fps"), digits=1)
    draw_fps = _format_floatish(gpu.get("draw_fps"), digits=1)
    parts: list[str] = []
    if camera_fps:
        parts.append(f"cam {camera_fps}")
    if import_fps:
        parts.append(f"imp {import_fps}")
    if draw_fps:
        parts.append(f"draw {draw_fps}")
    return "fps: " + " ".join(parts) if parts else ""


def _raw_capture_summary(raw_capture: object) -> str:
    if not isinstance(raw_capture, dict):
        return ""
    status = str(raw_capture.get("status", "-"))
    dng_path = raw_capture.get("last_dng_path")
    if isinstance(dng_path, str) and dng_path:
        return f"raw: {status} {dng_path.rsplit('/', 1)[-1]}"
    error = raw_capture.get("last_error")
    if isinstance(error, str) and error:
        return f"raw: {status} {error[:42]}"
    return f"raw: {status}"


def _preview_state_summary(camera: dict[str, object], display: dict[str, object]) -> str:
    quality = camera.get("preview_quality")
    target = camera.get("preview_target_mode")
    pipeline = camera.get("preview_pipeline_mode")
    controls = camera.get("preview_controls") if isinstance(camera.get("preview_controls"), dict) else {}
    gpu = camera.get("gpu_preview") if isinstance(camera.get("gpu_preview"), dict) else {}
    sharpness = gpu.get("filter_preset", gpu.get("downsample_filter"))
    hint = display.get("refresh_hint_mode") if display else None
    actual = _format_floatish(display.get("actual_refresh_hz"), digits=0) if display else ""
    parts: list[str] = []
    if isinstance(quality, str) and quality:
        parts.append(f"q:{quality}")
    if isinstance(target, str) and target:
        parts.append(f"t:{target}")
    if isinstance(pipeline, str) and pipeline:
        parts.append(f"p:{pipeline}")
    control_mode = controls.get("mode")
    if isinstance(control_mode, str) and control_mode:
        parts.append(f"m:{control_mode}")
    if isinstance(sharpness, str) and sharpness:
        parts.append(f"s:{sharpness}")
    if isinstance(hint, str) and hint:
        hz = f"{actual}Hz" if actual else ""
        parts.append(f"Hz:{hint}{('/' + hz) if hz else ''}")
    return " ".join(parts)


def _preview_downsample_filter_line(camera: dict[str, object]) -> str:
    gpu = camera.get("gpu_preview") if isinstance(camera.get("gpu_preview"), dict) else {}
    filter_name = gpu.get("filter_preset", gpu.get("downsample_filter"))
    if not isinstance(filter_name, str) or not filter_name:
        return ""
    taps = gpu.get("filter_taps", gpu.get("downsample_taps"))
    ms = _format_floatish(gpu.get("last_filter_ms", gpu.get("last_downsample_ms")), digits=1)
    label = filter_name.replace("_", " ")
    parts = [f"filter: {label}"]
    if isinstance(taps, int):
        parts.append(f"taps={taps}")
    luma = _format_floatish(gpu.get("luma_smoothing"), digits=2)
    if luma:
        parts.append(f"luma={luma}")
    chroma = _format_floatish(gpu.get("chroma_smoothing"), digits=2)
    if chroma:
        parts.append(f"chroma={chroma}")
    edge = _format_floatish(gpu.get("edge_preserve"), digits=2)
    if edge:
        parts.append(f"edge={edge}")
    strength = _format_floatish(gpu.get("downsample_strength"), digits=2)
    if strength:
        parts.append(f"str={strength}")
    if ms:
        parts.append(f"{ms}ms")
    return " ".join(parts)


def _preview_perf_detail_lines(camera: dict[str, object]) -> list[str]:
    private_preview = camera.get("private_preview") if isinstance(camera.get("private_preview"), dict) else {}
    gpu = camera.get("gpu_preview") if isinstance(camera.get("gpu_preview"), dict) else {}
    if not private_preview and not gpu:
        return []
    lines: list[str] = []
    selected_width = private_preview.get("selected_width")
    selected_height = private_preview.get("selected_height")
    active_targets = private_preview.get("active_targets")
    attempt_index = private_preview.get("attempt_index")
    attempt_count = private_preview.get("attempt_count")
    import_ms = _format_floatish(gpu.get("last_import_ms"), digits=1)
    draw_fps = _format_floatish(gpu.get("draw_fps"), digits=1)
    uploads = gpu.get("overlay_uploads")
    hits = gpu.get("overlay_cache_hits")
    queue_waits = gpu.get("queue_waits")
    cache_hits = gpu.get("import_cache_hits")
    cache_misses = gpu.get("import_cache_misses")
    cache_entries = gpu.get("import_cache_entries")
    cache_evictions = gpu.get("import_cache_evictions")
    cache_last_hit = gpu.get("last_import_cache_hit")
    intermediate_updates = gpu.get("intermediate_updates")
    intermediate_reuses = gpu.get("intermediate_reuses")
    intermediate_ms = _format_floatish(gpu.get("last_intermediate_ms"), digits=1)
    frames_in_flight = gpu.get("frames_in_flight")
    frame_waits = gpu.get("frame_fence_waits")
    image_waits = gpu.get("image_fence_waits")
    draw_parts: list[str] = []
    if draw_fps:
        draw_parts.append(f"d{draw_fps}")
    if import_ms:
        draw_parts.append(f"i{import_ms}ms")
    if isinstance(intermediate_updates, int) and isinstance(intermediate_reuses, int):
        middle = f"m{intermediate_updates}/{intermediate_reuses}"
        if intermediate_ms:
            middle += f" {intermediate_ms}ms"
        draw_parts.append(middle)
    if draw_parts:
        lines.append("perf3: " + " ".join(draw_parts))
    filter_line = _preview_downsample_filter_line(camera)
    if filter_line:
        lines.append(filter_line)

    cache_parts: list[str] = []
    if isinstance(cache_hits, int) and isinstance(cache_misses, int) and isinstance(cache_entries, int):
        evictions = cache_evictions if isinstance(cache_evictions, int) else 0
        hit_marker = "H" if cache_last_hit is True else "M" if cache_last_hit is False else "-"
        cache_parts.append(f"c{hit_marker}{cache_hits}/{cache_misses}/{cache_entries}e{evictions}")
    elif isinstance(cache_hits, int) and isinstance(cache_entries, int):
        evictions = cache_evictions if isinstance(cache_evictions, int) else 0
        cache_parts.append(f"c{cache_hits}/{cache_entries}e{evictions}")
    if isinstance(uploads, int) and isinstance(hits, int):
        cache_parts.append(f"o{uploads}/{hits}")
    elif isinstance(uploads, int):
        cache_parts.append(f"u{uploads}")
    elif isinstance(hits, int):
        cache_parts.append(f"h{hits}")
    if isinstance(queue_waits, int):
        cache_parts.append(f"w{queue_waits}")
    if isinstance(frames_in_flight, int):
        cache_parts.append(f"f{frames_in_flight}")
    if isinstance(frame_waits, int):
        cache_parts.append(f"fw{frame_waits}")
    if isinstance(image_waits, int):
        cache_parts.append(f"iw{image_waits}")
    if cache_parts:
        lines.append("perf4: " + " ".join(cache_parts))
    selected_parts: list[str] = []
    if isinstance(selected_width, int) and isinstance(selected_height, int) and selected_width > 0 and selected_height > 0:
        selected_parts.append(f"sel {selected_width}x{selected_height}")
    if isinstance(active_targets, list) and active_targets:
        selected_parts.append("+".join(str(item).replace("_preview", "").replace("_sensor", "") for item in active_targets))
    if isinstance(attempt_index, int) and isinstance(attempt_count, int) and attempt_count > 0:
        selected_parts.append(f"a{attempt_index + 1}/{attempt_count}")
    if selected_parts:
        lines.append("perf2: " + " ".join(selected_parts))
    return lines


def _preview_diagnostic_lines(camera: dict[str, object]) -> list[str]:
    lines: list[str] = []
    preview = _preview_renderer_line(camera)
    if preview:
        lines.append(preview)
    private_preview = camera.get("private_preview") if isinstance(camera.get("private_preview"), dict) else {}
    if private_preview:
        preset = private_preview.get("preset")
        selected_width = private_preview.get("selected_width")
        selected_height = private_preview.get("selected_height")
        candidate_count = private_preview.get("candidate_count")
        target_mode = private_preview.get("target_mode")
        active_target_mode = private_preview.get("active_target_mode")
        attempt_index = private_preview.get("attempt_index")
        attempt_count = private_preview.get("attempt_count")
        active_targets = private_preview.get("active_targets")
        last_good = private_preview.get("last_good_combo")
        yuv_width = private_preview.get("yuv_cache_width")
        yuv_height = private_preview.get("yuv_cache_height")
        private_fps = _format_floatish(private_preview.get("fps_estimate"), digits=1)
        bits: list[str] = []
        if isinstance(preset, str) and preset:
            bits.append(f"preset={preset}")
        if isinstance(selected_width, int) and isinstance(selected_height, int) and selected_width > 0 and selected_height > 0:
            bits.append(f"selected={selected_width}x{selected_height}")
        if isinstance(candidate_count, int):
            bits.append(f"private candidates={candidate_count}")
        if isinstance(active_target_mode, str) and active_target_mode:
            bits.append(f"target={active_target_mode}")
        elif isinstance(target_mode, str) and target_mode:
            bits.append(f"target={target_mode}")
        if isinstance(attempt_index, int) and isinstance(attempt_count, int) and attempt_count > 0:
            bits.append(f"attempt={attempt_index + 1}/{attempt_count}")
        if isinstance(active_targets, list) and active_targets:
            bits.append("targets=" + "+".join(str(item) for item in active_targets))
        if isinstance(yuv_width, int) and isinstance(yuv_height, int) and yuv_width > 0 and yuv_height > 0:
            bits.append(f"yuv cache={yuv_width}x{yuv_height}")
        if private_fps:
            bits.append(f"private fps={private_fps}")
        if bits:
            lines.append("preview diag: " + " | ".join(bits))
        if isinstance(last_good, dict):
            width = last_good.get("width")
            height = last_good.get("height")
            quality = last_good.get("quality")
            raw = "raw" if last_good.get("include_raw_sensor") else "noraw"
            yuv = "yuv" if last_good.get("include_yuv_cache") else "noyuv"
            if isinstance(width, int) and isinstance(height, int):
                lines.append(f"last good: {quality} {width}x{height} {yuv}+{raw}")
        failed = private_preview.get("failed_attempts")
        if isinstance(failed, list) and failed:
            first = failed[0] if isinstance(failed[0], dict) else {}
            width = first.get("width")
            height = first.get("height")
            reason = str(first.get("reason", ""))[:50]
            if isinstance(width, int) and isinstance(height, int):
                lines.append(f"private failed: {width}x{height} {reason}".rstrip())
    pipeline = camera.get("preview_pipeline") if isinstance(camera.get("preview_pipeline"), dict) else {}
    if pipeline:
        mode = pipeline.get("mode")
        template = pipeline.get("template")
        applied = pipeline.get("applied_options")
        errors = pipeline.get("errors")
        bits: list[str] = []
        if isinstance(mode, str) and mode:
            bits.append(f"mode={mode}")
        if isinstance(template, str) and template:
            bits.append(f"template={template}")
        if isinstance(applied, list):
            bits.append("applied=" + ",".join(str(item) for item in applied[:8]))
        if isinstance(errors, list) and errors:
            bits.append(f"errors={len(errors)}")
        if bits:
            lines.append("pipeline: " + " | ".join(bits))
    gpu = camera.get("gpu_preview") if isinstance(camera.get("gpu_preview"), dict) else {}
    lines.extend(_preview_perf_detail_lines(camera))
    if gpu:
        status = str(gpu.get("status", "-"))
        imports = gpu.get("imports")
        draws = gpu.get("draws")
        failures = gpu.get("failures")
        import_fps = _format_floatish(gpu.get("import_fps"), digits=1)
        draw_fps = _format_floatish(gpu.get("draw_fps"), digits=1)
        draw_ms = _format_floatish(gpu.get("last_draw_ms"), digits=1)
        import_ms = _format_floatish(gpu.get("last_import_ms"), digits=1)
        uploads = gpu.get("overlay_uploads")
        hits = gpu.get("overlay_cache_hits")
        queue_waits = gpu.get("queue_waits")
        render_imports = gpu.get("imports_on_render_thread")
        intermediate_width = gpu.get("intermediate_width")
        intermediate_height = gpu.get("intermediate_height")
        intermediate_updates = gpu.get("intermediate_updates")
        intermediate_reuses = gpu.get("intermediate_reuses")
        intermediate_ms = _format_floatish(gpu.get("last_intermediate_ms"), digits=1)
        frames_in_flight = gpu.get("frames_in_flight")
        frame_waits = gpu.get("frame_fence_waits")
        image_waits = gpu.get("image_fence_waits")
        frame_slot = gpu.get("current_frame_slot")
        image_index = gpu.get("acquired_image_index")
        sync_mode = gpu.get("sync_mode")
        acquire_nulls = private_preview.get("acquire_nulls")
        images_closed = private_preview.get("images_closed")
        hardware_buffers = private_preview.get("hardware_buffers")
        native_accepted = private_preview.get("native_accepted")
        native_rejected = private_preview.get("native_rejected")
        low_fps_restarts = private_preview.get("low_fps_restarts")
        parts = [f"gpu preview: {status}"]
        if isinstance(imports, int):
            parts.append(f"imports={imports}")
        if isinstance(draws, int):
            parts.append(f"draws={draws}")
        if isinstance(failures, int):
            parts.append(f"failures={failures}")
        if import_fps:
            parts.append(f"imp={import_fps}")
        if draw_fps:
            parts.append(f"draw={draw_fps}")
        if draw_ms:
            parts.append(f"{draw_ms}ms")
        if import_ms:
            parts.append(f"import={import_ms}ms")
        if isinstance(uploads, int):
            parts.append(f"uploads={uploads}")
        if isinstance(hits, int):
            parts.append(f"hits={hits}")
        if isinstance(queue_waits, int):
            parts.append(f"waits={queue_waits}")
        if isinstance(render_imports, int):
            parts.append(f"rt_imports={render_imports}")
        if isinstance(intermediate_width, int) and isinstance(intermediate_height, int) and intermediate_width > 0 and intermediate_height > 0:
            parts.append(f"mid={intermediate_width}x{intermediate_height}")
        if isinstance(intermediate_updates, int):
            parts.append(f"mid_updates={intermediate_updates}")
        if isinstance(intermediate_reuses, int):
            parts.append(f"mid_reuses={intermediate_reuses}")
        if intermediate_ms:
            parts.append(f"mid={intermediate_ms}ms")
        downsample_filter = gpu.get("filter_preset", gpu.get("downsample_filter"))
        downsample_taps = gpu.get("filter_taps", gpu.get("downsample_taps"))
        downsample_ms = _format_floatish(gpu.get("last_filter_ms", gpu.get("last_downsample_ms")), digits=1)
        if isinstance(downsample_filter, str) and downsample_filter:
            parts.append(f"filter={downsample_filter}")
        if isinstance(downsample_taps, int):
            parts.append(f"taps={downsample_taps}")
        luma_smoothing = _format_floatish(gpu.get("luma_smoothing"), digits=2)
        if luma_smoothing:
            parts.append(f"luma={luma_smoothing}")
        chroma_smoothing = _format_floatish(gpu.get("chroma_smoothing"), digits=2)
        if chroma_smoothing:
            parts.append(f"chroma={chroma_smoothing}")
        edge_preserve = _format_floatish(gpu.get("edge_preserve"), digits=2)
        if edge_preserve:
            parts.append(f"edge={edge_preserve}")
        if downsample_ms:
            parts.append(f"down={downsample_ms}ms")
        if isinstance(frames_in_flight, int):
            parts.append(f"frames={frames_in_flight}")
        if isinstance(frame_slot, int):
            parts.append(f"slot={frame_slot}")
        if isinstance(image_index, int):
            parts.append(f"img={image_index}")
        if isinstance(frame_waits, int):
            parts.append(f"fw={frame_waits}")
        if isinstance(image_waits, int):
            parts.append(f"iw={image_waits}")
        if isinstance(sync_mode, str) and sync_mode:
            parts.append(f"sync={sync_mode}")
        lines.append(" ".join(parts))
        delivery_parts: list[str] = []
        if isinstance(acquire_nulls, int):
            delivery_parts.append(f"nulls={acquire_nulls}")
        if isinstance(images_closed, int):
            delivery_parts.append(f"closed={images_closed}")
        if isinstance(hardware_buffers, int):
            delivery_parts.append(f"hb={hardware_buffers}")
        if isinstance(native_accepted, int):
            delivery_parts.append(f"accepted={native_accepted}")
        if isinstance(native_rejected, int):
            delivery_parts.append(f"rejected={native_rejected}")
        if isinstance(low_fps_restarts, int):
            delivery_parts.append(f"restarts={low_fps_restarts}")
        if delivery_parts:
            lines.append("private delivery: " + " ".join(delivery_parts))
        error = gpu.get("last_error")
        if isinstance(error, str) and error:
            lines.append(f"gpu error: {error[:80]}")
        intermediate_error = gpu.get("intermediate_last_error")
        if isinstance(intermediate_error, str) and intermediate_error:
            lines.append(f"intermediate error: {intermediate_error[:80]}")
    return lines


def _format_shutter(value: object) -> str:
    try:
        seconds = float(value) / 1_000_000_000.0
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    if seconds < 1.0:
        denom = max(1, int(round(1.0 / seconds)))
        return f"1/{denom}"
    return f"{seconds:0.1f}s"


def _display_refresh_lines(display: dict[str, object], camera: dict[str, object]) -> list[str]:
    lines: list[str] = []
    if display:
        modes = _display_mode_rates(display.get("supported_modes"))
        if modes:
            lines.append(f"display modes: {','.join(modes)}")
        requested = _format_floatish(display.get("requested_refresh_hz"), digits=0)
        actual = _format_floatish(display.get("actual_refresh_hz"), digits=0)
        selected = _format_floatish(display.get("selected_mode_hz"), digits=0)
        hint = _format_floatish(display.get("surface_frame_rate_hz"), digits=0)
        hint_mode = display.get("refresh_hint_mode")
        if requested or selected or actual or hint:
            parts: list[str] = []
            if requested:
                parts.append(f"req{requested}")
            if selected:
                parts.append(f"mode{selected}")
            if actual:
                parts.append(f"actual{actual}")
            if hint:
                parts.append(f"hint{hint}")
            if isinstance(hint_mode, str) and hint_mode:
                parts.append(str(hint_mode))
            lines.append("refresh: " + " ".join(parts))
        if requested:
            lines.append(f"refresh request: {requested}")
        if actual:
            honored = " honored" if display.get("honored") else " clamped"
            lines.append(f"refresh actual: {actual}{honored}")
    fps = _camera_fps(camera)
    if fps:
        lines.append(f"camera fps: {fps}")
    return lines


def _display_mode_rates(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    rates: list[float] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            rate = float(item.get("refresh_hz"))
        except (TypeError, ValueError):
            continue
        if rate > 0.0 and all(abs(rate - existing) > 0.5 for existing in rates):
            rates.append(rate)
    rates.sort()
    return [_format_floatish(rate, digits=0) for rate in rates if _format_floatish(rate, digits=0)]


def _camera_fps(camera: dict[str, object]) -> str:
    streams = camera.get("streams")
    if not isinstance(streams, dict):
        return ""
    primary = streams.get("primary")
    if not isinstance(primary, dict):
        return ""
    return _format_floatish(primary.get("fps_estimate"), digits=1)


def _format_floatish(value: object, *, digits: int) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0.0:
        return ""
    if digits == 0:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _physical_camera_lines(cameras: object) -> list[str]:
    if not isinstance(cameras, list):
        return []
    lines: list[str] = []
    for camera in cameras:
        if not isinstance(camera, dict) or camera.get("facing") != "back":
            continue
        camera_id = str(camera.get("camera_id", camera.get("id", "-")))
        physical_ids = camera.get("physical_camera_ids")
        details = camera.get("physical_camera_details")
        physical_count = len(physical_ids) if isinstance(physical_ids, list) else 0
        logical = "logical" if camera.get("is_logical_multi_camera") else "single"
        lines.append(f"rear {camera_id}: {logical} physical={physical_count}")
        if isinstance(details, list):
            for item in details[:3]:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("camera_id", item.get("id", "-")))
                cfa = str(item.get("color_filter_arrangement", "unknown"))
                mono = " mono" if item.get("monochrome_supported") or cfa == "MONO" else ""
                focal = _format_focal_lengths(item.get("focal_lengths_mm"))
                lines.append(f"  physical {pid}: {cfa}{mono}{focal}")
    return lines[:5]


def _resolution_probe_lines(cameras: object, inventory: object | None = None) -> list[str]:
    if not isinstance(cameras, list):
        return []
    summary = inventory.get("probe_summary") if isinstance(inventory, dict) else None
    if isinstance(summary, dict):
        still = _format_resolution_size(summary.get("largest_public_still"))
        any_size = _format_resolution_size(summary.get("largest_public_any"))
        verdict = str(summary.get("public_108mp_verdict", "unknown_failed"))
        return [
            f"best still: {still or 'none'}",
            f"largest any: {any_size or 'none'}",
            f"108MP public path: {_format_public_108mp_verdict(verdict)}",
            f"probe confidence: {summary.get('probe_status', 'failed')}",
            f"RAW public: {'yes' if summary.get('raw_public_supported') else 'no'}",
        ]
    rear_probes = [
        camera.get("resolution_probe")
        for camera in cameras
        if isinstance(camera, dict) and camera.get("facing") == "back" and isinstance(camera.get("resolution_probe"), dict)
    ]
    if not rear_probes:
        return []
    primary = rear_probes[0]
    standard = primary.get("standard") if isinstance(primary.get("standard"), dict) else {}
    maximum = primary.get("maximum_resolution") if isinstance(primary.get("maximum_resolution"), dict) else {}
    standard_still = _format_resolution_size(_largest_size((standard or {}).get("jpeg")))
    maximum_still = _format_resolution_size(_largest_size((maximum or {}).get("jpeg")))
    lines = [
        f"best still: std {standard_still or 'none'} | maxres {maximum_still or 'none'}",
        f"108MP public path: {'yes' if any(_bool_probe_value(probe, 'public_108mp_candidate') for probe in rear_probes) else 'no'}",
        f"RAW public: {'yes' if any(_bool_probe_value(probe, 'raw_public_supported') for probe in rear_probes) else 'no'}",
    ]
    return lines


def _format_public_108mp_verdict(verdict: str) -> str:
    if verdict == "yes":
        return "yes"
    if verdict == "no_complete":
        return "no"
    if verdict == "no_partial":
        return "no_partial"
    return "unknown"


def _bool_probe_value(probe: object, key: str) -> bool:
    return isinstance(probe, dict) and bool(probe.get(key))


def _largest_size(value: object) -> dict[str, object] | None:
    if not isinstance(value, list) or not value:
        return None
    best: dict[str, object] | None = None
    best_area = -1
    for item in value:
        if not isinstance(item, dict):
            continue
        width = item.get("width")
        height = item.get("height")
        if not isinstance(width, int) or not isinstance(height, int):
            continue
        area = width * height
        if area > best_area:
            best = item
            best_area = area
    return best


def _format_resolution_size(size: dict[str, object] | None) -> str:
    if not size:
        return ""
    width = size.get("width")
    height = size.get("height")
    if isinstance(width, int) and isinstance(height, int):
        return f"{width}x{height}"
    return ""


def _format_focal_lengths(value: object) -> str:
    if not isinstance(value, list) or not value:
        return ""
    out: list[str] = []
    for item in value[:3]:
        try:
            out.append(f"{float(item):.1f}mm")
        except (TypeError, ValueError):
            continue
    return f" focal={','.join(out)}" if out else ""


def _hidden_sensor_verdict(cameras: object) -> str:
    if not isinstance(cameras, list):
        return ""
    rear = [camera for camera in cameras if isinstance(camera, dict) and camera.get("facing") == "back"]
    if not rear:
        return "hidden rear sensor: no public rear camera"
    physical_total = 0
    monochrome = False
    for camera in rear:
        physical_ids = camera.get("physical_camera_ids")
        if isinstance(physical_ids, list):
            physical_total += len(physical_ids)
        details = camera.get("physical_camera_details")
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                cfa = str(item.get("color_filter_arrangement", ""))
                monochrome = monochrome or bool(item.get("monochrome_supported")) or cfa == "MONO"
    if monochrome:
        return "hidden rear sensor: MONO exposed"
    if physical_total == 0:
        return "hidden rear sensor: not exposed by Camera2"
    return "hidden rear sensor: physical IDs exposed"


def _hidden_probe_lines(probes: object) -> list[str]:
    if not isinstance(probes, list):
        return []
    interesting: list[str] = []
    failed = 0
    for probe in probes:
        if not isinstance(probe, dict):
            continue
        camera_id = str(probe.get("camera_id", "-"))
        status = str(probe.get("status", "-"))
        if status != "characteristics_ok":
            failed += 1
            continue
        facing = str(probe.get("facing", "unknown"))
        cfa = str(probe.get("color_filter_arrangement", "unknown"))
        mono = " mono" if probe.get("monochrome_supported") or cfa == "MONO" else ""
        yuv_sizes = probe.get("yuv_420_888_sizes")
        size = _first_size(yuv_sizes)
        logical = " logical" if probe.get("is_logical_multi_camera") else ""
        interesting.append(f"hidden id {camera_id}: {facing}{logical} {cfa}{mono}{size}")
    if interesting:
        return interesting[:3]
    if failed:
        return [f"hidden id probes: {failed} blocked"]
    return []


def _first_size(value: object) -> str:
    if not isinstance(value, list) or not value:
        return ""
    first = value[0]
    if not isinstance(first, dict):
        return ""
    width = first.get("width")
    height = first.get("height")
    if isinstance(width, int) and isinstance(height, int):
        return f" yuv={width}x{height}"
    return ""


def _format_sensor_sample_line(sample: SensorSample) -> str:
    if sample.sensor_type == "camera.device" and isinstance(sample.value, dict):
        status = str(sample.value.get("status", "-"))
        permission = str(sample.value.get("permission", "-"))
        count = sample.value.get("device_count", "-")
        return f"{sample.sensor_type}: {sample.status} status={status} permission={permission} devices={count}"
    if sample.sensor_type == "camera.permission" and isinstance(sample.value, dict):
        permission = str(sample.value.get("permission", "-"))
        granted = bool(sample.value.get("granted", False))
        return f"{sample.sensor_type}: {sample.status} {permission} granted={granted}"
    if sample.sensor_type == "display.refresh" and isinstance(sample.value, dict):
        actual = _format_floatish(sample.value.get("actual_refresh_hz"), digits=0) or "-"
        requested = _format_floatish(sample.value.get("requested_refresh_hz"), digits=0) or "-"
        return f"{sample.sensor_type}: {sample.status} request={requested} actual={actual}"
    detail = _sample_detail(sample)
    return f"{sample.sensor_type}: {sample.status} {detail}".rstrip()


def _sample_detail(sample: SensorSample) -> str:
    if sample.value is None:
        return ""
    text = str(sample.value)
    if sample.unit:
        text = f"{text} {sample.unit}"
    return text[:96]


def _fit_hud_lines(lines: list[str], *, max_chars: int, max_lines: int) -> list[str]:
    fitted: list[str] = []
    limit = max(12, max_chars)
    for line in lines:
        text = str(line)
        while len(text) > limit:
            fitted.append(text[: limit - 1] + "…")
            text = text[limit - 1 :]
            if len(fitted) >= max_lines:
                return fitted
        fitted.append(text)
        if len(fitted) >= max_lines:
            return fitted
    return fitted


def _as_tensor_rgba(image):
    import numpy as np
    import torch

    data = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    return torch.from_numpy(data.copy())


class CameraLabApp:
    def __init__(self) -> None:
        self._width = 0
        self._height = 0
        self._started = time.perf_counter()
        self._last_samples: list[SensorSample] = []
        self._last_sensor_read_s = 0.0
        self._frame_index = 0
        self._touch_count = 0
        self._last_key = "-"
        self._buttons: list[TouchButton] = []
        self._last_action_status = "ready"
        self._hud_mode = "collapsed"
        self._debug_hud = False
        self._preview_quality_mode = "max"
        self._preview_target_mode = "raw"
        self._preview_sharpness_mode = "natural"
        self._preview_convolution_layers = 0
        self._preview_white_balance_mode = "auto"
        self._preview_pipeline_mode = "hq"
        self._refresh_hint_mode = "60"

    def init(self, ctx) -> None:
        snap = ctx.read_matrix_snapshot()
        self._height, self._width, _ = snap.shape

    def loop(self, ctx, dt: float) -> None:
        _ = dt
        self._frame_index += 1
        self._consume_input(ctx.poll_hdi_events(max_events=128, frame="screen_tl"))
        now = time.perf_counter()
        if not self._last_samples or now - self._last_sensor_read_s >= 0.25:
            self._last_sensor_read_s = now
            self._last_samples = [ctx.read_sensor(sensor_type) for sensor_type in CAMERA_SENSOR_CANDIDATES]
        if getattr(ctx, "supports_scene_graph", False):
            self._render_scene_hud(ctx, now)
            return
        frame = self._render_frame(now)
        ctx.submit_write_batch(WriteBatch([FullRewrite(_as_tensor_rgba(frame))]))

    def stop(self, ctx) -> None:
        _ = ctx

    def _consume_input(self, events: list[object]) -> None:
        active_touches: set[int] = set()
        for event in events:
            if getattr(event, "status", "") != "OK" or not isinstance(getattr(event, "payload", None), dict):
                continue
            payload = event.payload
            if getattr(event, "device", "") == "touch":
                phase = str(payload.get("phase", ""))
                touch_id = int(payload.get("touch_id", 0) or 0)
                x = float(payload.get("x", -1.0) or -1.0)
                y = float(payload.get("y", -1.0) or -1.0)
                if phase in ("down", "move"):
                    active_touches.add(touch_id)
                    if phase == "down":
                        self._handle_touch_action(x, y)
                elif phase in ("up", "cancel"):
                    active_touches.discard(touch_id)
            if getattr(event, "device", "") == "keyboard":
                key = str(payload.get("key", "")).strip()
                if key:
                    self._last_key = key
                phase = str(payload.get("phase", ""))
                if phase in ("down", "single", "repeat"):
                    self._handle_camera_key(key.lower())
        if active_touches:
            self._touch_count = len(active_touches)

    def _handle_touch_action(self, x: float, y: float) -> None:
        for button in self._buttons:
            if button.contains(x, y):
                if button.action == "cycle_primary":
                    self._cycle_primary_camera()
                elif button.action == "toggle_dual":
                    self._toggle_dual_preview()
                elif button.action == "capture_raw":
                    self._capture_raw_still()
                elif button.action == "cycle_preview_quality":
                    self._cycle_preview_quality()
                elif button.action == "cycle_preview_target":
                    self._cycle_preview_target()
                elif button.action == "cycle_preview_sharpness":
                    self._cycle_preview_sharpness()
                elif button.action == "cycle_preview_convolution_layers":
                    self._cycle_preview_convolution_layers()
                elif button.action == "cycle_preview_white_balance":
                    self._cycle_preview_white_balance()
                elif button.action == "cycle_preview_pipeline":
                    self._cycle_preview_pipeline()
                elif button.action == "cycle_refresh_hint":
                    self._cycle_refresh_hint()
                elif button.action == "toggle_debug":
                    self._cycle_hud_mode()
                elif button.action == "toggle_raw_mode":
                    self._toggle_raw_capture_mode()
                elif button.action == "iso_down":
                    self._adjust_raw_control("iso", -1)
                elif button.action == "iso_up":
                    self._adjust_raw_control("iso", 1)
                elif button.action == "shutter_down":
                    self._adjust_raw_control("shutter", -1)
                elif button.action == "shutter_up":
                    self._adjust_raw_control("shutter", 1)
                elif button.action == "focus_down":
                    self._adjust_raw_control("focus", -1)
                elif button.action == "focus_up":
                    self._adjust_raw_control("focus", 1)
                elif button.action == "reset_raw":
                    self._reset_raw_controls()
                return

    def _handle_camera_key(self, key: str) -> None:
        if key in ("h", "keycode_h"):
            self._cycle_hud_mode()
            return
        if key in ("c", "keycode_c"):
            self._cycle_primary_camera()
            return
        if key in ("d", "keycode_d"):
            self._toggle_dual_preview()
            return
        if key in ("r", "keycode_r"):
            self._capture_raw_still()
            return
        if key in ("q", "keycode_q"):
            self._cycle_preview_quality()
            return
        if key in ("t", "keycode_t"):
            self._cycle_preview_target()
            return
        if key in ("s", "keycode_s"):
            self._cycle_preview_sharpness()
            return
        if key in ("l", "keycode_l"):
            self._cycle_preview_convolution_layers()
            return
        if key in ("w", "keycode_w"):
            self._cycle_preview_white_balance()
            return
        if key in ("p", "keycode_p"):
            self._cycle_preview_pipeline()
            return
        if key in ("v", "keycode_v"):
            self._cycle_refresh_hint()
            return
        if key in ("m", "keycode_m"):
            self._toggle_raw_capture_mode()
            return
        if key in ("[", "keycode_left_bracket"):
            self._adjust_raw_control("iso", -1)
            return
        if key in ("]", "keycode_right_bracket"):
            self._adjust_raw_control("iso", 1)
            return
        if key in ("-", "keycode_minus"):
            self._adjust_raw_control("shutter", -1)
            return
        if key in ("=", "+", "keycode_equals"):
            self._adjust_raw_control("shutter", 1)
            return
        if key in (",", "keycode_comma"):
            self._adjust_raw_control("focus", -1)
            return
        if key in (".", "keycode_period"):
            self._adjust_raw_control("focus", 1)
            return
        if key in ("0", "keycode_0"):
            self._reset_raw_controls()
            return

    def _latest_camera_payload(self) -> dict[str, object]:
        by_type = {sample.sensor_type: sample for sample in self._last_samples}
        return _camera_payload(by_type.get("camera.device"))

    def _cycle_primary_camera(self) -> None:
        payload = self._latest_camera_payload()
        inventory = payload.get("inventory") if isinstance(payload.get("inventory"), dict) else {}
        rear_ids = _rear_camera_ids(inventory.get("cameras"))
        if len(rear_ids) < 2:
            self._last_action_status = "no alternate rear camera exposed"
            return
        current = str(payload.get("primary_camera_id") or payload.get("camera_id") or rear_ids[0])
        next_id = rear_ids[(rear_ids.index(current) + 1) % len(rear_ids)] if current in rear_ids else rear_ids[0]
        if next_id == current:
            self._last_action_status = "already on only rear camera"
            return
        self._last_action_status = f"switching primary to camera {next_id}"
        _android_set_primary_camera(next_id)

    def _toggle_dual_preview(self) -> None:
        payload = self._latest_camera_payload()
        currently_enabled = bool(payload.get("dual_active"))
        if not currently_enabled and not bool(payload.get("dual_supported")):
            self._last_action_status = "dual preview unsupported by Camera2"
            return
        self._last_action_status = "disabling dual preview" if currently_enabled else "enabling dual preview"
        _android_set_dual_preview_enabled(not currently_enabled)

    def _capture_raw_still(self) -> None:
        payload = self._latest_camera_payload()
        raw = payload.get("raw_capture") if isinstance(payload.get("raw_capture"), dict) else {}
        if raw and not bool(raw.get("raw_supported", False)):
            self._last_action_status = "RAW_SENSOR unavailable"
            return
        self._last_action_status = "capturing RAW still"
        _android_capture_raw_still()

    def _cycle_preview_quality(self) -> None:
        order = ("max", "balanced", "fast")
        current = self._preview_quality_mode
        try:
            next_mode = order[(order.index(current) + 1) % len(order)]
        except ValueError:
            next_mode = "max"
        self._preview_quality_mode = next_mode
        self._last_action_status = f"quality {next_mode}"
        _android_set_preview_quality_mode(next_mode)

    def _cycle_preview_target(self) -> None:
        order = ("raw", "solo", "full", "auto")
        current = self._preview_target_mode
        try:
            next_mode = order[(order.index(current) + 1) % len(order)]
        except ValueError:
            next_mode = "auto"
        self._preview_target_mode = next_mode
        self._last_action_status = f"target {next_mode}"
        _android_set_preview_target_mode(next_mode)

    def _cycle_preview_sharpness(self) -> None:
        order = ("natural", "clean", "lowlight", "detail")
        current = self._preview_sharpness_mode
        try:
            next_mode = order[(order.index(current) + 1) % len(order)]
        except ValueError:
            next_mode = "natural"
        self._preview_sharpness_mode = next_mode
        self._last_action_status = f"sharpness {next_mode}"
        _android_set_preview_sharpness_mode(next_mode)

    def _cycle_preview_convolution_layers(self) -> None:
        next_layers = (self._preview_convolution_layers + 1) % 5
        self._preview_convolution_layers = next_layers
        self._last_action_status = f"convolution layer {next_layers}"
        _android_set_preview_convolution_layers(next_layers)

    def _cycle_preview_white_balance(self) -> None:
        order = ("auto", "neutral", "warm", "cool", "desk")
        current = self._preview_white_balance_mode
        try:
            next_mode = order[(order.index(current) + 1) % len(order)]
        except ValueError:
            next_mode = "auto"
        self._preview_white_balance_mode = next_mode
        self._last_action_status = f"white balance {next_mode}"
        _android_set_preview_white_balance_mode(next_mode)

    def _cycle_preview_pipeline(self) -> None:
        order = ("hq", "preview", "record", "rawish")
        current = self._preview_pipeline_mode
        try:
            next_mode = order[(order.index(current) + 1) % len(order)]
        except ValueError:
            next_mode = "preview"
        self._preview_pipeline_mode = next_mode
        self._last_action_status = f"pipeline {next_mode}"
        _android_set_preview_pipeline_mode(next_mode)

    def _cycle_refresh_hint(self) -> None:
        order = ("60", "120", "highest", "90", "default")
        current = self._refresh_hint_mode
        try:
            next_mode = order[(order.index(current) + 1) % len(order)]
        except ValueError:
            next_mode = "60"
        self._refresh_hint_mode = next_mode
        self._last_action_status = f"refresh {next_mode}"
        _android_set_refresh_hint_mode(next_mode)

    def _toggle_raw_capture_mode(self) -> None:
        payload = self._latest_camera_payload()
        controls = payload.get("preview_controls") if isinstance(payload.get("preview_controls"), dict) else {}
        next_mode = "auto" if controls.get("mode") == "manual" else "manual"
        self._last_action_status = f"manual mode {next_mode}"
        _android_set_preview_manual_mode(next_mode)

    def _adjust_raw_control(self, control: str, delta: int) -> None:
        self._last_action_status = f"manual {control} {'+' if delta > 0 else '-'}"
        if control == "iso":
            _android_adjust_raw_iso(delta)
        elif control == "shutter":
            _android_adjust_raw_shutter(delta)
        elif control == "focus":
            _android_adjust_raw_focus(delta)

    def _reset_raw_controls(self) -> None:
        self._last_action_status = "manual controls reset"
        _android_reset_raw_capture_controls()

    def _cycle_hud_mode(self) -> None:
        try:
            next_mode = HUD_MODES[(HUD_MODES.index(self._hud_mode) + 1) % len(HUD_MODES)]
        except ValueError:
            next_mode = "collapsed"
        self._set_hud_mode(next_mode)

    def _set_hud_mode(self, mode: str) -> None:
        self._hud_mode = mode if mode in HUD_MODES else "collapsed"
        self._debug_hud = self._hud_mode == "debug"
        self._last_action_status = f"HUD {self._hud_mode}"

    def _render_frame(self, now: float) -> Image.Image:
        from PIL import Image, ImageDraw, ImageFont

        width = max(1, self._width)
        height = max(1, self._height)
        image = Image.new("RGBA", (width, height), (5, 8, 11, 255))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()

        self._draw_sensor_grid(draw, width, height, now)
        margin = max(10, min(width, height) // 32)
        line_h = max(12, int(round(height * 0.022)))
        y = margin
        _draw_text(draw, (margin, y), "Luvatrix Camera Lab", font=font, fill=(238, 245, 250, 255))
        y += line_h + 4
        _draw_text(draw, (margin, y), "android-first scaffold / no Camera2 bridge yet", font=font, fill=(151, 192, 209, 255))
        y += line_h * 2

        max_lines = max(4, int((height - margin * 5 - line_h * 4) // line_h))
        hud_lines = self._status_lines_for_hud_mode()
        for line in _fit_hud_lines(hud_lines, max_chars=max(18, width // 8), max_lines=max_lines):
            _draw_text(draw, (margin, y), line, font=font, fill=(214, 225, 230, 255))
            y += line_h

        self._buttons = self._control_buttons(width=float(width), height=float(height), margin=float(margin))
        self._draw_touch_buttons(draw, font)
        footer = f"frames={self._frame_index} uptime={now - self._started:0.1f}s touches={self._touch_count} key={self._last_key}"
        _draw_text(draw, (margin, height - margin - line_h), footer, font=font, fill=(132, 160, 170, 255))
        _draw_text(
            draw,
            (margin, height - margin - line_h * 2),
            f"action={self._last_action_status}",
            font=font,
            fill=(180, 215, 218, 255),
        )
        return image

    def _render_scene_hud(self, ctx, now: float) -> None:
        width = float(max(1, self._width))
        height = float(max(1, self._height))
        margin = max(10.0, min(width, height) / 32.0)
        line_h = max(14.0, height * 0.024)
        panel_w = min(width - margin * 2.0, max(280.0, width * 0.78))
        self._buttons = self._control_buttons(width=width, height=height, margin=margin)
        status_lines = self._status_lines_for_hud_mode()
        footer = f"frames={self._frame_index} uptime={now - self._started:0.1f}s key={self._last_key}"
        subtitle = {
            "collapsed": "HUD collapsed (tap HUD / h)",
            "compact": "capture controls (tap HUD / h)",
            "debug": "full diagnostics (tap HUD / h)",
        }.get(self._hud_mode, "HUD collapsed (tap HUD / h)")
        raw_lines = status_lines if self._hud_mode == "collapsed" else ["Luvatrix Camera Lab", subtitle, *status_lines]
        if self._hud_mode != "collapsed":
            raw_lines.append(footer)
        max_chars = max(24, int(panel_w / 7.0))
        button_top = min((button.y0 for button in self._buttons), default=height - margin)
        available_h = max(line_h * 3.0, button_top - margin * 2.0)
        hud_fraction = {"collapsed": 0.18, "compact": 0.34, "debug": 0.52}.get(self._hud_mode, 0.18)
        max_lines = max(3, int((min(available_h, height * hud_fraction)) / line_h))
        lines = _fit_hud_lines(raw_lines, max_chars=max_chars, max_lines=max_lines)
        panel_h = margin + line_h * (len(lines) + 1)

        ctx.begin_scene_frame()
        ctx.clear_scene((0, 0, 0, 0))
        ctx.draw_rect(
            x=margin,
            y=margin,
            width=panel_w,
            height=panel_h,
            color_rgba=(4, 10, 14, 156),
            z_index=10,
        )
        y = margin * 1.55
        for idx, line in enumerate(lines):
            color = (238, 245, 250, 255) if idx == 0 else (188, 214, 221, 235)
            ctx.draw_text(
                line,
                x=margin * 1.45,
                y=y,
                font_size_px=13.0 if idx else 17.0,
                color_rgba=color,
                z_index=20 + idx,
                cache_key=f"camera_hud_{idx}_{line[:24]}",
            )
            y += line_h
        for button in self._buttons:
            ctx.draw_rect(
                x=button.x0,
                y=button.y0,
                width=button.x1 - button.x0,
                height=button.y1 - button.y0,
                color_rgba=(0, 116, 130, 235),
                z_index=60,
            )
            ctx.draw_rect(
                x=button.x0 + 3.0,
                y=button.y0 + 3.0,
                width=button.x1 - button.x0 - 6.0,
                height=button.y1 - button.y0 - 6.0,
                color_rgba=(7, 22, 28, 210),
                z_index=61,
            )
            ctx.draw_text(
                button.label,
                x=button.x0 + 8.0,
                y=button.y0 + 10.0,
                font_size_px=13.0,
                color_rgba=(232, 248, 248, 255),
                z_index=70,
                cache_key=f"camera_button_{button.action}_{button.label}",
            )
        ctx.finalize_scene_frame()

    def _status_lines_for_hud_mode(self) -> list[str]:
        if self._hud_mode == "debug":
            return format_camera_status_lines(self._last_samples)
        if self._hud_mode == "compact":
            return format_camera_compact_status_lines(self._last_samples, action_status=self._last_action_status)
        return format_camera_collapsed_status_lines(self._last_samples, action_status=self._last_action_status)

    def _control_buttons(self, *, width: float, height: float, margin: float) -> list[TouchButton]:
        gap = max(6.0, min(12.0, width * 0.018))
        cols = 4
        rows = [
            (("cycle_preview_quality", "qual"), ("cycle_preview_target", "target"), ("cycle_preview_convolution_layers", "layer"), ("cycle_preview_pipeline", "pipe")),
            (("toggle_raw_mode", "mode"), ("cycle_preview_white_balance", "WB"), ("iso_down", "ISO-"), ("iso_up", "ISO+")),
            (("shutter_down", "S-"), ("shutter_up", "S+"), ("focus_down", "F-"), ("focus_up", "F+")),
        ]
        usable = max(1.0, width - margin * 2.0 - gap * (cols - 1))
        button_w = usable / cols
        button_h = max(42.0, min(58.0, height * 0.062))
        footer_space = max(68.0, height * 0.095)
        group_h = len(rows) * button_h + (len(rows) - 1) * gap
        y0 = max(margin, height - footer_space - group_h)
        buttons: list[TouchButton] = []
        for row_idx, row in enumerate(rows):
            by0 = y0 + row_idx * (button_h + gap)
            by1 = by0 + button_h
            for col_idx, (action, label) in enumerate(row):
                bx0 = margin + col_idx * (button_w + gap)
                buttons.append(TouchButton(action, label, bx0, by0, bx0 + button_w, by1))
        return buttons

    def _draw_touch_buttons(self, draw: ImageDraw.ImageDraw, font) -> None:
        for button in self._buttons:
            draw.rounded_rectangle(
                [(button.x0, button.y0), (button.x1, button.y1)],
                radius=8,
                fill=(0, 116, 130, 235),
                outline=(212, 255, 246, 240),
                width=3,
            )
            _draw_text(
                draw,
                (int(button.x0 + 9), int(button.y0 + 12)),
                button.label,
                font=font,
                fill=(232, 248, 248, 255),
            )

    def _draw_sensor_grid(self, draw: ImageDraw.ImageDraw, width: int, height: int, now: float) -> None:
        for y in range(height):
            t = y / max(1, height - 1)
            color = (
                int(4 + 14 * t),
                int(9 + 28 * t),
                int(13 + 34 * t),
                255,
            )
            draw.line([(0, y), (width, y)], fill=color)

        grid = max(24, min(width, height) // 8)
        pulse = int((math.sin(now * 2.4) + 1.0) * 26.0)
        for x in range(0, width, grid):
            draw.line([(x, 0), (x, height)], fill=(38, 76 + pulse, 86 + pulse, 72))
        for y in range(0, height, grid):
            draw.line([(0, y), (width, y)], fill=(38, 76 + pulse, 86 + pulse, 72))

        box_margin = max(18, min(width, height) // 16)
        draw.rectangle(
            [(box_margin, box_margin), (width - box_margin, height - box_margin)],
            outline=(92, 170, 184, 160),
            width=max(1, min(width, height) // 180),
        )
        cross = max(10, min(width, height) // 26)
        cx = width // 2
        cy = height // 2
        draw.line([(cx - cross, cy), (cx + cross, cy)], fill=(112, 224, 210, 180), width=2)
        draw.line([(cx, cy - cross), (cx, cy + cross)], fill=(112, 224, 210, 180), width=2)


def _draw_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, font, fill: tuple[int, int, int, int]) -> None:
    x, y = xy
    draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 210))
    draw.text((x, y), text, font=font, fill=fill)


def _android_set_primary_camera(camera_id: str) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.set_primary_camera(str(camera_id))
    except Exception:
        return


def _android_set_dual_preview_enabled(enabled: bool) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.set_dual_preview_enabled(bool(enabled))
    except Exception:
        return


def _android_capture_raw_still() -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.capture_raw_still()
    except Exception:
        return


def _android_set_raw_capture_mode(mode: str) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.set_raw_capture_mode(str(mode))
    except Exception:
        return


def _android_set_preview_manual_mode(mode: str) -> None:
    try:
        import luvatrix_android_boot

        setter = getattr(luvatrix_android_boot, "set_preview_manual_mode", luvatrix_android_boot.set_raw_capture_mode)
        setter(str(mode))
    except Exception:
        return


def _android_adjust_raw_iso(delta_steps: int) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.adjust_raw_iso(int(delta_steps))
    except Exception:
        return


def _android_adjust_raw_shutter(delta_steps: int) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.adjust_raw_shutter(int(delta_steps))
    except Exception:
        return


def _android_adjust_raw_focus(delta_steps: int) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.adjust_raw_focus(int(delta_steps))
    except Exception:
        return


def _android_reset_raw_capture_controls() -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.reset_raw_capture_controls()
    except Exception:
        return


def _android_set_preview_quality_mode(mode: str) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.set_preview_quality_mode(str(mode))
    except Exception:
        return


def _android_set_preview_target_mode(mode: str) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.set_preview_target_mode(str(mode))
    except Exception:
        return


def _android_set_preview_sharpness_mode(mode: str) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.set_preview_sharpness_mode(str(mode))
    except Exception:
        return


def _android_set_preview_convolution_layers(layers: int) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.set_preview_convolution_layers(int(layers))
    except Exception:
        return


def _android_set_preview_white_balance_mode(mode: str) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.set_preview_white_balance_mode(str(mode))
    except Exception:
        return


def _android_set_preview_pipeline_mode(mode: str) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.set_preview_pipeline_mode(str(mode))
    except Exception:
        return


def _android_set_refresh_hint_mode(mode: str) -> None:
    try:
        import luvatrix_android_boot

        luvatrix_android_boot.set_refresh_hint_mode(str(mode))
    except Exception:
        return


def create() -> CameraLabApp:
    return CameraLabApp()
