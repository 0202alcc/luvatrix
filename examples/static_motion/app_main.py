"""Static-tier example: compiled to JS at build-web time (no Python at runtime).

This entrypoint exists only to satisfy the app manifest contract. The web
build compiles container.json through the static tier ([web]
static_container), so the browser never imports this module.
"""


def create():
    raise RuntimeError(
        "examples.static_motion is a static-tier web example; "
        "build it with `luvatrix build-web` (no native runtime)."
    )
