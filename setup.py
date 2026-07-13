from __future__ import annotations

import os

from setuptools import Extension, setup


extensions = []
if os.environ.get("LUVATRIX_BUILD_ACCEL", "").strip().lower() in {"1", "true", "yes", "on"}:
    extensions.append(
        Extension(
            "luvatrix_core._accel_native",
            ["luvatrix_core/_accel_native.c"],
            extra_compile_args=["-O3"],
        )
    )

setup(ext_modules=extensions)
