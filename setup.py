from __future__ import annotations

import os

from setuptools import Extension, setup


def _build_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


extensions = []
extra_options: dict[str, object] = {}
if _build_flag_enabled("LUVATRIX_BUILD_ACCEL"):
    extensions.append(
        Extension(
            "luvatrix_core._accel_native",
            ["luvatrix_core/_accel_native.c"],
            extra_compile_args=["-O3"],
        )
    )
if _build_flag_enabled("LUVATRIX_BUILD_RUST"):
    from setuptools_rust import RustExtension

    extra_options["rust_extensions"] = [
        RustExtension(
            "luvatrix_core._matrix_rs",
            path="rust/luvatrix-matrix/Cargo.toml",
            debug=False,
        )
    ]

setup(ext_modules=extensions, **extra_options)
