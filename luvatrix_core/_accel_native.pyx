# cython: language_level=3, boundscheck=False, wraparound=False, initializedcheck=False, freethreading_compatible=True

from libc.math cimport floor


cdef inline int _round_half_even(double value) noexcept nogil:
    cdef int whole = <int>floor(value)
    cdef double fraction = value - whole
    if fraction > 0.5 or (fraction == 0.5 and whole % 2 != 0):
        return whole + 1
    return whole


cdef void _alpha_blit_without_mask(
    unsigned char[::1] destination,
    int destination_width,
    const unsigned char[::1] source,
    int source_width,
    int destination_x0,
    int destination_y0,
    int source_x0,
    int source_y0,
    int copy_width,
    int copy_height,
) noexcept nogil:
    cdef int row, column, channel, source_pixel, destination_pixel
    cdef int source_alpha, destination_alpha, output_alpha, numerator, denominator
    for row in range(copy_height):
        for column in range(copy_width):
            source_pixel = ((source_y0 + row) * source_width + source_x0 + column) * 4
            destination_pixel = ((destination_y0 + row) * destination_width + destination_x0 + column) * 4
            source_alpha = source[source_pixel + 3]
            if source_alpha <= 0:
                continue
            destination_alpha = destination[destination_pixel + 3]
            output_alpha = source_alpha + (destination_alpha * (255 - source_alpha) + 127) // 255
            denominator = output_alpha * 255
            for channel in range(3):
                numerator = (
                    source[source_pixel + channel] * source_alpha * 255
                    + destination[destination_pixel + channel]
                    * destination_alpha
                    * (255 - source_alpha)
                )
                numerator = 0 if denominator <= 0 else (numerator + denominator // 2) // denominator
                destination[destination_pixel + channel] = max(0, min(255, numerator))
            destination[destination_pixel + 3] = output_alpha


cdef void _alpha_blit_with_mask(
    unsigned char[::1] destination,
    int destination_width,
    const unsigned char[::1] source,
    int source_width,
    const unsigned char[::1] mask,
    int mask_width,
    int mask_channels,
    int destination_x0,
    int destination_y0,
    int source_x0,
    int source_y0,
    int copy_width,
    int copy_height,
) noexcept nogil:
    cdef int row, column, channel, source_pixel, destination_pixel, mask_pixel
    cdef int coverage, source_alpha, destination_alpha, output_alpha, numerator, denominator
    for row in range(copy_height):
        for column in range(copy_width):
            source_pixel = ((source_y0 + row) * source_width + source_x0 + column) * 4
            destination_pixel = ((destination_y0 + row) * destination_width + destination_x0 + column) * 4
            mask_pixel = ((source_y0 + row) * mask_width + source_x0 + column) * mask_channels
            coverage = mask[mask_pixel]
            source_alpha = (source[source_pixel + 3] * coverage + 127) // 255
            if source_alpha <= 0:
                continue
            destination_alpha = destination[destination_pixel + 3]
            output_alpha = source_alpha + (destination_alpha * (255 - source_alpha) + 127) // 255
            denominator = output_alpha * 255
            for channel in range(3):
                numerator = (
                    source[source_pixel + channel] * source_alpha * 255
                    + destination[destination_pixel + channel]
                    * destination_alpha
                    * (255 - source_alpha)
                )
                numerator = 0 if denominator <= 0 else (numerator + denominator // 2) // denominator
                destination[destination_pixel + channel] = max(0, min(255, numerator))
            destination[destination_pixel + 3] = output_alpha


def alpha_blit_rgba_u8(
    destination,
    int destination_width,
    source,
    int source_width,
    mask,
    int mask_width,
    int mask_channels,
    int destination_x0,
    int destination_y0,
    int source_x0,
    int source_y0,
    int copy_width,
    int copy_height,
):
    cdef unsigned char[::1] destination_view = destination
    cdef const unsigned char[::1] source_view = source
    cdef const unsigned char[::1] mask_view
    if mask is None:
        with nogil:
            _alpha_blit_without_mask(
                destination_view, destination_width, source_view, source_width,
                destination_x0, destination_y0, source_x0, source_y0,
                copy_width, copy_height,
            )
    else:
        mask_view = mask
        with nogil:
            _alpha_blit_with_mask(
                destination_view, destination_width, source_view, source_width,
                mask_view, mask_width, mask_channels,
                destination_x0, destination_y0, source_x0, source_y0,
                copy_width, copy_height,
            )


def blend_solid_mask_rgba_u8(
    destination,
    int frame_width,
    int frame_height,
    mask,
    int mask_width,
    int mask_height,
    int x,
    int y,
    int red,
    int green,
    int blue,
    int alpha,
):
    cdef unsigned char[::1] destination_view = destination
    cdef const unsigned char[::1] mask_view = mask
    cdef int mask_x, mask_y, frame_x, frame_y, coverage, pixel, channel
    cdef int colors[3]
    cdef double source_alpha, destination_alpha, output_alpha, safe_alpha, output
    colors[0] = red
    colors[1] = green
    colors[2] = blue
    with nogil:
        for mask_y in range(mask_height):
            frame_y = y + mask_y
            if frame_y < 0 or frame_y >= frame_height:
                continue
            for mask_x in range(mask_width):
                frame_x = x + mask_x
                if frame_x < 0 or frame_x >= frame_width:
                    continue
                coverage = mask_view[mask_y * mask_width + mask_x]
                if coverage <= 0:
                    continue
                source_alpha = (coverage / 255.0) * (alpha / 255.0)
                pixel = (frame_y * frame_width + frame_x) * 4
                destination_alpha = destination_view[pixel + 3] / 255.0
                output_alpha = source_alpha + destination_alpha * (1.0 - source_alpha)
                safe_alpha = output_alpha if output_alpha > 1e-6 else 1.0
                for channel in range(3):
                    output = (
                        colors[channel] * source_alpha
                        + destination_view[pixel + channel]
                        * destination_alpha
                        * (1.0 - source_alpha)
                    ) / safe_alpha
                    destination_view[pixel + channel] = max(0, min(255, _round_half_even(output)))
                destination_view[pixel + 3] = max(
                    0,
                    min(255, _round_half_even(output_alpha * 255.0)),
                )
